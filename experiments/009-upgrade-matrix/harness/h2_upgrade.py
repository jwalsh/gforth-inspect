"""H2: a scripted consumer runs CONSUMER-AGENTS.md "A new version", steps 1-5, as written.

    uv run --no-project --with jsonschema python h2_upgrade.py WORK_DIR [--out ..]

For every ledger transition A -> B it logs each step as `ran`, `failed as
written` or `n/a`, with the evidence, to OUT/h2.tsv.  Step 0 is gate 8's
I-1 prefix check (D-38), run before SHA256SUMS.

The consumer it models carries the deviations a downstream copy carries
(issues #1, #2, #3, #17, all labelled downstream-patch).  A step "as
written" is the text of the step, or of the issue's reproducer, run
verbatim; where that fails, an adapted run (said so in the evidence)
tells whether B fixes the deviation, so step 3's verdict is still known.
Nothing is posted anywhere: step 5's reply is written to OUT/h2-replies.txt.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(HERE))

import consumers  # noqa: E402
import ledger  # noqa: E402
import prefix_check  # noqa: E402
import producer  # noqa: E402

ASSETS = [("env/inspect.fs", "inspect.fs"), ("contract/stacks-log.schema.json", "stacks-log.schema.json"),
          ("contract/stacks-log.org", "stacks-log.org"), ("contract/CONSUMERS.org", "CONSUMERS.org"),
          ("contract/CONSUMER-AGENTS.md", "CONSUMER-AGENTS.md"), ("contract/skill/SKILL.md", "SKILL.md")]
DEVIATIONS = (1, 2, 3, 17)
FIXTURE_ROWS = {
    "F1a": "| 2026-11-22 | release v0.5.0: no contract change | PATCH (no schema change) | #23 | 0.5.0 | none needed |",
    "F1": "| 2026-11-22 | release v1.0.0: no contract change | PATCH (no schema change) | #23 | 1.0.0 | none needed |",
    "F2": "| 2026-11-22 | =input.text=: DEL (0x7f) written as =\\u007f= | PATCH (values only) | (fixture) | 1.0.1 | none needed |",
    "F3": "| 2026-11-22 | 1.2: snapshot =depth= (optional) | MINOR | (fixture) | 1.1.0 | checker |",
    "F4": "| 2026-11-22 | 2.0: snapshot =data= renamed =cells=; record v2 | MAJOR | (fixture) | 2.0.0 | all |",
    "F5": "| 2026-11-22 | 10.0: =data=, =float= move into =stacks=; =task=, =caps=, =bye=; record v10 | MAJOR | (fixture) | 10.0.0 | all |",
}


def sandbox_env(root: Path) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items()
           if key not in ("GFORTH_INSPECT_LOG_DIR", "XDG_STATE_HOME")}
    env.update({"HOME": str(root / "home"), "XDG_STATE_HOME": str(root / "state"), "TMPDIR": str(root / "tmp")})
    for name in ("home", "state", "tmp"):
        (root / name).mkdir(parents=True, exist_ok=True)
    return env


# --- step 1: download, or a staged release dir ------------------------------------------

def stage(prod: ledger.Producer, directory: Path) -> tuple[list[str], list[str]]:
    """Build B's release dir as RELEASING.org "by hand" does; (assets present, assets missing)."""
    directory.mkdir(parents=True, exist_ok=True)
    commit = ledger.HARDEN if prod.key in ("V5", "Vc") or prod.source == "fixture from V5" else prod.source
    present, missing = [], []
    for source, name in ASSETS:
        if name == "inspect.fs":
            content = prod.fs_path.read_bytes()
        elif name == "stacks-log.schema.json":
            content = prod.schema_path.read_bytes()
        else:
            try:
                content = ledger.at_ref(commit, source).encode()
            except (FileNotFoundError, subprocess.CalledProcessError):
                missing.append(name)
                continue
        if name == "stacks-log.org":
            content = content.replace(b"../CONSUMERS.org", b"CONSUMERS.org")
            chain = {"F1a": ["F1a"], "F1": ["F1"], "F2": ["F1", "F2"], "F3": ["F1", "F2", "F3"],
                     "F4": ["F1", "F2", "F3", "F4"], "F5": ["F1", "F2", "F3", "F4", "F5"]}.get(prod.key, [])
            for key in chain:
                content = content.rstrip(b"\n") + b"\n" + FIXTURE_ROWS[key].encode() + b"\n"
        (directory / name).write_bytes(content)
        present.append(name)
    sums = "".join(f"{hashlib.sha256((directory / name).read_bytes()).hexdigest()}  {name}\n" for name in present)
    (directory / "SHA256SUMS").write_text(sums)
    return present, missing


