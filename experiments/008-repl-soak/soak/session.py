"""One soak session: a sandbox, a driven REPL, its followers, its checks.

The session's xrid is its log-id (RD-2): every snapshot it writes carries
it, and call.json, keyed by it, records the call (ref SHA, inspect.fs
blob, engine, units, cwd, seed).

Sandbox (one `mktemp -d` per session; it is also HOME and the cwd):
    env/                the seven release assets, installed (variant "installed")
    inspect.fs          the candidate's blob straight from its commit ("source")
    env-old/inspect.fs  the older ref, for the session that upgrades ("older")
    .claude/skills/gforth-inspect/SKILL.md
    state/              XDG_STATE_HOME; the log is state/gforth-inspect/ when
    log/                GFORTH_INSPECT_LOG_DIR is set (half the sessions)
    t/u<k>-<tree>/...   the units' files, hard links into the read-only pool
"""

from __future__ import annotations

import json
import random
import re
import shutil
import tempfile
import time
from pathlib import Path

from . import assets, checks, config, targets
from .followers import Followers
from .repl import Repl

CALLABLE_ARG = re.compile(r"^(n|u|x|k|m|i|j|a|b|c|n\d|u\d|x\d|k\d|w|y|z|count|limit|len|base|exp|e)$")


def callable_words(source: bytes) -> list[tuple[str, int]]:
    """Colon words whose stack comment takes only small numbers."""
    found = []
    for match in re.finditer(rb"(?m)^\s*:\s+(\S+)\s+\(\s*([^)\n]*?)--", source):
        name = match.group(1).decode("utf-8", "replace")
        args = match.group(2).decode("utf-8", "replace").split()
        if "F:" in match.group(2).decode("utf-8", "replace") or len(args) > 4:
            continue
        if name.lower().startswith("soak") or not all(CALLABLE_ARG.match(arg.lower()) for arg in args):
            continue
        found.append((name, len(args)))
    return found


