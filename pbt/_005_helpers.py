"""Helpers for experiment 005 (concurrent producers, issue #17).

gforth_run.py is shared and gives every run its own state dir.  Here N
gforth processes must share ONE log dir, so this module has its own
launcher, built on gforth_run.inspect_source() and the same isolation:

  - each producer runs with cwd in its own temp dir, holding a copy of
    inspect.fs loaded by relative name (no temp path reaches a record)
  - HOME is that temp dir too: gforth 0.7.3 writes .gforth-history there
  - XDG_STATE_HOME and GFORTH_INSPECT_LOG_DIR point at one shared temp dir;
    b1c162e logs to $XDG_STATE_HOME/course-repo/, harden to
    $GFORTH_INSPECT_LOG_DIR, so both are set

Pacing.  gforth 0.7.3 on a pipe reads stdin one line at a time and
processes each line as it arrives (checked by hand, see the 005 log); it
echoes the line and flushes stdout before it reads the next one.  Every
line sent here ends with `cr ." #ACK n" cr`, so `#ACK n` at the start of a
stdout line means the line has run, and the log-write in it has already
called flush-file.  The launcher then polls the log for the record's
marker before it sends the next line.  The schedule is therefore fixed by
the generated steps, never by timing, and Hypothesis can shrink it.

Identity.  b1c162e has no log-id, so every snapshot carries its identity
on the data stack: [MARK, producer, sequence].  On an inspect.fs that has
log-id the producer also tags its snapshots "p<producer>", and the check
asserts the tag agrees with the data.
"""

from __future__ import annotations

import contextlib
import json
import os
import select
import shutil
import subprocess
import tempfile
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import jsonschema

import gforth_run

OLD_REF = "b1c162e"   # the copy the course runs today
HARDEN_REF = "10a0da4"  # harden unfixed, blob a7e5c141af51 (same blob as 8deb780, where 005 started)
FIXED_REF = "c1a6a3a"   # harden with the #17 rework: whole record in a buffer, one seek + one write-file
MARK = 5005
SELECTORS = ("INSPECT_FS", "INSPECT_REF", "SCHEMA_JSON")

# the proposed fix (issue #17): seek to the current end before every record.
# One line of log-write changes; gforth 0.7.3 has no append fam.
FIX_FROM = "    base @ >r decimal"
FIX_TO = "    log-fid @ file-size throw log-fid @ reposition-file throw  base @ >r decimal"



# --- which inspect.fs ---------------------------------------------------


@contextlib.contextmanager
def source_env(ref: str | None = None, path: Path | None = None):
    """Within the block, gforth_run.inspect_source() sees `ref` or `path`.

    With neither, the caller's INSPECT_REF / INSPECT_FS are left as they are.
    """
    saved = {name: os.environ.get(name) for name in SELECTORS}
    try:
        if ref is not None or path is not None:
            for name in ("INSPECT_FS", "INSPECT_REF"):
                os.environ.pop(name, None)
        if ref is not None:
            os.environ["INSPECT_REF"] = ref
        if path is not None:
            os.environ["INSPECT_FS"] = str(path)
        yield
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def public_provenance(provenance: str) -> str:
    """INSPECT_FS gives a temp path: keep only the file name and blob id."""
    if provenance.startswith("file:"):
        path_part, digest = provenance[len("file:"):].rsplit(" ", 1)
        return f"file:{Path(path_part).name} {digest}"
    return provenance


def current_source(ref: str | None = None) -> tuple[bytes, str]:
    """(inspect.fs bytes, public provenance) for `ref`, or the runner's choice."""
    with source_env(ref=ref):
        path, provenance = gforth_run.inspect_source()
        return path.read_bytes(), public_provenance(provenance)


def definition_span(lines: list[bytes], word: str) -> tuple[int, int] | None:
    """Line indices [start, end) of the one `: <word>` definition, or None.

    It ends at the first line whose code (text before a backslash comment)
    ends in `;`.  A plain search for `;` stops early on harden, whose
    log-write comment reads "in decimal; BASE is restored after".
    """
    head = f": {word} ".encode()
    starts = [index for index, line in enumerate(lines) if line.startswith(head)]
    if len(starts) != 1:
        return None
    for end in range(starts[0], len(lines)):
        if lines[end].split(b"\\ ")[0].rstrip().endswith(b";"):
            return starts[0], end + 1
    return None


