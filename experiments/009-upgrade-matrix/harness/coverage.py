"""H4: corpus coverage, schema path x value class x version (gate 7).

    python3 coverage.py WORK_DIR [--out ..] [--scenarios ../../../corpus]

Records every corpus scenario under every ledger version and fixture (with
corpus/record.py, INSPECT_FS and SCHEMA_JSON pointing at the version; into
WORK_DIR, never into corpus/), classifies every value it finds, and writes
OUT/coverage.tsv: one row per (path, class), one column per version, the
cell being the number of scenarios that exercise it, "-" where the version
does not support the path, and GAP where it does and no scenario does.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(HERE))

import ledger  # noqa: E402
import producer  # noqa: E402
import shutil  # noqa: E402

VERSIONS = ["V0", "V1", "V2", "V3", "V4", "V5", "Vc", "F1", "F2", "F3", "F4", "F5"]


def snapshot_stacks(record: dict) -> tuple:
    if "stacks" in record:
        return record["stacks"].get("data"), record["stacks"].get("float")
    return record.get("cells", record.get("data")), record.get("float")


def classify_text(text: str) -> set[str]:
    classes = set()
    if text == "":
        classes.add("empty")
    if any(ord(char) < 0x20 for char in text):
        classes.add("control")
    if '"' in text or "\\" in text:
        classes.add("quote-backslash")
    if "\x7f" in text:
        classes.add("DEL")
    if any(ord(char) > 0x7f and char != "�" for char in text):
        classes.add("utf8-multibyte")
    if "�" in text:
        classes.add("U+FFFD")
    if len(text.encode()) > 1000:
        classes.add("long>1000")
    if text and not classes:
        classes.add("ascii")
    return classes


def classify(raw: bytes) -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    add = lambda path, value_class: found.add((path, value_class))
    lines = [line for line in raw.split(b"\n") if line]
    hellos = 0
    for line in lines:
        try:
            record = json.loads(line)
        except ValueError:
            add("log", "line not JSON")
            continue
        add("v", f"= {record.get('v')}")
        event = record.get("event")
        add("event", str(event))
        if event == "hello":
            hellos += 1
            add("hello.inspect", "present" if "inspect" in record else "absent")
            add("hello.contract", "present" if "contract" in record else "absent")
            continue
        if event != "snapshot":
            continue
        if "id" in record:
            add("snapshot.id", "escaped" if any(c in record["id"] for c in '"\\') else "present")
            if len(record["id"]) == 63:
                add("snapshot.id", "truncated at 63")
        else:
            add("snapshot.id", "absent")
        for key in ("where", "src"):
            add(key, "null" if record.get(key) is None else "string")
        if "depth" in record or "depth" in record.get("stacks", {}):
            add("depth", "present")
        data, floats = snapshot_stacks(record)
        data = data or []
        floats = floats or []
        add("data", "empty" if not data else "nonempty")
        for cell in data:
            if cell == 0:
                add("data", "zero")
            elif cell < 0:
                add("data", "negative")
            if abs(cell) > 2**53:
                add("data", "beyond 2^53")
            if cell in (2**63 - 1, -2**63):
                add("data", "int64 extreme")
        if len(data) > 100:
            add("data", "depth>100")
        add("float", "empty" if not floats else "nonempty")
        for value in floats:
            if value is None:
                add("float", "null")
            elif value == 0 and str(value).startswith("-"):
                add("float", "-0.0")
            elif value != 0 and abs(value) < 2.2250738585072014e-308:
                add("float", "subnormal")
            elif abs(value) > 1e308:
                add("float", "near DBL_MAX")
            else:
                add("float", "finite")
        rs = record.get("rs", [])
        add("rs", "empty" if not rs else "nonempty")
        for item in rs:
            add("rs", "frame" if isinstance(item, dict) else ("sp" if item == "sp" else "integer"))
        inp = record.get("input", {})
        add("input.file", "a .fs file" if str(inp.get("file", "")).endswith(".fs") else "other")
        add("input.line", "positive" if isinstance(inp.get("line"), int) and inp["line"] > 0 else "<= 0")
        add("input.in", "0" if inp.get("in") == 0 else "> 0")
        for text_class in classify_text(inp.get("text", "")):
            add("input.text", text_class)
    if hellos > 1:
        add("log", "several hellos")
    if lines and not lines[-1].startswith(b'{"v"'):
        add("log", "last line damaged")
    return found


def supports(version: str, path: str, value_class: str) -> bool:
    if path == "hello.inspect" and value_class == "present":
        return version not in ("V0", "Vc")
    if path == "hello.inspect" and value_class == "absent":
        return version in ("V0", "Vc")
    if path == "hello.contract" and value_class == "present":
        return version not in ("V0", "V1")
    if path == "hello.contract" and value_class == "absent":
        return version in ("V0", "V1")
    if path == "snapshot.id" and value_class != "absent":
        return version not in ("V0", "V1")
    if path == "depth":
        return version in ("F3", "F4", "F5")
    if path == "v":
        return value_class == {"F4": "= 2", "F5": "= 10"}.get(version, "= 1")
    if path == "event" and value_class in ("caps", "bye"):
        return version == "F5"
    if path == "input.text" and value_class == "DEL":
        return version not in ("V0", "Vc", "F2", "F3", "F4", "F5")  # V0 blanks it; F2 on escape it
    if path == "data" and value_class in ("negative", "int64 extreme", "beyond 2^53"):
        return version not in ("V0", "Vc")  # only 05 has them, under hex BASE: V0 and Vc write hex, not JSON
    if path == "float" and value_class == "-0.0":
        return version != "V0"  # issue #1
    if path == "input.text" and value_class in ("utf8-multibyte", "U+FFFD"):
        return version not in ("V0", "Vc")  # V0's json-str passes bytes through: invalid UTF-8, line unreadable
    if path == "input.text" and value_class == "control":
        return version not in ("V0", "Vc")  # V0's json-str writes controls as spaces
    if path == "log" and value_class in ("line not JSON", "last line damaged"):
        return version in ("V1", "V2")  # issue #17 (fixed from V3); V0, Vc: the schedule is not recordable
    if path == "snapshot.id" and value_class == "truncated at 63":
        return version not in ("V0", "V1")
    return True


def record_all(work: Path, scenarios: Path) -> dict[str, list[Path]]:
    producers = ledger.materialize(work)
    recorded = {}
    for version in VERSIONS:
        if version not in producers:
            continue
        out = work / "coverage" / version
        if producers[version].default_dir != "gforth-inspect":
            # record.py reads only $GFORTH_INSPECT_LOG_DIR/stacks.jsonl, which V0 and Vc ignore:
            # load each file scenario the way record.py does and take the log the producer wrote
            out.mkdir(parents=True, exist_ok=True)
            for scenario in sorted(scenarios.glob("[0-9][0-9]-*.fs")):
                if "\\ p0: " in scenario.read_text(errors="replace"):
                    continue  # a multi-producer schedule: not recordable this way
                sandbox = producer.Sandbox.make(work / "coverage", f"{version}-{scenario.stem}")
                shutil.copyfile(scenario, sandbox.root / scenario.name)
                (sandbox.root / "inspect.fs").write_bytes(producers[version].fs_path.read_bytes())
                subprocess.run(["gforth", "inspect.fs", scenario.name], cwd=sandbox.root, env=sandbox.env,
                               capture_output=True, stdin=subprocess.DEVNULL, timeout=30)
                logs = sandbox.logs()
                (out / f"{scenario.stem}.jsonl").write_bytes(logs[0].read_bytes() if logs else b"")
            recorded[version] = sorted(out.glob("*.jsonl"))
            continue
        if not (out / "PROVENANCE").exists():
            env = {**os.environ, "INSPECT_FS": str(producers[version].fs_path),
                   "SCHEMA_JSON": str(producers[version].schema_path)}
            subprocess.run([sys.executable, str(REPO / "corpus" / "record.py"), str(out), "--repo", str(REPO),
                            "--scenarios", str(scenarios)], env=env, check=True, capture_output=True)
        recorded[version] = sorted(out.glob("*.jsonl"))
    return recorded


def table(recorded: dict[str, list[Path]]) -> tuple[list[str], list[list[str]], list[tuple]]:
    counts: dict[tuple[str, str], dict[str, int]] = {}
    for version, logs in recorded.items():
        for log in logs:
            for key in classify(log.read_bytes()):
                counts.setdefault(key, {}).setdefault(version, 0)
                counts[key][version] += 1
    universe = set(counts) | {("rs", "sp"), ("rs", "integer"), ("input.file", "other"),
                              ("input.line", "<= 0"), ("snapshot.id", "escaped"), ("event", "caps"),
                              ("event", "bye"), ("depth", "present"), ("snapshot.id", "truncated at 63"), ("input.text", "DEL"),
                              ("float", "subnormal"), ("float", "near DBL_MAX"), ("float", "null"),
                              ("float", "-0.0"), ("data", "int64 extreme"), ("data", "beyond 2^53")}
    versions = list(recorded)
    rows, gaps = [], []
    for path, value_class in sorted(universe):
        cells = []
        for version in versions:
            if not supports(version, path, value_class):
                cells.append(str(counts.get((path, value_class), {}).get(version, "-")))
                continue
            count = counts.get((path, value_class), {}).get(version, 0)
            cells.append(str(count) if count else "GAP")
            if not count:
                gaps.append((path, value_class, version))
        rows.append([path, value_class, *cells])
    return versions, rows, gaps


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("work")
    parser.add_argument("--out", default=str(HERE.parent))
    parser.add_argument("--scenarios", default=str(REPO / "corpus"))
    parser.add_argument("--name", default="coverage.tsv")
    options = parser.parse_args(argv)
    work = Path(options.work).resolve()
    recorded = record_all(work, Path(options.scenarios).resolve())
    versions, rows, gaps = table(recorded)
    with open(Path(options.out) / options.name, "w") as handle:
        handle.write("\t".join(["path", "class", *versions]) + "\n")
        for row in rows:
            handle.write("\t".join(row) + "\n")
    print(f"{len(rows)} (path, class) rows x {len(versions)} versions; {len(gaps)} gaps")
    for gap in gaps:
        print("GAP", *gap)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
