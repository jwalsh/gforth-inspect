"""The three frozen reference consumers, following one session's log live (G5).

1. `tail -n +1 -F stacks.jsonl | jq -c -f stacks.jq` (pbt/consumers/stacks.jq),
   started before log-on, as a course pane would be.
2. pbt/consumers/checker.py, run after every line that wrote a record, as
   an editor's checker runs on each change.  It is pinned to a contract
   (--expect); the soak's are pinned to config.CONTRACT_EXPECTED.
3. pbt/consumers/mock_server.py, one per session, asked GET /stacks after
   every line that wrote a record.

The consumers are run as they are; nothing here edits them.  What each
should have said is computed here independently from the log, and any
difference is a G5 violation.
"""

from __future__ import annotations

import http.client
import json
import subprocess
import sys
import time
from pathlib import Path

from . import config

JQ_FILTER = config.CONSUMERS / "stacks.jq"
CHECKER = config.CONSUMERS / "checker.py"
MOCK = config.CONSUMERS / "mock_server.py"


def _contract_kind(announced, expected: str) -> str | None:
    """None if `announced` matches `expected` in MAJOR.MINOR, else 'minor'/'major'."""
    major, minor = expected.split(".")[:2]
    if isinstance(announced, str) and announced.split(".")[:2] == [major, minor]:
        return None
    if isinstance(announced, str) and announced.split(".")[0] == major:
        return "minor"
    return "major"


def expected_checker(lines: list[bytes], expected: str, validator) -> dict:
    """What a CONSUMERS.org checker written for `expected` must answer for this log.

    Computed from the contract (consumer obligations 2 and 3), not by
    calling the checker's code.
    """
    if not lines:
        return {"error": "empty log"}
    announced = None
    for line in lines:
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict) and record.get("event") == "hello":
            announced = record.get("contract")
    kind = _contract_kind(announced, expected)
    if kind:
        shown = announced if isinstance(announced, str) else "(none)"
        return {"stopped": f"contract {shown} from the producer, this consumer expects {expected} "
                           f"({kind} update): check the schema and change log"}
    try:
        record = json.loads(lines[-1].decode("utf-8"), parse_constant=_reject)
    except (UnicodeDecodeError, ValueError):
        return {"error": "last line is not JSON"}
    if not isinstance(record, dict) or any(validator.iter_errors(record)):
        return {"error": "invalid"}
    result = {"event": record["event"]}
    if record["event"] == "snapshot":
        for key in ("where", "src", "data", "float", "rs"):
            result[key] = record[key]
        result["input"] = {key: record["input"][key] for key in ("file", "line", "in", "text")}
    return result


def _reject(name: str):
    raise ValueError(name)


def expected_jq(line: bytes) -> dict:
    record = json.loads(line)
    return {"e": record.get("event"), "w": record.get("where"), "d": record.get("data"), "f": record.get("float")}


def _same(left, right) -> bool:
    """Equal as JSON values (jq prints 1.5 where the log has 1.5000000000000000E0)."""
    from .checks import same_json
    return same_json(left, right)