def definition(source: bytes, word: str) -> bytes:
    """The text of `: <word> ... ;`, or b"" if there is not exactly one."""
    lines = source.split(b"\n")
    span = definition_span(lines, word)
    return b"\n".join(lines[span[0]:span[1]]) if span else b""


def log_write_body(source: bytes) -> bytes:
    return definition(source, "log-write")


def write_path(source: bytes) -> tuple[bytes, bytes]:
    """log-on and log-write: the two words where a #17 fix can live."""
    return definition(source, "log-on"), definition(source, "log-write")


def known_unfixed(source: bytes, unfixed_sources: list[bytes]) -> bool:
    """True if log-on and log-write are word for word those of a known-unfixed ref.

    Used to decide the #17 xfail.  Any change to either word, whatever shape
    the fix takes (a seek in log-write, a helper word, an append-mode open
    in log-on), makes the test a plain one, which then has to pass; edits
    elsewhere in inspect.fs leave the xfail in place.
    """
    path = write_path(source)
    return all(path) and any(path == write_path(other) for other in unfixed_sources)


def patched(source: bytes) -> bytes:
    """The seek-before-write fix applied to `source`; exactly one line changes."""
    lines = source.split(b"\n")
    span = definition_span(lines, "log-write")
    assert span, "patch: no single `: log-write ... ;` definition"
    hits = [index for index in range(*span) if lines[index] == FIX_FROM.encode()]
    assert len(hits) == 1, (
        "patch: log-write no longer has exactly one `base @ >r decimal` line; "
        "harden changed, revisit the 005 fixture")
    lines[hits[0]] = FIX_TO.encode()
    return b"\n".join(lines)


def patchable(source: bytes) -> bool:
    """True if `patched` applies: harden's log-write shape, not b1c162e's one-liner."""
    lines = source.split(b"\n")
    span = definition_span(lines, "log-write")
    return bool(span) and sum(lines[index] == FIX_FROM.encode() for index in range(*span)) == 1


def seeks_per_write(source: bytes) -> bool:
    """True if log-write repositions before each record (the fix's usual shape).

    Reported only; the xfail is decided by `known_unfixed`.
    """
    return b"reposition-file" in log_write_body(source)


def has_log_id(source: bytes) -> bool:
    return b"\n: log-id " in source


def schema_for(ref: str | None) -> dict:
    """contract/stacks-log.schema.json at `ref` (b1c162e has its own, v1)."""
    with source_env(ref=ref):
        return gforth_run.schema()


# --- one producer -------------------------------------------------------


class Producer:
    """One gforth process with inspect.fs loaded, driven line by line."""

    def __init__(self, index: int, engine: str, source: bytes, root: Path, log_root: Path):
        self.index = index
        self.home = root / f"p{index}"
        self.home.mkdir()
        (self.home / "inspect.fs").write_bytes(source)
        env = {
            **os.environ,
            "HOME": str(self.home),
            "XDG_STATE_HOME": str(log_root),
            "GFORTH_INSPECT_LOG_DIR": str(log_root / "gforth-inspect"),
        }
        self.proc = subprocess.Popen(
            [engine, "inspect.fs"], cwd=self.home, env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.buffer = b""
        self.acks = 0

    def send(self, line: str, timeout: float = 10.0) -> None:
        """Run one line and wait until gforth has finished it."""
        self.acks += 1
        ack = f"#ACK {self.acks}".encode()
        self.proc.stdin.write(f'{line} cr ." #ACK {self.acks}" cr\n'.encode())
        self.proc.stdin.flush()
        deadline = time.monotonic() + timeout
        while True:
            offset = 0
            while (newline := self.buffer.find(b"\n", offset)) >= 0:
                if self.buffer[offset:newline].rstrip() == ack:
                    self.buffer = self.buffer[newline + 1:]
                    return
                offset = newline + 1
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"producer {self.index}: no {ack!r} within {timeout}s")
            ready, _, _ = select.select([self.proc.stdout], [], [], remaining)
            if ready:
                data = os.read(self.proc.stdout.fileno(), 65536)
                if not data:
                    raise RuntimeError(f"producer {self.index} exited before {ack!r}")
                self.buffer += data

    def finish(self, timeout: float = 10.0) -> int:
        try:
            self.proc.stdin.write(b"log-off bye\n")
            self.proc.stdin.flush()  # communicate() closes stdin; it must still be open
        except BrokenPipeError:
            pass
        try:
            self.proc.communicate(timeout=timeout)
            return self.proc.returncode
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()
            raise

    def kill(self) -> None:
        if self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait()


