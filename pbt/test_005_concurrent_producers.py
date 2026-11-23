"""Experiment 005: concurrent producers (experiments/005-concurrent-producers/README.org).

Producer obligation 1 (CONSUMERS.org): append-only, one complete JSON
object per line.  N gforth processes (2 to 4) log to one stacks.jsonl.
Hypothesis generates the schedule: which producer writes next and how many
snapshots it writes.  _005_helpers drives it one stdin line at a time and
waits for each record to land, so the schedule is deterministic and
shrinkable.  Every line of the log must parse (bytes split on LF), validate
against the schema, and every (producer, sequence) written must be there
exactly once, with one hello per producer.

  test_concurrent_producers  the runner's inspect.fs (INSPECT_REF /
                             INSPECT_FS, default this checkout's).  Strict xfail
                             citing #17 while its log-on and log-write are
                             those of a pinned unfixed ref (b1c162e,
                             10a0da4), a plain test once either changes
  test_patched_copy          the runner's inspect.fs with the proposed fix
                             applied in a temp copy: must pass
  test_paced_tally           report only: totals per pinned ref
  test_uncoordinated_race    report only: no pacing, the producers really
                             run at once

Volume: the default profile runs the gate's 200 / 50 / 50 schedules per
engine; PROFILE=ci runs five times that.

Seed: `gmake -C pbt check SEED=N` (pytest --hypothesis-seed=N) always wins;
PBT_SEED=N is a fallback when --hypothesis-seed is absent.
"""

from __future__ import annotations

import os
from collections import defaultdict

import jsonschema
import pytest
from hypothesis import Phase, example, given, note, seed, settings
from hypothesis import strategies as st

import _005_helpers as helpers
import gforth_run

ENGINES = gforth_run.ENGINES
CI = settings.default.max_examples >= 1000
SCALE = 5 if CI else 1
GATE_EXAMPLES = {"gforth": 200, "gforth-fast": 50, "gforth-itc": 50}
UNCOORDINATED_EXAMPLES = 50 * SCALE

# the inspect.fs under test, read once: it decides the xfail at collection.
# xfail(strict) only while its log-on and log-write are word for word those
# of a pinned unfixed ref; any change there makes it a plain test (005 Log,
# decision of 2026-11-21)
SOURCE, PROVENANCE = helpers.current_source()
UNFIXED_SOURCES = [helpers.current_source(ref)[0] for ref in (helpers.OLD_REF, helpers.HARDEN_REF)]
SOURCE_IS_UNFIXED = helpers.known_unfixed(SOURCE, UNFIXED_SOURCES)

TALLIES: dict = defaultdict(helpers.Tally)
SCHEDULES: dict = defaultdict(int)
PROVENANCES: dict = {"under test": PROVENANCE}


# --- strategies ---------------------------------------------------------


@st.composite
def schedules(draw):
    """(producers, [(producer, snapshots)]); every producer writes at least once."""
    producers = draw(st.integers(2, 4))
    steps = draw(st.lists(st.tuples(st.integers(0, producers - 1), st.integers(1, 3)),
                          min_size=1, max_size=12))
    for producer in range(producers):
        if producer not in {step[0] for step in steps}:
            steps.append((producer, 1))
    return producers, steps


uncoordinated_counts = st.lists(st.integers(20, 200), min_size=2, max_size=4)


def seed_in_force(config) -> tuple[int | None, str]:
    """(fallback seed to apply, text for the summary).  --hypothesis-seed always wins,
    however it was passed (command line, PYTEST_ADDOPTS, ini); PBT_SEED applies only
    without it."""
    cli_seed = config.getoption("--hypothesis-seed", default=None)
    if cli_seed is not None:
        return None, f"{cli_seed} (--hypothesis-seed)"
    if os.environ.get("PBT_SEED"):
        return int(os.environ["PBT_SEED"]), f"{os.environ['PBT_SEED']} (PBT_SEED)"
    return None, "random (pass SEED=N to fix it)"


@pytest.fixture
def apply_seed(request):
    fallback, _ = seed_in_force(request.config)
    return (lambda wrapped: seed(fallback)(wrapped)) if fallback is not None else (lambda wrapped: wrapped)


def check(source: bytes, provenance: str, engine: str, schedule, validator) -> helpers.Tally:
    producers, steps = schedule
    note(f"schedule: {producers} producers, steps {steps}")
    tally = helpers.run_paced(source, engine, producers, steps, validator)
    SCHEDULES[(provenance, engine)] += 1
    TALLIES[(provenance, engine)].add(tally)
    assert tally.ok(), (
        f"005 producer obligation 1 broken on {provenance} {engine}: {tally.summary()} "
        f"| first bad lines {tally.examples[:2]} | {producers} producers, steps {steps}")
    return tally


def schema_validator(ref: str | None = None) -> jsonschema.Validator:
    return jsonschema.Draft202012Validator(helpers.schema_for(ref))


# --- the property, on the runner's inspect.fs -----------------------------

XFAIL_17 = pytest.mark.xfail(
    strict=True,
    reason="#17: log-write writes at the fd's stale offset, so a second producer's "
           "records are overwritten; remove this when harden seeks before every write")


def engine_params(xfail: bool):
    marks = [XFAIL_17] if xfail else []
    return [pytest.param(engine, id=engine, marks=marks) for engine in ENGINES]


