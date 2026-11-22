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
                             INSPECT_FS, default harden).  Strict xfail
                             citing #17 when its log-write does not seek
                             before each record, a plain test when it does
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
import sys
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

SEED_FROM_CLI = any(arg.startswith("--hypothesis-seed") for arg in sys.argv)
FALLBACK_SEED = None if SEED_FROM_CLI or not os.environ.get("PBT_SEED") else int(os.environ["PBT_SEED"])

# the inspect.fs under test, read once: it decides the xfail at collection
SOURCE, PROVENANCE = helpers.current_source()
SOURCE_IS_FIXED = helpers.seeks_per_write(SOURCE)

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


def apply_seed(wrapped):
    return seed(FALLBACK_SEED)(wrapped) if FALLBACK_SEED is not None else wrapped


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


@pytest.mark.parametrize("engine", engine_params(xfail=not SOURCE_IS_FIXED))
def test_concurrent_producers(engine):
    validator = schema_validator()

    # the regression case: the shrunk failure on 18ebe2d and on harden 6af19f0
    @apply_seed
    @settings(max_examples=GATE_EXAMPLES[engine] * SCALE, database=None)
    @example(schedule=(2, [(0, 1), (1, 1), (0, 1)]))
    @given(schedule=schedules())
    def run(schedule):
        check(SOURCE, PROVENANCE, engine, schedule, validator)
    run()


@pytest.mark.parametrize("engine", ENGINES)
def test_patched_copy(engine):
    if SOURCE_IS_FIXED:
        pytest.skip("the inspect.fs under test already seeks before every write; "
                    "test_concurrent_producers covers it")
    source = helpers.patched(SOURCE)
    provenance = f"{PROVENANCE} +seek-per-write"
    PROVENANCES["patched"] = provenance
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
    sides = [("18ebe2d", old, old_prov, helpers.OLD_REF),
             ("harden", harden, harden_prov, helpers.HARDEN_REF)]
    if not helpers.seeks_per_write(harden):
        sides.append(("patched", helpers.patched(harden), f"{harden_prov} +seek-per-write",
                      helpers.HARDEN_REF))
    return sides


SIDES = ("18ebe2d", "harden", "patched")
REPORTS: dict = defaultdict(helpers.Tally)
REPORT_RUNS: dict = defaultdict(int)


def side(label):
    for candidate in pinned_sides():
        if candidate[0] == label:
            return candidate
    pytest.skip(f"no {label} side (pinned harden already carries the fix)")


@pytest.mark.parametrize("engine", ENGINES)
@pytest.mark.parametrize("label", SIDES)
def test_paced_tally(label, engine):
    """Report only: the paced schedules against each pinned ref, all counted."""
    _, source, provenance, schema_ref = side(label)
    PROVENANCES[label] = provenance
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
def test_uncoordinated_race(label):
    """Report only: no pacing; evidence about the race window, not pass or fail."""
    _, source, provenance, schema_ref = side(label)
    PROVENANCES[label] = provenance
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
    cli_seed = request.config.getoption("--hypothesis-seed", default=None)
    if cli_seed is not None:
        seed_text = f"{cli_seed} (--hypothesis-seed)"
    elif FALLBACK_SEED is not None:
        seed_text = f"{FALLBACK_SEED} (PBT_SEED)"
    else:
        seed_text = "random (pass SEED=N to fix it)"
    fixed = "seeks before every write" if SOURCE_IS_FIXED else "no seek per write: xfail #17"
    reporter.write_line(f"005: under test {PROVENANCE} ({fixed})  seed {seed_text}  "
                        f"profile {'ci' if CI else 'default'}")
    for label, provenance in sorted(PROVENANCES.items()):
        reporter.write_line(f"005: side {label:10} {provenance}")
    for (provenance, engine), count in sorted(SCHEDULES.items()):
        reporter.write_line(f"005: property {engine:11} {count:5} schedules  {provenance}  "
                            f"{TALLIES[(provenance, engine)].summary()}")
    for (mode, label, engine), tally in sorted(REPORTS.items()):
        runs = REPORT_RUNS[(mode, label, engine)]
        reporter.write_line(f"005: report {mode:13} {label:8} {engine:11} {runs:5} runs  "
                            f"{tally.summary()}")
