"""Experiment 009's matrix: ledger transitions x N in 0..5 x 4 orders x consumers, and X-streams.

    uv run --no-project --with jsonschema python matrix.py WORK_DIR [--live N,..] [--orders ...]
        [--only x,n0,live] [--out ..]

WORK_DIR is outside the repository (a mktemp -d).  Outputs, all free of
absolute paths: OUT/matrix.tsv (one row per cell), OUT/manifest.tsv (one
row per producer run, keyed by xrid: ref, blob, engine, seed, cwd relative
to WORK_DIR), OUT/xstreams.tsv (envelope / prefix / compound per X-stream).
The absolute WORK_DIR and Vc's blob go only to the local manifest in
${XDG_CONFIG_HOME:-~/.config}/gforth-inspect-009/.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import compare  # noqa: E402
import compound_check  # noqa: E402
import consumers  # noqa: E402
import ledger  # noqa: E402
import prefix_check  # noqa: E402
import producer  # noqa: E402
import rulings  # noqa: E402
import sessions  # noqa: E402
import xstreams  # noqa: E402

ORDERS = ("producer-first", "consumer-first", "rolling", "mixed")
COLUMNS = ["cell", "run", "N", "order", "transition", "step", "slot", "engine", "xrid",
           "consumer", "expect", "predicted", "observed", "match", "note"]
LOCAL = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "gforth-inspect-009"


class Out:
    def __init__(self, out_dir: Path, work: Path):
        self.out_dir, self.work = out_dir, work
        self.rows: list[dict] = []
        self.manifest: list[dict] = []
        self.cache: dict = {}

    def row(self, **values) -> None:
        values.setdefault("cell", f"c{len(self.rows) + 1:05d}")
        self.rows.append({column: str(values.get(column, "")) for column in COLUMNS})

    def rel(self, path: Path) -> str:
        relative = str(Path(path).resolve().relative_to(self.work.resolve()))
        # the import's own default directory is named after its first consumer: not in public files
        parts = relative.split("/")
        return "/".join("legacy" if part not in ("logdir", "gforth-inspect") and index > 0
                        and parts[index - 1] == "state" else part for index, part in enumerate(parts))

    def write(self, name: str = "matrix.tsv") -> None:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        with open(self.out_dir / name, "w") as handle:
            handle.write("\t".join(COLUMNS) + "\n")
            for row in self.rows:
                handle.write("\t".join(row[column].replace("\t", " ").replace("\n", " ")
                                       for column in COLUMNS) + "\n")
        columns = ["xrid", "run", "slot", "key", "source", "blob", "engine", "seed", "cwd", "log", "lines"]
        manifest = "manifest.tsv" if name == "matrix.tsv" else name.replace(".tsv", "-manifest.tsv")
        with open(self.out_dir / manifest, "w") as handle:
            handle.write("\t".join(columns) + "\n")
            for entry in self.manifest:
                handle.write("\t".join(str(entry.get(column, "")) for column in columns) + "\n")


def state_for(prod: ledger.Producer, fallback: ledger.Producer) -> tuple[str, Path]:
    """A consumer's (expected contract, schema) for a producer: its own, or 1.1 if it has none."""
    if prod.contract:
        return prod.contract, prod.schema_path
    return "1.1", fallback.schema_path


def digest(*parts) -> str:
    sha = hashlib.sha256()
    for part in parts:
        sha.update(part if isinstance(part, bytes) else str(part).encode())
        sha.update(b"\0")
    return sha.hexdigest()


def cached(out: Out, name: str, log: Path, schema: Path, expect: str, no_stop: bool = False):
    content = log.read_bytes() if log.exists() else None
    key = digest(name, content if content is not None else b"<absent>",
                 schema.read_bytes(), expect, no_stop)
    if key in out.cache:
        return out.cache[key]
    if content is None:
        result = consumers.Result(name, "absent")
    elif name == "jq":
        result = consumers.run_jq(out.work, log)
    elif name in ("checker", "bb-checker"):
        result = consumers.run_checker(out.work, log, schema, expect, twin=name == "bb-checker",
                                       no_stop=no_stop)
    elif name in ("mock", "bb-mock"):
        result = consumers.run_mock(out.work, log, twin=name == "bb-mock")
    elif name == "follower":
        result = consumers.run_follower(out.work, log, settle=0.7)
    else:
        raise ValueError(name)
    out.cache[key] = result
    return result


