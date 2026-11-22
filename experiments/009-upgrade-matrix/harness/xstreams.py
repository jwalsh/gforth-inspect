"""Pathological streams X1-X11 of experiment 009, built from recorded logs.

Every stream is bytes (a whole stacks.jsonl), plus the schema the consumer
holds (its own 1.1 schema unless the stream is an X9 schema mismatch).
`usable` says whether a consumer written for contract 1.1, v 1 can use the
stream: the newest hello announces exactly 1.1, every line is a JSON object
with v 1, and every record validates against the 1.1 schema (unknown keys
are allowed where the schema allows them).  A consumer that presents data
from a stream that is not usable emits wrong data.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Stream:
    key: str          # X3-num, X11-bom, ...
    family: str       # X3
    content: bytes
    usable: bool
    note: str
    schema: dict | None = None   # None: the consumer's own 1.1 schema


def lines_of(raw: bytes) -> list[bytes]:
    return [line for line in raw.split(b"\n") if line]


def join(lines: list[bytes]) -> bytes:
    return b"".join(line + b"\n" for line in lines)


def records(raw: bytes) -> list[dict]:
    return [json.loads(line) for line in lines_of(raw)]


def dump(record: dict) -> bytes:
    return json.dumps(record, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def with_hello(raw: bytes, change) -> bytes:
    out = []
    for record in records(raw):
        if record.get("event") == "hello":
            record = change(dict(record))
        out.append(dump(record))
    return join(out)


def each_record(raw: bytes, change) -> bytes:
    return join([dump(change(dict(record))) for record in records(raw)])


def build(v5: bytes, f3: bytes, f5: bytes, x6: dict[str, bytes], v5_schema: dict) -> list[Stream]:
    """v5, f3, f5: one batch log each; x6: logs appended across upgrades in one file."""
    streams: list[Stream] = []
    add = lambda key, content, usable, note, schema=None: streams.append(
        Stream(key, key.split("-")[0], content, usable, note, schema))
    hello, *snaps = lines_of(v5)

    add("X1-none", join(snaps), False, "no hello at all")
    add("X2-no-contract", with_hello(v5, lambda r: {k: v for k, v in r.items() if k != "contract"}),
        False, "hello without contract")
    add("X2-no-inspect", with_hello(v5, lambda r: {k: v for k, v in r.items() if k != "inspect"}),
        True, "hello without inspect (optional key)")
    add("X2-no-v", with_hello(v5, lambda r: {k: v for k, v in r.items() if k != "v"}),
        False, "hello without v")
    for label, value in (("1", "1"), ("1.1.1", "1.1.1"), ("num", 1.1), ("empty", ""), ("x.y", "x.y")):
        add(f"X3-{label}", with_hello(v5, lambda r, value=value: {**r, "contract": value}),
            False, f"contract {json.dumps(value)}")
    add("X4-v2", each_record(v5, lambda r: {**r, "v": 2}), False, "every record v 2")
    add("X4-missing", each_record(v5, lambda r: {k: v for k, v in r.items() if k != "v"}),
        False, "every record without v")
    add("X4-string", each_record(v5, lambda r: {**r, "v": "1"}), False, 'every record v "1"')
    add("X4-v2-last", join([hello, *snaps[:-1], dump({**json.loads(snaps[-1]), "v": 2})]),
        False, "only the last record v 2")
    add("X4-v2-middle", join([hello, snaps[0], dump({**json.loads(snaps[1]), "v": 2}), *snaps[2:]]),
        False, "one middle record v 2, last record fine")
    # envelope t (H3 names it): not in the plan's X4 list, added as cells, never as predictions
    add("X4-t-missing", each_record(v5, lambda r: {k: v for k, v in r.items() if k != "t"}),
        False, "every record without t")
    add("X4-t-string", each_record(v5, lambda r: {**r, "t": "1970-01-01T00:00:00Z"}),
        False, "every record t a string")
    tick = dump({"v": 1, "event": "tick", "t": 0, "seq": 1})
    add("X5-event-last", join([hello, *snaps, tick]), False, "unknown event as the last line")
    add("X5-event-middle", join([hello, snaps[0], tick, *snaps[1:]]), False, "unknown event mid-stream")
    add("X5-field-hello", with_hello(v5, lambda r: {**r, "zz-new": {"a": [1]}}), True,
        "unknown key in hello")
    add("X5-field-snapshot", each_record(v5, lambda r: r if r["event"] != "snapshot" else {**r, "zz-new": 1}),
        True, "unknown key in every snapshot")
    add("X5-field-input", each_record(v5, lambda r: r if r["event"] != "snapshot"
                                      else {**r, "input": {**r["input"], "zz-new": 1}}),
        True, "unknown key in input")

    def frame_key(record: dict) -> dict:
        if record["event"] != "snapshot":
            return record
        return {**record, "rs": [{**frame, "zz-new": 1} if isinstance(frame, dict) else frame
                                 for frame in record["rs"]]}
    add("X5-field-rs-frame", each_record(v5, frame_key), False,
        "unknown key in an rs frame object (schema: additionalProperties false)")
    for label, content in x6.items():
        add(f"X6-{label}", content, label == "V2-V5", f"one append-only file: {label}")
    h11 = json.loads(hello)
    h12 = {**h11, "contract": "1.2"}
    add("X7-hello-middle", join([snaps[0], hello, *snaps[1:]]), True, "the only hello on line 2")
    add("X7-newest-1.1", join([dump(h12), snaps[0], hello, *snaps[1:]]), True,
        "1.2 hello first, newest hello 1.1")
    add("X7-newest-1.2", join([hello, snaps[0], dump(h12), *snaps[1:]]), False,
        "1.1 hello first, newest hello 1.2")
    add("X7-row-1.1-1.2", join([hello, dump(h12), *snaps]), False, "two hellos in a row: 1.1 then 1.2")
    add("X7-row-1.2-1.1", join([dump(h12), hello, *snaps]), True, "two hellos in a row: 1.2 then 1.1")
    add("X8-F5", f5, False, "contract 10.0 stream")
    # X9: stream and schema disagree
    add("X9-xcontract", f3, False, "consumer schema x-contract 1.1, stream contract 1.2")
    add("X9-xversion", each_record(v5, lambda r: {**r, "v": 2}), False,
        "consumer schema x-version 1, stream v 2 under contract 1.1")
    draft07 = {**v5_schema, "$schema": "http://json-schema.org/draft-07/schema#"}
    add("X9-draft07", v5, True, "consumer schema declares draft-07", draft07)
    add("X9-schema-1.2", v5, True, "consumer schema x-contract 1.2, stream and expectation 1.1",
        {**v5_schema, "x-contract": "1.2"})
    add("X9-schema-xv2", v5, True, "consumer schema x-version 2, stream v 1",
        {**v5_schema, "x-version": 2})
    # X11: I-1 broken (D-38)
    def i1(change) -> bytes:
        return join([change(line) for line in lines_of(v5)])
    add("X11-event-first", i1(lambda l: dump({k: v for k, v in json.loads(l).items() if k != "v"})),
        False, 'line starts {"event": (v dropped)')
    add("X11-v-second", i1(lambda l: dump({"event": json.loads(l)["event"],
                                          **{k: v for k, v in json.loads(l).items() if k != "event"}})),
        False, "v is the second key")
    add("X11-v-string", i1(lambda l: dump({**json.loads(l), "v": "1"})), False, '{"v":"1"')
    add("X11-space", i1(lambda l: b'{ "v":' + l[len(b'{"v":'):]), False, '{ "v":1 (a space)')
    add("X11-bom", b"\xef\xbb\xbf" + v5, False, "UTF-8 BOM before the first {")
    add("X11-v999", i1(lambda l: b'{"v":999,' + l[len(b'{"v":1,'):]), False, "v 999")
    add("X11-later-line", join([hello, snaps[0], b'{"event":"snapshot",' + snaps[1][len(b'{"v":1,"event":"snapshot",'):],
                                *snaps[2:]]), False, "first line fine, line 3 without v")
    return streams


def write(streams: list[Stream], out: Path, v5_schema_path: Path) -> dict[str, tuple[Path, Path]]:
    """Each stream to OUT/<key>/stacks.jsonl; its consumer schema beside it."""
    paths = {}
    for stream in streams:
        directory = out / stream.key
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "stacks.jsonl").write_bytes(stream.content)
        schema_path = directory / "consumer.schema.json"
        if stream.schema is None:
            schema_path.write_bytes(v5_schema_path.read_bytes())
        else:
            schema_path.write_text(json.dumps(stream.schema, indent=2) + "\n")
        paths[stream.key] = (directory / "stacks.jsonl", schema_path)
    return paths
