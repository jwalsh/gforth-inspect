"""The version ledger of experiment 009: producers and their schemas, pinned by blob.

    python3 ledger.py WORK_DIR      materialize every producer into WORK_DIR/producers/

V0-V5 come from `git show <commit>:env/inspect.fs` (and the schema at the
same commit).  Vc is read from the path in the local, uncommitted file
${XDG_CONFIG_HOME:-~/.config}/gforth-inspect-009/vc.root; if that file is
missing, Vc is skipped.  F1-F5 are fixtures: text substitutions on V5, each
refused if it changed nothing (the 004 plant rule).  Nothing here writes
to env/ or contract/ (E-6).  Standard library only.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]

# key, commit; V5 is the release candidate on harden, pinned by its blob
LEDGER = [
    ("V0", "18ebe2d"),
    ("V1", "6238b09"),
    ("V2", "0842eda"),
    ("V3", "7f58633"),
    ("V4", "7dff143"),
    ("V5", "5aac06a"),
]
V5_BLOB = "af95cdf354af"
SEQUENCE = ["V0", "V1", "V2", "V3", "V4", "V5", "F1", "F2", "F3", "F4", "F5"]
SKIPS = [("V2", "V5"), ("Vc", "V5"), ("V5", "F4"), ("V5", "F5")]


def transitions() -> list[tuple[str, str]]:
    return list(zip(SEQUENCE, SEQUENCE[1:])) + SKIPS


@dataclass
class Producer:
    key: str
    source: str          # commit, "fixture from V5", or "local" (Vc)
    blob: str            # git blob id of inspect.fs, full
    inspect: str | None  # hello.inspect it announces
    contract: str | None # hello.contract it announces
    v: int               # record v
    fs_path: Path
    schema_path: Path
    has_log_id: bool
    default_dir: str     # the XDG fallback: "gforth-inspect", or "legacy" (the import's own name)


def git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(REPO), *args], check=True,
                          capture_output=True, text=True).stdout


def blob_of(path: Path) -> str:
    return git("hash-object", str(path)).strip()


def vc_root() -> Path | None:
    config = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    root_file = config / "gforth-inspect-009" / "vc.root"
    if not root_file.exists():
        return None
    return Path(root_file.read_text().strip())


def substitute(text: str, pairs: list[tuple[str, str]], label: str) -> str:
    for old, new in pairs:
        if old not in text:
            raise RuntimeError(f"{label}: plant did not apply: {old!r}")
        text = text.replace(old, new)
    return text


# --- the fixtures, all from V5 ------------------------------------------

def version_pairs(inspect: str, contract: str | None = None) -> list[tuple[str, str]]:
    pairs = [("\\ gforth-inspect v0.1.0", f"\\ gforth-inspect v{inspect}"),
             (': inspect-version ( -- c-addr u ) s" 0.1.0" ;',
              f': inspect-version ( -- c-addr u ) s" {inspect}" ;')]
    if contract:
        pairs.append((': contract-version ( -- c-addr u ) s" 1.1" ;',
                      f': contract-version ( -- c-addr u ) s" {contract}" ;'))
    return pairs


V_HEAD = 's" v" jkey 1 0 .r'
DEL_OLD = "ELSE r@ $80 < IF r@ emit 1"
DEL_NEW = "ELSE r@ 127 = IF [char] u jesc r@ .hex4 1\n        ELSE r@ $80 < IF r@ emit 1"
THENS_9 = "THEN THEN THEN THEN THEN THEN THEN THEN THEN"
SNAP_DATA = 'jc s" data" jkey json-data\n    jc s" float" jkey json-float'
HELLO_TAIL = 'jc s" contract" jkey contract-version json-str  [char] } emit cr ;'

F5_WORDS = '''
: (caps) ( -- )  \\ far future: a capabilities record after every hello
    s" caps" json-head  jc s" words" jkey
    [char] [ emit  s" log-id" json-str jc s" rs-full" json-str jc s" log-event" json-str [char] ] emit
    jc s" engine" jkey s" unknown" json-str  [char] } emit cr ;
: (bye) ( -- )  \\ far future: a closing record on log-off
    s" bye" json-head  jc s" reason" jkey s" log-off" json-str  [char] } emit cr ;
'''


def fixture_texts(v5: str) -> dict[str, tuple[str, str, str | None, int]]:
    """key -> (inspect.fs text, inspect, contract, v)."""
    fixtures: dict[str, tuple[str, str, str | None, int]] = {}
    # F1: the release bump only (D-32 plans 1.0.0; F1a is the 0.5.0 spelling, D-19)
    fixtures["F1a"] = (substitute(v5, version_pairs("0.5.0"), "F1a"), "0.5.0", "1.1", 1)
    fixtures["F1"] = (substitute(v5, version_pairs("1.0.0"), "F1"), "1.0.0", "1.1", 1)
    # F2: a PATCH: DEL (0x7f) escaped as \u007f; the decoded string is unchanged
    f2 = substitute(v5, version_pairs("1.0.1") + [(DEL_OLD, DEL_NEW),
                                                    (THENS_9, THENS_9 + " THEN")], "F2")
    fixtures["F2"] = (f2, "1.0.1", "1.1", 1)
    # F3: a MINOR: optional snapshot key "depth" (data stack depth), contract 1.2
    f3 = substitute(f2, version_pairs("1.0.1", "1.2")[2:] + [
        ('\\ gforth-inspect v1.0.1', '\\ gforth-inspect v1.1.0'),
        (': inspect-version ( -- c-addr u ) s" 1.0.1" ;', ': inspect-version ( -- c-addr u ) s" 1.1.0" ;'),
        (SNAP_DATA, 'jc s" depth" jkey depth 0 .r\n    ' + SNAP_DATA)], "F3")
    fixtures["F3"] = (f3, "1.1.0", "1.2", 1)
    # F4: a MAJOR: data renamed to cells, v 2, contract 2.0
    f4 = substitute(f3, [
        ('\\ gforth-inspect v1.1.0', '\\ gforth-inspect v2.0.0'),
        (': inspect-version ( -- c-addr u ) s" 1.1.0" ;', ': inspect-version ( -- c-addr u ) s" 2.0.0" ;'),
        (': contract-version ( -- c-addr u ) s" 1.2" ;', ': contract-version ( -- c-addr u ) s" 2.0" ;'),
        (V_HEAD, 's" v" jkey 2 0 .r'),
        ('jc s" data" jkey json-data', 'jc s" cells" jkey json-data')], "F4")
    fixtures["F4"] = (f4, "2.0.0", "2.0", 2)
    # F5: far future, contract 10.0: stacks nested, new keys, new events caps and bye
    f5 = substitute(f3, [
        ('\\ gforth-inspect v1.1.0', '\\ gforth-inspect v10.0.0'),
        (': inspect-version ( -- c-addr u ) s" 1.1.0" ;', ': inspect-version ( -- c-addr u ) s" 10.0.0" ;'),
        (': contract-version ( -- c-addr u ) s" 1.2" ;', ': contract-version ( -- c-addr u ) s" 10.0" ;'),
        (V_HEAD, 's" v" jkey 10 0 .r'),
        ('jc s" depth" jkey depth 0 .r\n    ' + SNAP_DATA,
         'jc s" stacks" jkey [char] { emit s" data" jkey json-data\n'
         '    jc s" float" jkey json-float  jc s" depth" jkey depth 0 .r [char] } emit\n'
         '    jc s" task" jkey s" main" json-str'),
        (HELLO_TAIL, 'jc s" contract" jkey contract-version json-str\n'
         '    jc s" features" jkey [char] [ emit s" caps" json-str jc s" bye" json-str [char] ] emit\n'
         '    [char] } emit cr ;' + F5_WORDS),
        ("logging on  ['] (hello) log-write ;", "logging on  ['] (hello) log-write  ['] (caps) log-write ;"),
        ("logging @ 0= IF EXIT THEN  logging off", "logging @ 0= IF EXIT THEN  ['] (bye) log-write  logging off"),
    ], "F5")
    fixtures["F5"] = (f5, "10.0.0", "10.0", 10)
    return fixtures


def fixture_schema(v5_schema: dict, key: str) -> dict:
    schema = json.loads(json.dumps(v5_schema))
    hello, snapshot = schema["oneOf"]
    if key in ("F1", "F1a", "F2"):
        return schema
    schema["x-contract"] = {"F3": "1.2", "F4": "2.0", "F5": "10.0"}[key]
    snapshot["properties"]["depth"] = {"type": "integer", "description": "data stack depth (since 1.2)"}
    if key == "F3":
        return schema
    if key == "F4":
        schema["x-version"] = 2
        schema["properties"]["v"] = {"const": 2}
        props = snapshot["properties"]
        props["cells"] = props.pop("data")
        snapshot["required"] = ["cells" if name == "data" else name for name in snapshot["required"]]
        return schema
    # F5
    schema["x-version"] = 10
    schema["properties"]["v"] = {"const": 10}
    schema["properties"]["event"] = {"enum": ["hello", "caps", "snapshot", "bye"]}
    props = snapshot["properties"]
    data, floats, depth = props.pop("data"), props.pop("float"), props.pop("depth")
    props["stacks"] = {"type": "object", "required": ["data", "float", "depth"],
                       "properties": {"data": data, "float": floats, "depth": depth}}
    props["task"] = {"type": "string"}
    snapshot["required"] = [n for n in snapshot["required"] if n not in ("data", "float")] + ["stacks"]
    hello["properties"]["features"] = {"type": "array", "items": {"type": "string"}}
    schema["oneOf"] = [hello,
                       {"properties": {"event": {"const": "caps"}, "words": {"type": "array"}},
                        "required": ["words"]},
                       snapshot,
                       {"properties": {"event": {"const": "bye"}, "reason": {"type": "string"}},
                        "required": ["reason"]}]
    return schema


# --- materialize -----------------------------------------------------------

def materialize(work: Path) -> dict[str, Producer]:
    out = work / "producers"
    out.mkdir(parents=True, exist_ok=True)
    producers: dict[str, Producer] = {}

    def add(key: str, source: str, text: str, schema_text: str,
            inspect: str | None, contract: str | None, v: int) -> None:
        fs_path = out / f"{key}.fs"
        fs_path.write_text(text)
        schema_path = out / f"{key}.schema.json"
        schema_path.write_text(schema_text)
        producers[key] = Producer(key, source, blob_of(fs_path), inspect, contract, v, fs_path,
                                  schema_path, ": log-id " in text,
                                  "gforth-inspect" if 's" /gforth-inspect"' in text else "legacy")

    for key, commit in LEDGER:
        text = git("show", f"{commit}:env/inspect.fs")
        schema_text = git("show", f"{commit}:contract/stacks-log.schema.json")
        inspect = "0.1.0" if 's" 0.1.0"' in text else None
        contract = "1.1" if ': contract-version ( -- c-addr u ) s" 1.1"' in text else None
        add(key, commit, text, schema_text, inspect, contract, 1)
    if not producers["V5"].blob.startswith(V5_BLOB):
        raise RuntimeError(f"V5 blob {producers['V5'].blob[:12]} is not {V5_BLOB}")
    root = vc_root()
    if root is not None:
        vc_text = (root / "forth" / "env" / "inspect.fs").read_text()
        vc_schema = (root / "forth" / "env" / "stacks-log.schema.json").read_text()
        contract = "1.1" if 's" contract" jkey s" 1.1"' in vc_text else None
        add("Vc", "local", vc_text, vc_schema, None, contract, 1)
    v5_text = producers["V5"].fs_path.read_text()
    v5_schema = json.loads(producers["V5"].schema_path.read_text())
    for key, (text, inspect, contract, v) in fixture_texts(v5_text).items():
        add(key, "fixture from V5", text,
            json.dumps(fixture_schema(v5_schema, key), indent=2) + "\n", inspect, contract, v)
    return producers


def public_blob(producer: Producer) -> str:
    """The blob as it may appear in a committed file: never Vc's."""
    return "local-only" if producer.key == "Vc" else producer.blob[:12]


if __name__ == "__main__":
    work = Path(sys.argv[1])
    for key, producer in materialize(work).items():
        print(f"{key:4} {public_blob(producer)} inspect={producer.inspect} "
              f"contract={producer.contract} v={producer.v} log-id={producer.has_log_id} "
              f"dir={producer.default_dir}")