class Feeder:
    """What a person might type: blocks of lines, each inside a marker so a
    long session's dictionary does not grow."""

    def __init__(self, rng: random.Random, units: list, long_lived: bool, pool):
        self.rng, self.units, self.long_lived, self.pool = rng, units, long_lived, pool
        self.block = 0
        self.serial = 100000

    def next_serial(self) -> int:
        self.serial += 1
        return self.serial

    def block_lines(self) -> tuple[list[dict], object]:
        """(steps, unit or None).  A step is {"text", "kind"}."""
        self.block += 1
        if self.units and self.rng.random() < 0.6:
            unit = self.rng.choice(self.units)
            return self._target_block(unit), unit
        return self._typed_block(), None

    def _probe(self, extra: str = "") -> dict:
        cells = " ".join(str(self.rng.randint(-999, 999)) for _ in range(self.rng.randint(0, 4)))
        return {"text": f"{self.next_serial()} {cells} {extra}.stacks soak-o".replace("  ", " "), "kind": "probe"}

    def _target_block(self, unit) -> list[dict]:
        k = self.block
        steps = [{"text": f"marker soak-u{k}", "kind": "marker"},
                 {"text": "decimal clearstack fclearstack", "kind": "misc"}]
        steps += [{"text": line, "kind": "setup"} for line in unit.setup]
        steps.append({"text": "", "kind": "include", "unit": unit})   # expanded by the session
        if not self.long_lived and unit.target in ("C", "S"):
            main = next(item for item in unit.files if item.rel == unit.main)
            words = callable_words(self.pool.get(main.copy_blob))
            for name, count in self.rng.sample(words, min(len(words), self.rng.randint(0, 3))):
                args = " ".join(str(self.rng.randint(1, 9)) for _ in range(count))
                steps.append({"text": f"{args} {name}".strip(), "kind": "call"})
                steps.append({"text": ".stacks soak-o", "kind": "probe"})
                steps.append({"text": "clearstack fclearstack", "kind": "misc"})
        steps.append(self._probe())
        steps.append({"text": "clearstack fclearstack", "kind": "misc"})
        steps.append({"text": f"soak-u{k}", "kind": "forget"})
        return steps

    def _typed_block(self) -> list[dict]:
        k, rng = self.block, self.rng
        a, b = rng.randint(2, 9), rng.randint(1, 50)
        op = rng.choice(["+", "-", "*", "max", "min", "xor"])
        pool = [
            [self._probe()],
            [{"text": f": soak-d{k} ( n -- n' ) dup {a} * ~~~ soak-o {op} ;", "kind": "def"},
             {"text": f"{self.next_serial()} {b} soak-d{k} .stacks soak-o", "kind": "probe"}],
            [{"text": f": soak-m{k} ( n -- n )", "kind": "def"},
             {"text": f"  dup {a} + ~~~ soak-o", "kind": "def"},
             {"text": "  drop ;", "kind": "def"},
             {"text": f"{self.next_serial()} soak-m{k} .stacks soak-o", "kind": "probe"}],
            [{"text": f": soak-t{k} 2* ~~ soak-o ;", "kind": "def"},
             {"text": f"{self.next_serial()} {b} soak-t{k} .stacks soak-o", "kind": "probe"}],
            [{"text": f"{self.next_serial()} {b} ~~ soak-o", "kind": "probe"}],
            [{"text": f"{self.next_serial()} 1.5e -0.25e {b}e 3e f/ .stacks soak-o", "kind": "probe"},
             {"text": "fclearstack", "kind": "misc"}],
            [{"text": f"hex {self.next_serial():x} ff -1 decimal .stacks soak-o", "kind": "probe"}],
            [{"text": "rs-full on", "kind": "misc"},
             {"text": f": soak-r{k} ( n -- n ) ~~~ soak-o 1+ ;", "kind": "def"},
             {"text": f": soak-q{k} ( n -- n ) soak-r{k} ~~~ soak-o ;", "kind": "def"},
             {"text": f"{self.next_serial()} soak-q{k} .stacks soak-o", "kind": "probe"},
             {"text": "rs-full off", "kind": "misc"}],
            [{"text": f"{self.next_serial()} " + " ".join(str(rng.randint(-10**6, 10**6)) for _ in range(rng.randint(20, 120)))
              + " .stacks soak-o", "kind": "probe"},
             {"text": "clearstack", "kind": "misc"}],
            [{"text": f"{self.next_serial()} soak-nosuch{k}", "kind": "error"}],
            [self._probe(), {"text": f"{self.next_serial()} .stacks soak-o \\ héllo € \U0001d11e \"q\" \\\\", "kind": "probe"}],
            [{"text": f"{self.next_serial()} -9223372036854775808 9223372036854775807 .stacks soak-o", "kind": "probe"},
             {"text": "clearstack", "kind": "misc"}],
        ]
        chosen = rng.sample(pool, rng.randint(2, 5))
        steps = [{"text": f"marker soak-u{k}", "kind": "marker"}]
        for group in chosen:
            steps += group
        if rng.random() < 0.5:
            steps.append({"text": "clearstack fclearstack", "kind": "misc"})
        steps.append({"text": f"soak-u{k}", "kind": "forget"})
        return steps


