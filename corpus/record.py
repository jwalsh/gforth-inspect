"""Record the consumer corpus: every NN-slug.fs here, run under gforth 0.7.3.

    python3 record.py OUT_DIR [--engine gforth] [--repo ..]

For each scenario it writes, into OUT_DIR:

  NN-slug.jsonl        the stacks.jsonl the program wrote, with every "t"
                       set to 0 (a clock, not a stack: consumers must not
                       rely on it)
  NN-slug.expect.json  what the frozen reference consumers in
                       pbt/consumers/ produce from that .jsonl

and OUT_DIR/PROVENANCE, the blob ids of the inspect.fs and schema used.

inspect.fs and the schema come from pbt/gforth_run.py's selection
(INSPECT_FS, else INSPECT_REF, else the `harden` ref).  Each run is
isolated the way gforth_run does it: a fresh temp dir as cwd and HOME,
inspect.fs and the scenario loaded by relative name (so input.file is
"NN-slug.fs"), and the log in a fresh GFORTH_INSPECT_LOG_DIR.

A scenario whose comment lines read `\\ pN: <forth>` is a multi-producer
schedule (16-two-producers.fs): it is not loaded; one gforth per N is
started, all logging to one directory, and each line is sent to its
producer on stdin, paced as experiment 005 paces them.

Standard library only.  Nothing here types into a tmux pane.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import select
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

CORPUS = Path(__file__).resolve().parent
SCENARIO_NAME = re.compile(r"^\d\d-[a-z0-9-]+\.fs$")
SCHEDULE_LINE = re.compile(r"^\\ p(\d+): (.*)$")
# the "t" key, not the text `"t":` inside a string (there its quote is escaped)
TIME_FIELD = re.compile(rb'(?<!\\)"t":-?[0-9]+')


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          capture_output=True, text=True).stdout


# --- which producer -----------------------------------------------------

def producer_source(repo: Path) -> tuple[bytes, bytes, str, str]:
    """(inspect.fs bytes, schema bytes, inspect blob, schema blob)."""
    sys.path.insert(0, str(repo / "pbt"))
    import gforth_run  # the shared runner's selection; read, never edited

    inspect_path, _ = gforth_run.inspect_source()
    inspect_bytes = inspect_path.read_bytes()
    explicit_schema = os.environ.get("SCHEMA_JSON")
    if explicit_schema:
        schema_bytes = Path(explicit_schema).read_bytes()
    else:
        schema_bytes = b""
        for ref in [os.environ.get("INSPECT_REF", "harden"), "origin/harden"]:
            try:
                schema_bytes = subprocess.run(
                    ["git", "-C", str(repo), "show", f"{ref}:contract/stacks-log.schema.json"],
                    check=True, capture_output=True).stdout
                break
            except subprocess.CalledProcessError:
                continue
        if not schema_bytes:
            raise RuntimeError("no contract/stacks-log.schema.json; set SCHEMA_JSON")
    return inspect_bytes, schema_bytes, blob_id(repo, inspect_bytes), blob_id(repo, schema_bytes)


def blob_id(repo: Path, content: bytes) -> str:
    return subprocess.run(["git", "-C", str(repo), "hash-object", "--stdin"], input=content,
                          check=True, capture_output=True).stdout.decode().strip()


# --- running a scenario ------------------------------------------------

def isolated_env(home: Path, log_dir: Path) -> dict[str, str]:
    return {**os.environ, "HOME": str(home), "XDG_STATE_HOME": str(log_dir.parent),
            "GFORTH_INSPECT_LOG_DIR": str(log_dir)}


def read_log(log_dir: Path) -> bytes:
    log_path = log_dir / "stacks.jsonl"
    return log_path.read_bytes() if log_path.exists() else b""


def run_file(scenario: Path, inspect_bytes: bytes, engine: str, root: Path) -> tuple[bytes, int]:
    """Load the scenario after inspect.fs; (raw log, exit status)."""
    (root / "inspect.fs").write_bytes(inspect_bytes)
    shutil.copyfile(scenario, root / scenario.name)
    log_dir = root / "state" / "gforth-inspect"
    proc = subprocess.run([engine, "inspect.fs", scenario.name], cwd=root,
                          env=isolated_env(root, log_dir), capture_output=True,
                          stdin=subprocess.DEVNULL, timeout=30)
    return read_log(log_dir), proc.returncode


class Producer:
    """One gforth on a pipe.  A line is finished when its #ACK is printed."""

    def __init__(self, index: int, engine: str, inspect_bytes: bytes, root: Path, log_dir: Path):
        self.index = index
        home = root / f"p{index}"
        home.mkdir()
        (home / "inspect.fs").write_bytes(inspect_bytes)
        self.proc = subprocess.Popen([engine, "inspect.fs"], cwd=home,
                                     env=isolated_env(home, log_dir), stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.buffer = b""
        self.acks = 0

    def send(self, line: str, timeout: float = 10.0) -> None:
        """Send `line`, then an acknowledgement on a line of its own.

        gforth 0.7.3 reads a pipe one line at a time and runs each line
        before it reads the next, so the ack prints only after `line` has
        run and any record it wrote has been flushed (experiment 005).
        Keeping the ack off `line` keeps it out of input.text.
        """
        self.acks += 1
        ack = f"#ACK {self.acks}".encode()
        self.proc.stdin.write(f'{line}\ncr ." #ACK {self.acks}" cr\n'.encode())
        self.proc.stdin.flush()
        deadline = time.monotonic() + timeout
        while ack not in [chunk.rstrip() for chunk in self.buffer.split(b"\n")]:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"producer {self.index}: no {ack!r} in {timeout}s")
            ready, _, _ = select.select([self.proc.stdout], [], [], remaining)
            if ready:
                data = os.read(self.proc.stdout.fileno(), 65536)
                if not data:
                    raise RuntimeError(f"producer {self.index} exited before {ack!r}")
                self.buffer += data
        self.buffer = b""

    def finish(self, line: str, timeout: float = 10.0) -> int:
        self.proc.stdin.write(f"{line}\n".encode())
        self.proc.stdin.close()
        self.proc.stdout.read()
        return self.proc.wait(timeout=timeout)