@pytest.mark.parametrize("engine", engine_params(xfail=SOURCE_IS_UNFIXED))
def test_concurrent_producers(engine, apply_seed):
    validator = schema_validator()

    # the regression case: the shrunk failure on b1c162e and on unfixed harden (8deb780 = 10a0da4)
    @apply_seed
    @settings(max_examples=GATE_EXAMPLES[engine] * SCALE, database=None)
    @example(schedule=(2, [(0, 1), (1, 1), (0, 1)]))
    @given(schedule=schedules())
    def run(schedule):
        check(SOURCE, PROVENANCE, engine, schedule, validator)
    run()


@pytest.mark.parametrize("engine", ENGINES)
def test_patched_copy(engine, apply_seed):
    if not SOURCE_IS_UNFIXED:
        pytest.skip("the inspect.fs under test changed its write path; "
                    "test_concurrent_producers runs on it as a plain test")
    if not helpers.patchable(SOURCE):
        pytest.skip("the fixture patches harden's log-write shape; this is b1c162e's one-liner")
    source = helpers.patched(SOURCE)
    provenance = f"{PROVENANCE} +seek-per-write"
    PROVENANCES["patched (under test)"] = provenance
    validator = schema_validator()

    @apply_seed
    @settings(max_examples=GATE_EXAMPLES[engine] * SCALE, database=None)
    @example(schedule=(2, [(0, 1), (1, 1), (0, 1)]))
    @given(schedule=schedules())
    def run(schedule):
        check(source, provenance, engine, schedule, validator)
    run()


# --- reports: never fail --------------------------------------------------


def pinned_sides():
    """(label, source, provenance, schema ref) for every pinned ref and the patch."""
    old, old_prov = helpers.current_source(helpers.OLD_REF)
    harden, harden_prov = helpers.current_source(helpers.HARDEN_REF)
    fixed, fixed_prov = helpers.current_source(helpers.FIXED_REF)
    sides = [("b1c162e", old, old_prov, helpers.OLD_REF),
             ("harden", harden, harden_prov, helpers.HARDEN_REF),
             ("fixed", fixed, fixed_prov, helpers.FIXED_REF)]
    if helpers.patchable(harden):
        sides.append(("patched", helpers.patched(harden), f"{harden_prov} +seek-per-write",
                      helpers.HARDEN_REF))
    return sides


SIDES = ("b1c162e", "harden", "patched", "fixed")
REPORTS: dict = defaultdict(helpers.Tally)
REPORT_RUNS: dict = defaultdict(int)


def side(label):
    for candidate in pinned_sides():
        if candidate[0] == label:
            return candidate
    pytest.skip(f"no {label} side (the fix sed does not apply to pinned harden)")


@pytest.mark.parametrize("engine", ENGINES)
@pytest.mark.parametrize("label", SIDES)
def test_paced_tally(label, engine, apply_seed):
    """Report only: the paced schedules against each pinned ref, all counted."""
    _, source, provenance, schema_ref = side(label)
    PROVENANCES[f"{label} (pinned)"] = provenance
    validator = schema_validator(schema_ref)

    @apply_seed
    @settings(max_examples=GATE_EXAMPLES[engine] * SCALE, database=None, phases=[Phase.generate])
    @given(schedule=schedules())
    def run(schedule):
        producers, steps = schedule
        REPORTS[("paced", label, engine)].add(
            helpers.run_paced(source, engine, producers, steps, validator))
        REPORT_RUNS[("paced", label, engine)] += 1
    run()


@pytest.mark.parametrize("label", SIDES)
def test_uncoordinated_race(label, apply_seed):
    """Report only: no pacing; evidence about the race window, not pass or fail."""
    _, source, provenance, schema_ref = side(label)
    PROVENANCES[f"{label} (pinned)"] = provenance
    validator = schema_validator(schema_ref)

    @apply_seed
    @settings(max_examples=UNCOORDINATED_EXAMPLES, database=None, phases=[Phase.generate])
    @given(counts=uncoordinated_counts)
    def run(counts):
        REPORTS[("uncoordinated", label, "gforth")].add(
            helpers.run_uncoordinated(source, "gforth", counts, validator))
        REPORT_RUNS[("uncoordinated", label, "gforth")] += 1
    run()


@pytest.fixture(scope="session", autouse=True)
def session_summary(request):
    yield
    reporter = request.config.pluginmanager.get_plugin("terminalreporter")
    if reporter is None:
        return
    _, seed_text = seed_in_force(request.config)
    fixed = ("write path of a pinned unfixed ref: xfail #17" if SOURCE_IS_UNFIXED
             else "write path changed: plain test")
    fixed += f", seek per write {'yes' if helpers.seeks_per_write(SOURCE) else 'no'}"
    reporter.write_line(f"005: under test {PROVENANCE} ({fixed})  seed {seed_text}  "
                        f"profile {'ci' if CI else 'default'}")
    for label, provenance in sorted(PROVENANCES.items()):
        reporter.write_line(f"005: side {label:20} {provenance}")
    for (provenance, engine), count in sorted(SCHEDULES.items()):
        reporter.write_line(f"005: property {engine:11} {count:5} schedules  {provenance}  "
                            f"{TALLIES[(provenance, engine)].summary()}")
    for (mode, label, engine), tally in sorted(REPORTS.items()):
        runs = REPORT_RUNS[(mode, label, engine)]
        reporter.write_line(f"005: report {mode:13} {label:8} {engine:11} {runs:5} runs  "
                            f"{tally.summary()}")
