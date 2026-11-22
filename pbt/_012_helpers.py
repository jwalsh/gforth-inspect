"""Helpers for experiment 012 (experiments/012-log-paths/README.org).

reference   the Python reference of the default log directory, executed
            from its block in contract/stacks-log.org (#+name:
            log-dir-reference), so the published copy is the tested one.
Fixture     one project tree to build under a temp dir: a .git directory,
            a linked worktree's .git file (absolute or relative gitdir:),
            or no repository; HEAD, origin's url, an optional .env.
forth_dirs  build a batch of fixtures and run ONE gforth over them: a
            driver calls (log-dir-for), what log-on uses for the current
            directory, on each fixture's directory and prints the log dir.
forth_cwd   one gforth per fixture, started IN the fixture's directory
            with $PWD set to another fixture (or unset); prints log-where.
            HOME and XDG_STATE_HOME are inside the temp dir, and so is every
            cwd (E-10, #46); nothing is logged.
git_accepts `git check-ref-format --branch`, cached; real git decides which
            generated branch names are kept.
"""

from __future__ import annotations

import functools
import os
import re
import subprocess
import tempfile
import types
from dataclasses import dataclass
from pathlib import Path

import gforth_run

REPO = Path(__file__).resolve().parent.parent
CONTRACT = REPO / "contract" / "stacks-log.org"


def _load_reference() -> types.ModuleType:
    text = CONTRACT.read_text()
    match = re.search(r"#\+name: log-dir-reference\n#\+begin_src python\n(.*?)\n#\+end_src", text, re.S)
    if not match:
        raise RuntimeError("no log-dir-reference block in contract/stacks-log.org")
    module = types.ModuleType("log_dir_reference")
    exec(compile(match.group(1), "stacks-log.org:log-dir-reference", "exec"), module.__dict__)
    return module


reference = _load_reference()


@functools.lru_cache(maxsize=None)
def git_accepts(name: bytes) -> bool:
    """Real git's verdict; names it would rewrite (it prints them back) are refused too."""
    if not name or b"\0" in name:
        return False
    with tempfile.TemporaryDirectory(prefix="gfi-012-git-") as tmp:
        proc = subprocess.run(["git", "check-ref-format", "--branch", name], cwd=tmp,
                              capture_output=True, env={**os.environ, "GIT_CEILING_DIRECTORIES": tmp})
    return proc.returncode == 0 and proc.stdout.rstrip(b"\n") == name


@dataclass(frozen=True)
class Fixture:
    kind: str                 # "main", "linked-abs", "linked-rel", "nogit"
    name: str                 # the root directory's name (the worktree's, when linked)
    main: str                 # the main worktree's directory name (linked kinds)
    config: bytes | None      # the common dir's config file, None for none
    head: bytes | None        # HEAD's content, None for none
    dotenv: bytes | None      # <root>/.env, None for none
    depth: int                # how far below the root the directory is (0..2)


def build(fixture: Fixture, parent: Path) -> bytes:
    """Create the fixture under parent; return its directory as bytes."""
    if fixture.kind in ("linked-abs", "linked-rel"):
        main = parent / fixture.main
        gitdir = main / ".git" / "worktrees" / "w"
        gitdir.mkdir(parents=True)
        (gitdir / "commondir").write_bytes(b"../..\n")
        (main / ".git" / "HEAD").write_bytes(b"ref: refs/heads/main\n")
        root = parent / "wt" / fixture.name
        root.mkdir(parents=True)
        target = os.fsencode(gitdir) if fixture.kind == "linked-abs" \
            else b"../../" + os.fsencode(fixture.main) + b"/.git/worktrees/w"
        (root / ".git").write_bytes(b"gitdir: " + target + b"\n")
        common = main / ".git"
    else:
        root = parent / fixture.name
        root.mkdir(parents=True)
        gitdir = common = root / ".git"
        if fixture.kind == "main":
            gitdir.mkdir()
    if fixture.kind != "nogit":
        if fixture.head is not None:
            (gitdir / "HEAD").write_bytes(fixture.head)
        if fixture.config is not None:
            (common / "config").write_bytes(fixture.config)
    if fixture.dotenv is not None:
        (root / ".env").write_bytes(fixture.dotenv)
    pwd = root
    for _ in range(fixture.depth):
        pwd = pwd / "sub"
    pwd.mkdir(parents=True, exist_ok=True)
    return os.fsencode(pwd)


DRIVER = """\
: next-pwd ( c-addr u -- rest-a rest-u pwd-a pwd-u ) \\ split at the first NUL
    2dup 0 scan dup >r 2swap r> - 2swap dup IF 1 /string THEN 2swap ;
: fixtures ( c-addr u -- ) \\ NUL-terminated directories in, NUL-terminated log dirs out
    BEGIN dup WHILE next-pwd
        0 log-dir# !  depth >r  (log-dir-for)
        depth r> 2 - <> IF ." STACK-CHANGED " THEN
        log-dir log-dir# @ type 0 emit
    REPEAT 2drop ;
base @ s" pwds.bin" slurp-file fixtures base @ <> [IF] .\" BASE-CHANGED\" [THEN]
bye
"""


@dataclass
class Batch:
    pwds: list[bytes]
    forth: list[bytes]
    expected: list[bytes]
    raw: list[tuple]
    base: bytes
    stderr: bytes
    returncode: int