def step1(prod: ledger.Producer, root: Path) -> list[tuple[str, str]]:
    rows = []
    tag = f"v{prod.inspect}" if prod.inspect else None
    if tag is None:
        rows.append(("1", "failed as written", "B announces no version (no hello.inspect): no vX.Y.Z to download"))
    else:
        target = root / "download"
        target.mkdir(exist_ok=True)
        proc = subprocess.run(["gh", "release", "download", tag, "-R", "jwalsh/gforth-inspect"], cwd=target,
                              capture_output=True, text=True)
        message = (proc.stderr or proc.stdout).strip().splitlines()[-1:] or ["(no output)"]
        status = "ran" if proc.returncode == 0 else "failed as written"
        rows.append(("1", status, f"gh release download {tag}: exit {proc.returncode}: {message[0][:80]}"))
    staged = root / "release"
    present, missing = stage(prod, staged)
    check = subprocess.run(["shasum", "-a", "256", "-c", "SHA256SUMS"], cwd=staged, capture_output=True, text=True)
    rows.append(("1-staged", "ran" if check.returncode == 0 and not missing else "failed as written",
                 f"staged {len(present)}/6 assets{' (missing ' + ', '.join(missing) + ')' if missing else ''}; "
                 f"shasum -c exit {check.returncode}"))
    return rows


# --- step 2: the change log and the version stop ------------------------------------------

def change_rows(release: Path) -> list[str]:
    path = release / "stacks-log.org"
    if not path.exists():
        return []
    text = path.read_text()
    tail = text.split("* Change log", 1)[1] if "* Change log" in text else ""
    return [line for line in tail.splitlines() if line.startswith("| 20")]


def step2(a: ledger.Producer, b: ledger.Producer, root: Path, work: Path, log_b: Path) -> list[tuple[str, str]]:
    rows_a = change_rows(root / "release-a")
    rows_b = change_rows(root / "release")
    new_rows = [row for row in rows_b if row not in rows_a]
    changed_rows = len([row for row in rows_a if row not in rows_b])
    expect_a = a.contract or "1.1"
    before = consumers.run_checker(work, log_b, a.schema_path if a.contract else b.schema_path, expect_a)
    evidence = [f"change log: {len(rows_b)} rows, {len(new_rows)} new since A, {changed_rows} of A's rows rewritten"]
    differs = (b.contract or "") .split(".")[:2] != expect_a.split(".")[:2]
    if not rows_b:
        return [("2", "failed as written", "B ships no change log table; " + evidence[0])]
    if not differs:
        evidence.append(f"contract {b.contract} = expected {expect_a}: checker {before.verdict}")
        if before.verdict != "accept":
            return [("2", "failed as written", "; ".join(evidence))]
        status = "ran" if new_rows or a.blob == b.blob else "failed as written"
        if status != "ran":
            evidence.append("B differs from A but the change log has no new row")
        return [("2", status, "; ".join(evidence))]
    evidence.append(f"checker (expects {expect_a}) on B: {before.verdict}")
    if not before.verdict.startswith("stop"):
        return [("2", "failed as written", "; ".join(evidence) + ": no stop")]
    bumped = consumers.run_checker(work, log_b, b.schema_path, b.contract or expect_a)
    evidence.append(f"after the bump to {b.contract}: {bumped.verdict}")
    return [("2", "ran" if bumped.verdict == "accept" else "failed as written", "; ".join(evidence))]