# --- predictions for a whole-log read ---------------------------------------------

def predict(name: str, content: bytes | None, schema: dict, expect: str) -> str:
    if content is None:
        return "absent"
    lines = [line for line in content.split(b"\n") if line]
    objects = True
    for line in lines:
        try:
            objects = objects and isinstance(json.loads(line.decode("utf-8", "strict")), dict)
        except ValueError:
            objects = False
    if name in ("checker", "bb-checker"):
        return rulings.checker_verdict(content, schema, expect)
    if name == "jq":
        return "follow" if objects else "die"
    if name in ("mock", "bb-mock"):
        return "serve" if lines else "404"
    if name == "follower":
        return "follow"
    raise ValueError(name)


def verdict_match(name: str, predicted: str, observed: str) -> bool:
    if name in ("checker", "bb-checker"):
        return rulings.matches_checker(predicted, observed)
    if predicted == "die":
        return observed.startswith("die")
    if predicted == "follow" and name == "follower":
        return observed.startswith("follow")
    return predicted == observed


def observe(out: Out, log: Path, schema_path: Path, expect: str, names: list[str],
            present: bool | None = None, **context) -> dict:
    """`present`: whether the ruling says a log is at this path (None: not judged)."""
    content = log.read_bytes() if log.exists() else None
    schema = json.loads(schema_path.read_text())
    results = {}
    for name in names:
        result = cached(out, name, log, schema_path, expect)
        predicted = predict(name, content, schema, expect)
        if present is False:
            predicted = "absent"
        elif present is True and content is None:
            predicted = "present"
        out.row(consumer=name, expect=expect, predicted=predicted, observed=result.verdict,
                match="yes" if verdict_match(name, predicted, result.verdict) else "NO",
                note=json.dumps(result.extra, sort_keys=True) if result.extra else "", **context)
        results[name] = result
    return results


# --- values: B against A on the same workload --------------------------------------------

def values(out: Out, transition: tuple[str, str], log_a: Path, log_b: Path,
           state_a: tuple[str, Path], state_b: tuple[str, Path], workload: producer.Workload,
           **context) -> None:
    allowed = rulings.allowed(transition)
    shown = "any (" + rulings.BUMP[transition] + ")" if allowed is None else "|".join(sorted(allowed))
    jq_a, jq_b = cached(out, "jq", log_a, state_a[1], state_a[0]), cached(out, "jq", log_b, state_b[1], state_b[0])
    rows = []
    if jq_a.output is not None and jq_b.output is not None:
        rows.append(("values:jq", compare.jq_classes(jq_a.output, jq_b.output, workload)))
    for name in ("checker",) + (("bb-checker",) if "bb-checker" in consumers.available(out.work) else ()):
        before = cached(out, name, log_a, state_a[1], state_a[0], no_stop=True)
        after = cached(out, name, log_b, state_b[1], state_b[0], no_stop=True)
        if before.verdict == "accept" and after.verdict == "accept":
            rows.append((f"values:{name}", compare.record_classes(before.output, after.output, workload)))
        else:
            rows.append((f"values:{name}", {f"verdict {before.verdict} -> {after.verdict}": 1}))
    mock_a, mock_b = cached(out, "mock", log_a, state_a[1], "-"), cached(out, "mock", log_b, state_b[1], "-")
    body_a, body_b = compare.decode_body(mock_a.output), compare.decode_body(mock_b.output)
    if body_a is not None and body_b is not None:
        rows.append(("values:mock", compare.record_classes(body_a, body_b, workload, keyed=True)))
    for name, counts in rows:
        is_verdict = any(key.startswith("verdict ") for key in counts)
        crashed = any("crash" in key for key in counts)
        ok = (allowed is None and not (crashed and rulings.BUMP[transition] != "MAJOR")) or \
             (not is_verdict and compare.within(counts, allowed))
        if is_verdict and allowed is not None:
            ok = not crashed and all(" accept -> accept" in key for key in counts)
        out.row(consumer=name, transition="->".join(transition), predicted=shown,
                observed=compare.summarize(counts), match="yes" if ok else "NO", **context)