class Followers:
    """jq and the mock server for one log; the checker on demand."""

    def __init__(self, log: Path, schema: Path, out_dir: Path, pin: str = config.CONTRACT_EXPECTED,
                 checker_args: tuple = ()):
        self.log, self.schema, self.pin = log, schema, pin
        self.checker_args = checker_args
        self.jq_out = out_dir / "jq.out"
        self.tail = subprocess.Popen(["tail", "-n", "+1", "-F", str(log)], stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL)
        self.jq = subprocess.Popen(["jq", "-c", "--unbuffered", "-f", str(JQ_FILTER)], stdin=self.tail.stdout,
                                   stdout=open(self.jq_out, "wb"), stderr=open(out_dir / "jq.err", "wb"))
        self.tail.stdout.close()
        self.mock = subprocess.Popen([sys.executable, str(MOCK), str(log)], stdout=subprocess.PIPE,
                                     stderr=open(out_dir / "mock.err", "wb"))
        port_line = self.mock.stdout.readline().decode().split()
        self.port = int(port_line[1]) if len(port_line) == 2 and port_line[0] == "PORT" else None
        self.checker_ok = True
        self.checker_runs = 0
        self.jq_seen = 0
        self._jq_lines, self._jq_offset, self._jq_partial = [], 0, b""
        self.jq_dead_reported = False

    # --- liveness ------------------------------------------------------

    def alive(self) -> dict:
        return {"jq": self.jq.poll() is None and self.tail.poll() is None,
                "mock": self.mock.poll() is None and self.port is not None,
                "checker": self.checker_ok}

    def stop(self) -> None:
        for proc in (self.tail, self.jq, self.mock):
            if proc.poll() is None:
                proc.terminate()
        for proc in (self.tail, self.jq, self.mock):
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()

    # --- the three, against the log as it is now --------------------

    def get_stacks(self) -> tuple[int, bytes]:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            connection.request("GET", "/stacks")
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()

    def run_checker(self) -> dict | None:
        self.checker_runs += 1
        proc = subprocess.run([sys.executable, str(CHECKER), str(self.log), str(self.schema),
                               "--expect", self.pin, *self.checker_args],
                              capture_output=True, timeout=60)
        try:
            result = json.loads(proc.stdout)
            self.checker_ok = proc.returncode in (0, 1)
            return result
        except ValueError:
            self.checker_ok = False
            return None

    def jq_lines(self) -> list[bytes]:
        """jq's output so far, read incrementally."""
        size = self.jq_out.stat().st_size
        if size > self._jq_offset:
            with open(self.jq_out, "rb") as handle:
                handle.seek(self._jq_offset)
                chunk = handle.read(size - self._jq_offset)
            self._jq_offset += len(chunk)
            parts = (self._jq_partial + chunk).split(b"\n")
            self._jq_partial = parts.pop()
            self._jq_lines.extend(part for part in parts if part)
        return self._jq_lines

    def verify(self, lines: list[bytes], validator, expected_contract: str = config.CONTRACT_EXPECTED,
               jq_wait: float = 10.0, full: bool = True) -> list[str]:
        """Problems with what the followers report for `lines` (the whole log,
        at rest).  jq is checked every time; with full, the mock and the
        checker too."""
        problems = []
        if full:
            problems += self._verify_mock_checker(lines, validator, expected_contract)
        problems += self._verify_jq(lines, jq_wait)
        return problems

    def _verify_mock_checker(self, lines, validator, expected_contract) -> list[str]:
        problems = []
        # mock: the last line, byte for byte
        if self.port is None or self.mock.poll() is not None:
            problems.append("mock server not running")
        else:
            try:
                status, body = self.get_stacks()
                want = lines[-1] if lines else None
                if want is None and status != 404:
                    problems.append(f"mock: {status} on an empty log")
                elif want is not None and (status != 200 or body != want):
                    problems.append(f"mock: {status} {body[:80]!r} is not the last line {want[:80]!r}")
            except OSError as error:
                problems.append(f"mock: {error}")
        # checker: as a checker written for expected_contract must answer
        got = self.run_checker()
        want = expected_checker(lines, expected_contract, validator)
        if got is None:
            problems.append("checker: no JSON answer")
        elif "error" in want or "error" in got:
            if set(got) != set(want) or ("error" in want and not str(got["error"]).startswith(want["error"].split(":")[0])):
                problems.append(f"checker: {json.dumps(got)[:160]} where {json.dumps(want)[:160]}")
        elif not _same(got, want):
            problems.append(f"checker: {json.dumps(got)[:160]} where {json.dumps(want)[:160]}")
        return problems

    def _verify_jq(self, lines, jq_wait) -> list[str]:
        """jq: one object per line, in order, each {e,w,d,f} of its line."""
        problems = []
        deadline = time.monotonic() + jq_wait
        while True:
            out = self.jq_lines()
            if len(out) >= len(lines) or time.monotonic() > deadline or self.jq.poll() is not None:
                break
            time.sleep(0.05)
        if len(out) != len(lines):
            dead = "" if self.jq.poll() is None else f" (jq exited {self.jq.returncode})"
            problems.append(f"jq: {len(out)} objects for {len(lines)} lines{dead}")
        for index in range(self.jq_seen, min(len(out), len(lines))):
            try:
                if not _same(json.loads(out[index]), expected_jq(lines[index])):
                    problems.append(f"jq: object {index + 1} is {out[index][:120]!r}")
                    break
            except ValueError as error:
                problems.append(f"jq: object {index + 1}: {error}")
                break
        self.jq_seen = min(len(out), len(lines))
        return problems
