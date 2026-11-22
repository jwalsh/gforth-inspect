"""Live producer sessions of experiment 009: one tmux session per producer slot.

A session is named gforth-inspect-009-<session xrid> and runs /bin/sh in
its own sandbox (cwd, HOME, XDG_STATE_HOME; GFORTH_INSPECT_LOG_DIR unless
the slot exercises the XDG fallback).  The pane's output goes to
<sandbox>/pane.log through pipe-pane, and that file is what this module
reads: never capture-pane, and never any session it did not create.

Text is typed with `send-keys -l --` (literal: a trailing ";" or a leading
"-3" is not parsed by tmux) and Enter is sent on its own.  A line is done
when gforth prints the acknowledgement `ACK<n>`, which the typed text never
contains (it types `s" ACK" type <n> 0 .r`).  gforth is started from the
shell and left with `bye`; the shell prompt is `[sh-ready] `.
"""

from __future__ import annotations

import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

PREFIX = "gforth-inspect-009-"
PROMPT = "[sh-ready] "


def tmux(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["tmux", *args], capture_output=True, text=True, check=check)


@dataclass
class Session:
    name: str
    sandbox: Path
    env: dict[str, str]
    acks: int = 0
    prompts_seen: int = 0

    @classmethod
    def start(cls, sxrid: str, sandbox: Path, env: dict[str, str]) -> "Session":
        name = PREFIX + sxrid
        if not name.startswith(PREFIX):
            raise ValueError(name)
        assignments = [f"{key}={value}" for key, value in env.items()
                       if key in ("PATH", "HOME", "XDG_STATE_HOME", "GFORTH_INSPECT_LOG_DIR", "TERM", "LANG")]
        command = ["env", "-i", *assignments, f"PS1={PROMPT}", "/bin/sh"]
        tmux("new-session", "-d", "-s", name, "-x", "400", "-y", "50", "-c", str(sandbox),
             " ".join(_quote(part) for part in command))
        (sandbox / "pane.log").touch()
        tmux("pipe-pane", "-t", name, "-o", f"cat >> {_quote(str(sandbox / 'pane.log'))}")
        session = cls(name, sandbox, env)
        session._wait_prompt()
        return session

    def pane(self) -> str:
        return (self.sandbox / "pane.log").read_bytes().decode("utf-8", "replace")

    def _type(self, text: str) -> None:
        if text:
            tmux("send-keys", "-t", self.name, "-l", "--", text)
        tmux("send-keys", "-t", self.name, "Enter")

    def _wait(self, predicate, timeout: float, what: str) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate(self.pane()):
                return
            time.sleep(0.03)
        raise TimeoutError(f"{self.name}: no {what} in {timeout}s")

    def _wait_prompt(self, timeout: float = 10.0) -> None:
        target = self.prompts_seen + 1
        self._wait(lambda text: text.count(PROMPT) >= target, timeout, "shell prompt")
        self.prompts_seen = self.pane().count(PROMPT)

    def run_gforth(self, engine: str, fs_name: str, lines: list[str], timeout: float = 15.0) -> None:
        """Start `engine fs_name` in the pane, type every line, then bye."""
        self.acks += 1
        banner_ack = self.acks
        self._type(f"{engine} {fs_name}")
        self._ack(banner_ack, timeout)
        for line in lines:
            self._type(line)
            self.acks += 1
            self._ack(self.acks, timeout)
        self._type("bye")
        self._wait_prompt(timeout)

    def _ack(self, number: int, timeout: float) -> None:
        self._type(f's" ACK" type {number} 0 .r')
        pattern = re.compile(rf"ACK{number}(?!\d)")
        self._wait(lambda text: pattern.search(text) is not None, timeout, f"ACK{number}")

    def kill(self) -> None:
        tmux("kill-session", "-t", self.name, check=False)


def _quote(text: str) -> str:
    return "'" + text.replace("'", "'\\''") + "'"


def ours() -> list[str]:
    proc = tmux("list-sessions", "-F", "#{session_name}", check=False)
    return [name for name in proc.stdout.split() if name.startswith(PREFIX)]


def kill_ours() -> None:
    for name in ours():
        tmux("kill-session", "-t", name, check=False)