# --- N = 0: recorded logs ------------------------------------------------------------

def record_base(out: Out, producers: dict[str, ledger.Producer]) -> dict[tuple[str, str], Path]:
    logs = {}
    base = out.work / "n0"
    base.mkdir(exist_ok=True)
    for key, prod in producers.items():
        for engine in producer.ENGINES:
            xrid = f"n0-{key}-{producer.ENGINE_SHORT[engine]}"
            sandbox = producer.Sandbox.make(base, xrid)
            work_load = producer.workload("009-" + xrid, 9009)
            status = producer.run_batch(prod.fs_path, engine, sandbox, work_load.lines)
            found = sandbox.logs()
            if status != 0 or len(found) != 1:
                raise RuntimeError(f"{xrid}: exit {status}, logs {found}")
            logs[(key, engine)] = found[0]
            out.manifest.append({"xrid": xrid, "run": "n0", "slot": "-", "key": key, "source": prod.source,
                                 "blob": ledger.public_blob(prod), "engine": engine, "seed": 9009,
                                 "cwd": out.rel(sandbox.root), "log": out.rel(found[0]),
                                 "lines": found[0].read_bytes().count(b"\n")})
    return logs


def append_logs(out: Out, producers: dict[str, ledger.Producer], keys: list[str], engine: str,
                name: str) -> list[bytes]:
    """Run KEYS one after another on one sandbox (one append-only file); the file after each."""
    sandbox = producer.Sandbox.make(out.work / "n0", name)
    snapshots = []
    for index, key in enumerate(keys):
        xrid = f"{name}-{index}-{key}-{producer.ENGINE_SHORT[engine]}"
        status = producer.run_batch(producers[key].fs_path, engine, sandbox,
                                    producer.workload("009-" + xrid, 9009).lines)
        log = sandbox.expected_log()
        content = log.read_bytes() if log.exists() else b""
        if status != 0 or len(content) <= len(snapshots[-1] if snapshots else b""):
            raise RuntimeError(f"{xrid}: exit {status}, log did not grow: no stream is built on it")
        snapshots.append(content)
        out.manifest.append({"xrid": xrid, "run": "n0", "slot": name, "key": key,
                             "source": producers[key].source, "blob": ledger.public_blob(producers[key]),
                             "engine": engine, "seed": 9009, "cwd": out.rel(sandbox.root),
                             "log": out.rel(log), "lines": snapshots[-1].count(b"\n")})
    return snapshots


