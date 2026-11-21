"""Reference consumer 2: the editor checker / dashboard reader.  Frozen as written.

    python3 checker.py stacks.jsonl schema.json [--expect 1.1] [--no-version-stop]

It does what an editor's checker does (CONSUMERS.org, consumer obligations):

1. Version stop.  Read the newest `hello`.  If its `contract` differs from
   the expected MAJOR.MINOR in MAJOR or MINOR, or is missing, stop and say
   so.  `--no-version-stop` bypasses this; a result produced that way must
   be labelled as such.
2. Read the last line, decode it as strict UTF-8 and strict JSON.
3. Validate it with a hand-written subset of JSON Schema (type, required,
   enum, const, items, oneOf, properties, additionalProperties), not the
   jsonschema package: an editor does not carry one.
4. Extract what the dashboard renders: data, float, rs, input (file, line,
   in, text only), where, src.  Unknown keys are ignored.

The result is one JSON object on stdout.  Standard library only.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

EXPECTED_CONTRACT = "1.1"
INPUT_KEYS = ("file", "line", "in", "text")
SNAPSHOT_KEYS = ("where", "src", "data", "float", "rs", "input")


# --- subset validator -------------------------------------------------

def _type_ok(value: object, type_name: str) -> bool:
    if type_name == "null":
        return value is None
    if type_name == "boolean":
        return isinstance(value, bool)
    if type_name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if type_name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if type_name == "string":
        return isinstance(value, str)
    if type_name == "array":
        return isinstance(value, list)
    if type_name == "object":
        return isinstance(value, dict)
    raise ValueError(f"unknown type {type_name}")


def validate(value: object, schema: dict, where: str = "$") -> str | None:
    """None if value conforms, else the first error found."""
    if "type" in schema:
        allowed_types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_type_ok(value, type_name) for type_name in allowed_types):
            return f"{where}: not of type {allowed_types}"
    if "const" in schema and not _json_equal(value, schema["const"]):
        return f"{where}: not {schema['const']!r}"
    if "enum" in schema and not any(_json_equal(value, option) for option in schema["enum"]):
        return f"{where}: not one of {schema['enum']}"
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                return f"{where}: missing {key!r}"
        properties = schema.get("properties", {})
        for key, subschema in properties.items():
            if key in value:
                error = validate(value[key], subschema, f"{where}.{key}")
                if error:
                    return error
        if schema.get("additionalProperties") is False:
            extra_keys = sorted(set(value) - set(properties))
            if extra_keys:
                return f"{where}: unexpected {extra_keys}"
    if isinstance(value, list) and "items" in schema:
        for index, item in enumerate(value):
            error = validate(item, schema["items"], f"{where}[{index}]")
            if error:
                return error
    if "oneOf" in schema:
        matches = [validate(value, branch, where) is None for branch in schema["oneOf"]]
        if matches.count(True) != 1:
            return f"{where}: matches {matches.count(True)} of oneOf, not 1"
    return None


def _json_equal(left: object, right: object) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return left is right
    return left == right


# --- the checker ------------------------------------------------------

def _reject_constant(name: str) -> None:
    raise ValueError(f"{name} is not JSON")  # strict JSON: no NaN / Infinity


def _version_stop(lines: list[str], expected: str) -> str | None:
    """The stop message, or None if the newest hello announces `expected`."""
    announced = None
    for line in lines:
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict) and record.get("event") == "hello":
            announced = record.get("contract")
    expected_major, expected_minor = expected.split(".")[:2]
    if isinstance(announced, str) and announced.split(".")[:2] == [expected_major, expected_minor]:
        return None
    if isinstance(announced, str) and announced.split(".")[0] == expected_major:
        kind = "minor"
    else:
        kind = "major"
    shown = announced if isinstance(announced, str) else "(none)"
    return (f"contract {shown} from the producer, this consumer expects {expected} "
            f"({kind} update): check the schema and change log")


def check(log_path: Path, schema: dict, expected: str = EXPECTED_CONTRACT,
          version_stop: bool = True) -> dict:
    try:
        text = Path(log_path).read_bytes().decode("utf-8")
    except OSError as error:
        return {"error": f"unreadable: {error.strerror}"}
    except UnicodeDecodeError:
        return {"error": "not UTF-8"}
    lines = [line for line in text.split("\n") if line]
    if not lines:
        return {"error": "empty log"}
    if version_stop:
        stop_message = _version_stop(lines, expected)
        if stop_message:
            return {"stopped": stop_message}
    try:
        record = json.loads(lines[-1], parse_constant=_reject_constant)
    except ValueError:
        return {"error": "last line is not JSON"}
    error = validate(record, schema)
    if error:
        return {"error": f"invalid: {error}"}
    result: dict = {"event": record["event"]}
    if record["event"] == "snapshot":
        for key in SNAPSHOT_KEYS:
            result[key] = record[key]
        result["input"] = {key: record["input"][key] for key in INPUT_KEYS}
    return result


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="editor checker for stacks.jsonl")
    parser.add_argument("log")
    parser.add_argument("schema")
    parser.add_argument("--expect", default=EXPECTED_CONTRACT)
    parser.add_argument("--no-version-stop", action="store_true")
    options = parser.parse_args(argv)
    result = check(Path(options.log), json.loads(Path(options.schema).read_text()),
                   options.expect, not options.no_version_stop)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if "event" in result else 1

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
