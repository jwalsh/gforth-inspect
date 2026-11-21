"""Experiment 002: input.text survives JSON.  experiments/002-escaping/README.org

For each input class and engine, a Hypothesis example is a batch of source
lines run in one gforth process (log-on once, one .stacks per line).  Each
snapshot line must decode as strict UTF-8, parse with json.loads, validate
against the schema, have input.text equal to the text oracle's reading of
the line, and input.in == >IN just past .stacks.

Two text oracles (see _002_helpers): "legacy" is the pre-registered one
(bytes < 0x20 become a space, the rest raw), which is what json-str did at
harden@18ebe2d; "contract" is contract/stacks-log.org from inspect 0.1.0
(controls escaped, each invalid UTF-8 byte -> U+FFFD).  The hello record
says which producer is attached, and the oracle follows it.

Budget: the profile's max_examples on gforth, a fifth of it on gforth-fast
and gforth-itc (PROFILE=ci: 1000 / 200 / 200, the gate's numbers).

test_census_* never fails: it runs mixed batches and prints the pass rate
per class at the end of the module, because the strict tests stop at the
first failure and cannot give a rate.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict

import pytest
from hypothesis import given, note, settings
from jsonschema import Draft202012Validator

import gforth_run
from _002_helpers import (
    CLASSES, Case, CaseFailure, batches, check_run, mixed_batches, oracle_for,
    program_for, reproducer, run_bytes,
)

VALIDATOR = Draft202012Validator(gforth_run.schema())
PROFILE_EXAMPLES = settings().max_examples


def budget(engine: str) -> int:
    return PROFILE_EXAMPLES if engine == "gforth" else max(PROFILE_EXAMPLES // 5, 10)


def run_cases(batch: list[Case], engine: str):
    return check_run(batch, run_bytes(program_for(batch), engine), VALIDATOR)


# --- strict properties, one test per (class, engine) ----------------------

def _strict_test(line_class: str, engine: str):
    def strict(batch: list[Case]) -> None:
        for case, message in run_cases(batch, engine):
            if message:
                note(f"reproducer: {reproducer(case)}")
                raise CaseFailure(f"{message}\n  class={case.line_class} position={case.position}"
                                  f"\n  line={case.line()!r}")

    name = f"test_escaping_{line_class}_{engine.replace('-', '_')}"
    strict.__name__ = strict.__qualname__ = name  # distinct Hypothesis database key
    return name, settings(max_examples=budget(engine))(given(batch=batches(line_class))(strict))


for _class in CLASSES:
    for _engine in gforth_run.ENGINES:
        _name, _test = _strict_test(_class, _engine)
        globals()[_name] = _test


# --- fixed cases: line ends and a 1 MiB line --------------------------------


@pytest.mark.parametrize("engine", gforth_run.ENGINES)
def test_cr_lf_crlf_each_end_a_line(engine):
    # gforth 0.7.3 ends a line at LF, CR or CRLF; LF CR is two line ends
    program = b"log-on\n.stacks \\ a\r.stacks \\ b\r\n.stacks \\ c\n\r.stacks \\ d\nlog-off"
    result = run_bytes(program, engine)
    assert result.returncode == 0, result.stderr[-300:]
    snapshots = [line for line in result.log_lines if b'"snapshot"' in line]
    inputs = [json.loads(line.decode("utf-8"))["input"] for line in snapshots]
    assert [(i["line"], i["text"], i["in"]) for i in inputs] == [
        (2, ".stacks \\ a", 8), (3, ".stacks \\ b", 8), (4, ".stacks \\ c", 8), (6, ".stacks \\ d", 8),
    ]


@pytest.mark.parametrize("engine", gforth_run.ENGINES)
def test_one_mebibyte_line(engine):
    chunk = 'x"\\\x01\x1f\x7fé€😀 '.encode("utf-8")
    after = (chunk * ((1 << 20) // len(chunk) + 1))[: (1 << 20) - 10]
    while True:
        try:
            after.decode("utf-8")
            break
        except UnicodeDecodeError:
            after = after[:-1]
    case = Case("long", "comment", b"", after)
    for _, message in run_cases([case], engine):
        assert message is None, message


# --- census: pass rate per class --------------------------------------------

CENSUS: dict[tuple[str, str], Counter] = defaultdict(Counter)
ORACLES_SEEN: set[str] = set()


def _census_test(engine: str):
    def census(batch: list[Case]) -> None:
        result = run_bytes(program_for(batch), engine)
        if result.log_lines:
            ORACLES_SEEN.add(oracle_for(result.log_lines[0]))
        try:
            outcomes = check_run(batch, result, VALIDATOR)
        except CaseFailure as failure:  # the run broke: every line in it failed
            outcomes = [(case, str(failure)) for case in batch]
        lenient = None
        for index, (case, message) in enumerate(outcomes):
            tally = CENSUS[(engine, case.line_class)]
            tally["lines"] += 1
            if message is None:
                tally["pass"] += 1
                continue
            kind = message.split("]")[0] + "]"
            if kind == "[utf8]":  # is the record right apart from the bytes?
                if lenient is None:
                    lenient = check_run(batch, result, VALIDATOR, errors="surrogateescape")
                rest = lenient[index][1]
                kind += " rest ok" if rest is None else " and " + rest.split("]")[0] + "]"
            tally[kind] += 1

    name = f"test_census_{engine.replace('-', '_')}"
    census.__name__ = census.__qualname__ = name
    return name, settings(max_examples=budget(engine))(given(batch=mixed_batches())(census))


for _engine in gforth_run.ENGINES:
    _name, _test = _census_test(_engine)
    globals()[_name] = _test


@pytest.fixture(scope="module", autouse=True)
def census_report(request):
    yield
    if not CENSUS:
        return
    reporter = request.config.pluginmanager.get_plugin("terminalreporter")
    _, provenance = gforth_run.inspect_source()
    if provenance.startswith("file:"):  # keep machine paths out of pasted output
        provenance = "file:<INSPECT_FS> " + provenance.split(" ", 1)[1]
    reporter.write_line("")
    reporter.write_line(f"002 census  inspect.fs {provenance}  profile max_examples={PROFILE_EXAMPLES}"
                        f"  text oracle: {'/'.join(sorted(ORACLES_SEEN))}")
    for engine in gforth_run.ENGINES:
        for line_class in CLASSES:
            tally = CENSUS.get((engine, line_class))
            if not tally:
                continue
            failures = ", ".join(f"{kind} {count}" for kind, count in sorted(tally.items())
                                 if kind not in ("lines", "pass"))
            rate = 100.0 * tally["pass"] / tally["lines"]
            reporter.write_line(f"  {engine:<12} {line_class:<9} {tally['pass']:>6}/{tally['lines']:<6}"
                                f" {rate:6.2f}%  {failures}")
