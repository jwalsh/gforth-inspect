"""X10 and gate 6: GET /stacks checked against its API spec, and the compound check on the ledger.

    uv run --no-project --with jsonschema python x10_api.py WORK_DIR [--out ..]

Part 1 (X10): for each ledger and fixture log, the frozen mock server
serves GET /stacks; the response is checked against ../openapi-stacks.json:
status listed, Content-Type listed, body valid against
components.schemas.Record, and the API version: the spec's info.version
against the newest hello.contract of the log, which the response itself
does not carry (no X-Stacks-Contract header from the frozen mock).
Part 2 (gate 6, green side): compound_check on every ledger and fixture
log, each with its own schema and expected contract, plus the API spec.
Writes OUT/x10.tsv.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import compound_check  # noqa: E402
import consumers  # noqa: E402
import ledger  # noqa: E402
import producer  # noqa: E402
import rulings  # noqa: E402


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("work")
    parser.add_argument("--out", default=str(HERE.parent))
    options = parser.parse_args(argv)
    work = Path(options.work).resolve()
    work.mkdir(parents=True, exist_ok=True)
    import jsonschema
    api = json.loads((HERE.parent / "openapi-stacks.json").read_text())
    envelope = json.loads((HERE.parent / "envelope.schema.json").read_text())
    record_validator = jsonschema.Draft202012Validator(api["components"]["schemas"]["Record"])
    producers = ledger.materialize(work)
    consumers.pin(work)
    rows = []
    for key, prod in producers.items():
        sandbox = producer.Sandbox.make(work, f"x10-{key}")
        producer.run_batch(prod.fs_path, "gforth", sandbox, producer.workload(f"009-x10-{key}", 9009).lines)
        log = sandbox.logs()[0]
        lines = [line for line in log.read_bytes().split(b"\n") if line]
        served = consumers.run_mock(work, log)
        response = api["paths"]["/stacks"]["get"]["responses"]
        status = served.extra.get("status")
        problems = []
        if str(status) not in response:
            problems.append(f"status {status} not in the spec")
        if served.extra.get("content-type") not in response.get(str(status), {}).get("content", {"": 0}):
            problems.append(f"content-type {served.extra.get('content-type')}")
        body = json.loads(served.output) if served.output else None
        error = next(iter(record_validator.iter_errors(body)), None) if body is not None else None
        if error is not None:
            problems.append(f"body invalid: {error.message[:50]}")
        hello = rulings.newest_hello(lines)
        contract = hello.get("contract") if hello else None
        api_version = api["info"]["version"]
        version_check = ("agrees" if contract == api_version else f"log {contract}, spec {api_version}")
        rows.append((key, "X10", "valid" if not problems else "; ".join(problems),
                     f"API version {version_check}; the response carries no contract (last record is "
                     f"{body.get('event') if isinstance(body, dict) else None})"))
        expect = prod.contract or "1.1"
        result = compound_check.run(log.read_bytes(), json.loads(prod.schema_path.read_text()), expect,
                                    api if expect == api_version else {**api, "info": {**api["info"], "version": expect,
                                                                                       "x-contract": expect}},
                                    envelope)
        rows.append((key, "compound (own schema, own contract)", "ok" if result.get("ok") else result["stopped"],
                     json.dumps(result.get("tuple")) if result.get("ok") else ""))
    out = Path(options.out)
    with open(out / "x10.tsv", "w") as handle:
        handle.write("producer\tcheck\tresult\tnote\n")
        for row in rows:
            handle.write("\t".join(row) + "\n")
    for row in rows:
        print(*row, sep="\t")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