def n0_transitions(out: Out, producers, logs, names) -> None:
    v5 = producers["V5"]
    for transition in ledger.transitions():
        a_key, b_key = transition
        if a_key not in producers or b_key not in producers:
            continue
        a, b = producers[a_key], producers[b_key]
        state_a, state_b = state_for(a, v5), state_for(b, v5)
        for engine in producer.ENGINES:
            work_load = producer.workload("x", 9009)
            log_a, log_b = logs[(a_key, engine)], logs[(b_key, engine)]
            ctx = dict(run="n0", N=0, transition=f"{a_key}->{b_key}", engine=engine,
                       xrid=f"n0-{a_key}-{producer.ENGINE_SHORT[engine]}|n0-{b_key}-{producer.ENGINE_SHORT[engine]}")
            appended = out.work / "n0" / "appended" / f"{a_key}-{b_key}-{engine}" / "stacks.jsonl"
            appended.parent.mkdir(parents=True, exist_ok=True)
            appended.write_bytes(log_a.read_bytes() + log_b.read_bytes())
            for order in ORDERS:
                if order == "producer-first":
                    steps = [("A", log_a, state_a), ("B-before-bump", log_b, state_a), ("B-after-bump", log_b, state_b)]
                elif order == "consumer-first":
                    steps = [("A", log_a, state_a), ("A-after-bump", log_a, state_b), ("B", log_b, state_b)]
                elif order == "rolling":
                    steps = [("A", log_a, state_a), ("A+B one file", appended, state_a),
                             ("A+B one file, bumped", appended, state_b)]
                else:
                    steps = [("steady A", log_a, state_a), ("steady B", log_b, state_a), ("B-after-bump", log_b, state_b)]
                for step, log, (expect, schema_path) in steps:
                    observe(out, log, schema_path, expect, names, order=order, step=step, slot="-", **ctx)
            values(out, transition, log_a, log_b, state_a, state_b, work_load, order="all", step="values",
                   slot="-", run="n0", N=0, engine=engine, xrid=ctx["xrid"])


# --- X-streams -------------------------------------------------------------------------

def h3_class(stream: xstreams.Stream, name: str, verdict: str) -> str:
    if verdict.startswith("crash") or verdict.startswith("die"):
        return "crash"
    if verdict.startswith("stop") or verdict.startswith("reject") or verdict == "404":
        return "stop" if not stream.usable else "stop-usable"
    if stream.usable:
        return "ok"
    return "wrong-data"


def x_cells(out: Out, producers, logs, x6, names, api: dict, envelope: dict) -> list[dict]:
    v5 = producers["V5"]
    built = xstreams.build(logs[("V5", "gforth")].read_bytes(), logs[("F3", "gforth")].read_bytes(),
                           logs[("F5", "gforth")].read_bytes(), x6,
                           json.loads(v5.schema_path.read_text()))
    paths = xstreams.write(built, out.work / "x", v5.schema_path)
    summary = []
    for stream in built:
        log, schema_path = paths[stream.key]
        schema = json.loads(schema_path.read_text())
        for name in names:
            result = cached(out, name, log, schema_path, "1.1")
            predicted = predict(name, stream.content, schema, "1.1")
            out.row(run="x", N=0, order="-", transition=stream.key, step=stream.family, slot="-",
                    engine="gforth", xrid=f"x-{stream.key}", consumer=name, expect="1.1",
                    predicted=predicted, observed=result.verdict,
                    match="yes" if verdict_match(name, predicted, result.verdict) else "NO",
                    note=f"h3={h3_class(stream, name, result.verdict)}; usable={stream.usable}; {stream.note}")
        first = prefix_check.check(stream.content, {1})
        every = prefix_check.check(stream.content, {1}, every_line=True)
        compound = compound_check.run(stream.content, schema, "1.1", api, envelope)
        env_errors = envelope_errors(stream.content, envelope)
        summary.append({"stream": stream.key, "usable": stream.usable, "note": stream.note,
                        "prefix-first": "ok" if first.get("ok") else first["stopped"],
                        "prefix-every": "ok" if every.get("ok") else every["stopped"],
                        "envelope": env_errors or "valid",
                        "compound": "ok" if compound.get("ok") else compound["stopped"]})
    return summary


def envelope_errors(content: bytes, envelope: dict) -> str:
    try:
        import jsonschema
    except ImportError:
        raise SystemExit("009 needs jsonschema: uv run --no-project --with jsonschema python ...")
    validator = jsonschema.Draft202012Validator(envelope)
    reasons = {}
    for number, line in enumerate([line for line in content.split(b"\n") if line], 1):
        try:
            record = json.loads(line.decode("utf-8-sig"))
        except ValueError:
            reasons.setdefault("not JSON", []).append(number)
            continue
        for error in validator.iter_errors(record):
            reasons.setdefault(error.message[:50], []).append(number)
    return "; ".join(f"{reason} (lines {','.join(map(str, numbers[:4]))})" for reason, numbers in reasons.items())