def run_schedule(schedule: list[tuple[int, str]], inspect_bytes: bytes, engine: str,
                 root: Path) -> tuple[bytes, int]:
    """Drive the producers line by line; (raw shared log, worst exit status).

    A producer's last line is sent without an ack and must end it (bye).
    """
    log_dir = root / "state" / "gforth-inspect"
    log_dir.mkdir(parents=True)
    count = max(index for index, _ in schedule) + 1
    last_step = {index: position for position, (index, _) in enumerate(schedule)}
    producers = []
    status = 0
    try:
        for index in range(count):
            producers.append(Producer(index, engine, inspect_bytes, root, log_dir))
        for producer in producers:
            producer.send("")  # inspect.fs has loaded
        for position, (index, line) in enumerate(schedule):
            if last_step[index] == position:
                status = max(status, producers[index].finish(line))
            else:
                producers[index].send(line)
    finally:
        for producer in producers:
            if producer.proc.poll() is None:
                producer.proc.kill()
                producer.proc.wait()
    return read_log(log_dir), status


def schedule_of(scenario: Path) -> list[tuple[int, str]]:
    lines = scenario.read_bytes().decode("utf-8", "replace").split("\n")
    return [(int(match.group(1)), match.group(2))
            for match in map(SCHEDULE_LINE.match, lines) if match]


def mask_time(raw: bytes) -> bytes:
    return TIME_FIELD.sub(b'"t":0', raw)


# --- the reference consumers ------------------------------------------

def run_jq(repo: Path, log_path: Path) -> dict:
    proc = subprocess.run(["jq", "-c", "-f", str(repo / "pbt" / "consumers" / "stacks.jq"),
                           str(log_path)], capture_output=True)
    # stderr is left out: jq's message names a position and differs by version
    return {"exit": proc.returncode,
            "lines": proc.stdout.decode("utf-8").splitlines()}


