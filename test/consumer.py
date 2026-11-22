#!/usr/bin/env python3
"""consumer.py MAJOR.MINOR FILE.jsonl -- the consumer rule of contract 1.1.

A consumer built for contract MAJOR.MINOR reads a stream only if the newest
hello record announces exactly that MAJOR.MINOR.  It refuses (exit 1, the
reason on stderr) a stream with no hello, whose newest hello has no
"contract", or announces another MAJOR or another MINOR.  A stream may hold
several hellos (one per log-on); only the newest counts.
    --expect-refused   invert: the stream must be refused
"""
import json
import re
import sys


def verdict(want, path):
    newest = None
    for raw in open(path, "rb").read().splitlines():
        record = json.loads(raw.decode("utf-8"))
        if record.get("event") == "hello":
            newest = record
    if newest is None:
        return "no hello record"
    have = newest.get("contract")
    if have is None:
        return "newest hello announces no contract"
    if not isinstance(have, str) or not re.fullmatch(r"[0-9]+\.[0-9]+", have):
        return "newest hello announces a malformed contract %r" % (have,)
    if have.split(".")[0] != want.split(".")[0]:
        return "contract MAJOR %s, consumer wants %s" % (have, want)
    if have != want:
        return "contract MINOR %s, consumer wants %s" % (have, want)
    return None


def main(argv):
    refused = "--expect-refused" in argv
    args = [a for a in argv if a != "--expect-refused"]
    if len(args) != 2:
        raise SystemExit(__doc__)
    reason = verdict(args[0], args[1])
    if refused:
        if reason is None:
            print("%s: accepted, but must be refused" % args[1], file=sys.stderr)
            return 1
        print("%s: refused as it must be: %s" % (args[1], reason), file=sys.stderr)
        return 0
    if reason is not None:
        print("%s: refused: %s" % (args[1], reason), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