def snapshot_line(producer: int, sequence: int, tagged: bool) -> str:
    tag = f's" p{producer}" log-id ' if tagged else ""
    return f"{tag}{MARK} {producer} {sequence} .stacks clearstack"


def marker(producer: int, sequence: int) -> bytes:
    return f'"data":[{MARK},{producer},{sequence}]'.encode()


def log_file(log_root: Path) -> Path | None:
    logs = sorted(log_root.glob("*/stacks.jsonl"))
    if len(logs) > 1:
        raise RuntimeError(f"more than one stacks.jsonl: {[log_path.parent.name for log_path in logs]}")
    return logs[0] if logs else None


def wait_for(log_root: Path, needle: bytes | None, timeout: float = 10.0) -> None:
    """Poll the shared log until `needle` is in it, or with None until it ends in a hello.

    log-on seeks to the real end on every ref, so a fresh hello is the last
    line.  Counting hellos would not do: an earlier one may be overwritten.
    """
    deadline = time.monotonic() + timeout
    while True:
        path = log_file(log_root)
        raw = path.read_bytes() if path else b""
        if needle is None:
            last = raw.rstrip(b"\n").rpartition(b"\n")[2]
            if b'"event":"hello"' in last:
                return
        elif needle in raw:
            return
        if time.monotonic() > deadline:
            raise TimeoutError(f"record {needle or 'hello'!r} not in the log within {timeout}s")
        time.sleep(0.001)


# --- a schedule, and what the file says about it -------------------------


@dataclass
class Tally:
    """What one log holds against what its producers wrote."""

    lines: int = 0
    parse_failures: int = 0
    schema_failures: int = 0
    lost: int = 0
    duplicated: int = 0
    foreign: int = 0      # a snapshot no producer was asked to write
    tag_mismatch: int = 0  # "id" disagrees with the producer in data
    hellos_expected: int = 0
    hellos: int = 0
    examples: list = field(default_factory=list)  # a few bad lines, for the message

    def ok(self) -> bool:
        return not (self.parse_failures or self.schema_failures or self.lost or self.duplicated
                    or self.foreign or self.tag_mismatch or self.hellos != self.hellos_expected)

    def add(self, other: "Tally") -> None:
        for name in ("lines", "parse_failures", "schema_failures", "lost", "duplicated",
                     "foreign", "tag_mismatch", "hellos_expected", "hellos"):
            setattr(self, name, getattr(self, name) + getattr(other, name))

    def summary(self) -> str:
        return (f"lines {self.lines} parse failures {self.parse_failures} "
                f"schema failures {self.schema_failures} lost {self.lost} "
                f"duplicated {self.duplicated} foreign {self.foreign} "
                f"tag mismatches {self.tag_mismatch} hellos {self.hellos}/{self.hellos_expected}")