def raw_components(pwd: bytes) -> tuple:
    """What each component is made from, before encoding: (kind, bytes) x 3."""
    ref = reference
    root, has_git = ref.find_root(pwd)
    if not has_git:
        return (("marker", b"_nogit"), ("name", ref.basename(root)), ("marker", b"_"))
    gitdir = ref.git_dir(root)
    common = ref.common_dir(gitdir)
    config = ref.read(common + b"/config")
    url = ref.origin_url(config)
    pair = ref.owner_repo(url) if url is not None else None
    if pair:
        owner = ("marker", b"_") if pair[0] is None else ("name", pair[0])
        repo = ("name", pair[1])
    else:
        owner, repo = ("marker", b"_local"), ("name", ref.main_name(common))
    name = None if ref.reftable(config) else ref.branch(ref.read(gitdir + b"/HEAD"))
    if ref.reftable(config) or name == b".invalid":
        worktree = ("reftable", root)
    elif name is None:
        worktree = ("detached", root)
    else:
        worktree = ("name", name)
    return (owner, repo, worktree)


def forth_dirs(fixtures: list[Fixture], engine: str = "gforth") -> Batch:
    inspect_fs, _ = gforth_run.inspect_source()
    with tempfile.TemporaryDirectory(prefix="gfi-012-") as tmp:
        tmp_path = Path(tmp)
        for sub in ("home", "state"):
            (tmp_path / sub).mkdir()
        pwds = [build(fixture, tmp_path / "fx" / f"f{index}") for index, fixture in enumerate(fixtures)]
        (tmp_path / "pwds.bin").write_bytes(b"".join(pwd + b"\0" for pwd in pwds))
        (tmp_path / "inspect.fs").write_bytes(inspect_fs.read_bytes())
        (tmp_path / "driver.fs").write_text(DRIVER)
        env = {key: value for key, value in os.environ.items()
               if key not in ("GFORTH_INSPECT_LOG_DIR", "PWD")}
        env.update(HOME=str(tmp_path / "home"), XDG_STATE_HOME=str(tmp_path / "state"))
        proc = subprocess.run([engine, "inspect.fs", "driver.fs"], cwd=tmp_path, env=env,
                              capture_output=True, timeout=60, stdin=subprocess.DEVNULL)
        environ = {os.fsencode(key): os.fsencode(value) for key, value in env.items()}
        expected = [reference.log_dir(environ, cwd=pwd) for pwd in pwds]
        raw = [raw_components(pwd) for pwd in pwds]
        # NUL-separated: a log dir may hold LF (a .env value relative to a root named so)
        lines = proc.stdout.split(b"\0")
        forth = lines[:len(pwds)]
        base = environ[b"XDG_STATE_HOME"] + b"/gforth-inspect"
        # temp paths never leave this function: the caller sees them relative
        rel = [_relative(line, tmp_path) for line in forth]
        return Batch([_relative(p, tmp_path) for p in pwds], rel,
                     [_relative(e, tmp_path) for e in expected], raw,
                     _relative(base, tmp_path),
                     proc.stderr + b"".join(lines[len(pwds):]), proc.returncode)


def _relative(path: bytes, tmp_path: Path) -> bytes:
    path = path.replace(os.fsencode(os.path.realpath(tmp_path)), b"$TMP")
    return path.replace(os.fsencode(tmp_path), b"$TMP")


@dataclass
class CwdRun:
    cwd: bytes
    pwd: bytes | None
    forth: bytes
    expected: bytes
    stderr: bytes
    returncode: int


def forth_cwd(fixtures: list[Fixture], pwd_shift: int | None, engine: str = "gforth") -> list[CwdRun]:
    """Each fixture's log dir as log-where prints it, gforth started in that
    fixture's directory with $PWD = the fixture pwd_shift places on (None:
    unset).  The reference is given the physical cwd, as getcwd returns it."""
    inspect_fs, _ = gforth_run.inspect_source()
    runs = []
    with tempfile.TemporaryDirectory(prefix="gfi-012-cwd-") as tmp:
        tmp_path = Path(tmp)
        for sub in ("home", "state"):
            (tmp_path / sub).mkdir()
        (tmp_path / "inspect.fs").write_bytes(inspect_fs.read_bytes())
        dirs = [build(fixture, tmp_path / "fx" / f"f{index}") for index, fixture in enumerate(fixtures)]
        base_env = {key: value for key, value in os.environ.items()
                    if key not in ("GFORTH_INSPECT_LOG_DIR", "PWD")}
        base_env.update(HOME=str(tmp_path / "home"), XDG_STATE_HOME=str(tmp_path / "state"))
        environ = {os.fsencode(key): os.fsencode(value) for key, value in base_env.items()}
        for index, cwd in enumerate(dirs):
            env = dict(base_env)
            pwd = None if pwd_shift is None else dirs[(index + pwd_shift) % len(dirs)]
            if pwd is not None:
                env["PWD"] = os.fsdecode(pwd)
            proc = subprocess.run([engine, os.fsdecode(tmp_path / "inspect.fs"), "-e", "log-where bye"],
                                  cwd=cwd, env=env, capture_output=True, timeout=30,
                                  stdin=subprocess.DEVNULL)
            # log-where prints LF, the path, LF; the path itself may hold LF
            out = proc.stdout
            printed = out[1:-1] if out.startswith(b"\n") and out.endswith(b"\n") else out
            forth = printed[:-len(b"/stacks.jsonl")] if printed.endswith(b"/stacks.jsonl") else printed
            expected = reference.log_dir(environ, cwd=os.fsencode(os.path.realpath(cwd)))
            runs.append(CwdRun(_relative(cwd, tmp_path), None if pwd is None else _relative(pwd, tmp_path),
                               _relative(forth, tmp_path), _relative(expected, tmp_path),
                               proc.stderr, proc.returncode))
    return runs
