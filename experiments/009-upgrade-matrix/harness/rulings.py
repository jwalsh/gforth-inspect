"""What RELEASING.org::*Rulings and CONSUMERS.org predict, per transition and per read.

Two predictions per cell:

verdict   what a consumer does with a log, from the consumer obligations:
          the checker accepts iff the newest hello announces exactly the
          expected MAJOR.MINOR and the stream is valid at that version
          (obligation 3: every record from the newest hello on, not only the last); otherwise it
          stops (minor / major) or rejects.  jq and the course follower
          follow (they cannot stop).  The mock server serves the last line.

values    how consumer output on B may differ from output on A, from the
          bump table: PATCH {same, fix}; MINOR {same, fix, added-key,
          extra-event}; MAJOR anything (a break with a new v); pre-release
          (below v0.5.0): a break costs a note, so anything, noted.
"""

from __future__ import annotations

import json
import re

CONTRACT_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")

BUMP = {
    ("V0", "V1"): "pre-release",   # default dir moved, hello.inspect, #1 floats, escaping
    ("V1", "V2"): "MINOR",         # hello.contract, snapshot id, #2 where/src (fix)
    ("V2", "V3"): "PATCH",         # #17 seek
    ("V3", "V4"): "PATCH",         # #17 buffered
    ("V4", "V5"): "PATCH",         # review of #19
    ("V5", "F1"): "PATCH",         # the release bump: hello.inspect only
    ("F1", "F2"): "PATCH",         # DEL escaped: bytes change, values do not
    ("F2", "F3"): "MINOR",         # optional snapshot depth, contract 1.2
    ("F3", "F4"): "MAJOR",         # data renamed cells, v 2, contract 2.0
    ("F4", "F5"): "MAJOR",         # contract 10.0
    ("V2", "V5"): "PATCH",
    ("Vc", "V5"): "pre-release",   # hello.inspect; default dir moved; escaping
    ("V5", "F4"): "MAJOR",
    ("V5", "F5"): "MAJOR",
}

ALLOWED = {
    "PATCH": {"same", "fix"},
    "MINOR": {"same", "fix", "added-key", "extra-event"},
    "MAJOR": None,          # any
    "pre-release": None,    # any, with a note
}


def newest_hello(lines: list[bytes]) -> dict | None:
    hello = None
    for line in lines:
        try:
            record = json.loads(line.decode("utf-8", "strict"))
        except ValueError:
            continue
        if isinstance(record, dict) and record.get("event") == "hello":
            hello = record
    return hello


def newest_hello_index(lines: list[bytes]) -> int:
    """The newest hello governs the records after it (CONSUMERS.org obligation 2)."""
    index = 0
    for number, line in enumerate(lines):
        try:
            record = json.loads(line.decode("utf-8", "strict"))
        except ValueError:
            continue
        if isinstance(record, dict) and record.get("event") == "hello":
            index = number
    return index


def full_validate(lines: list[bytes], schema: dict) -> str | None:
    """Every record against the consumer's schema with a 2020-12 validator; None if valid."""
    try:
        import jsonschema
    except ImportError:
        return None
    validator = jsonschema.Draft202012Validator(schema)
    for number, line in enumerate(lines, 1):
        try:
            record = json.loads(line.decode("utf-8", "strict"))
        except ValueError:
            return f"line {number}: not JSON"
        error = next(iter(validator.iter_errors(record)), None)
        if error is not None:
            return f"line {number}: {error.message[:60]}"
    return None


def checker_verdict(content: bytes, schema: dict, expect: str) -> str:
    lines = [line for line in content.split(b"\n") if line]
    if not lines:
        return "reject:empty log"
    hello = newest_hello(lines)
    contract = hello.get("contract") if hello else None
    if not isinstance(contract, str) or not CONTRACT_RE.match(contract):
        expected_major = expect.split(".")[0]
        if isinstance(contract, str) and contract.split(".")[0] == expected_major:
            return "stop:malformed"
        return "stop:major" if contract is None or not isinstance(contract, str) else "stop:malformed"
    if contract != expect:
        return "stop:minor" if contract.split(".")[0] == expect.split(".")[0] else "stop:major"
    error = full_validate(lines[newest_hello_index(lines):], schema)
    return f"reject:{error}" if error else "accept"


def matches_checker(predicted: str, observed: str) -> bool:
    if predicted == observed:
        return True
    if predicted == "stop:malformed":
        return observed.startswith("stop:") or observed.startswith("reject:")
    if predicted.startswith("reject:"):
        return observed.startswith("reject:")
    return False


def allowed(transition: tuple[str, str]) -> set[str] | None:
    return ALLOWED[BUMP[transition]]
