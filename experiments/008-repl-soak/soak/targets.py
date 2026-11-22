"""Targets: what the sessions load, and the copies they load it from.

A unit is one thing a person might load at the prompt: a prelude (santa's
elf.fs, say) and one main file.  Every file comes from its commit (`git
show`, read only) or, for a plain directory, from disk, and is copied once
into a read-only pool.  A session hard-links a unit's files into its own
sandbox under t/u<n>-<tree>/ and includes them by that relative path, so
input.file never holds a real path (G7) and two units never share a file.

Probe copies.  The feeder needs a logged point it can check against the
REPL (G3), so a main file is loaded as a copy in which:
- a few top-level blank lines, and one appended last line, hold
  `.stacks soak-o` (a probe);
- for this repository's own inputs, every `.stacks`, `~~~` and `~~` is
  followed by `soak-o`, `log-on` / `log-off` / `bye` are removed and
  `log-id` becomes `2drop`, so the session's xrid tag and its logging stay
  the driver's.
Every other line is byte-identical to the original at the same number, and
the copy records which lines it changed: the xref check (G6) compares
input.text with the copy, and the copy with the original outside those
lines.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, asdict
from pathlib import Path

from . import assets, config

PROBE = b".stacks soak-o"
ORACLE_DEFS = [
    "999 maxdepth-.s !",
    "variable soak-base",
    ': soak-o ( -- ) base @ soak-base ! decimal ." #O " depth 0 .r space fdepth 0 .r space .s ." #E" soak-base @ base ! ;',
]
SNAP_TOKENS = {b".stacks", b"~~~", b"~~"}
DROP_TOKENS = {b"log-on", b"log-off", b"bye", b"(bye)"}
NAMING = {b":", b"'", b"[']", b"postpone", b"[compile]", b"defer", b"is", b"create",
          b"variable", b"constant", b"value", b"alias", b"to", b"marker"}
UNSAFE_INPUTS = re.compile(rb"\bdbg\b|\bdbg\+|\bkey\b|\bekey\b|\baccept\b|\bsystem\b|getenv|included|"
                           rb"\\ test: (skip|stdin|noinspect|load|env|unset|exit)")


@dataclass
class FileCopy:
    rel: str                 # path inside the unit dir
    origin: dict             # {target, tree, commit, path}: where it came from
    orig_blob: str
    copy_blob: str
    modified: list = field(default_factory=list)  # 1-based line numbers changed in the copy


@dataclass
class Unit:
    uid: str
    target: str              # L, C, S, R
    tree: str                # anonymised worktree / ref label, e.g. S07, Rmain
    prelude: list            # rel paths, included first
    main: str                # rel path of the probed file
    files: list              # FileCopy, every file linked into the unit dir
    setup: list = field(default_factory=list)    # lines typed before the prelude
    engines: list = field(default_factory=list)  # where the preflight passed
    markers: dict = field(default_factory=dict)  # engine -> probes seen in the preflight

    def to_json(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_json(data: dict) -> "Unit":
        data = dict(data)
        data["files"] = [FileCopy(**item) for item in data["files"]]
        return Unit(**data)


# --- the probe rewrite --------------------------------------------------


def _scan(line: bytes, state: dict) -> list[tuple[int, int, bytes]]:
    """Tokens of `line` outside comments and strings, as (start, end, token);
    updates the colon/paren state carried between lines."""
    tokens = []
    position, length = 0, len(line)
    previous = b""
    while position < length:
        while position < length and line[position] in b" \t":
            position += 1
        if position >= length:
            break
        end = position
        while end < length and line[end] not in b" \t":
            end += 1
        token = line[position:end]
        lower = token.lower()
        if state["paren"]:
            close = line.find(b")", position)
            if close < 0:
                return tokens
            state["paren"] = False
            position = close + 1
            continue
        if lower in (b"\\", b"\\g"):
            return tokens
        if lower in (b"(", b".("):
            close = line.find(b")", end)
            if close < 0:
                state["paren"] = lower == b"("
                return tokens
            position = close + 1
            continue
        if lower.endswith(b'"') and lower in (b'."', b's"', b'c"', b'abort"', b',"', b'.\\"', b's\\"'):
            close = line.find(b'"', end + 1)
            position = (close + 1) if close >= 0 else length
            continue
        if lower in (b"char", b"[char]"):
            position = end
            while position < length and line[position] in b" \t":
                position += 1
            while position < length and line[position] not in b" \t":
                position += 1
            continue
        if previous not in NAMING:
            tokens.append((position, end, lower))
        if lower in (b":", b":noname") and previous not in NAMING:
            state["colon"] = True
        elif lower == b";" or lower.startswith(b";"):
            state["colon"] = False
        previous = lower
        position = end
    return tokens


def probe_copy(original: bytes, blank_probes: int, inputs_rewrite: bool) -> tuple[bytes, list[int]]:
    """(copy, modified line numbers).  See the module docstring."""
    lines = original.split(b"\n")
    trailing_newline = original.endswith(b"\n")
    if trailing_newline:
        lines = lines[:-1]
    state = {"colon": False, "paren": False}
    modified: list[int] = []
    sites: list[int] = []
    for index, line in enumerate(lines):
        if not line.strip() and not state["colon"] and not state["paren"]:
            sites.append(index)
        tokens = _scan(line, state)
        if inputs_rewrite and tokens:
            pieces, cursor, changed = [], 0, False
            for start, end, token in tokens:
                if token in DROP_TOKENS:
                    pieces += [line[cursor:start]]
                    cursor, changed = end, True
                elif token == b"log-id":
                    pieces += [line[cursor:start], b"2drop"]
                    cursor, changed = end, True
                elif token in SNAP_TOKENS:
                    pieces += [line[cursor:end], b" soak-o"]
                    cursor, changed = end, True
            if changed:
                pieces.append(line[cursor:])
                lines[index] = b"".join(pieces)
                modified.append(index + 1)
    if blank_probes and sites:
        step = max(1, len(sites) // blank_probes)
        for index in sites[::step][:blank_probes]:
            lines[index] = PROBE
            modified.append(index + 1)
    lines.append(PROBE)
    modified.append(len(lines))
    copy = b"\n".join(lines) + b"\n"
    return copy, sorted(set(modified))


# --- enumerating the targets --------------------------------------------


class GitReader:
    """Read-only access to one repository's objects: ls-tree and one
    long-lived `git cat-file --batch`, with blobs cached by id."""

    def __init__(self, repo: Path):
        self.repo = repo
        self.batch = subprocess.Popen(["git", "-C", str(repo), "cat-file", "--batch"],
                                      stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        self.cache: dict = {}

    def head(self, ref: str = "HEAD") -> str:
        return subprocess.run(["git", "-C", str(self.repo), "rev-parse", ref], check=True,
                              capture_output=True, text=True).stdout.strip()

    def files(self, commit: str, prefix: str = "") -> dict:
        """{path: blob id} for the files under prefix at commit."""
        out = subprocess.run(["git", "-C", str(self.repo), "ls-tree", "-r", commit, "--", prefix or "."],
                             check=True, capture_output=True, text=True).stdout
        found = {}
        for line in out.splitlines():
            meta, _, path = line.partition("\t")
            mode, kind, blob = meta.split()
            if kind == "blob":
                found[path] = blob
        return found

    def blob(self, blob: str) -> bytes:
        if blob not in self.cache:
            self.batch.stdin.write(blob.encode() + b"\n")
            self.batch.stdin.flush()
            header = self.batch.stdout.readline().split()
            size = int(header[2])
            data = self.batch.stdout.read(size)
            self.batch.stdout.read(1)
            self.cache[blob] = data
        return self.cache[blob]

    def close(self) -> None:
        self.batch.stdin.close()
        self.batch.wait()


def _worktrees(main: Path) -> list[Path]:
    """The main worktree and its siblings, from `git worktree list` (read only)."""
    out = subprocess.run(["git", "-C", str(main), "worktree", "list", "--porcelain"],
                         check=True, capture_output=True, text=True).stdout
    paths = [Path(line[len("worktree "):]) for line in out.splitlines() if line.startswith("worktree ")]
    return sorted(paths, key=lambda path: (path != main, str(path)))


class Pool:
    """Read-only copies, by blob, under one directory."""

    def __init__(self, root: Path):
        self.root = root
        (root / "blobs").mkdir(parents=True, exist_ok=True)

    def put(self, data: bytes) -> str:
        blob = assets.blob_of_bytes(data)
        path = self.path(blob)
        if not path.exists():
            temporary = path.with_suffix(".tmp")
            temporary.write_bytes(data)
            os.chmod(temporary, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
            os.replace(temporary, path)
        return blob

    def path(self, blob: str) -> Path:
        return self.root / "blobs" / f"{blob}.fs"

    def get(self, blob: str) -> bytes:
        return self.path(blob).read_bytes()


def _unit_id(target: str, tree: str, main: str, prelude: list) -> str:
    digest = hashlib.sha1(json.dumps([target, tree, main, prelude]).encode()).hexdigest()[:10]
    return f"{target}-{digest}"


def enumerate_units(entries: list, pool: Pool, candidate_commit: str) -> tuple[list[Unit], dict]:
    """Every unit of every target, and a private map of tree labels to places."""
    units: list[Unit] = []
    trees: dict = {}   # label -> {kind, path, commit}: local only, never committed
    probes: dict = {}  # (orig blob, blank probes, rewrite) -> (copy blob, modified)

    def probed(data: bytes, blank: int, rewrite: bool) -> tuple[str, list]:
        key = (assets.blob_of_bytes(data), blank, rewrite)
        if key not in probes:
            copy, modified = probe_copy(data, blank, rewrite)
            probes[key] = (pool.put(copy), modified)
        return probes[key]

    for entry in entries:
        if entry.kind == "lib":
            tree = entry.label
            trees[tree] = {"kind": "lib", "path": str(entry.path), "commit": None}
            originals = {str(path.relative_to(entry.path)): path.read_bytes()
                         for path in sorted(entry.path.rglob("*.fs"))}
            support = {rel: pool.put(data) for rel, data in originals.items()}
            origin = lambda rel: {"target": entry.label, "tree": tree, "commit": None, "path": rel}  # noqa: E731
            for rel, data in originals.items():
                copy_blob, modified = probed(data, 3, False)
                files = [FileCopy(other, origin(other), support[other], support[other])
                         for other in originals if other != rel]
                files.append(FileCopy(rel, origin(rel), support[rel], copy_blob, modified))
                units.append(Unit(_unit_id(entry.label, tree, rel, []), entry.label, tree, [], rel, files))
        elif entry.kind == "course":
            reader = GitReader(entry.path)
            commit = reader.head()
            tree = entry.label
            trees[tree] = {"kind": "course", "path": str(entry.path), "commit": commit}
            for rel, blob in reader.files(commit, entry.options.get("subdir", "")).items():
                # the exercises only: the course's own env/ (its copy of the
                # inspector) is not something a student loads as an exercise
                if not rel.endswith(".fs") or "/env/" in f"/{rel}":
                    continue
                data = reader.blob(blob)
                copy_blob, modified = probed(data, 3, False)
                files = [FileCopy(rel, {"target": entry.label, "tree": tree, "commit": commit, "path": rel},
                                  pool.put(data), copy_blob, modified)]
                units.append(Unit(_unit_id(entry.label, tree, rel, []), entry.label, tree, [], rel, files))
            reader.close()
        elif entry.kind == "santa":
            reader = GitReader(entry.path)   # the worktrees share one object store
            worktrees = _worktrees(entry.path) if entry.options.get("worktrees") == "yes" else [entry.path]
            for number, worktree in enumerate(worktrees):
                tree = f"{entry.label}{number:02d}"
                commit = subprocess.run(["git", "-C", str(worktree), "rev-parse", "HEAD"], check=True,
                                        capture_output=True, text=True).stdout.strip()
                trees[tree] = {"kind": "santa", "path": str(worktree), "commit": commit}
                tracked = {rel: blob for rel, blob in reader.files(commit).items() if rel.endswith(".fs")}
                if "src/elf.fs" not in tracked:
                    continue
                origin = lambda rel: {"target": entry.label, "tree": tree, "commit": commit, "path": rel}  # noqa: E731

                def plain(rel: str) -> FileCopy:
                    blob = pool.put(reader.blob(tracked[rel]))
                    return FileCopy(rel, origin(rel), blob, blob)

                elf_file = plain("src/elf.fs")
                variants = [([], [elf_file])]
                if "src/repl.fs" in tracked:
                    variants.append(([], [elf_file, plain("src/repl.fs")]))
                if "src/solve.fs" in tracked:   # as the Makefile's toy target loads it
                    solve_file = plain("src/solve.fs")
                    variants.append((["false constant reuse?"], [elf_file, solve_file]))
                    variants.append((["true constant reuse?"], [elf_file, solve_file]))
                for rel, blob in tracked.items():
                    if rel.startswith("src/"):
                        continue
                    data = reader.blob(blob)
                    copy_blob, modified = probed(data, 2, False)
                    main = FileCopy(rel, origin(rel), pool.put(data), copy_blob, modified)
                    for setup, prelude in variants:
                        names = [item.rel for item in prelude]
                        units.append(Unit(_unit_id(entry.label, tree, rel, setup + names), entry.label, tree,
                                          names, rel, prelude + [main], setup=setup))
            reader.close()
        elif entry.kind == "inputs":
            reader = GitReader(entry.path)
            dirs = entry.options.get("dirs", "corpus").split(",")
            for ref in entry.options.get("refs", "main").split(","):
                commit = reader.head(candidate_commit if ref == "CANDIDATE" else ref)
                tree = f"{entry.label}{'cand' if ref == 'CANDIDATE' else ref[:7]}"
                trees[tree] = {"kind": "inputs", "path": "(this repository)", "commit": commit}
                tracked = {rel: blob for d in dirs for rel, blob in reader.files(commit, d).items()
                           if rel.endswith(".fs")}
                copies = {}
                for rel, blob in tracked.items():
                    data = reader.blob(blob)
                    copy_blob, modified = probed(data, 0, True)
                    copies[rel] = FileCopy(rel, {"target": entry.label, "tree": tree, "commit": commit, "path": rel},
                                           pool.put(data), copy_blob, modified)
                for rel in tracked:
                    if "/lib/" in rel or UNSAFE_INPUTS.search(pool.get(copies[rel].orig_blob)):
                        continue
                    units.append(Unit(_unit_id(entry.label, tree, rel, []), entry.label, tree, [], rel,
                                      list(copies.values())))
            reader.close()
    return units, trees


# --- linking a unit into a sandbox --------------------------------------


def link_unit(unit: Unit, pool: Pool, sandbox: Path, unit_dir: str) -> list[str]:
    """Hard-link the unit's files under sandbox/unit_dir; returns the include
    paths (relative to the sandbox), prelude first."""
    base = sandbox / unit_dir
    for item in unit.files:
        destination = base / item.rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(pool.path(item.copy_blob), destination)
        except OSError:
            shutil.copyfile(pool.path(item.copy_blob), destination)
    return [f"{unit_dir}/{rel}" for rel in unit.prelude] + [f"{unit_dir}/{unit.main}"]


# --- the preflight -------------------------------------------------------


def minimal_env(sandbox: Path, log_dir: Path | None) -> dict:
    env = {
        "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
        "HOME": str(sandbox),
        "XDG_STATE_HOME": str(sandbox / "state"),
        "TERM": "xterm",
        "LANG": "en_US.UTF-8",
        "TMPDIR": str(sandbox / "tmp"),
    }
    if log_dir is not None:
        env["GFORTH_INSPECT_LOG_DIR"] = str(log_dir)
    return env


ORACLE_RE = re.compile(rb"#O (-?\d+) (-?\d+) <(-?\d+)> ((?:-?\d+ )*)#E")


def _preflight_one(unit: Unit, engine: str, pool: Pool, inspect_fs: Path, scratch: Path) -> dict:
    sandbox = Path(tempfile.mkdtemp(prefix="pre-", dir=scratch))
    try:
        (sandbox / "env").mkdir()
        (sandbox / "tmp").mkdir()
        shutil.copyfile(inspect_fs, sandbox / "env" / "inspect.fs")
        includes = link_unit(unit, pool, sandbox, "t/u0")
        program = "\n".join(ORACLE_DEFS + ['s" pre" log-id', "log-on", "all-~~", "marker soak-pre"]
                            + unit.setup + [f"include {path}" for path in includes]
                            + ["soak-pre", "decimal clearstack fclearstack 3 ~~ soak-o",
                               "clearstack 1 2 .stacks soak-o", "bye", ""])
        (sandbox / "pre.fs").write_text(program)
        started = time.monotonic()
        try:
            proc = subprocess.run([engine, "env/inspect.fs", "pre.fs"], cwd=sandbox, capture_output=True,
                                  env=minimal_env(sandbox, sandbox / "log"), stdin=subprocess.DEVNULL, timeout=20)
        except subprocess.TimeoutExpired:
            return {"ok": False, "why": "timeout"}
        elapsed = time.monotonic() - started
        markers = ORACLE_RE.findall(proc.stdout)
        log_path = sandbox / "log" / "stacks.jsonl"
        lines = [line for line in log_path.read_bytes().split(b"\n") if line] if log_path.exists() else []
        if proc.returncode != 0:
            return {"ok": False, "why": f"exit {proc.returncode}"}
        if not markers or markers[-1] != (b"2", b"0", b"2", b"1 2 "):
            return {"ok": False, "why": "no final marker"}
        if len(lines) != 1 + len(markers):
            return {"ok": False, "why": f"{len(lines)} log lines for {len(markers)} markers"}
        if len(proc.stdout) > 2_000_000 or elapsed > 10:
            return {"ok": False, "why": "too big or slow"}
        for line in lines:
            json.loads(line)
        return {"ok": True, "markers": len(markers) - 2, "elapsed": round(elapsed, 3)}
    except Exception as error:  # a unit that cannot be judged is not used
        return {"ok": False, "why": f"{type(error).__name__}: {error}"}
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)


def _content_key(unit: Unit, engine: str, inspect_blob: str) -> str:
    material = json.dumps(["pre-2", engine, inspect_blob, unit.setup, unit.prelude, unit.main,
                           sorted((item.rel, item.copy_blob) for item in unit.files)])
    return hashlib.sha1(material.encode()).hexdigest()


def preflight(units: list[Unit], pool: Pool, inspect_fs: Path, cache_path: Path, scratch: Path,
              workers: int = 8, log=print) -> None:
    """Fill unit.engines: the engines on which the unit loads cleanly."""
    inspect_blob = assets.blob_of(inspect_fs)
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    jobs = {}
    for unit in units:
        for engine in config.ENGINES:
            key = _content_key(unit, engine, inspect_blob)
            if key not in cache and key not in jobs:
                jobs[key] = (unit, engine)
    log(f"preflight: {len(units)} units, {len(jobs)} new (unit, engine) runs, {len(cache)} cached")
    scratch.mkdir(parents=True, exist_ok=True)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {key: executor.submit(_preflight_one, unit, engine, pool, inspect_fs, scratch)
                   for key, (unit, engine) in jobs.items()}
        for done, (key, future) in enumerate(futures.items(), 1):
            cache[key] = future.result()
            if done % 200 == 0:
                log(f"preflight: {done}/{len(futures)}")
                cache_path.write_text(json.dumps(cache))
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(cache))
    for unit in units:
        unit.engines, unit.markers = [], {}
        for engine in config.ENGINES:
            result = cache[_content_key(unit, engine, inspect_blob)]
            if result.get("ok"):
                unit.engines.append(engine)
                unit.markers[engine] = result["markers"]