# --- live sessions -----------------------------------------------------------------------

class Slot:
    def __init__(self, out: Out, run: str, index: int, engine: str, xdg_fallback: bool, seed: int):
        self.out, self.run, self.index, self.engine = out, run, index, engine
        self.sxrid = f"{run}s{index}"
        self.seed = seed
        (out.work / "runs" / run).mkdir(parents=True, exist_ok=True)
        self.sandbox = producer.Sandbox.make(out.work / "runs" / run, f"s{index}", xdg_fallback)
        self.session = sessions.Session.start(self.sxrid, self.sandbox.root, self.sandbox.env)
        self.current: str | None = None
        self.counter = 0
        self.segments: dict[str, tuple[Path, str]] = {}  # key -> (segment file, xrid)
        self.contract_log = self.sandbox.expected_log()
        self.followers = []

    def follow(self) -> None:
        jq_file = self.out.work / "consumers" / "stacks.jq"
        live_out = open(self.sandbox.root / "jq-live.out", "wb")
        live_err = open(self.sandbox.root / "jq-live.err", "wb")
        self.followers.append(("jq-live", subprocess.Popen(
            ["sh", "-c", 'exec tail -n +1 -F "$1" 2>/dev/null | jq --unbuffered -c -f "$2"', "_",
             str(self.contract_log), str(jq_file)], stdout=live_out, stderr=live_err, start_new_session=True)))
        follower = self.out.work / "consumers" / "follower.sh"
        if follower.exists():
            env = {key: value for key, value in self.sandbox.env.items()}
            env["TZ"] = "UTC"
            self.followers.append(("follower-live", subprocess.Popen(
                ["bash", str(follower)], env=env, stdout=open(self.sandbox.root / "follower-live.out", "wb"),
                stderr=open(self.sandbox.root / "follower-live.err", "wb"), start_new_session=True)))

    def live_status(self) -> dict[str, str]:
        status = {}
        file_lines = self.contract_log.read_bytes().count(b"\n") if self.contract_log.exists() else 0
        time.sleep(0.3)
        for name, proc in self.followers:
            err = (self.sandbox.root / f"{name}.err").read_bytes().decode("utf-8", "replace")
            out_lines = (self.sandbox.root / f"{name}.out").read_bytes().count(b"\n")
            jq_errors = [line for line in err.splitlines() if line.startswith("jq:")]
            if jq_errors:
                status[name] = f"crash:{jq_errors[0].split(':', 2)[-1].strip()[:50]}"
            elif proc.poll() is not None:
                status[name] = f"exited:{proc.returncode}"
            else:
                status[name] = f"follow lines={out_lines} file={file_lines}"
        return status

    def run_producer(self, prod: ledger.Producer) -> str:
        self.counter += 1
        xrid = f"{self.sxrid}-{self.counter:02d}-{prod.key}{producer.ENGINE_SHORT[self.engine]}"
        fs_name = f"inspect-{prod.key}.fs"
        if not (self.sandbox.root / fs_name).exists():
            shutil.copyfile(prod.fs_path, self.sandbox.root / fs_name)
        before = {path: path.stat().st_size for path in self.sandbox.logs()}
        work_load = producer.workload("009-" + xrid, self.seed, tty=True)
        self.session.run_gforth(self.engine, fs_name, work_load.lines)
        grown = [path for path in self.sandbox.logs() if path.stat().st_size != before.get(path, 0)]
        if len(grown) != 1:
            raise RuntimeError(f"{xrid}: {len(grown)} logs grew")
        segment = grown[0].read_bytes()[before.get(grown[0], 0):]
        segment_file = self.sandbox.root / "segments" / xrid / "stacks.jsonl"
        segment_file.parent.mkdir(parents=True, exist_ok=True)
        segment_file.write_bytes(segment)
        self.segments[prod.key] = (segment_file, xrid)
        self.current = prod.key
        self.out.manifest.append({"xrid": xrid, "run": self.run, "slot": self.index, "key": prod.key,
                                  "source": prod.source, "blob": ledger.public_blob(prod), "engine": self.engine,
                                  "seed": self.seed, "cwd": self.out.rel(self.sandbox.root),
                                  "log": self.out.rel(grown[0]), "lines": segment.count(b"\n")})
        return xrid

    def close(self) -> None:
        for _, proc in self.followers:
            try:
                os.killpg(proc.pid, 15)
            except ProcessLookupError:
                pass
        self.session.kill()


