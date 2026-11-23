"""Classify how a consumer's output on B differs from its output on A (same workload).

Classes, per field:
  same         equal as decoded JSON (floats by their bits, so -0.0 != 0.0)
  fix          B equals the true value and A does not (RELEASING.org Rulings)
  null-break   A had a value, B has null (a renamed or moved key)
  added-key    B has a key A did not (mock body only)
  removed-key  A had a key B does not (mock body only)
  extra-event  B has records of an event A never wrote (jq only)
  other        anything else: a finding
"""

from __future__ import annotations

import json
import struct

from producer import Workload

TRUE_WHERE = [None, None, "w-a", "w-b", None]
IGNORED = ("t", "id")  # a clock and the xrid: they differ by construction


def bits(value):
    if isinstance(value, float):
        return ("f", struct.pack("<d", value))
    if isinstance(value, list):
        return tuple(bits(item) for item in value)
    if isinstance(value, dict):
        return tuple(sorted((key, bits(item)) for key, item in value.items()))
    return ("v", value)


def equal(left, right) -> bool:
    return bits(left) == bits(right)


def truth(workload: Workload, index: int) -> dict:
    data = [workload.data, [], [7, 7], [6], [5]][index]
    floats = [[], workload.floats, [], [], []][index]
    return {"d": data, "f": [float(value) for value in floats], "w": TRUE_WHERE[index],
            "data": data, "float": [float(value) for value in floats], "where": TRUE_WHERE[index],
            "text": workload.lines[[2, 3, 4, 5, 6][index]]}


def field_class(before, after, true_value) -> str:
    if equal(before, after):
        return "same"
    if true_value is not None and equal(after, true_value) and not equal(before, true_value):
        return "fix"
    if after is None and before is not None:
        return "null-break"
    return "other"


def jq_classes(before: list[dict], after: list[dict], workload: Workload) -> dict[str, int]:
    counts: dict[str, int] = {}
    bump = lambda name: counts.__setitem__(name, counts.get(name, 0) + 1)
    snaps_before = [line for line in before if line.get("e") == "snapshot"]
    snaps_after = [line for line in after if line.get("e") == "snapshot"]
    known_events = {line.get("e") for line in before}
    for line in after:
        if line.get("e") not in known_events and line.get("e") != "snapshot":
            bump("extra-event")
    if len(snaps_before) != len(snaps_after):
        bump("other")
    for index, (old, new) in enumerate(zip(snaps_before, snaps_after)):
        true_record = truth(workload, index) if index < 5 else {}
        for key in ("d", "f", "w"):
            bump(field_class(old.get(key), new.get(key), true_record.get(key)))
    return counts


def record_classes(before: dict, after: dict, workload: Workload, index: int = 4,
                   keyed: bool = False) -> dict[str, int]:
    """Checker output (keyed=False: fixed keys) or a decoded mock body (keyed=True)."""
    counts: dict[str, int] = {}
    bump = lambda name: counts.__setitem__(name, counts.get(name, 0) + 1)
    true_record = truth(workload, index)
    keys = set(before) | set(after)
    for key in sorted(keys - set(IGNORED)):
        if key not in after:
            bump("removed-key" if keyed else "other")
            continue
        if key not in before:
            bump("added-key" if keyed else "other")
            continue
        old, new = before[key], after[key]
        if key == "input" and isinstance(old, dict) and isinstance(new, dict):
            for sub in sorted(set(old) | set(new)):
                true_value = true_record["text"] if sub == "text" else None
                bump(field_class(old.get(sub), new.get(sub), true_value))
            continue
        if key == "src" and old is None and isinstance(new, str) and true_record["where"] is not None:
            bump("fix")
            continue
        bump(field_class(old, new, true_record.get(key)))
    return counts


def summarize(counts: dict[str, int]) -> str:
    return ",".join(f"{name}:{count}" for name, count in sorted(counts.items())) or "same:0"


def within(counts: dict[str, int], allowed: set[str] | None) -> bool:
    return allowed is None or set(counts) <= allowed


def decode_body(body: str | None) -> dict | None:
    try:
        value = json.loads(body) if body else None
    except ValueError:
        return None
    return value if isinstance(value, dict) else None