def audit(raw: bytes, expected: list[tuple[int, int]], producers: int, tagged: bool,
          validator: jsonschema.Validator) -> Tally:
    """Check every line of `raw` (split on LF bytes) against what was written."""
    tally = Tally(hellos_expected=producers)
    seen: Counter = Counter()
    for chunk in raw.split(b"\n"):
        if not chunk:
            continue
        tally.lines += 1
        try:
            record = json.loads(chunk.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            tally.parse_failures += 1
            if len(tally.examples) < 3:
                tally.examples.append(chunk[:120])
            continue
        if not isinstance(record, dict) or any(validator.iter_errors(record)):
            tally.schema_failures += 1
            if len(tally.examples) < 3:
                tally.examples.append(chunk[:120])
            continue
        if record["event"] == "hello":
            tally.hellos += 1
            continue
        data = record.get("data", [])
        if len(data) != 3 or data[0] != MARK:
            tally.foreign += 1
            continue
        key = (data[1], data[2])
        seen[key] += 1
        if tagged and record.get("id") != f"p{data[1]}":
            tally.tag_mismatch += 1
    wanted = Counter(expected)
    tally.lost = sum(1 for key in wanted if key not in seen)
    tally.duplicated = sum(count - 1 for count in seen.values() if count > 1)
    tally.foreign += sum(count for key, count in seen.items() if key not in wanted)
    return tally


def run_paced(source: bytes, engine: str, producers: int, steps: list[tuple[int, int]],
              validator: jsonschema.Validator) -> Tally:
    """Drive `steps` [(producer, snapshots)] one line at a time; audit the log.

    A producer's first step starts with log-on, so its hello is paced too.
    """
    tagged = has_log_id(source)
    root = Path(tempfile.mkdtemp(prefix="gfi005-"))
    log_root = root / "state"
    log_root.mkdir()
    team = []
    try:
        for index in range(producers):  # appended one by one, so a failed start still cleans up
            team.append(Producer(index, engine, source, root, log_root))
        for member in team:
            member.send("")  # ready: inspect.fs is loaded
        sequence = Counter()
        expected = []
        logging_on = set()
        for producer, count in steps:
            member = team[producer]
            if producer not in logging_on:
                logging_on.add(producer)
                member.send("log-on")
                wait_for(log_root, None)
            for _ in range(count):
                sequence[producer] += 1
                member.send(snapshot_line(producer, sequence[producer], tagged))
                wait_for(log_root, marker(producer, sequence[producer]))
                expected.append((producer, sequence[producer]))
        for member in team:
            returncode = member.finish()
            assert returncode == 0, f"producer {member.index} exited {returncode}"
        path = log_file(log_root)
        raw = path.read_bytes() if path else b""
        return audit(raw, expected, len(logging_on), tagged, validator)
    finally:
        for member in team:
            member.kill()
        shutil.rmtree(root, ignore_errors=True)


def run_uncoordinated(source: bytes, engine: str, counts: list[int],
                      validator: jsonschema.Validator, timeout: float = 30.0) -> Tally:
    """Every producer gets its whole program at once, and they all run together."""
    tagged = has_log_id(source)
    root = Path(tempfile.mkdtemp(prefix="gfi005u-"))
    log_root = root / "state"
    log_root.mkdir()
    procs = []
    try:
        programs = []
        for producer, count in enumerate(counts):
            lines = ["log-on"] + [snapshot_line(producer, sequence, tagged)
                                  for sequence in range(1, count + 1)] + ["log-off bye"]
            programs.append(("\n".join(lines) + "\n").encode())
            home = root / f"p{producer}"
            home.mkdir()
            (home / "inspect.fs").write_bytes(source)
        for producer, program in enumerate(programs):
            home = root / f"p{producer}"
            env = {**os.environ, "HOME": str(home), "XDG_STATE_HOME": str(log_root),
                   "GFORTH_INSPECT_LOG_DIR": str(log_root / "gforth-inspect")}
            proc = subprocess.Popen([engine, "inspect.fs"], cwd=home, env=env,
                                    stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL)
            procs.append((proc, program))
        for proc, program in procs:  # all are loading inspect.fs; now release them
            proc.stdin.write(program)
            proc.stdin.close()
        for proc, _ in procs:
            proc.wait(timeout=timeout)
        expected = [(producer, sequence) for producer, count in enumerate(counts)
                    for sequence in range(1, count + 1)]
        path = log_file(log_root)
        raw = path.read_bytes() if path else b""
        return audit(raw, expected, len(counts), tagged, validator)
    finally:
        for proc, _ in procs:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
        shutil.rmtree(root, ignore_errors=True)