def live_run(out: Out, producers, n: int, order: str, run_index: int, names) -> None:
    run = f"r{run_index:02d}"
    v5 = producers["V5"]
    poll = [name for name in names if name != "follower"]
    slots = [Slot(out, run, index, producer.ENGINES[(index + run_index) % 3],
                  (index + run_index) % 4 == 3, zlib.crc32(f"{run}-{index}".encode()))
             for index in range(n)]
    try:
        for slot in slots:
            slot.follow()

        def obs(step: str, transition: str, expect_state) -> None:
            expect, schema_path = expect_state
            for slot in slots:
                ctx = dict(run=run, N=n, order=order, transition=transition, step=step, slot=slot.index,
                           engine=slot.engine, xrid=slot.segments.get(slot.current, (None, ""))[1])
                # V1 on honour GFORTH_INSPECT_LOG_DIR and fall back to .../gforth-inspect/;
                # V0 and Vc write their legacy default whatever the environment says
                present = any(producers[key].default_dir == "gforth-inspect" for key in slot.segments)
                observe(out, slot.contract_log, schema_path, expect, poll, present=present, **ctx)
                for name, status in slot.live_status().items():
                    predicted = "follow" if present or name == "follower-live" else "absent"
                    observed = status.split()[0]
                    if name == "jq-live" and observed == "follow":
                        parts = dict(item.split("=") for item in status.split()[1:])
                        observed = "follow" if parts["lines"] == parts["file"] else f"lag {status}"
                        if parts["file"] == "0":
                            observed = "absent"
                    out.row(consumer=name, expect="-", predicted=predicted, observed=observed,
                            match="yes" if observed == predicted else "NO", note=status, **ctx)

        def compare_slot(transition: tuple[str, str], slot: Slot) -> None:
            a_key, b_key = transition
            seg_a, xrid_a = slot.segments[a_key]
            seg_b, xrid_b = slot.segments[b_key]
            work_load = producer.workload("x", slot.seed, tty=True)
            values(out, transition, seg_a, seg_b, state_for(producers[a_key], v5), state_for(producers[b_key], v5),
                   work_load, run=run, N=n, order=order, step="values", slot=slot.index, engine=slot.engine,
                   xrid=f"{xrid_a}|{xrid_b}")

        transitions = [t for t in ledger.transitions() if t[0] in producers and t[1] in producers]
        if order == "mixed":
            sequence = [key for key in ledger.SEQUENCE if key in producers]
            for slot_index, slot in enumerate(slots):
                slot.run_producer(producers[sequence[min(slot_index, len(sequence) - 1)]])
            for step in range(len(sequence) - 1):
                oldest = sequence[min(step, len(sequence) - 1)]
                state = state_for(producers[oldest], v5)
                obs("steady", f"window@{oldest}", state)
                moved = []
                for slot_index, slot in enumerate(slots):
                    position = step + slot_index
                    if position + 1 < len(sequence):
                        slot.run_producer(producers[sequence[position + 1]])
                        moved.append((slot, (sequence[position], sequence[position + 1])))
                obs("steady after step", f"window@{oldest}", state)
                for slot, transition in moved:
                    compare_slot(transition, slot)
                if not moved:
                    break
            transitions = ledger.SKIPS
        for transition in transitions:
            if order == "mixed" and transition not in ledger.SKIPS:
                continue
            a_key, b_key = transition
            if a_key not in producers or b_key not in producers:
                continue
            label = f"{a_key}->{b_key}"
            state_a, state_b = state_for(producers[a_key], v5), state_for(producers[b_key], v5)
            for slot in slots:
                if slot.current != a_key:
                    slot.run_producer(producers[a_key])
            obs("A", label, state_a)
            if order == "consumer-first":
                obs("A-after-bump", label, state_b)
                for slot in slots:
                    slot.run_producer(producers[b_key])
                obs("B", label, state_b)
            elif order == "rolling":
                for slot in slots:
                    slot.run_producer(producers[b_key])
                    obs(f"rolled {slot.index + 1}/{n}", label, state_a)
                obs("B-after-bump", label, state_b)
            else:
                for slot in slots:
                    slot.run_producer(producers[b_key])
                obs("B-before-bump", label, state_a)
                obs("B-after-bump", label, state_b)
            for slot in slots:
                compare_slot(transition, slot)
    finally:
        for slot in slots:
            slot.close()


