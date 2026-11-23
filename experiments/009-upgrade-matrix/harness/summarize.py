"""Summarize ../matrix.tsv and ../manifest.tsv: counts, mismatches, P9 (N changes no verdict).

    python3 summarize.py [DIR]
"""

from __future__ import annotations

import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path


def load(path: Path) -> list[dict]:
    with open(path) as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def main(argv: list[str]) -> int:
    base = Path(argv[0]) if argv else Path(__file__).resolve().parent.parent
    rows = load(base / "matrix.tsv")
    manifest = load(base / "manifest.tsv")
    kinds = Counter()
    for row in rows:
        kind = "x" if row["run"] == "x" else ("n0" if row["run"] == "n0" else "live")
        kinds[(kind, "values" if row["step"] == "values" else "verdict", row["match"])] += 1
    print("cells:", sum(kinds.values()))
    for key, count in sorted(kinds.items()):
        print("  ", *key, count)
    print("producer runs:", len(manifest), "engines:", dict(Counter(entry["engine"] for entry in manifest)))
    live = [entry for entry in manifest if entry["run"].startswith("r")]
    print("live producer runs:", len(live), "sessions:", len({(e["run"], e["slot"]) for e in live}),
          "runs:", len({e["run"] for e in live}))
    print("mismatches by (kind, transition, consumer, observed):")
    groups = Counter()
    for row in rows:
        if row["match"] == "NO":
            kind = "x" if row["run"] == "x" else ("n0" if row["run"] == "n0" else "live")
            transition = row["transition"] if kind != "x" else row["transition"]
            groups[(kind, transition, row["consumer"], row["predicted"][:40], row["observed"][:50])] += 1
    for key, count in sorted(groups.items()):
        print("  ", count, *key, sep=" | ")
    # P9: for live verdict cells, does the verdict at (order, transition, step, consumer, engine) depend on N?
    by_key = defaultdict(set)
    for row in rows:
        if row["run"].startswith("r") and row["step"] != "values" and not row["step"].startswith("rolled"):
            if row["consumer"] in ("jq-live", "follower-live"):
                continue
            # the slot's current producer, from its xrid (<run>s<slot>-<nn>-<key><engine>)
            current = row["xrid"].rsplit("-", 1)[-1][:-1] if row["xrid"] else "-"
            by_key[(row["order"], row["transition"], row["step"], row["consumer"], current, row["expect"])].add(
                (row["N"], row["observed"]))
    varying = {key: values for key, values in by_key.items() if len({observed for _, observed in values}) > 1}
    print("P9 keys:", len(by_key), "keys whose verdict differs across N:", len(varying))
    for key, values in list(varying.items())[:20]:
        print("  ", key, sorted(values))
    follower = Counter(row["observed"] for row in rows if row["consumer"] in ("follower", "follower-live"))
    print("course follower verdicts:", dict(follower))
    jq_live = Counter(row["observed"].split()[0] for row in rows if row["consumer"] == "jq-live")
    print("jq live follower:", dict(jq_live))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
