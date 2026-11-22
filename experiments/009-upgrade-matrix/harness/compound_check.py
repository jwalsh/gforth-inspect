"""The compound version check (H5, D-37): a proposal, run by experiment 009.

    python3 compound_check.py stacks.jsonl schema.json [--api openapi.json]
        [--expect 1.1] [--envelope envelope.schema.json]

The version is a tuple; every field is checked, together, and the first
disagreement stops the consumer with a message naming that field:

  0. I-1        every line begins {"v":<int>,                  (D-38)
  1. v          every record's v equals the expected MAJOR
  2. hello      the newest hello exists
  3. contract   hello.contract is MAJOR.MINOR and equals --expect
  4. v/contract record v equals hello.contract's MAJOR
  5. inspect    hello.inspect is X.Y.Z
  6. $schema    the schema's dialect is 2020-12
  7. x-version  the schema's x-version equals v
  8. x-contract the schema's x-contract equals hello.contract
  9. api        (with --api) openapi is 3.1.x, info.version and
                info.x-contract equal hello.contract
 10. envelope   (with --envelope) every record validates against it
 11. payload    every record from the newest hello on validates against
                the schema (2020-12 validator, if jsonschema is importable)

Output: {"ok": true, "tuple": {...}} (exit 0) or {"stopped": "<field>: ..."}
(exit 1).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

PREFIX = re.compile(rb'^\{"v":(0|[1-9][0-9]*),')
CONTRACT = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
SEMVER = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
DIALECT = "https://json-schema.org/draft/2020-12/schema"


class Stop(Exception):
    pass


def validator_for(schema: dict):
    try:
        import jsonschema
    except ImportError:
        return None
    return jsonschema.Draft202012Validator(schema)


def check(content: bytes, schema: dict, expect: str, api: dict | None = None,
          envelope: dict | None = None) -> dict:
    lines = [line for line in content.split(b"\n") if line]
    if not lines:
        raise Stop("I-1: empty log")
    expected_v = int(expect.split(".")[0])
    records = []
    for number, line in enumerate(lines, 1):
        match = PREFIX.match(line)
        if match is None:
            raise Stop(f"I-1: line {number} does not begin {{\"v\":<int>,")
        if int(match.group(1)) != expected_v:
            raise Stop(f"v: line {number} has v {match.group(1).decode()}, expected {expected_v}")
        try:
            record = json.loads(line)
        except ValueError:
            raise Stop(f"v: line {number} is not JSON") from None
        records.append(record)
    hello_index = max((index for index, record in enumerate(records) if record.get("event") == "hello"),
                      default=None)
    if hello_index is None:
        raise Stop("hello: no hello record")
    hello = records[hello_index]
    contract = hello.get("contract")
    if not isinstance(contract, str) or not CONTRACT.match(contract):
        raise Stop(f"contract: hello.contract {json.dumps(contract)} is not MAJOR.MINOR")
    if contract != expect:
        raise Stop(f"contract: hello.contract {contract}, this consumer expects {expect}")
    if int(contract.split(".")[0]) != hello["v"]:
        raise Stop(f"v/contract: v {hello['v']} is not the MAJOR of {contract}")
    inspect = hello.get("inspect")
    if not isinstance(inspect, str) or not SEMVER.match(inspect):
        raise Stop(f"inspect: hello.inspect {json.dumps(inspect)} is not X.Y.Z")
    if schema.get("$schema") != DIALECT:
        raise Stop(f"$schema: schema dialect {schema.get('$schema')!r}, expected 2020-12")
    if schema.get("x-version") != expected_v:
        raise Stop(f"x-version: schema x-version {schema.get('x-version')!r}, records v {expected_v}")
    if schema.get("x-contract") != contract:
        raise Stop(f"x-contract: schema x-contract {schema.get('x-contract')!r}, stream {contract}")
    if api is not None:
        if not str(api.get("openapi", "")).startswith("3.1."):
            raise Stop(f"api: openapi {api.get('openapi')!r}, expected 3.1.x")
        info = api.get("info", {})
        if info.get("version") != contract or info.get("x-contract") != contract:
            raise Stop(f"api: info.version {info.get('version')!r} / x-contract "
                       f"{info.get('x-contract')!r}, stream {contract}")
    if envelope is not None:
        envelope_validator = validator_for(envelope)
        if envelope_validator is not None:
            for number, record in enumerate(records, 1):
                error = next(iter(envelope_validator.iter_errors(record)), None)
                if error is not None:
                    raise Stop(f"envelope: line {number}: {error.message[:60]}")
    payload_validator = validator_for(schema)
    if payload_validator is not None:
        for number, record in enumerate(records[hello_index:], hello_index + 1):
            error = next(iter(payload_validator.iter_errors(record)), None)
            if error is not None:
                raise Stop(f"payload: line {number}: {error.message[:60]}")
    return {"ok": True, "tuple": {"v": expected_v, "contract": contract, "inspect": inspect,
                                  "$schema": "2020-12", "x-version": schema["x-version"],
                                  "x-contract": schema["x-contract"],
                                  "api": api["info"]["version"] if api else None}}


def run(content: bytes, schema: dict, expect: str, api: dict | None = None,
        envelope: dict | None = None) -> dict:
    try:
        return check(content, schema, expect, api, envelope)
    except Stop as stop:
        return {"stopped": str(stop)}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="compound version check")
    parser.add_argument("log")
    parser.add_argument("schema")
    parser.add_argument("--expect", default="1.1")
    parser.add_argument("--api")
    parser.add_argument("--envelope")
    options = parser.parse_args(argv)
    load = lambda path: json.loads(Path(path).read_text()) if path else None
    result = run(Path(options.log).read_bytes(), load(options.schema), options.expect,
                 load(options.api), load(options.envelope))
    print(json.dumps(result))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
