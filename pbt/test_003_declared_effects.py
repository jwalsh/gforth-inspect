"""Experiment 003: the model's declared stack effects against measured deltas.

See experiments/003-declared-effects/README.org for the hypothesis and gate.
The sweep runs once per session (module fixture).  Inputs per word are
max(20, max_examples // 5) of the active Hypothesis profile: 20 for
`default`, 200 for `ci`.  The seed is EFFECTS_SEED (default 3) and each
word's inputs depend only on (seed, word name).

A JSON report is written to EFFECTS_REPORT, default
$XDG_CACHE_HOME/gforth-inspect/003-report.json; the calibration reads it.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest
from hypothesis import settings

import _003_helpers as helpers

AGREEMENT_THRESHOLD = 0.95

MODEL_PARSE = "model parse"
GFORTH_COMMENT = "gforth differs from its own comment"
HARNESS_TYPING = "harness typing"
DATA_DEPENDENT = "data-dependent effect"

# Every disagreement seen in gforth, with its one class.  A word that
# disagrees and is not here, or is here and now agrees, turns the test red.
CLASSIFIED: dict[str, tuple[str, str]] = {
    # alternatives (`|`, `/`) are kept as one list, so both branches are summed
    "(BranchAddr?)": (MODEL_PARSE, "a-addr1 -- a-addr2 true | false: both branches summed"),
    "CheckEnd": (MODEL_PARSE, "a-addr -- true | false: both branches summed"),
    "MoreBranchAddr?": (MODEL_PARSE, "a-addr1 -- a-addr2 true | false: both branches summed"),
    "(search-wordlist)": (MODEL_PARSE, "addr count wid -- nt | false: both branches summed"),
    "search-wordlist": (MODEL_PARSE, "c-addr count wid -- 0 | xt +-1: both branches summed"),
    "find": (MODEL_PARSE, "c-addr -- xt +-1 | c-addr 0: both branches summed"),
    "find-name": (MODEL_PARSE, "c-addr u -- nt | 0: both branches summed"),
    "sfind": (MODEL_PARSE, "c-addr u -- 0 / xt +-1: both branches summed"),
    "sfnumber": (MODEL_PARSE, "c-addr u -- r true | false: both branches summed"),
    "snumber?": (MODEL_PARSE, "c-addr u -- 0 / n -1 / d 0>: three branches summed"),
    "environment?": (MODEL_PARSE, "c-addr u -- false / ... true: both branches summed"),
    "last?": (MODEL_PARSE, "-- false / nfa nfa: both branches summed"),
    # variadic outputs (`x1 .. xn n`, `n*`) cannot be counted from the list
    "(save-input)": (MODEL_PARSE, "-- x1 .. xn n: variadic"),
    "get-order": (MODEL_PARSE, "-- widn .. wid1 n: variadic"),
    "save-see-flags": (MODEL_PARSE, "-- n* cnt: `n*` is a repeat count, read as one cell"),
    # item width lives only in the name; the model records no width
    "utime": (MODEL_PARSE, "-- dtime: a double, read as one cell"),
    "cputime": (MODEL_PARSE, "-- duser dsystem: two doubles, read as one cell each"),
    # synthesized `( -- w )` for end-struct names, which are 2Constants
    "buffer%": (MODEL_PARSE, "end-struct: synthesized -- w, pushes align size"),
    "buffer-struct": (MODEL_PARSE, "end-struct: synthesized -- w, pushes align size"),
    "c-lib%": (MODEL_PARSE, "end-struct: synthesized -- w, pushes align size"),
    "c-prefix%": (MODEL_PARSE, "end-struct: synthesized -- w, pushes align size"),
    "cff%": (MODEL_PARSE, "end-struct: synthesized -- w, pushes align size"),
    "interpret/compile-struct": (MODEL_PARSE, "end-struct: synthesized -- w, pushes align size"),
    "list%": (MODEL_PARSE, "end-struct: synthesized -- w, pushes align size"),
    "wordlist-map-struct": (MODEL_PARSE, "end-struct: synthesized -- w, pushes align size"),
    "wordlist-struct": (MODEL_PARSE, "end-struct: synthesized -- w, pushes align size"),
    # the r* -> float heuristic applied to a Forth-source comment
    "scratch": (MODEL_PARSE, "r -- addr len: r read as a float, but scratch takes none"),
    # gforth's code does not do what its comment says
    "uallot": (GFORTH_COMMENT, "( n -- ) but leaves the old udp: 1 uallot depth . -> 1"),
    # the effect depends on the value
    "?dup": (DATA_DEPENDENT, "w -- S:... w: copies w only when w is nonzero"),
    "digit?": (DATA_DEPENDENT, "char -- digit true / false: one or two cells by char"),
}

# Words excluded by measurement in gforth: they killed gforth, hung, broke
# the harness, threw on every-day typed inputs, or printed.
KNOWN_CRASHED = {"(;code)", "unkeys", "unkey", "clearhash", "(endtry)", "del-string", "(reveal)",
                 "compile-only", "restrict", "(does>2)", "!does", "open-lib"}
KNOWN_THREW = {"c-library-incomplete", "c-source-file", "Type!", ",Branch", "MyBranch",
               "char-append-buffer", "?CSP", "new-locals-reveal", "?struc", "CS-PICK", "cs-item?",
               "non-orig?", "scope?", "do-dest?", "dest?", "orig?", "def?", "(compile)",
               "interpreter1", "no.extensions", "interpreter-notfound1", "compiler-notfound1",
               "parser", "parser1", "compile-only-error", "ticking-compile-only-error", "#>>",
               'c(abort")', "wcall", "lib-sym", "(tablelfind)", "(hashlfind)"}
KNOWN_WROTE = {"c-source-file", "vlist", "?", "dobacktrace", "dec.", "."}


def report_path() -> Path:
    explicit = os.environ.get("EFFECTS_REPORT")
    if explicit:
        return Path(explicit)
    cache = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "gforth-inspect"
    cache.mkdir(parents=True, exist_ok=True)
    return cache / "003-report.json"


@pytest.fixture(scope="module")
def sweep() -> dict:
    model, live_text, provenance = helpers.model_source()
    selection = helpers.select(model, live_text)
    per_word = max(20, settings.default.max_examples // 5)
    seed = int(os.environ.get("EFFECTS_SEED", "3"))
    started = time.monotonic()
    outcomes = helpers.measure(selection.tested, "gforth", per_word, seed)
    measured_excluded = {
        "crashed": sorted(n for n, o in outcomes.items() if o.crashed),
        "threw": sorted(n for n, o in outcomes.items() if o.threw and not o.crashed),
        "wrote": sorted(n for n, o in outcomes.items() if o.wrote and not o.crashed),
    }
    gone = set().union(*measured_excluded.values())
    tested = {n: o for n, o in outcomes.items() if n not in gone}
    disagree = {n: o for n, o in tested.items() if not o.agrees}
    by_name = {w["name"]: w for w in selection.tested}
    engines = {}
    for engine in helpers.ENGINES[1:]:
        others = helpers.measure([by_name[n] for n in disagree], engine, per_word, seed)
        engines[engine] = {n: sorted(o.measured) for n, o in others.items()}
    result = {
        "model": provenance, "engine": "gforth", "seed": seed, "inputs_per_word": per_word,
        "universe": selection.universe,
        "excluded_static": {k: sorted(v) for k, v in selection.excluded.items()},
        "excluded_measured": measured_excluded,
        "crash_detail": {n: o.crash_detail for n, o in outcomes.items() if o.crashed},
        "tested": len(tested), "agree": len(tested) - len(disagree),
        "disagree": {n: {"declared": o.declared, "measured": sorted(o.measured),
                         "stack": by_name[n]["stack"]} for n, o in sorted(disagree.items())},
        "engines": engines,
        "wall_seconds": round(time.monotonic() - started, 1),
    }
    result["unclassified"] = sorted(set(disagree) - set(CLASSIFIED))
    result["classified_but_agree"] = sorted(set(CLASSIFIED) - set(disagree))
    report_path().write_text(json.dumps(result, indent=1, sort_keys=True))
    return result


def test_coverage_accounts_for_every_word(sweep):
    static = sum(len(v) for v in sweep["excluded_static"].values())
    measured = sum(1 for _ in set().union(*map(set, sweep["excluded_measured"].values())))
    assert static + measured + sweep["tested"] == sweep["universe"] == 2018
    assert "untypable-input" in sweep["excluded_static"]


def test_agreement_threshold(sweep):
    agreement = sweep["agree"] / sweep["tested"]
    assert agreement >= AGREEMENT_THRESHOLD, f"{sweep['agree']}/{sweep['tested']} = {agreement:.3f}"


def test_every_disagreement_is_classified(sweep):
    assert sweep["unclassified"] == [], f"unclassified disagreements: {sweep['unclassified']}"
    assert sweep["classified_but_agree"] == [], f"classified but agree: {sweep['classified_but_agree']}"


def test_measured_exclusions_are_known(sweep):
    measured = sweep["excluded_measured"]
    assert set(measured["crashed"]) == KNOWN_CRASHED, measured["crashed"]
    assert set(measured["threw"]) == KNOWN_THREW, measured["threw"]
    assert set(measured["wrote"]) == KNOWN_WROTE, measured["wrote"]


def test_disagreements_do_not_depend_on_engine(sweep):
    for engine, measured in sweep["engines"].items():
        for name, info in sweep["disagree"].items():
            assert measured.get(name) == info["measured"], (engine, name)