# --- main --------------------------------------------------------------------------

def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("work")
    parser.add_argument("--live", default="1,2,3,4,5")
    parser.add_argument("--orders", default=",".join(ORDERS))
    parser.add_argument("--only", default="x,n0,live")
    parser.add_argument("--out", default=str(HERE.parent))
    parser.add_argument("--tag", default="matrix")
    options = parser.parse_args(argv)
    work = Path(options.work).resolve()
    work.mkdir(parents=True, exist_ok=True)
    out = Out(Path(options.out), work)
    out.out_dir.mkdir(parents=True, exist_ok=True)
    producers = ledger.materialize(work)
    blobs = consumers.pin(work)
    names = consumers.available(work)
    LOCAL.mkdir(parents=True, exist_ok=True)
    with open(LOCAL / "runs.tsv", "a") as handle:
        handle.write(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\t{options.tag}\t{work}\t"
                     f"Vc={producers['Vc'].blob if 'Vc' in producers else 'absent'}\n")
    print("consumers", blobs, names, flush=True)
    api = json.loads((HERE.parent / "openapi-stacks.json").read_text())
    envelope = json.loads((HERE.parent / "envelope.schema.json").read_text())
    only = set(options.only.split(","))
    logs = record_base(out, producers)
    if "x" in only:
        snapshots = append_logs(out, producers, ["V2", "V5", "F3", "F4"], "gforth", "x6")
        x6 = {"V2-V5": snapshots[1], "V2-V5-F3": snapshots[2], "V2-V5-F3-F4": snapshots[3]}
        summary = x_cells(out, producers, logs, x6, names, api, envelope)
        xname = "xstreams.tsv" if options.tag == "matrix" else f"{options.tag}-xstreams.tsv"
        with open(out.out_dir / xname, "w") as handle:
            columns = ["stream", "usable", "prefix-first", "prefix-every", "envelope", "compound", "note"]
            handle.write("\t".join(columns) + "\n")
            for entry in summary:
                handle.write("\t".join(str(entry[column]) for column in columns) + "\n")
        print("x done", len(out.rows), flush=True)
    if "n0" in only:
        n0_transitions(out, producers, logs, names)
        print("n0 done", len(out.rows), flush=True)
    out.write(f"{options.tag}.tsv")
    if "live" in only:
        sessions.kill_ours()
        run_index = 0
        for n in [int(part) for part in options.live.split(",") if part]:
            for order in options.orders.split(","):
                run_index += 1
                started = time.monotonic()
                try:
                    live_run(out, producers, n, order, run_index, names)
                except Exception as error:  # a failed run is a row, never a silent gap
                    out.row(run=f"r{run_index:02d}", N=n, order=order, consumer="harness",
                            predicted="run completes", observed=f"error:{type(error).__name__}: {error}".replace(str(work), "$WORK")[:200],
                            match="NO")
                    sessions.kill_ours()
                print(f"live N={n} {order} r{run_index:02d} {time.monotonic() - started:.0f}s rows={len(out.rows)}",
                      flush=True)
                out.write(f"{options.tag}.tsv")
    out.write(f"{options.tag}.tsv")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
