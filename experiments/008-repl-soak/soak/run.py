"""The orchestrator: prepare, run the slots, keep the clock, write status.

Clock (gate 2).  Every tick (5 s) the run counts the tick only if the
driver (every slot thread), the followers (jq and the mock server of every
running session, and the checker's last run) and the leak guard are all
alive, and at least `min_live` REPLs are running.  The counted total is
saved every tick, so a harness crash stops the clock without resetting it
(`resume` picks it up).

Slots.  Slot 0 is the long session: one REPL for the whole run, on the
installed candidate.  Slot 1 is the upgrade session: it starts on the older
ref and upgrades to the candidate at half time.  The other slots run short
sessions that restart every 5 to 60 minutes, cycling the three engines,
half with GFORTH_INSPECT_LOG_DIR and half on the XDG fallback.  A
replacement is started before the session it replaces is retired, so the
live count does not dip.
"""

from __future__ import annotations

import datetime
import json
import os
import random
import re
import shutil
import subprocess
import tempfile
import threading
import time
import traceback
from pathlib import Path

from . import assets, checks, config, targets
from .session import Session


def utc(stamp: float | None = None) -> str:
    return datetime.datetime.fromtimestamp(stamp or time.time(), datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def local(stamp: float | None = None) -> str:
    return datetime.datetime.fromtimestamp(stamp or time.time()).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def write_atomic(path: Path, text: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text)
    os.replace(temporary, path)


class Run:
    def __init__(self, run_id: str, hours: float, slots: int, min_live: int = 8, stall: float = 300.0,
                 pace: float = 1.0, short_minutes: tuple = (5, 60), seed: int | None = None,
                 resume: bool = False, guard_period: float = 600.0, log=print):
        self.run_id, self.hours, self.slots, self.min_live = run_id, hours, slots, min_live
        self.stall, self.pace, self.short_minutes, self.guard_period = stall, pace, short_minutes, guard_period
        self.log = log
        self.run_dir = config.state_root() / "runs" / run_id
        self.tmp = config.tmp_root() / f"gforth-inspect-soak-{run_id}"
        if not resume and self.run_dir.exists():
            raise SystemExit(f"run {run_id} exists; use resume")
        self.run_dir.mkdir(parents=True, exist_ok=True)
        (self.run_dir / "sessions").mkdir(exist_ok=True)
        self.tmp.mkdir(parents=True, exist_ok=True)
        self.shared_log_dir = self.tmp / "shared-log"
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.reported: set = set()
        self.counts = {goal: 0 for goal in ("G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8", "monitor", "harness")}
        self.last_violation = None
        self.g4_ours = 0
        self.sessions: dict = {}           # slot -> live Session
        self.state = self._load_state() if resume else {}
        self.state.setdefault("seed", seed if seed is not None else random.randrange(1 << 30))
        self.state.setdefault("counted", 0.0)
        self.state.setdefault("wall_started", time.time())
        self.state.setdefault("next_xrid", 0)
        self.state.setdefault("engine_hours", {engine: 0.0 for engine in config.ENGINES})
        self.state.setdefault("ended", [])
        self.state.setdefault("upgrade", None)
        self.state.setdefault("xref", [])
        self.state.setdefault("min_live_counted", None)
        self.state.setdefault("restarts", 0)
        self.state.setdefault("clock_stops", [])
        self.state.setdefault("first_counted_utc", None)
        existing = [int(path.name[1:]) for path in (self.run_dir / "sessions").glob("s*") if path.name[1:].isdigit()]
        self.state["next_xrid"] = max([self.state["next_xrid"]] + [number + 1 for number in existing])
        self.rng = random.Random(self.state["seed"] + int(time.time()) if resume else self.state["seed"])
        for item in checks.read_jsonl(self.run_dir / "violations.jsonl"):
            self.reported.add(self._key(item))
            self.counts[item["goal"]] = self.counts.get(item["goal"], 0) + 1
            if item["goal"] == "G4" and "WRITTEN BY A SOAK SESSION" in item["detail"]:
                self.g4_ours += 1
            self.last_violation = item
        self.clock_running = False
        self.clock_reason = "not started"

    # --- bookkeeping ---------------------------------------------------

    def _load_state(self) -> dict:
        path = self.run_dir / "state.json"
        return json.loads(path.read_text()) if path.exists() else {}

    def save_state(self) -> None:
        write_atomic(self.run_dir / "state.json", json.dumps(self.state, indent=1))

    @staticmethod
    def _key(item: dict) -> str:
        return json.dumps([item["goal"], item.get("xrid"), item["detail"]])

    def report(self, item: dict) -> None:
        with self.lock:
            key = self._key(item)
            if key in self.reported:
                return
            self.reported.add(key)
            self.counts[item["goal"]] = self.counts.get(item["goal"], 0) + 1
            if item["goal"] == "G4" and "WRITTEN BY A SOAK SESSION" in item["detail"]:
                self.g4_ours += 1
            self.last_violation = item
            with open(self.run_dir / "violations.jsonl", "a") as handle:
                handle.write(json.dumps(item) + "\n")
        self.event(f"VIOLATION {item['goal']} {item.get('xrid')}: {item['detail'][:200]}")

    def event(self, text: str) -> None:
        line = f"{utc()} {text}"
        with self.lock:
            with open(self.run_dir / "events.log", "a") as handle:
                handle.write(line + "\n")
        self.log(line)

    def manifest_append(self, item: dict) -> None:
        with self.lock:
            with open(self.run_dir / "manifest.jsonl", "a") as handle:
                handle.write(json.dumps(item) + "\n")

    # --- prepare -------------------------------------------------------

    def prepare(self, differential: bool = True) -> None:
        entries = config.read_manifest()
        candidate = config.one(entries, "candidate")
        repo = config.one(entries, "repo")
        self.candidate_blob = candidate.options["blob"]
        self.dist = self.run_dir / "assets" / "dist"
        saved = json.loads((self.run_dir / "run.json").read_text()) if (self.run_dir / "run.json").exists() else None
        if saved and self.dist.exists():
            # a resumed run keeps the assets it started with: the candidate's
            # worktree may have moved since (its prose assets pin the commit)
            provenance = saved["assets"]
            now = {path.name: assets.blob_of(path) for path in self.dist.iterdir()}
            if now != provenance["assets"]:
                raise SystemExit("resume: the run's dist/ is not the one it started with")
        else:
            provenance = assets.build(candidate.path, self.candidate_blob, self.dist)
        self.candidate_commit = provenance["commit"]
        self.candidate_source = (self.dist / "inspect.fs").read_bytes()   # the same blob as the commit's
        older_ref = repo.options["older"]
        self.older_commit = assets.git(repo.path, "rev-parse", older_ref).strip()
        self.older_source = subprocess.run(["git", "-C", str(repo.path), "show", f"{older_ref}:env/inspect.fs"],
                                           check=True, capture_output=True).stdout
        self.older_blob = assets.blob_of_bytes(self.older_source)
        self.inspect_versions = {self.candidate_blob: assets.version_of(self.candidate_source),
                                 self.older_blob: assets.version_of(self.older_source)}
        self.validator = checks.validator_for(self.dist / "stacks-log.schema.json")
        schema = json.loads((self.dist / "stacks-log.schema.json").read_text())
        if schema.get("x-contract") != config.CONTRACT_EXPECTED:
            raise SystemExit(f"candidate schema announces {schema.get('x-contract')}, followers are written for "
                             f"{config.CONTRACT_EXPECTED}: stop and read the change log")
        self.pool = targets.Pool(self.tmp / "pool")
        self.units, trees = targets.enumerate_units(entries, self.pool, self.candidate_commit)
        write_atomic(self.run_dir / "trees.json", json.dumps(trees, indent=1))   # local only
        targets.preflight(self.units, self.pool, self.dist / "inspect.fs",
                          config.state_root() / "cache" / "preflight.json", self.tmp / "preflight", log=self.event)
        usable = [unit for unit in self.units if unit.engines]
        self.units = usable
        self.prepared = {
            "candidate_commit": self.candidate_commit, "candidate_blob": self.candidate_blob,
            "older_commit": self.older_commit, "older_blob": self.older_blob,
            "versions": self.inspect_versions, "assets": provenance,
            "units": len(usable), "units_by_target": _count(unit.target for unit in usable),
            "trees": len({unit.tree for unit in usable}),
            "lines_by_target": self._lines_by_target(usable),
        }
        if not (self.run_dir / "run.json").exists():
            write_atomic(self.run_dir / "run.json", json.dumps({
                "run_id": self.run_id, "hours": self.hours, "slots": self.slots, "min_live": self.min_live,
                "tmp": str(self.tmp), "created": time.time(), "stall": self.stall, "pace": self.pace,
                "short_minutes": list(self.short_minutes), "guard_period": self.guard_period,
                **self.prepared}, indent=1))
        self.event(f"prepared: candidate {self.candidate_commit[:7]} blob {self.candidate_blob[:12]}, older "
                   f"{self.older_commit[:7]} blob {self.older_blob[:12]}, {len(usable)} units over "
                   f"{self.prepared['trees']} trees")
        if differential:
            self.g8 = self.g8_differential()
            self.event(f"G8 differential: {self.g8['summary']}")

    PREPARED = ("dist", "candidate_blob", "candidate_commit", "candidate_source", "older_commit", "older_source",
                "older_blob", "inspect_versions", "validator", "pool", "units", "prepared")

    def adopt(self, other: "Run") -> None:
        """Share another run's prepared assets, pool and units (calibration)."""
        for name in self.PREPARED:
            setattr(self, name, getattr(other, name))

    def _lines_by_target(self, units) -> dict:
        seen, totals = set(), {}
        for unit in units:
            for item in unit.files:
                if (unit.tree, item.rel) in seen:
                    continue
                seen.add((unit.tree, item.rel))
                totals[unit.target] = totals.get(unit.target, 0) + self.pool.get(item.orig_blob).count(b"\n")
        return totals

    def g8_differential(self) -> dict:
        """The installed assets load and log the same as the worktree they
        were built from: main's corpus programs, every engine, both ways."""
        entries = config.read_manifest()
        candidate = config.one(entries, "candidate")
        repo = config.one(entries, "repo")
        reader = targets.GitReader(repo.path)
        main = reader.head("main")
        programs = {rel: reader.blob(blob) for rel, blob in reader.files(main, "corpus").items() if rel.endswith(".fs")}
        reader.close()
        differ, runs = [], 0
        scratch = self.tmp / "g8"
        scratch.mkdir(exist_ok=True)

        def one(inspect_bytes: bytes, program: bytes, engine: str) -> bytes:
            box = Path(tempfile.mkdtemp(dir=scratch))
            try:
                (box / "tmp").mkdir()
                (box / "inspect.fs").write_bytes(inspect_bytes)
                (box / "prog.fs").write_bytes(program)
                proc = subprocess.run([engine, "inspect.fs", "prog.fs", "-e", "bye"], cwd=box, capture_output=True,
                                      env=targets.minimal_env(box, box / "log"), stdin=subprocess.DEVNULL, timeout=30)
                log = (box / "log" / "stacks.jsonl").read_bytes() if (box / "log" / "stacks.jsonl").exists() else b""
                log = re.sub(rb'"t":\d+', b'"t":0', log)
                log = re.sub(rb'"rs":\[[^\]]*\]', b'"rs":[]', log)   # raw return addresses move between runs
                out = re.sub(rb"\$[0-9A-F]+", b"$X", proc.stdout + proc.stderr)
                return b"%d\n" % proc.returncode + log + out
            finally:
                shutil.rmtree(box, ignore_errors=True)

        project = Path(tempfile.mkdtemp(dir=scratch))
        installed = assets.install(self.dist, project)
        installed_bytes = (project / "env" / "inspect.fs").read_bytes()
        worktree_bytes = (candidate.path / "env" / "inspect.fs").read_bytes()
        for rel, program in sorted(programs.items()):
            for engine in config.ENGINES:
                runs += 1
                if one(installed_bytes, program, engine) != one(worktree_bytes, program, engine):
                    differ.append(f"{rel}@{engine}")
        ok = installed["sha256sums_ok"] and installed["skill_ok"] and installed["inspect_blob"] == self.candidate_blob
        if not ok:
            self.report(checks.violation("G8", None, f"install: {json.dumps(installed)[:300]}"))
        for item in differ:
            self.report(checks.violation("G8", None, f"installed and worktree inspect.fs log differently: {item}"))
        shutil.rmtree(project, ignore_errors=True)
        return {"runs": runs, "differ": differ, "install": installed,
                "summary": f"{runs} runs, {len(differ)} differ, SHA256SUMS {'ok' if installed['sha256sums_ok'] else 'FAILED'}, "
                           f"skill {'ok' if installed['skill_ok'] else 'FAILED'}"}

    def overhead(self) -> dict:
        """log-on's cost on a loaded REPL: µs per .stacks with the log off and on."""
        result = {}
        units = [unit for unit in self.units if unit.target == "S" and unit.setup][:1] + \
                [unit for unit in self.units if unit.target == "L"][:2]
        for engine in config.ENGINES:
            box = Path(tempfile.mkdtemp(dir=self.tmp))
            try:
                (box / "tmp").mkdir()
                shutil.copyfile(self.dist / "inspect.fs", box / "inspect.fs")
                lines = list(targets.ORACLE_DEFS)
                for number, unit in enumerate(units):
                    lines += unit.setup + [f"include {path}" for path in targets.link_unit(unit, self.pool, box, f"t/u{number}")]
                lines += [": soak-bench ( n -- ) 0 ?do .stacks loop ;", "clearstack 1 2 3",
                          'utime 400 soak-bench utime 2swap d- d>s ." #T-OFF " . cr',
                          "log-on",
                          'utime 400 soak-bench utime 2swap d- d>s ." #T-ON " . cr', "bye", ""]
                (box / "bench.fs").write_text("\n".join(lines))
                proc = subprocess.run([engine, "inspect.fs", "bench.fs"], cwd=box, capture_output=True,
                                      env=targets.minimal_env(box, box / "log"), stdin=subprocess.DEVNULL, timeout=120)
                off = re.search(rb"#T-OFF (\d+)", proc.stdout)
                on = re.search(rb"#T-ON (\d+)", proc.stdout)
                if off and on:
                    result[engine] = {"off_us": round(int(off.group(1)) / 400, 1), "on_us": round(int(on.group(1)) / 400, 1)}
            finally:
                shutil.rmtree(box, ignore_errors=True)
        return result

    # --- sessions ------------------------------------------------------

    def new_xrid(self) -> str:
        with self.lock:
            number = self.state["next_xrid"]
            self.state["next_xrid"] += 1
        return f"s{number}"

    def new_session(self, slot: int) -> Session | None:
        xrid = self.new_xrid()
        number = int(xrid[1:])
        if slot == 0:
            engine, variant, log_mode, long_lived, lifetime = "gforth", "installed", "env", True, None
        elif slot == 1:
            upgraded = bool(self.state["upgrade"])
            engine, variant, log_mode, long_lived, lifetime = ("gforth-fast", "installed" if upgraded else "older",
                                                               "xdg", True, None)
        else:
            engine = config.ENGINES[(slot + self.state["restarts"]) % 3]
            variant = "source" if number % 4 == 3 else "installed"
            log_mode = "env" if number % 2 == 0 else "xdg"
            long_lived = False
            lifetime = self.rng.uniform(*self.short_minutes) * 60
        seed = self.state["seed"] * 1000003 + number
        session = Session(self, xrid, slot, engine, variant, log_mode, long_lived, seed, lifetime)
        try:
            ok = session.start()
        except Exception:
            ok = False
            self.event(f"session {xrid} failed to start: {traceback.format_exc()[-400:]}")
        if not ok:
            self.report(checks.violation("harness", xrid, f"session failed to start (state {session.state})"))
            try:
                session.retire("failed to start")
            except Exception:
                pass
            return None
        with self.lock:
            self.state["restarts"] += 1
        self.event(f"start {xrid} slot {slot} {engine} {variant} log={log_mode}"
                   + (f" lifetime {lifetime / 60:.0f}m" if lifetime else " long"))
        return session

    def finish(self, session: Session | None, reason: str) -> None:
        if session is None:
            return
        try:
            final = session.retire(reason)
        except Exception:
            self.report(checks.violation("harness", session.xrid, f"retire failed: {traceback.format_exc()[-300:]}"))
            return
        with self.lock:
            self.state["ended"].append({"xrid": session.xrid, "engine": session.engine, "hours": final["hours"],
                                        "reason": reason, "state": final["state"], "violations": final["violations"]})
        self.event(f"end {session.xrid} ({reason}, {final['state']}): {final['stats']['records']} records, "
                   f"{final['lines']} lines, {final['violations']} violations")

    def slot_loop(self, slot: int) -> None:
        session = None
        while not self.stop_event.is_set():
            try:
                if session is None:
                    session = self.new_session(slot)
                    with self.lock:
                        if session:
                            self.sessions[slot] = session
                        else:
                            self.sessions.pop(slot, None)
                    if session is None:
                        self.stop_event.wait(10)
                    continue
                if not session.alive():
                    if session.long_lived:
                        self.report(checks.violation("harness", session.xrid,
                                                     f"long session ended early ({session.state})"))
                    self.finish(session, f"ended: {session.state}")
                    session = None
                    continue
                if session.deadline and time.time() > session.deadline:
                    replacement = self.new_session(slot)
                    if replacement:
                        with self.lock:
                            self.sessions[slot] = replacement
                    self.finish(session, "lifetime")
                    session = replacement
                    continue
                # between blocks only: inside a block's marker the forget at its
                # end would take the new inspect.fs away again (seen in a dev run)
                if slot == 1 and not self.state["upgrade"] and session.variant == "older" \
                        and not session.pending and self.state["counted"] >= self.hours * 3600 / 2:
                    evidence = session.upgrade()
                    evidence["counted_hours"] = self.state["counted"] / 3600
                    with self.lock:
                        self.state["upgrade"] = evidence
                    self.event(f"upgrade {session.xrid}: {json.dumps(evidence)[:400]}")
                    if not evidence["mock_serves_new_hello"]:
                        self.report(checks.violation("G5", session.xrid, "after the upgrade the mock does not serve the new hello"))
                session.step()
                session.monitor(self.stall)
            except Exception:
                xrid = session.xrid if session else None
                self.report(checks.violation("harness", xrid, f"slot {slot}: {traceback.format_exc()[-500:]}"))
                self.finish(session, "harness error")
                session = None
                self.stop_event.wait(5)
        self.finish(session, "run end")
        with self.lock:
            self.sessions.pop(slot, None)

    # --- the clock and status -------------------------------------------

    def tick(self, dt: float, threads: list, guard: checks.LeakGuard) -> None:
        with self.lock:
            live = [session for session in self.sessions.values() if session.alive()]
        reasons = []
        if not all(thread.is_alive() for thread in threads):
            reasons.append("a slot thread died")
        if len(live) < self.min_live:
            reasons.append(f"{len(live)} REPLs live, fewer than {self.min_live}")
        dead = [session.xrid for session in live if not session.followers_alive()]
        if dead:
            reasons.append(f"followers down for {', '.join(dead)}")
        if not guard.alive():
            reasons.append("leak guard not alive")
        if dt > 30:   # the machine slept, or the harness stalled: that time is not counted
            reasons.append(f"tick gap of {dt:.0f} s")
        running = not reasons
        if running != self.clock_running:
            if not running and self.state["counted"] > 0:
                self.state["clock_stops"].append({"utc": utc(), "counted": self.state["counted"], "why": reasons})
            self.event(f"clock {'running' if running else 'STOPPED: ' + '; '.join(reasons)}")
        self.clock_running, self.clock_reason = running, "; ".join(reasons) or "running"
        if running:
            if self.state["first_counted_utc"] is None:
                self.state["first_counted_utc"] = utc()
                self.state["first_counted_local"] = local()
            self.state["counted"] += dt
            for session in live:
                self.state["engine_hours"][session.engine] += dt / 3600
            low = self.state["min_live_counted"]
            self.state["min_live_counted"] = len(live) if low is None else min(low, len(live))
        self.save_state()

    def status_text(self, guard: checks.LeakGuard) -> str:
        state = self.state
        with self.lock:
            live = [session for session in self.sessions.values() if session.alive()]
        counted_h = state["counted"] / 3600
        hours = state["engine_hours"]
        total = sum(hours.values()) or 1.0
        ended = state["ended"]
        records = sum(session.records_seen for session in live)
        lines = [
            f"gforth-inspect 008 repl-soak   run {self.run_id}   target {self.hours:g} h counted",
            f"written   {utc()}  ({local()})",
            f"clock     {counted_h:.2f} h counted of {self.hours:g}   wall {(time.time() - state['wall_started']) / 3600:.2f} h   "
            f"{'RUNNING' if self.clock_running else 'STOPPED: ' + self.clock_reason}",
            f"first counted tick  {state['first_counted_utc'] or '-'}  ({state.get('first_counted_local') or '-'})",
            f"REPLs     {len(live)} live (min while counted: {state['min_live_counted']})   started {state['next_xrid']}   "
            f"ended {len(ended)} (hung {sum(1 for item in ended if item['state'] == 'hung')}, "
            f"died {sum(1 for item in ended if item['state'] == 'dead')})",
            "engines   " + "   ".join(f"{engine} {hours[engine]:.1f} h ({100 * hours[engine] / total:.0f}%)" for engine in config.ENGINES),
            f"live      " + " ".join(f"{session.xrid}:{session.engine.replace('gforth', 'g')}:{session.records_seen}"
                                    for session in sorted(live, key=lambda item: item.slot)),
            f"records   {records} in live logs, {sum(item.get('records', 0) for item in state['xref'][-1:])} at the last xref",
            f"leak guard  last {utc(guard.last_check)}  checks {guard.checks}  changes {guard.changes}  "
            f"{'alive' if guard.alive() else 'NOT ALIVE'}",
            f"xref      " + (f"{len(state['xref'])} done, last {state['xref'][-1]['utc']}: "
                             f"{state['xref'][-1]['violations']} violations over {state['xref'][-1]['sessions']} sessions"
                             if state["xref"] else "none yet"),
            f"upgrade   " + (f"done at {state['upgrade']['counted_hours']:.2f} h ({state['upgrade']['xrid']}), "
                             f"mock serves new hello: {state['upgrade']['mock_serves_new_hello']}, "
                             f"hellos in log {state['upgrade']['hellos_in_log']}"
                             if state["upgrade"] else f"pending at {self.hours / 2:g} h counted"),
            "violations " + "  ".join(f"{goal} {count}" for goal, count in self.counts.items())
            + f"   (G4 written by a soak session: {self.g4_ours})",
            f"last      " + (f"{self.last_violation['goal']} {self.last_violation.get('xrid')}: "
                             f"{self.last_violation['detail'][:110]}" if self.last_violation else "-"),
            f"clock stops {len(state['clock_stops'])}" + (f", last {state['clock_stops'][-1]['utc']}: "
                                                          f"{'; '.join(state['clock_stops'][-1]['why'])[:90]}"
                                                          if state["clock_stops"] else ""),
            f"files     {self.run_dir}",
        ]
        return "\n".join(lines) + "\n"

    def write_status(self, guard) -> None:
        text = self.status_text(guard)
        write_atomic(self.run_dir / "status.txt", text)
        current = config.state_root() / "status.txt"
        write_atomic(current, text)
        write_atomic(self.run_dir / "status.json", json.dumps({
            "utc": utc(), "counted_hours": self.state["counted"] / 3600, "target_hours": self.hours,
            "clock_running": self.clock_running, "clock_reason": self.clock_reason,
            "violations": self.counts, "engine_hours": self.state["engine_hours"],
            "min_live_counted": self.state["min_live_counted"], "upgrade": self.state["upgrade"],
            "xref": self.state["xref"][-1:], "sessions_started": self.state["next_xrid"]}, indent=1))

    def do_xref(self) -> None:
        with self.lock:
            live = {session.xrid for session in self.sessions.values()}
        if not hasattr(self, "xref_cache"):
            self.xref_cache = {}
        found, totals = checks.xref(self.run_dir, self.pool, self.validator, live, self.xref_cache)
        for item in found:
            self.report(item)
        entry = {"utc": utc(), "counted_hours": self.state["counted"] / 3600, "violations": len(found), **totals}
        with self.lock:
            self.state["xref"].append(entry)
        self.event(f"xref: {json.dumps(entry)}")

    def orphans(self) -> None:
        """Sessions a crashed harness left without an end: audit what they wrote."""
        for session_dir in sorted((self.run_dir / "sessions").glob("*")):
            if (session_dir / "call.json").exists() and not (session_dir / "final.json").exists():
                found, stats = checks.audit_session(session_dir, self.pool, self.validator, final=False)
                for item in found:
                    self.report(item)
                final = {"xrid": session_dir.name, "reason": "harness restart", "state": "orphaned", "stats": stats}
                (session_dir / "final.json").write_text(json.dumps(final, indent=1))
                self.event(f"orphan {session_dir.name}: {stats['records']} records audited")

    def main(self) -> int:
        self.prepare()
        self.orphans()
        guard = checks.LeakGuard(config.real_guarded_paths(), config.real_guarded_dirs(), self.guard_period,
                                 report=self.report)
        self.event(f"leak guard baseline: {len(guard.baseline)} entries")
        guard.start()
        threads = [threading.Thread(target=self.slot_loop, args=(slot,), name=f"slot-{slot}", daemon=True)
                   for slot in range(self.slots)]
        for thread in threads:
            thread.start()
            time.sleep(0.5)
        last, last_status, next_xref = time.time(), 0.0, (int(self.state["counted"] // 3600) + 1) * 3600
        xref_thread: threading.Thread | None = None
        try:
            while self.state["counted"] < self.hours * 3600:
                self.stop_event.wait(5)
                now = time.time()
                self.tick(now - last, threads, guard)
                last = now
                if now - last_status >= 60:
                    self.write_status(guard)
                    last_status = now
                if self.state["counted"] >= next_xref and (xref_thread is None or not xref_thread.is_alive()):
                    next_xref += 3600
                    xref_thread = threading.Thread(target=self.do_xref, name="xref", daemon=True)
                    xref_thread.start()
                if (self.run_dir / "STOP").exists():
                    self.event("STOP file seen")
                    break
        except KeyboardInterrupt:
            self.event("interrupted")
        self.stop_event.set()
        for thread in threads:
            thread.join(timeout=300)
        if xref_thread:
            xref_thread.join(timeout=600)
        guard.stop()
        self.do_xref()
        self.state["overhead"] = self.overhead()
        self.state["done_utc"] = utc()
        self.save_state()
        self.write_status(guard)
        self.event(f"done: counted {self.state['counted'] / 3600:.2f} h, violations {json.dumps(self.counts)}, "
                   f"overhead {json.dumps(self.state['overhead'])}")
        return 0


def _count(items) -> dict:
    counts: dict = {}
    for item in items:
        counts[item] = counts.get(item, 0) + 1
    return counts
