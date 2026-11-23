"""One producer run of experiment 009: a sandbox, a seeded workload, an xrid.

Every run gets its own sandbox (cwd, HOME, XDG_STATE_HOME under one
mktemp -d); GFORTH_INSPECT_LOG_DIR points inside it unless `xdg_fallback`
is set, which leaves it unset to exercise the XDG fallback inside the
sandbox.  The xrid is the snapshot `id` (log-id) where the version has
log-id (V2 on); for V0, V1 the log directory is the cross-reference
(RD-2, RD-3).  Standard library only.
"""

from __future__ import annotations

import os
import random
import struct
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

ENGINES = ("gforth", "gforth-fast", "gforth-itc")
ENGINE_SHORT = {"gforth": "g", "gforth-fast": "f", "gforth-itc": "i"}


@dataclass
class Workload:
    lines: list[str]
    data: list[int]          # the true data stack at the first .stacks
    floats: list[float]      # the true float stack at the second .stacks
    snapshots: int           # snapshots the workload writes


def float_literal(value: float) -> str:
    text = repr(value)
    if text == "-0.0":
        return "-0e"
    return text if "e" in text else text + "e0"


def workload(xrid: str, seed: int, tty: bool = False) -> Workload:
    """The program, one line per element.  `tty`: no control bytes (a pane
    would read DEL as backspace and TAB as completion)."""
    rng = random.Random(seed)
    data = [0, -1, 2**63 - 1, -2**63] + [rng.randrange(-2**63, 2**63) for _ in range(4)]
    floats = [-0.0, 1.7976931348623157e308, 0.1, 5e-324]
    while len(floats) < 8:
        value = struct.unpack("<d", rng.getrandbits(64).to_bytes(8, "little"))[0]
        if value == value and abs(value) != float("inf"):
            floats.append(value)
    tail = "" if tty else " \x7f\t"
    lines = [
        f'[defined] log-id [if] s" {xrid}" log-id [then]',
        "log-on",
        " ".join(str(cell) for cell in data) + " .stacks clearstack",
        " ".join(float_literal(value) for value in floats) + " .stacks fclearstack",
        ": w-a ( n -- n n ) dup ~~~ ; 7 w-a 2drop",
        "all-~~ : w-b ( n -- n ) 2* ~~ ; 3 w-b drop",
        '5 .stacks drop \\ q"\\' + tail,
        "log-off",
    ]
    return Workload(lines, data, floats, 4)


@dataclass
class Sandbox:
    root: Path
    xdg_fallback: bool = False
    env: dict[str, str] = field(default_factory=dict)

    @classmethod
    def make(cls, parent: Path, name: str, xdg_fallback: bool = False) -> "Sandbox":
        root = Path(tempfile.mkdtemp(prefix=f"{name}-", dir=parent))
        (root / "home").mkdir()
        (root / "state").mkdir()
        env = {key: value for key, value in os.environ.items()
               if key not in ("GFORTH_INSPECT_LOG_DIR", "XDG_STATE_HOME", "HOME")}
        env.update({"HOME": str(root / "home"), "XDG_STATE_HOME": str(root / "state")})
        if not xdg_fallback:
            env["GFORTH_INSPECT_LOG_DIR"] = str(root / "state" / "logdir")
        return cls(root, xdg_fallback, env)

    def logs(self) -> list[Path]:
        return sorted(self.root.glob("state/*/stacks.jsonl"))

    def expected_log(self) -> Path:
        """Where the contract (CONSUMERS.org) says a 1.1 consumer looks."""
        if not self.xdg_fallback:
            return self.root / "state" / "logdir" / "stacks.jsonl"
        return self.root / "state" / "gforth-inspect" / "stacks.jsonl"


def run_batch(fs_path: Path, engine: str, sandbox: Sandbox, program: list[str],
              timeout: float = 30.0) -> int:
    """Load inspect.fs and prog.fs by relative name from the sandbox; exit status."""
    (sandbox.root / "inspect.fs").write_bytes(fs_path.read_bytes())
    (sandbox.root / "prog.fs").write_bytes(("\n".join(program) + "\nbye\n").encode("utf-8"))
    proc = subprocess.run([engine, "inspect.fs", "prog.fs"], cwd=sandbox.root, env=sandbox.env,
                          capture_output=True, stdin=subprocess.DEVNULL, timeout=timeout)
    (sandbox.root / "gforth.stderr").write_bytes(proc.stderr)
    return proc.returncode


def run_checked(fs_path: Path, engine: str, sandbox: Sandbox, program: list[str], label: str,
                timeout: float = 30.0) -> Path:
    """run_batch, then its one log; a failed run or a missing log raises, never a stale log."""
    status = run_batch(fs_path, engine, sandbox, program, timeout)
    found = sandbox.logs()
    if status != 0 or len(found) != 1:
        raise RuntimeError(f"{label}: exit {status}, {len(found)} logs")
    return found[0]