class Session:
    def __init__(self, run, xrid: str, slot: int, engine: str, variant: str, log_mode: str,
                 long_lived: bool, seed: int, lifetime: float | None, follower_pin: str = config.CONTRACT_EXPECTED,
                 checker_args: tuple = (), sandbox: Path | None = None, inspect_override: bytes | None = None,
                 custom_inspect: bytes | None = None, env_patch: dict | None = None, absolute_includes: bool = False):
        self.run, self.xrid, self.slot, self.engine = run, xrid, slot, engine
        self.variant, self.log_mode, self.long_lived = variant, log_mode, long_lived
        self.seed, self.rng = seed, random.Random(seed)
        self.started = time.time()
        self.deadline = None if lifetime is None else self.started + lifetime
        self.dir = run.run_dir / "sessions" / xrid
        self.dir.mkdir(parents=True)
        self.sandbox = sandbox or Path(tempfile.mkdtemp(prefix=f"{xrid}-", dir=run.tmp))
        self.logging = False
        self.line_number = 0
        self.records_seen = 0
        self.last_growth = time.time()
        self.stall_reported = False
        self.state = "starting"
        self.violations = 0
        self.units_loaded = 0
        self.upgraded = False
        self.follower_pin, self.checker_args = follower_pin, checker_args
        self.inspect_override = inspect_override    # calibration: the file is not the manifest's blob
        self.custom_inspect = custom_inspect        # calibration: a planted producer, named in the manifest
        self.env_patch = env_patch or {}            # calibration: e.g. the real HOME of a fake user
        self.absolute_includes = absolute_includes  # calibration: G7
        self.transcript = open(self.dir / "transcript.jsonl", "a")
        self.files_log = open(self.dir / "files.jsonl", "a")
        self.entries: list = []
        self.repl: Repl | None = None
        self.followers: Followers | None = None
        units = [unit for unit in run.units if engine in unit.engines]
        self.feeder = Feeder(self.rng, units, long_lived, run.pool)
        self.pending: list = []
        self._follower_kinds: set = set()

    # --- setting up ----------------------------------------------------

    def _install(self) -> list[dict]:
        sandbox = self.sandbox
        (sandbox / "tmp").mkdir(exist_ok=True)
        plan = []
        install = assets.install(self.run.dist, sandbox)
        self.install = install
        if not (install["sha256sums_ok"] and install["skill_ok"] and install["inspect_blob"] == self.run.candidate_blob):
            self.run.report(checks.violation("G8", self.xrid, f"install check failed: {json.dumps(install)[:300]}"))
        if self.variant == "installed":
            plan.append({"path": "env/inspect.fs", "blob": self.run.candidate_blob, "ref": self.run.candidate_commit})
        elif self.variant == "source":
            (sandbox / "inspect.fs").write_bytes(self.run.candidate_source)
            plan.append({"path": "inspect.fs", "blob": self.run.candidate_blob, "ref": self.run.candidate_commit})
        elif self.variant == "custom":
            (sandbox / "custom").mkdir()
            (sandbox / "custom" / "inspect.fs").write_bytes(self.custom_inspect)
            plan.append({"path": "custom/inspect.fs", "blob": assets.blob_of_bytes(self.custom_inspect),
                         "ref": "planted"})
        elif self.variant == "older":
            (sandbox / "env-old").mkdir()
            (sandbox / "env-old" / "inspect.fs").write_bytes(self.run.older_source)
            plan.append({"path": "env-old/inspect.fs", "blob": self.run.older_blob, "ref": self.run.older_commit})
            plan.append({"path": "env/inspect.fs", "blob": self.run.candidate_blob, "ref": self.run.candidate_commit})
        else:
            raise ValueError(self.variant)
        return plan

    def log_dir(self) -> Path:
        return self.sandbox / "log" if self.log_mode == "env" else self.sandbox / "state" / "gforth-inspect"

    def start(self) -> bool:
        plan = self._install()
        self.plan = plan
        if self.inspect_override is not None:   # calibration: the sandbox holds another blob
            (self.sandbox / plan[0]["path"]).write_bytes(self.inspect_override)
        env = targets.minimal_env(self.sandbox, self.sandbox / "log" if self.log_mode == "env" else None)
        if self.log_mode == "shared":            # calibration only
            env["GFORTH_INSPECT_LOG_DIR"] = str(self.run.shared_log_dir)
        for key, value in self.env_patch.items():
            if value is None:
                env.pop(key, None)
            else:
                env[key] = value
        self.log_path = (self.run.shared_log_dir if self.log_mode == "shared" else self.log_dir()) / "stacks.jsonl"
        if self.log_mode == "home":              # calibration only: the log follows HOME
            self.log_path = Path(env["HOME"]) / ".local" / "state" / "gforth-inspect" / "stacks.jsonl"
        self.call = {
            "xrid": self.xrid, "run": self.run.run_id, "slot": self.slot, "engine": self.engine,
            "variant": self.variant, "log_mode": self.log_mode, "long": self.long_lived, "seed": self.seed,
            "sandbox": str(self.sandbox), "cwd": str(self.sandbox), "log_path": str(self.log_path),
            "inspect_plan": plan,
            "inspect_versions": {**self.run.inspect_versions,
                                 **({plan[0]["blob"]: assets.version_of(self.custom_inspect)} if self.custom_inspect else {})},
            "env_keys": sorted(env), "started": self.started, "logged": False,
            "follower_pin": self.follower_pin,
        }
        (self.dir / "call.json").write_text(json.dumps(self.call, indent=1))
        self.run.manifest_append({"event": "start", **self.call})
        self.audit = checks.SessionAudit(self.call, self.run.validator, checks.FileTable([], self.run.pool))
        self.repl = Repl(self.engine, self.sandbox, env, self.dir / "pty.log")
        if not self.repl.wait_banner():
            self.state = "failed"
            return False
        self.log_path.parent.mkdir(parents=True, exist_ok=True) if self.log_mode == "shared" else None
        self.followers = Followers(self.log_path, self.sandbox / "env" / "stacks-log.schema.json", self.dir,
                                   pin=self.follower_pin, checker_args=self.checker_args)
        self.load_inspect(plan[0])
        for line in targets.ORACLE_DEFS:
            self.type(line, "oracle")
        self.type(f's" {self.xrid}" log-id', "log-id")
        self.type("log-on", "log-on")
        self.type("all-~~", "misc")
        self.state = "running"
        return True

    def load_inspect(self, item: dict, absolute: bool = False) -> None:
        path = self.sandbox / item["path"]
        blob = assets.blob_of(path)
        text = f"include {path if absolute else item['path']}"
        self.type(text, "inspect", inspect={"path": item["path"], "blob": blob})

    # --- typing --------------------------------------------------------

    def type(self, text: str, kind: str, **extra) -> dict:
        hello = kind == "log-on" and not self.logging
        result = self.repl.type_line(text, timeout=120 if kind == "include-file" else 60)
        self.line_number += 1
        if kind == "log-on" and result.status == "ok":
            self.logging = True
            if not self.call["logged"]:
                self.call["logged"] = True
                (self.dir / "call.json").write_text(json.dumps(self.call, indent=1))
        if kind == "log-off" and result.status == "ok":
            self.logging = False
        entry = {"n": self.line_number, "t": time.time(), "text": text, "kind": kind, "status": result.status,
                 "markers": result.markers, "hello": hello and result.status == "ok", "elapsed": result.elapsed,
                 **extra}
        self.transcript.write(json.dumps(entry) + "\n")
        self.transcript.flush()
        self.entries.append(entry)
        self._check_after(entry)
        if result.status in ("hung", "dead"):
            self.state = result.status
        return entry

    def _read_log(self) -> list[bytes]:
        """The log's complete lines, read incrementally (a long session's log
        is read after every line for hours).  A log that shrinks or is
        rewritten under us is re-read from the start."""
        if not hasattr(self, "_log_lines"):
            self._log_lines, self._log_offset, self._log_partial = [], 0, b""
        try:
            size = self.log_path.stat().st_size
        except FileNotFoundError:
            return self._log_lines
        if size < self._log_offset:
            self._log_lines, self._log_offset, self._log_partial = [], 0, b""
        if size > self._log_offset:
            with open(self.log_path, "rb") as handle:
                handle.seek(self._log_offset)
                chunk = handle.read(size - self._log_offset)
            self._log_offset += len(chunk)
            parts = (self._log_partial + chunk).split(b"\n")
            self._log_partial = parts.pop()
            self._log_lines.extend(parts)
        return self._log_lines

    def _check_after(self, entry: dict) -> None:
        wrote = entry["hello"] or entry["markers"]
        lines = self._read_log()
        if len(lines) != self.records_seen:
            self.last_growth = time.time()
            self.stall_reported = False
        if not wrote and len(lines) == self.records_seen:
            return
        before = len(self.audit.violations)
        self.audit.feed(self.entries, lines, rest=True)
        for item in self.audit.violations[before:]:
            self.violations += 1
            self.run.report(item)
        self.records_seen = len(lines)
        if self.followers and lines:
            # mock and checker read the whole log on every call (as written):
            # at most every 5 s, and always right after a hello
            full = entry["hello"] or time.time() - getattr(self, "_last_full", 0.0) >= 5.0
            if full:
                self._last_full = time.time()
            for problem in self.followers.verify(lines, self.run.validator, full=full):
                kind = re.sub(r"\d+", "N", problem)[:60]   # one report per kind of problem per session
                if kind in self._follower_kinds:
                    continue
                self._follower_kinds.add(kind)
                self.violations += 1
                self.run.report(checks.violation("G5", self.xrid, f"after line {entry['n']}: {problem}"))

    def link(self, unit) -> list[str]:
        self.units_loaded += 1
        unit_dir = f"t/u{self.units_loaded}-{unit.tree}"
        includes = targets.link_unit(unit, self.run.pool, self.sandbox, unit_dir)
        for item in unit.files:
            record = {"path": f"{unit_dir}/{item.rel}", "unit": unit.uid, "origin": item.origin,
                      "orig_blob": item.orig_blob, "copy_blob": item.copy_blob, "modified": item.modified,
                      "copy_ok": checks.copy_matches(self.run.pool, {"orig_blob": item.orig_blob,
                                                                     "copy_blob": item.copy_blob,
                                                                     "modified": item.modified})
                      if item.orig_blob != item.copy_blob else True}
            self.audit.files.entries[record["path"]] = record
            self.files_log.write(json.dumps(record) + "\n")
        self.files_log.flush()
        return includes

    # --- driving -------------------------------------------------------

    def step(self) -> None:
        """Type the next line, then pause as a person would."""
        if not self.pending:
            steps, _ = self.feeder.block_lines()
            self.pending = steps
        step = self.pending.pop(0)
        if step["kind"] == "include":
            includes = self.link(step["unit"])
            if self.absolute_includes:
                includes = [str(self.sandbox / path) for path in includes]
            self.pending[0:0] = [{"text": f"include {path}", "kind": "include-file", "unit": step["unit"].uid}
                                 for path in includes]
            return
        entry = self.type(step["text"], step["kind"], **({"unit": step["unit"]} if "unit" in step else {}))
        if entry["status"] == "error" and step["kind"] in ("include-file", "setup"):
            # the rest of the unit would fail the same way: go to its forget
            while self.pending and self.pending[0]["kind"] != "forget":
                self.pending.pop(0)
        self.pause()

    def pause(self) -> None:
        roll = self.rng.random()
        if roll < 0.80:
            delay = self.rng.uniform(0.2, 2.0)
        elif roll < 0.97:
            delay = self.rng.uniform(2.0, 8.0)
        else:
            delay = self.rng.uniform(8.0, 25.0)
        self.run.stop_event.wait(delay * self.run.pace)

    def upgrade(self) -> dict:
        """The mid-run upgrade (gate 3): log-off, include the candidate, log-on."""
        before = len(self._read_log())
        self.type("log-off", "log-off")
        self.load_inspect(self.plan[1])
        self.type(f's" {self.xrid}" log-id', "log-id")
        self.type("log-on", "log-on")
        self.type("all-~~", "misc")
        lines = self._read_log()
        new = lines[before:]
        hello = json.loads(new[-1]) if new else {}
        status, body = self.followers.get_stacks()
        jq_last = self.followers.jq_lines()[-1:]
        checker = self.followers.run_checker()
        self.upgraded = True
        evidence = {
            "xrid": self.xrid, "t": time.time(), "new_hello": hello,
            "mock_serves_new_hello": status == 200 and bool(new) and body == new[-1],
            "jq_last": jq_last[0].decode() if jq_last else None,
            "checker": checker,
            "hellos_in_log": sum(1 for line in lines if b'"event":"hello"' in line),
        }
        return evidence

    def alive(self) -> bool:
        return self.repl is not None and self.repl.alive() and self.state == "running"

    def followers_alive(self) -> bool:
        return self.followers is not None and all(self.followers.alive().values())

    def monitor(self, stall: float) -> None:
        """A log that stops growing while its REPL is alive."""
        if self.state != "running" or not self.repl.alive():
            return
        size = len(self._read_log())
        if size != self.records_seen:
            self.records_seen = size
            self.last_growth = time.time()
            self.stall_reported = False
        elif time.time() - self.last_growth > stall and not self.stall_reported:
            self.stall_reported = True
            self.violations += 1
            self.run.report(checks.violation("monitor", self.xrid,
                                             f"log has not grown for {time.time() - self.last_growth:.0f}s "
                                             f"while the REPL is alive ({size} records)"))

    def retire(self, reason: str) -> dict:
        if self.repl and self.repl.alive() and self.state == "running":
            if self.logging:
                self.type("log-off", "log-off")
        self.state = "retired" if self.state == "running" else self.state
        returncode = self.repl.close() if self.repl else None
        if self.followers:
            self.followers.stop()
        self.transcript.close()
        self.files_log.close()
        found, stats = checks.audit_session(self.dir, self.run.pool, self.run.validator, final=True)
        reported = {json.dumps([item["goal"], item["detail"]]) for item in self.audit.violations}
        for item in found:
            if json.dumps([item["goal"], item["detail"]]) not in reported:
                self.violations += 1
                self.run.report(item)
        final = {"xrid": self.xrid, "ended": time.time(), "reason": reason, "state": self.state,
                 "returncode": returncode, "stats": stats, "violations": self.violations,
                 "lines": self.line_number, "units": self.units_loaded, "upgraded": self.upgraded,
                 "hours": (time.time() - self.started) / 3600}
        (self.dir / "final.json").write_text(json.dumps(final, indent=1))
        self.run.manifest_append({"event": "end", **final})
        shutil.rmtree(self.sandbox / "t", ignore_errors=True)   # the copies stay in the pool, by blob
        return final
