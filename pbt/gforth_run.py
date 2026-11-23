"""Run one gforth 0.7.3 program with env/inspect.fs loaded, in isolation.

Every call gets its own XDG_STATE_HOME, so stacks.jsonl is per run and the
user's ~/.local/state is never touched.  Nothing here types into a tmux pane.

inspect.fs comes from, in order:
  INSPECT_FS     a path (use this to test a planted fault)
  INSPECT_REF    a git ref; `git show REF:env/inspect.fs` is cached by blob id
  otherwise      env/inspect.fs of the checkout this file is in, so each
                 worktree tests its own tree, uncommitted edits included;
                 copied with the schema once per process, so one run never
                 mixes versions (an explicit INSPECT_FS is read as it is)
The schema is SCHEMA_JSON, else INSPECT_REF's, else this checkout's; INSPECT_FS
does not change it, so set SCHEMA_JSON with INSPECT_FS when the two differ.
"""

from __future__ import annotations

import atexit
import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ENGINES = ("gforth", "gforth-fast", "gforth-itc")
CACHE = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "gforth-inspect"


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(REPO), *args], check=True, capture_output=True, text=True
    ).stdout


FIXTURE_REFS = Path(__file__).resolve().parent / "fixtures" / "refs"


_SNAPSHOT: tuple[Path, Path, str] | None = None


def _worktree_snapshot() -> tuple[Path, Path, str]:
    """(inspect.fs, schema, provenance): this checkout's two files, copied
    together on the first call into a temp dir that lives as long as the
    process, so one run never mixes versions and nothing is shared or kept."""
    global _SNAPSHOT
    if _SNAPSHOT is None:
        live_fs = REPO / "env" / "inspect.fs"
        live_schema = REPO / "contract" / "stacks-log.schema.json"
        if not live_fs.exists() or not live_schema.exists():
            raise RuntimeError("no env/inspect.fs or schema in this checkout; set INSPECT_FS or INSPECT_REF")
        content = live_fs.read_bytes()
        schema_content = live_schema.read_bytes()
        blob = subprocess.run(["git", "-C", str(REPO), "hash-object", "--stdin"], input=content,
                              check=True, capture_output=True).stdout.decode().strip()
        snap = Path(tempfile.mkdtemp(prefix="gforth-inspect-snapshot-"))
        atexit.register(shutil.rmtree, snap, ignore_errors=True)
        (snap / "inspect.fs").write_bytes(content)
        (snap / "stacks-log.schema.json").write_bytes(schema_content)
        _SNAPSHOT = (snap / "inspect.fs", snap / "stacks-log.schema.json",
                     f"worktree:env/inspect.fs blob:{blob[:12]}")
    return _SNAPSHOT


def worktree_schema_path() -> Path:
    """The schema snapshotted with the default inspect.fs (corpus/record.py)."""
    return _worktree_snapshot()[1]


def inspect_source() -> tuple[Path, str]:
    """(path to inspect.fs, provenance string for run logs)."""
    explicit = os.environ.get("INSPECT_FS")
    if explicit:
        path = Path(explicit).resolve()
        # name and git blob id only: the provenance line goes into public
        # logs, and the blob id matches the ref form's, so the two compare
        blob = _git("hash-object", str(path)).strip()
        return path, f"file:{path.name} blob:{blob[:12]}"
    ref = os.environ.get("INSPECT_REF")
    if not ref:
        path, _, provenance = _worktree_snapshot()
        return path, provenance
    fixture = FIXTURE_REFS / ref / "inspect.fs"
    if fixture.exists():
        # a pinned commit that is no longer in the history (2026-11-22 scrub)
        blob = _git("hash-object", str(fixture)).strip()
        return fixture, f"ref:{ref}@fixture blob:{blob[:12]}"
    try:
        blob = _git("rev-parse", f"{ref}:env/inspect.fs").strip()
    except subprocess.CalledProcessError:
        raise RuntimeError(f"no env/inspect.fs at {ref}; set INSPECT_FS or another INSPECT_REF") from None
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"inspect-{blob[:12]}.fs"
    if not path.exists():
        # atomic: worktrees share this cache, and a reader must never see half a file
        fd, partial = tempfile.mkstemp(dir=CACHE, prefix=path.name + ".")
        with os.fdopen(fd, "w") as out:
            out.write(_git("show", f"{ref}:env/inspect.fs"))
        os.replace(partial, path)
    commit = _git("rev-parse", "--short", ref).strip()
    return path, f"ref:{ref}@{commit} blob:{blob[:12]}"


