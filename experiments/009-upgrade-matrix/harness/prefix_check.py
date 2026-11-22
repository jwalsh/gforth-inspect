"""I-1 (D-38): the prefix check, step 0 of an upgrade, before SHA256SUMS.

    python3 prefix_check.py stacks.jsonl [--known 1] [--every-line]

Every line of every log begins with the bytes {"v": then a decimal integer
(the envelope version) then ",".  The check reads bytes, before any JSON
parse: the first line by default, every line with --every-line.  It stops,
naming the line and what it found, on a line that does not match, and on a
v it does not know.  Exit 0 only when every checked line passes.
Standard library only.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

PREFIX = re.compile(rb'^\{"v":(0|[1-9][0-9]*),')


def check(content: bytes, known: set[int], every_line: bool = False) -> dict:
    lines = [line for line in content.split(b"\n") if line]
    if not lines:
        return {"stopped": "empty log: no first line to check"}
    for number, line in enumerate(lines if every_line else lines[:1], 1):
        match = PREFIX.match(line)
        if match is None:
            shown = line[:12].decode("utf-8", "backslashreplace")
            return {"stopped": f"line {number}: no I-1 prefix {{\"v\":<int>, (starts {shown!r})"}
        version = int(match.group(1))
        if version not in known:
            return {"stopped": f"line {number}: envelope v {version}, this consumer knows {sorted(known)}"}
    return {"ok": True, "v": int(PREFIX.match(lines[0]).group(1)), "lines": len(lines) if every_line else 1}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="I-1 prefix check")
    parser.add_argument("log")
    parser.add_argument("--known", default="1", help="comma-separated envelope versions")
    parser.add_argument("--every-line", action="store_true")
    options = parser.parse_args(argv)
    known = {int(part) for part in options.known.split(",")}
    result = check(Path(options.log).read_bytes(), known, options.every_line)
    print(json.dumps(result))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