# --- step 3: each deviation's reproducer ------------------------------------------------

REPRODUCERS = HERE.parent / "reproducers"


def reproducer(number: int) -> str | None:
    """The issue's first code block, from the reviewed copy in reproducers/: never the live issue text."""
    pinned = REPRODUCERS / f"issue-{number}.txt"
    return pinned.read_text() if pinned.exists() else None


def as_written(number: int, code: str | None, release: Path, scratch: Path) -> str:
    if code is None:
        return "no code block"
    root = Path(tempfile.mkdtemp(prefix=f"repro{number}-", dir=scratch))
    for item in release.iterdir():
        shutil.copyfile(item, root / item.name)
    proc = subprocess.run(["sh", "-c", code], cwd=root, env=sandbox_env(root), capture_output=True, text=True,
                          timeout=60)
    errors = [line for line in (proc.stderr + proc.stdout).splitlines()
              if re.search(r"No such file|not found|Error|error|Undefined", line)]
    if proc.returncode != 0 or errors:
        shown = re.sub(r"/\S+/", ".../", (errors or [f"exit {proc.returncode}"])[0])
        return f"exit {proc.returncode}: {shown[:70]}"
    return "ok"


def stack(record: dict, name: str):
    """data / float from a snapshot of any ledger or fixture shape (F4 renames, F5 nests)."""
    if "stacks" in record:
        return record["stacks"].get(name)
    if name == "data" and "cells" in record:
        return record["cells"]
    return record.get(name)