@dataclass
class Run:
    returncode: int
    stdout: str
    stderr: str
    log_lines: list[str] = field(default_factory=list)  # raw stacks.jsonl lines

    def records(self) -> list[dict]:
        return [json.loads(line) for line in self.log_lines]


def run(program: str, engine: str = "gforth", timeout: float = 10.0) -> Run:
    """Run `program` (Forth source text, loaded as a file after inspect.fs).

    The program should end with `bye`; one is appended regardless, so a
    program that leaves the interpreter running still exits.
    """
    if engine not in ENGINES:
        raise ValueError(engine)
    inspect_fs, _ = inspect_source()
    with tempfile.TemporaryDirectory(prefix="gfi-") as tmp:
        tmp_path = Path(tmp)
        prog = tmp_path / "prog.fs"
        prog.write_bytes(program.encode("utf-8", "surrogateescape") + b"\nbye\n")
        # both files by relative name from cwd=tmp: input.file in a record is
        # then "prog.fs", never a home or temp path (output may be committed)
        (tmp_path / "inspect.fs").write_bytes(inspect_fs.read_bytes())
        # GFORTH_INSPECT_LOG_DIR is the release contract; XDG_STATE_HOME covers
        # inspect.fs versions from before it (they write .../course-repo/)
        env = {
            **os.environ,
            "XDG_STATE_HOME": str(tmp_path / "state"),
            "GFORTH_INSPECT_LOG_DIR": str(tmp_path / "state" / "gforth-inspect"),
        }
        proc = subprocess.run(
            [engine, "inspect.fs", "prog.fs"],
            cwd=tmp_path,
            capture_output=True,
            env=env,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
        )
        logs = sorted((tmp_path / "state").glob("*/stacks.jsonl"))
        if len(logs) > 1:
            raise RuntimeError(f"more than one stacks.jsonl written: {[p.parent.name for p in logs]}")
        # split the bytes on LF only: str.splitlines() also breaks on U+0085,
        # U+2028/9, VT, FF and 0x1c-0x1e, which may sit inside a JSON string
        raw = logs[0].read_bytes() if logs else b""
        lines = [chunk.decode("utf-8", "surrogateescape") for chunk in raw.split(b"\n") if chunk]
        return Run(
            proc.returncode,
            proc.stdout.decode("utf-8", "surrogateescape"),
            proc.stderr.decode("utf-8", "surrogateescape"),
            lines,
        )


def schema() -> dict:
    """contract/stacks-log.schema.json from the same place inspect.fs came from."""
    explicit = os.environ.get("SCHEMA_JSON")
    if explicit:
        return json.loads(Path(explicit).read_text())
    ref = os.environ.get("INSPECT_REF")
    if not ref:
        return json.loads(_worktree_snapshot()[1].read_text())
    fixture = FIXTURE_REFS / ref / "stacks-log.schema.json"
    if fixture.exists():
        return json.loads(fixture.read_text())
    try:
        return json.loads(_git("show", f"{ref}:contract/stacks-log.schema.json"))
    except subprocess.CalledProcessError:
        raise RuntimeError(f"no contract/stacks-log.schema.json at {ref}; set SCHEMA_JSON") from None


if __name__ == "__main__":
    path, provenance = inspect_source()
    print(provenance)
    smoke = run("log-on 1 2 -3 1e .stacks log-off")
    print("rc", smoke.returncode)
    for line in smoke.log_lines:
        print(line)
