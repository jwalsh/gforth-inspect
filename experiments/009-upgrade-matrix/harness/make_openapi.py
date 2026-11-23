"""Write ../openapi-stacks.json: an OpenAPI 3.1 draft for GET /stacks (proposal, E-6).

    python3 make_openapi.py [REF]     REF holds contract/stacks-log.schema.json (default harden's head, pinned)

info.version is the contract MAJOR.MINOR the API serves, so it is one field
of the compound version tuple (H5, D-37).  The record schema is embedded
as components.schemas.Record, from the schema at REF, unchanged.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import ledger  # noqa: E402


def build(schema: dict) -> dict:
    contract = schema["x-contract"]
    return {
        "openapi": "3.1.0",
        "jsonSchemaDialect": "https://json-schema.org/draft/2020-12/schema",
        "info": {
            "title": "gforth-inspect stacks log: GET /stacks",
            "version": contract,
            "summary": "the last record of stacks.jsonl, byte for byte (reference consumer 3)",
            "license": {"name": "GPL-3.0-or-later", "identifier": "GPL-3.0-or-later"},
            "x-contract": contract,
            "x-version": schema["x-version"],
            "x-envelope": "1.0.0",
        },
        "paths": {
            "/stacks": {
                "get": {
                    "operationId": "getStacks",
                    "summary": "the newest line of the log, unchanged",
                    "description": "The body is one record: often a snapshot, so it does not carry hello.contract. The API version is this document's info.version; the proposed X-Stacks-Contract header carries the newest hello.contract of the log being served.",
                    "responses": {
                        "200": {
                            "description": "the last line of the log",
                            "headers": {
                                "X-Stacks-Contract": {
                                    "description": "PROPOSAL: the newest hello.contract in the log; absent from the frozen mock server",
                                    "required": False,
                                    "schema": {"type": "string", "pattern": "^(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)$"},
                                }
                            },
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Record"}}},
                        },
                        "404": {"description": "no log file, or a log with no line"},
                    },
                }
            }
        },
        "components": {"schemas": {"Record": schema}},
    }


def main(argv: list[str]) -> int:
    ref = argv[0] if argv else ledger.HARDEN
    schema = json.loads(ledger.at_ref(ref, "contract/stacks-log.schema.json"))
    (HERE.parent / "openapi-stacks.json").write_text(json.dumps(build(schema), indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
