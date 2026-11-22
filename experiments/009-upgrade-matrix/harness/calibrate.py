"""Gate 1 of experiment 009: every consumer-behaviour check goes red on a planted fault.

    uv run --no-project --with jsonschema python calibrate.py WORK_DIR

Plants (each on a copy in WORK_DIR, never on pbt/ or env/):
  a. checker.py with its version stop disabled: the V0 and F3 cells must
     show match NO (predicted stop, observed accept).
  b. a fixture labelled PATCH that changes jq output (F2 with "where"
     renamed "at"): the F1 -> F2 values row must show match NO.
  c. a checker that crashes on X5 (an unknown event raises): the cell must
     be observed as crash, never as stop, and show match NO.
  d. the I-1 prefix check: red on every X11 stream, green on every ledger
     and fixture log (gate 8 calibrated on both sides).
Exit 0 only if every plant was caught.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import consumers  # noqa: E402
import ledger  # noqa: E402
import matrix  # noqa: E402
import prefix_check  # noqa: E402
import producer  # noqa: E402
import xstreams  # noqa: E402


def plant_file(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    if old not in text:
        raise SystemExit(f"plant did not apply: {old!r}")
    path.write_text(text.replace(old, new))


def main(argv: list[str]) -> int:
    work = Path(argv[0]).resolve()
    work.mkdir(parents=True, exist_ok=True)
    out = matrix.Out(work / "out", work)
    producers = ledger.materialize(work)
    consumers.pin(work)
    v5 = producers["V5"]
    logs = {}
    for key in ("V0", "V5", "F1", "F3"):
        sandbox = producer.Sandbox.make(work, f"cal-{key}")
        producer.run_batch(producers[key].fs_path, "gforth", sandbox, producer.workload("009-cal", 9009).lines)
        logs[key] = sandbox.logs()[0]
    caught = {}
    checker = work / "consumers" / "checker.py"
    original = checker.read_text()

    # a. version stop disabled
    plant_file(checker, "    if version_stop:\n", "    if False:  # PLANT a\n")
    out.rows.clear()
    out.cache.clear()
    for key in ("V0", "F3"):
        matrix.observe(out, logs[key], v5.schema_path, "1.1", ["checker"], run="cal-a", transition=key)
    caught["a"] = all(row["match"] == "NO" for row in out.rows)
    print("a", [(row["transition"], row["predicted"], row["observed"], row["match"]) for row in out.rows])
    checker.write_text(original)

    # b. a PATCH fixture that changes jq output
    f2_plant = work / "F2-plant.fs"
    f2_plant.write_text(producers["F2"].fs_path.read_text().replace('s" where" jkey', 's" at" jkey'))
    if f2_plant.read_text() == producers["F2"].fs_path.read_text():
        raise SystemExit("plant b did not apply")
    sandbox = producer.Sandbox.make(work, "cal-F2-plant")
    producer.run_batch(f2_plant, "gforth", sandbox, producer.workload("009-cal", 9009).lines)
    out.rows.clear()
    out.cache.clear()
    state = matrix.state_for(v5, v5)
    matrix.values(out, ("F1", "F2"), logs["F1"], sandbox.logs()[0], state, state,
                  producer.workload("x", 9009), run="cal-b")
    jq_rows = [row for row in out.rows if row["consumer"] == "values:jq"]
    caught["b"] = bool(jq_rows) and all(row["match"] == "NO" for row in jq_rows)
    print("b", [(row["consumer"], row["observed"], row["match"]) for row in out.rows])

    # c. a checker that crashes on an unknown event
    plant_file(checker, '    if "enum" in schema and not any(',
               '    if "enum" in schema and value not in schema["enum"] and where == "$.event":\n'
               '        raise RuntimeError("PLANT c: unknown event")\n'
               '    if "enum" in schema and not any(')
    streams = xstreams.build(logs["V5"].read_bytes(), logs["F3"].read_bytes(), logs["V5"].read_bytes(),
                             {}, json.loads(v5.schema_path.read_text()))
    x5 = next(stream for stream in streams if stream.key == "X5-event-last")
    paths = xstreams.write([x5], work / "cal-x", v5.schema_path)
    out.rows.clear()
    out.cache.clear()
    matrix.observe(out, paths[x5.key][0], paths[x5.key][1], "1.1", ["checker"], run="cal-c")
    row = out.rows[0]
    h3 = matrix.h3_class(x5, "checker", row["observed"])
    caught["c"] = row["observed"].startswith("crash") and h3 == "crash" and row["match"] == "NO"
    print("c", row["observed"], h3, row["match"])
    checker.write_text(original)

    # d. I-1: red on every X11, green on every ledger and fixture log
    x11 = [stream for stream in streams if stream.family == "X11"]
    red = [prefix_check.check(stream.content, {1}, every_line=True).get("ok") is None for stream in x11]
    green = []
    for key, prod in producers.items():
        sandbox = producer.Sandbox.make(work, f"cal-d-{key}")
        producer.run_batch(prod.fs_path, "gforth", sandbox, producer.workload("009-cal", 9009).lines)
        known = {prod.v}
        green.append(prefix_check.check(sandbox.logs()[0].read_bytes(), known, every_line=True).get("ok") is True)
    caught["d"] = all(red) and all(green) and len(x11) >= 6
    print("d", f"X11 red {sum(red)}/{len(red)}, ledger+fixtures green {sum(green)}/{len(green)}")

    for plant, ok in caught.items():
        print(f"calibrate {plant}: {'red as expected' if ok else 'NOT CAUGHT'}")
    return 0 if all(caught.values()) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