def adapted(number: int, prod: ledger.Producer, scratch: Path) -> str:
    """The reproducer's intent, runnable: 'fixed', 'not fixed' or why it cannot tell."""
    root = Path(tempfile.mkdtemp(prefix=f"adapt{number}-", dir=scratch))
    env = sandbox_env(root)
    env["GFORTH_INSPECT_LOG_DIR"] = str(root / "state" / "logdir")
    shutil.copyfile(prod.fs_path, root / "inspect.fs")
    log_glob = lambda: sorted(root.glob("state/*/stacks.jsonl"))

    def one(program: str) -> list[dict]:
        subprocess.run(["gforth", "inspect.fs", "-e", program], cwd=root, env=env, capture_output=True, timeout=30)
        logs = log_glob()
        return [json.loads(line) for line in logs[0].read_bytes().split(b"\n") if line] if logs else []

    if number == 1:
        records = one("log-on -0e 1.7976931348623157e308 0.1e .stacks bye")
        snapshots = [record for record in records if record.get("event") == "snapshot"]
        floats = stack(snapshots[-1], "float") if snapshots else None
        if not floats:
            return "cannot tell: no snapshot"
        ok = str(floats[0]).startswith("-") and floats[1] == 1.7976931348623157e308
        return "fixed" if ok else f"not fixed ({floats[:2]})"
    if number == 2:
        records = one("log-on all-~~ : t ( -- ) -7 ~~ drop ; t bye")
        snapshot = ([record for record in records if record.get("event") == "snapshot"] or [{}])[-1]
        return "fixed" if snapshot.get("where") == "t" and snapshot.get("src") else \
            f"not fixed (where {snapshot.get('where')!r})"
    if number == 3:
        records = one('log-on s" R1-floats" log-id -0e 1e .stacks bye')
        snapshots = [record for record in records if record.get("event") == "snapshot"]
        return "fixed" if snapshots and snapshots[-1].get("id") == "R1-floats" else "not fixed (no id)"
    if number == 17:
        import time
        tag = (lambda name: f's" {name}" log-id ') if prod.has_log_id else (lambda name: "")
        first = subprocess.Popen(["gforth", "inspect.fs"], cwd=root, env=env, stdin=subprocess.PIPE,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        first.stdin.write(("log-on " + tag("A1") + "1 .stacks\n").encode())
        first.stdin.flush()
        time.sleep(1)
        subprocess.run(["gforth", "inspect.fs", "-e", "log-on " + tag("B1") + "9 .stacks bye"],
                       cwd=root, env=env, capture_output=True, timeout=30)
        time.sleep(0.5)
        first.stdin.write((tag("A2") + "2 .stacks bye\n").encode())
        first.stdin.close()
        first.wait(timeout=30)
        logs = log_glob()
        if not logs:
            return "cannot tell: no log"
        lines = [line for line in logs[0].read_bytes().split(b"\n") if line]
        try:
            records = [json.loads(line) for line in lines]
        except ValueError:
            return f"not fixed ({len(lines)} lines, one not JSON)"
        hellos = sum(1 for record in records if record.get("event") == "hello")
        data = [stack(record, "data") for record in records if record.get("event") == "snapshot"]
        ok = hellos == 2 and data == [[1], [9], [1, 2]]  # A keeps its 1 under the 2
        return "fixed" if ok else f"not fixed (hellos {hellos}, snapshots {data})"
    raise ValueError(number)


def step3(b: ledger.Producer, root: Path, scratch: Path, codes: dict[int, str | None],
          cache: dict) -> list[tuple[str, str]]:
    parts, written_ok = [], True
    for number in DEVIATIONS:
        written = as_written(number, codes[number], root / "release", scratch)
        written_ok = written_ok and written == "ok"
        key = (b.key, number)
        if key not in cache:
            cache[key] = adapted(number, b, scratch)
        parts.append(f"#{number}: as written {written}; adapted {cache[key]}")
    fixed = [number for number in DEVIATIONS if cache[(b.key, number)] == "fixed"]
    summary = f"drop rows {['#%d' % n for n in fixed] or 'none'}, keep {['#%d' % n for n in DEVIATIONS if n not in fixed] or 'none'}"
    return [("3", "ran" if written_ok else "failed as written", summary + " | " + " | ".join(parts))]


# --- step 4: own init and tests ---------------------------------------------------------

def step4(a: ledger.Producer, b: ledger.Producer, log_b: Path) -> list[tuple[str, str]]:
    records = [json.loads(line) for line in log_b.read_bytes().split(b"\n") if line]
    hello = next(record for record in records if record.get("event") == "hello")
    schema = json.loads(b.schema_path.read_text())
    problems = []
    if hello.get("inspect") is None:
        problems.append("hello has no inspect: no version to check")
    if hello.get("contract") is None:
        problems.append("hello has no contract")
    elif hello.get("contract") != schema.get("x-contract"):
        problems.append(f"hello.contract {hello.get('contract')} != schema x-contract {schema.get('x-contract')}")
    try:
        import jsonschema
        validator = jsonschema.Draft202012Validator(schema)
        invalid = sum(1 for record in records if next(iter(validator.iter_errors(record)), None))
        if invalid:
            problems.append(f"{invalid} records invalid under B's schema")
    except ImportError:
        raise SystemExit("009 needs jsonschema: uv run --no-project --with jsonschema python ...")
    if a.inspect == b.inspect and a.blob != b.blob:
        problems.append(f"version cannot tell A from B: both hello.inspect {b.inspect}, blobs differ")
    return [("4", "failed as written" if problems else "ran", "; ".join(problems) or
             f"inspect {hello.get('inspect')}, contract {hello.get('contract')} = x-contract, all records valid")]


# --- step 5: reply in the release thread ------------------------------------------------

def step5(b: ledger.Producer, releases: int, replies: list[str]) -> list[tuple[str, str]]:
    replies.append(f"upgraded to v{b.inspect}" if b.inspect else "staying: B has no version")
    if releases == 0:
        return [("5", "failed as written", f"no GitHub release exists ({releases}): no release thread; reply kept locally")]
    return [("5", "ran", "reply drafted")]


# --- Vc: which differences carry an issue and a reproducer (P8) ----------------------------------

def vc_hunks(producers: dict[str, ledger.Producer], codes: dict[int, str | None]) -> str:
    if "Vc" not in producers:
        return "Vc absent"
    base = producers["V0"].fs_path.read_text().splitlines()
    local = producers["Vc"].fs_path.read_text().splitlines()
    hunks = [group for group in difflib.SequenceMatcher(None, base, local).get_grouped_opcodes(0)]
    cited, uncited, code_only = 0, 0, 0
    for group in hunks:
        added = "\n".join(line for tag, _, _, j1, j2 in group if tag != "delete" for line in local[j1:j2])
        changed = "\n".join(line for tag, _, _, j1, j2 in group if tag != "delete" for line in local[j1:j2]
                            if not line.lstrip().startswith("\\"))
        if re.search(r"issue #\d+", added):
            cited += 1
        elif changed.strip():
            uncited += 1
        else:
            code_only += 1
    runnable = [n for n in DEVIATIONS if codes.get(n) and "gforth" in (codes[n] or "")]
    return (f"Vc vs V0: {len(hunks)} hunks; {cited} cite an issue in their comment, {uncited} change code "
            f"with no issue cited, {code_only} comment-only; reproducers with a gforth command: "
            f"{len(runnable)}/{len(DEVIATIONS)}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("work")
    parser.add_argument("--out", default=str(HERE.parent))
    options = parser.parse_args(argv)
    work = Path(options.work).resolve()
    work.mkdir(parents=True, exist_ok=True)
    out = Path(options.out)
    producers = ledger.materialize(work)
    consumers.pin(work)
    codes = {number: reproducer(number) for number in DEVIATIONS}
    listed = subprocess.run(["gh", "release", "list", "-R", "jwalsh/gforth-inspect", "--json", "tagName",
                             "--jq", "length"], capture_output=True, text=True)
    if listed.returncode != 0:  # a failed gh is not "no release"
        raise RuntimeError(f"gh release list: exit {listed.returncode}: {listed.stderr.strip()[:80]}")
    releases = int(listed.stdout.strip())
    rows, replies, cache = [], [], {}
    scratch = work / "h2"
    scratch.mkdir(exist_ok=True)
    for a_key, b_key in ledger.transitions():
        if a_key not in producers or b_key not in producers:
            continue
        a, b = producers[a_key], producers[b_key]
        root = scratch / f"{a_key}-{b_key}"
        root.mkdir(exist_ok=True)
        stage(a, root / "release-a")
        vc = ledger.vc_root()
        if a_key == "Vc" and vc is not None:  # the downstream copy's own prose, never committed
            shutil.copyfile(vc / "forth" / "env" / "stacks-log.org", root / "release-a" / "stacks-log.org")
        sandbox = producer.Sandbox.make(root, "b-run")
        log_b = producer.run_checked(b.fs_path, "gforth", sandbox,
                                     producer.workload(f"009-h2-{b_key}", 9009).lines, f"h2 {b_key}")
        label = f"{a_key}->{b_key}"
        first = prefix_check.check(log_b.read_bytes(), {a.v}, every_line=True)
        steps = [("0", "ran", "I-1 ok, v " + str(first["v"])) if first.get("ok")
                 else ("0", "ran", "I-1 stop: " + first["stopped"])]
        steps += step1(b, root)
        steps += step2(a, b, root, work, log_b)
        steps += step3(b, root, scratch, codes, cache)
        steps += step4(a, b, log_b)
        steps += step5(b, releases, replies)
        rows += [(label, *step) for step in steps]
        print(label, " ".join(f"{step[0]}:{step[1]}" for step in steps), flush=True)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "h2.tsv", "w") as handle:
        handle.write("transition\tstep\tstatus\tevidence\n")
        for row in rows:
            handle.write("\t".join(str(part).replace("\t", " ") for part in row) + "\n")
        handle.write(f"Vc\tP8\t-\t{vc_hunks(producers, codes)}\n")
    (out / "h2-replies.txt").write_text("\n".join(replies) + "\n")
    print(vc_hunks(producers, codes))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
