"""Helpers for experiment 004.  gforth_run.py is shared and is not edited.

Two sides are compared:
  old  inspect.fs at OLD_REF (18ebe2d, the copy the course runs today)
  new  INSPECT_FS if set (a planted copy), else INSPECT_REF if set, else
       NEW_REF (fc283da, harden's head when 004 ran; pinned, not the
       moving `harden` name)

gforth_run reads its environment on every call, so a side is selected by
setting INSPECT_FS / INSPECT_REF / SCHEMA_JSON around the call.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import tempfile
from pathlib import Path

import gforth_run

OLD_REF = "18ebe2d"
NEW_REF = "fc283da"
SELECTORS = ("INSPECT_FS", "INSPECT_REF", "SCHEMA_JSON")


@contextlib.contextmanager
def side_env(side: str):
    """Within the block, gforth_run sees the environment of `side`."""
    saved = {name: os.environ.get(name) for name in SELECTORS}
    try:
        if side == "old":
            for name in SELECTORS:
                os.environ.pop(name, None)
            os.environ["INSPECT_REF"] = OLD_REF
        elif not os.environ.get("INSPECT_FS") and not os.environ.get("INSPECT_REF"):
            os.environ["INSPECT_REF"] = NEW_REF
        yield
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def provenance(side: str) -> str:
    with side_env(side):
        _, prov = gforth_run.inspect_source()
    # INSPECT_FS gives an absolute path; keep only the file name (public repo)
    if prov.startswith("file:"):
        path_part, digest = prov[len("file:"):].rsplit(" ", 1)
        prov = f"file:{Path(path_part).name} {digest}"
    return prov


def run(side: str, program: str, timeout: float = 30.0) -> gforth_run.Run:
    with side_env(side):
        return gforth_run.run(program, timeout=timeout)


def schema(side: str) -> dict:
    with side_env(side):
        return gforth_run.schema()


LAST_DEFAULT_CWD: str | None = None  # the physical cwd of the last run_default_location


def run_default_location(side: str, program: str) -> dict[str, bytes]:
    """Run with GFORTH_INSPECT_LOG_DIR unset, so inspect.fs falls back to its
    default.  cwd (<tmp>/proj, since 0.3.0 the default is per project:
    _nogit/proj/_), XDG_STATE_HOME and HOME are fresh temp dirs.  Returns every
    file written under XDG_STATE_HOME, keyed by its path relative to it
    (prefixed `state/`), so the caller sees where the log went.
    """
    with side_env(side):
        inspect_fs, _ = gforth_run.inspect_source()
    with tempfile.TemporaryDirectory(prefix="gfi-004-") as tmp:
        tmp_path = Path(tmp)
        (tmp_path / "inspect.fs").write_bytes(inspect_fs.read_bytes())
        (tmp_path / "prog.fs").write_text(program + "\nbye\n")
        (tmp_path / "home").mkdir()
        (tmp_path / "proj").mkdir()
        global LAST_DEFAULT_CWD
        LAST_DEFAULT_CWD = os.path.realpath(tmp_path / "proj")
        env = {key: value for key, value in os.environ.items() if key != "GFORTH_INSPECT_LOG_DIR"}
        env["XDG_STATE_HOME"] = str(tmp_path / "state")
        env["HOME"] = str(tmp_path / "home")
        subprocess.run(["gforth", "../inspect.fs", "../prog.fs"], cwd=tmp_path / "proj", env=env,
                       capture_output=True, timeout=30, stdin=subprocess.DEVNULL, check=False)
        written = {}
        for root in ("state", "home"):
            for path in sorted((tmp_path / root).rglob("*")):
                if path.is_file():
                    written[str(path.relative_to(tmp_path))] = path.read_bytes()
        return written