def run_checker(repo: Path, log_path: Path, schema_path: Path) -> dict:
    proc = subprocess.run([sys.executable, str(repo / "pbt" / "consumers" / "checker.py"),
                           str(log_path), str(schema_path)], capture_output=True)
    return {"exit": proc.returncode, "output": json.loads(proc.stdout.decode("utf-8"))}


def run_mock(repo: Path, log_path: Path) -> dict:
    server = subprocess.Popen([sys.executable, str(repo / "pbt" / "consumers" / "mock_server.py"),
                               str(log_path)], stdout=subprocess.PIPE, text=True)
    try:
        port_line = server.stdout.readline()
        if not port_line.startswith("PORT "):
            raise RuntimeError(f"mock server did not start: {port_line!r}")
        url = f"http://127.0.0.1:{port_line.split()[1]}/stacks"
        try:
            with urllib.request.urlopen(url, timeout=10) as response:
                status, body = response.status, response.read()
        except urllib.error.HTTPError as error:
            status, body = error.code, error.read()
    finally:
        server.terminate()
        server.wait(timeout=5)
    return {"status": status, "body": body.decode("utf-8")}


def expectations(repo: Path, log_path: Path, schema_path: Path, producer_exit: int) -> dict:
    return {
        "producer_exit": producer_exit,
        "jq": run_jq(repo, log_path),
        "checker": run_checker(repo, log_path, schema_path),
        "mock_get_stacks": run_mock(repo, log_path),
    }


# --- main ---------------------------------------------------------------

def tool_version(*command: str) -> str:
    proc = subprocess.run(list(command), capture_output=True, text=True)
    return (proc.stdout or proc.stderr).strip().splitlines()[0]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out_dir")
    parser.add_argument("--engine", default="gforth")
    parser.add_argument("--repo", default=str(CORPUS.parent))
    parser.add_argument("--scenarios", default=str(CORPUS),
                        help="directory holding the NN-slug.fs files")
    options = parser.parse_args(argv)
    repo = Path(options.repo).resolve()
    out_dir = Path(options.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    inspect_bytes, schema_bytes, inspect_blob, schema_blob = producer_source(repo)
    gforth_version = tool_version(options.engine, "--version")
    jq_version = tool_version("jq", "--version")
    print(f"record: inspect.fs blob {inspect_blob}, schema blob {schema_blob}, "
          f"engine {options.engine} ({gforth_version}), {jq_version}")
    (out_dir / "PROVENANCE").write_text(
        f"inspect.fs blob {inspect_blob}\n"
        f"stacks-log.schema.json blob {schema_blob}\n"
        f"recorded with {gforth_version} and {jq_version}\n")

    scenarios = sorted(path for path in Path(options.scenarios).iterdir()
                       if SCENARIO_NAME.match(path.name))
    with tempfile.TemporaryDirectory(prefix="gfi-corpus-") as scratch:
        schema_path = Path(scratch) / "stacks-log.schema.json"
        schema_path.write_bytes(schema_bytes)
        for scenario in scenarios:
            root = Path(tempfile.mkdtemp(prefix=scenario.stem + "-", dir=scratch))
            schedule = schedule_of(scenario)
            if schedule:
                raw, status = run_schedule(schedule, inspect_bytes, options.engine, root)
            else:
                raw, status = run_file(scenario, inspect_bytes, options.engine, root)
            log_path = out_dir / f"{scenario.stem}.jsonl"
            log_path.write_bytes(mask_time(raw))
            expect = expectations(repo, log_path, schema_path, status)
            (out_dir / f"{scenario.stem}.expect.json").write_text(
                json.dumps(expect, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            record_count = raw.count(b"\n")
            print(f"  {scenario.name:32} records {record_count:3}  exit {status}  "
                  f"checker {'accepts' if expect['checker']['exit'] == 0 else 'refuses'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
