"""Gate item 1: every check seen red on its planted fault, then green.

Each scenario runs real driven sessions (the same Session, followers and
checks as the soak) in a run of its own, so one plant cannot leak into
another's xref.  A scenario passes when its check reports at least one
violation of its goal on the plant and none on the control.

Nothing here writes the user's real files.  The G4 plant points a session's
HOME at a fake home made for the purpose; a guard on the REAL files runs
across the whole calibration and must see nothing.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import time
from pathlib import Path

from . import assets, checks, config, targets
from .run import Run, utc


def count(run: Run, goal: str) -> int:
    return sum(1 for item in checks.read_jsonl(run.run_dir / "violations.jsonl") if item["goal"] == goal)


def examples(run: Run, goal: str, limit: int = 2) -> list[str]:
    return [item["detail"][:220] for item in checks.read_jsonl(run.run_dir / "violations.jsonl")
            if item["goal"] == goal][:limit]


class Calibration:
    def __init__(self):
        self.stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime())
        self.base = Run(f"calib-{self.stamp}", hours=0, slots=0, log=lambda line: None)
        self.base.prepare(differential=False)
        self.serial = 500000

    def run(self, name: str) -> Run:
        scenario = Run(f"calib-{self.stamp}-{name}", hours=0, slots=0, pace=0.02, log=lambda line: None)
        scenario.adopt(self.base)
        (scenario.run_dir / "run.json").write_text(json.dumps({"run_id": scenario.run_id, "tmp": str(scenario.tmp)}))
        return scenario

    def session(self, run: Run, **options):
        from .session import Session
        xrid = run.new_xrid()
        defaults = dict(slot=0, engine="gforth", variant="installed", log_mode="env", long_lived=True,
                        seed=int(xrid[1:]) + 7, lifetime=None)
        defaults.update(options)
        session = Session(run, xrid, **defaults)
        if not session.start():
            raise RuntimeError(f"{xrid} did not start")
        return session

    def probe(self, session, cells: int = 3) -> dict:
        self.serial += 1
        values = " ".join(str(self.serial * 10 + index) for index in range(cells))
        return session.type(f"{self.serial} {values} .stacks soak-o", "probe")

    def drive(self, session, steps: int) -> None:
        for _ in range(steps):
            session.step()

    # --- the scenarios: each returns (red count, green count, evidence) ---

    def g4_leak_guard(self):
        def one(planted: bool):
            run = self.run("g4-" + ("plant" if planted else "control"))
            fake = Path(tempfile.mkdtemp(prefix="fake-home-", dir=run.tmp))
            files = [fake / ".local/state/gforth-inspect/stacks.jsonl", fake / ".local/state/course-repo/stacks.jsonl",
                     fake / ".gforth-history"]
            for path in files:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'{"planted copy, not the real file":1}\n')
            guard = checks.LeakGuard(files, [path.parent for path in files[:2]], report=run.report)
            if planted:   # HOME is the fake user's home, and nothing else points elsewhere
                session = self.session(run, log_mode="home",
                                       env_patch={"HOME": str(fake), "XDG_STATE_HOME": None})
            else:
                session = self.session(run)
            for _ in range(6):
                self.probe(session)
            session.retire("calibration")
            guard.check()
            return count(run, "G4"), examples(run, "G4", 3)
        red, red_examples = one(True)
        green, _ = one(False)
        return red, green, {"plant": "HOME points at a fake home; XDG_STATE_HOME unset", "red_examples": red_examples}

    def g6_shared_dir(self):
        def one(planted: bool):
            run = self.run("g6shared-" + ("plant" if planted else "control"))
            mode = "shared" if planted else "env"
            first, second = self.session(run, log_mode=mode), self.session(run, log_mode=mode, engine="gforth-itc")
            for _ in range(4):
                self.probe(first)
                self.probe(second)
            first.retire("calibration")
            second.retire("calibration")
            run.do_xref()
            return count(run, "G6"), examples(run, "G6")
        red, red_examples = one(True)
        green, _ = one(False)
        return red, green, {"plant": "two sessions, one GFORTH_INSPECT_LOG_DIR", "red_examples": red_examples}

    def g6_other_blob(self):
        def one(override):
            run = self.run("g6blob-" + ("plant" if override else "control"))
            session = self.session(run, inspect_override=override)
            for _ in range(3):
                self.probe(session)
            session.retire("calibration")
            run.do_xref()
            hello = next((json.loads(line) for line in Path(session.log_path).read_bytes().split(b"\n")
                          if b'"hello"' in line), None)
            return count(run, "G6"), examples(run, "G6"), hello
        red, red_examples, red_hello = one(self.base.older_source)
        green, _, green_hello = one(None)
        return red, green, {"plant": "the manifest names the candidate blob; the sandbox file is the older ref's",
                            "red_examples": red_examples, "hello_of_plant": red_hello, "hello_of_control": green_hello,
                            "hello_tells_them_apart": {k: v for k, v in (red_hello or {}).items() if k != "t"}
                                                      != {k: v for k, v in (green_hello or {}).items() if k != "t"}}

    def g1_truncated(self):
        def one(planted: bool):
            run = self.run("g1-" + ("plant" if planted else "control"))
            session = self.session(run)
            self.probe(session)
            if planted:
                line = Path(session.log_path).read_bytes().rstrip(b"\n").rsplit(b"\n", 1)[-1]
                with open(session.log_path, "ab") as handle:   # the session's own sandbox log, never a real one
                    handle.write(line[: len(line) // 2] + b"\n")
            for _ in range(3):
                self.probe(session)
            session.retire("calibration")
            return count(run, "G1"), examples(run, "G1")
        red, red_examples = one(True)
        green, _ = one(False)
        return red, green, {"plant": "half a record appended to a session's log", "red_examples": red_examples}

    def g2_unfixed_shared(self):
        def one(variant: str):
            run = self.run(f"g2-{variant}")
            source = self.base.unfixed_source if variant == "unfixed" else None
            kind = "custom" if source else variant
            first = self.session(run, log_mode="shared", variant=kind, custom_inspect=source)
            second = self.session(run, log_mode="shared", variant=kind, custom_inspect=source, engine="gforth-fast")
            for _ in range(6):
                self.probe(first)
                self.probe(second)
            first.retire("calibration")
            second.retire("calibration")
            return count(run, "G2"), examples(run, "G2")
        red, red_examples = one("unfixed")
        green, _ = one("installed")
        return red, green, {"plant": f"unfixed {self.base.unfixed_commit[:7]} (pre-#17 fix), two sessions on one dir; "
                                     "control: the candidate, same two sessions", "red_examples": red_examples}

    def g7_absolute(self):
        unit = next(unit for unit in self.base.units if unit.target == "C" and "gforth" in unit.engines)

        def one(absolute: bool):
            run = self.run("g7-" + ("plant" if absolute else "control"))
            session = self.session(run, absolute_includes=absolute)
            session.pending = session.feeder._target_block(unit)
            while session.pending:
                session.step()
            session.retire("calibration")
            return count(run, "G7"), examples(run, "G7")
        red, red_examples = one(True)
        green, _ = one(False)
        return red, green, {"plant": "include by absolute path", "red_examples": red_examples}

    def g3_drop_top(self):
        source = self.base.candidate_source
        original = b"    n# @ 0 ?DO sep n# @ 1- i - pick 0 .r LOOP  [char] ] emit ;"
        assert source.count(original) == 1, "json-data changed shape: revisit the G3 plant"
        planted = source.replace(original, b"    n# @ 1- 0 max 0 ?DO sep n# @ 1- i - pick 0 .r LOOP  [char] ] emit ;")

        def one(custom):
            run = self.run("g3-" + ("plant" if custom else "control"))
            session = self.session(run, variant="custom" if custom else "installed", custom_inspect=custom)
            for cells in (1, 3, 0, 5):
                self.probe(session, cells)
            session.retire("calibration")
            return count(run, "G3"), examples(run, "G3")
        red, red_examples = one(planted)
        green, _ = one(None)
        return red, green, {"plant": "json-data leaves out the top cell", "red_examples": red_examples}

    def g5_pinned_2_0(self):
        def one(pin: str):
            run = self.run(f"g5pin-{pin}")
            session = self.session(run, follower_pin=pin)
            for _ in range(3):
                self.probe(session)
            session.retire("calibration")
            return count(run, "G5"), examples(run, "G5")
        red, red_examples = one("2.0")
        green, _ = one(config.CONTRACT_EXPECTED)
        return red, green, {"plant": "the checker pinned to contract 2.0 on a 1.1 stream", "red_examples": red_examples}

    def g5_must_stop(self):
        source = self.base.candidate_source
        original = b': contract-version ( -- c-addr u ) s" 1.1" ;'
        assert source.count(original) == 1
        announcing = source.replace(original, b': contract-version ( -- c-addr u ) s" 2.0" ;')

        def one(no_stop: bool):
            run = self.run("g5stop-" + ("plant" if no_stop else "control"))
            session = self.session(run, variant="custom", custom_inspect=announcing,
                                   checker_args=("--no-version-stop",) if no_stop else ())
            for _ in range(3):
                self.probe(session)
            answer = session.followers.run_checker()
            session.retire("calibration")
            return count(run, "G5"), examples(run, "G5"), answer
        red, red_examples, _ = one(True)
        green, _, green_answer = one(False)
        return red, green, {"plant": "a producer announcing 2.0; the 1.1 checker run with --no-version-stop",
                            "red_examples": red_examples, "control_checker_answer": green_answer}

    def monitor_stall(self):
        def one(planted: bool):
            run = self.run("monitor-" + ("plant" if planted else "control"))
            session = self.session(run)
            if planted:
                session.type("log-off", "log-off")
            started = time.time()
            while time.time() - started < 40:
                if planted:
                    session.type("1 2 + drop", "misc")
                else:
                    self.probe(session)
                session.monitor(15.0)
                time.sleep(2)
            session.retire("calibration")
            return count(run, "monitor"), examples(run, "monitor")
        red, red_examples = one(True)
        green, _ = one(False)
        return red, green, {"plant": "log-off, then 40 s of typing with the REPL alive (stall threshold 15 s)",
                            "red_examples": red_examples}

    def g8_install(self):
        def one(tamper: bool):
            dist = Path(tempfile.mkdtemp(prefix="dist-", dir=self.base.tmp))
            for path in self.base.dist.iterdir():
                shutil.copyfile(path, dist / path.name)
            if tamper:
                with open(dist / "inspect.fs", "ab") as handle:
                    handle.write(b"\\ tampered after SHA256SUMS\n")
            project = Path(tempfile.mkdtemp(prefix="project-", dir=self.base.tmp))
            result = assets.install(dist, project)
            ok = result["sha256sums_ok"] and result["skill_ok"] and result["inspect_blob"] == self.base.candidate_blob
            return (0 if ok else 1), result
        red, red_result = one(True)
        green, _ = one(False)
        return red, green, {"plant": "inspect.fs changed after SHA256SUMS was written",
                            "red_examples": red_result["sha256sums_output"]}


SCENARIOS = [
    ("G4 leak guard", "g4_leak_guard"),
    ("G6 two sessions, one log dir", "g6_shared_dir"),
    ("G6 a blob the manifest does not name", "g6_other_blob"),
    ("G1 truncated record", "g1_truncated"),
    ("G2 unfixed producer, shared dir", "g2_unfixed_shared"),
    ("G7 absolute include", "g7_absolute"),
    ("G3 top cell dropped", "g3_drop_top"),
    ("G5 follower pinned to 2.0", "g5_pinned_2_0"),
    ("G5 follower that does not stop", "g5_must_stop"),
    ("monitor: log stops, REPL alive", "monitor_stall"),
    ("G8 tampered asset", "g8_install"),
]


def main(only: str | None = None) -> int:
    real_guard = checks.LeakGuard(config.real_guarded_paths(), config.real_guarded_dirs())
    calibration = Calibration()
    results = []
    for label, method in SCENARIOS:
        if only and only not in (method, label):
            continue
        started = time.time()
        try:
            red, green, evidence = getattr(calibration, method)()
            passed = red > 0 and green == 0
        except Exception as error:   # a scenario that cannot run has not been seen red
            import traceback
            red, green, evidence, passed = None, None, {"error": traceback.format_exc()[-800:]}, False
        results.append({"check": label, "method": method, "red": red, "green": green, "passed": passed,
                        "seconds": round(time.time() - started, 1), "evidence": evidence})
        print(f"{'PASS' if passed else 'FAIL'}  {label}: red {red}, green {green}", flush=True)
    real = real_guard.check()
    results.append({"check": "the real files during calibration", "method": "real_guard",
                    "red": None, "green": len(real), "passed": not real,
                    "evidence": {"changes": [item["detail"] for item in real]}})
    print(f"{'PASS' if not real else 'FAIL'}  real guarded files unchanged during calibration: {len(real)} changes")
    out = config.state_root() / f"calibration-{calibration.stamp}.json"
    out.write_text(json.dumps({"utc": utc(), "candidate_blob": calibration.base.candidate_blob,
                               "candidate_release": calibration.base.candidate_release,
                               "unfixed_commit": calibration.base.unfixed_commit,
                               "candidate_commit": calibration.base.candidate_commit,
                               "older_commit": calibration.base.older_commit, "older_blob": calibration.base.older_blob,
                               "results": results}, indent=1))
    print(f"written {out}")
    return 0 if all(item["passed"] for item in results) else 1
