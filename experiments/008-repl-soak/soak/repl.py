"""One gforth 0.7.3 REPL on a real pty, typed into a line at a time.

No -e, no piped stdin: gforth sees a terminal, uses its own line editor
and writes ~/.gforth-history (HOME is the sandbox).  After each line the
driver waits for the prompt gforth prints when it is done with a line:
" ok" in interpret state, " compiled" in compile state.  After an error
gforth prints the message (":<line>: <what>", ">>>word<<<", a backtrace)
and no prompt, so an error is recognised by its shape once output has
stopped.  A line still running at its timeout gets ^C (gforth answers
"User interrupt" and returns to the prompt); if even that gets nothing,
the REPL is killed.

The G3 oracle is `soak-o` (targets.ORACLE_DEFS): it prints
"#O <depth> <fdepth> <.s output>#E" in decimal, BASE restored, with
maxdepth-.s raised so .s shows every cell.
"""

from __future__ import annotations

import fcntl
import os
import pty
import re
import select
import signal
import struct
import termios
import time
from dataclasses import dataclass, field
from pathlib import Path

from .targets import ORACLE_RE

BANNER_END = b"Type `bye' to exit\r\n"
ERROR_SHAPE = re.compile(rb"(?:^|\n)[^\r\n]*:-?\d+: [^\r\n]+\r\n(?:[^\r\n]*>>>[^\r\n]*<<<\r\n|Backtrace:)")
OUTPUT_KEEP = 4096
PTY_LOG_CAP = 50_000_000          # after this, only the typed lines are kept


@dataclass
class LineResult:
    text: str
    status: str                    # ok, compiled, error, interrupted, hung, dead
    markers: list = field(default_factory=list)   # [depth, fdepth, [cells]]
    elapsed: float = 0.0
    output: bytes = b""


def parse_markers(output: bytes) -> list:
    markers = []
    for depth, fdepth, count, cells in ORACLE_RE.findall(output):
        markers.append([int(depth), int(fdepth), [int(cell) for cell in cells.split()], int(count)])
    return markers


class Repl:
    def __init__(self, engine: str, sandbox: Path, env: dict, pty_log: Path, args: tuple = ()):
        self.engine = engine
        self.pty_log = open(pty_log, "ab", buffering=0)
        pid, fd = pty.fork()
        if pid == 0:  # the child: gforth, in the sandbox, with only the sandbox's env
            try:
                os.chdir(sandbox)
                os.execvpe(engine, [engine, *args], env)
            finally:
                os._exit(127)
        self.pid, self.fd = pid, fd
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 50, 200, 0, 0))
        self.returncode: int | None = None
        self.buffer = b""

    # --- low level ---------------------------------------------------

    def alive(self) -> bool:
        if self.returncode is not None:
            return False
        try:
            pid, status = os.waitpid(self.pid, os.WNOHANG)
        except ChildProcessError:
            self.returncode = -1
            return False
        if pid:
            self.returncode = os.waitstatus_to_exitcode(status)
            return False
        return True

    def _read(self, timeout: float) -> bytes:
        ready, _, _ = select.select([self.fd], [], [], timeout)
        if not ready:
            return b""
        try:
            chunk = os.read(self.fd, 65536)
        except OSError:
            return b""
        if self.pty_log.tell() < PTY_LOG_CAP:
            self.pty_log.write(chunk)
        return chunk

    def _write(self, data: bytes) -> None:
        self.pty_log.write(b"\n<<< " + data + b"\n")
        while data:
            written = os.write(self.fd, data)
            data = data[written:]

    def wait_banner(self, timeout: float = 20.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.buffer += self._read(0.2)
            if BANNER_END in self.buffer:
                self.buffer = b""
                return True
            if not self.alive():
                return False
        return False

    # --- one line ----------------------------------------------------

    def type_line(self, text: str, timeout: float = 60.0, quiet: float = 0.6) -> LineResult:
        started = time.monotonic()
        self.buffer = b""
        if not self.alive():
            return LineResult(text, "dead")
        self._write(text.encode("utf-8") + b"\r")
        output = b""
        last_output = time.monotonic()
        deadline = started + timeout
        interrupted = False
        while True:
            chunk = self._read(0.1)
            now = time.monotonic()
            if chunk:
                output += chunk
                last_output = now
                if output.endswith(b" ok\r\n") or output.endswith(b"ok\r\n"):
                    status = "interrupted" if interrupted else "ok"
                    break
                if output.endswith(b" compiled\r\n"):
                    status = "compiled"
                    break
                continue
            if not self.alive():
                status = "dead"
                break
            if now - last_output > quiet and ERROR_SHAPE.search(output):
                status = "interrupted" if interrupted else "error"
                break
            if now > deadline:
                if interrupted:
                    status = "hung"
                    break
                self._write(b"\x03")
                interrupted = True
                deadline = now + 10.0
        return LineResult(text, status, parse_markers(output), round(time.monotonic() - started, 3),
                          output[-OUTPUT_KEEP:])

    def close(self, timeout: float = 10.0) -> int | None:
        """bye, then wait; kill if it will not go."""
        if self.alive():
            try:
                self._write(b"bye\r")
            except OSError:
                pass
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline and self.alive():
                self._read(0.1)
        if self.alive():
            self.kill()
        try:
            os.close(self.fd)
        except OSError:
            pass
        self.pty_log.close()
        return self.returncode

    def kill(self) -> None:
        if self.alive():
            try:
                os.kill(self.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                _, status = os.waitpid(self.pid, 0)
                self.returncode = os.waitstatus_to_exitcode(status)
            except ChildProcessError:
                self.returncode = -9
