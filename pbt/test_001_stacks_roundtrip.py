"""Experiment 001: stacks-roundtrip (experiments/001-stacks-roundtrip/README.org).

P1 non-interference: after the inspector word runs, the data and float
stacks are bit-identical to before.
P2 faithfulness: the snapshot record's `data` and `float` equal an
independent read of the stacks, and every log line validates against
contract/stacks-log.schema.json.

Three code paths x three engines.  The independent read is raw: `depth` +
`pick` printed with `hex u.`, floats as their 64-bit patterns via
`fp@ i floats + @`.  Never `.s` or `f.s`.  Many cases are batched into one
gforth process; one Hypothesis example is one batch.

The tests are ref-agnostic: which inspect.fs they run against is decided by
INSPECT_REF / INSPECT_FS (see gforth_run.py), never here.

Seed: `gmake -C pbt check SEED=N` (pytest --hypothesis-seed=N) is the
documented way and always wins.  PBT_SEED=N is a fallback, applied only when
--hypothesis-seed is absent.  The session summary prints the seed in force.
"""

from __future__ import annotations

import json
import math
import os
import re
import struct
import sys
from collections import Counter, defaultdict

import jsonschema
import pytest
from hypothesis import given, note, seed, settings
from hypothesis import strategies as st

import gforth_run

CELL_BITS = 64
CELL_MASK = (1 << CELL_BITS) - 1
MAX_DATA_DEPTH = 20
MAX_FLOAT_DEPTH = 8
MAX_BATCH = 12

SEED_FROM_CLI = any(arg.startswith("--hypothesis-seed") for arg in sys.argv)
FALLBACK_SEED = None if SEED_FROM_CLI or not os.environ.get("PBT_SEED") else int(os.environ["PBT_SEED"])

# --- the Forth side -----------------------------------------------------

PRELUDE = r"""
create fbits 1 floats allot
: bits>f ( u -- F: r ) fbits ! fbits f@ ;
: raw-read ( -- )
    \ top first; cells and float bit patterns as unsigned hex
    hex cr ." #R D " depth 0 .r ." :"
    depth 0 ?DO space i pick u. LOOP
    ."  F " fdepth 0 .r ." :"
    fdepth 0 ?DO space fp@ i floats + @ u. LOOP
    ."  #" decimal cr ;
: probe-tilde3 ( -- ) raw-read ~~~ raw-read ;
all-~~
: probe-tilde2 ( -- ) raw-read ~~ raw-read ;
log-on
"""

# path id -> lines that run the inspector between two raw reads
PATHS = {
    "dotstacks": ["raw-read", ".stacks", "raw-read"],
    "tilde3": ["probe-tilde3"],
    "tilde2all": ["probe-tilde2"],
}
ENGINES = gforth_run.ENGINES

READ_RE = re.compile(r"^#R D ([0-9A-F]+):((?: [0-9A-F]+ )*) F ([0-9A-F]+):((?: [0-9A-F]+ )*) #$")


def push_line(case) -> str:
    data_cells, float_bits = case
    words = [f"${cell:X}" for cell in data_cells]
    words += [f"${bits:X} bits>f" for bits in float_bits]
    return " ".join(words)


def program(path: str, cases) -> str:
    lines = [PRELUDE]
    for case in cases:
        lines.append("clearstack fclearstack")
        lines.append(push_line(case))
        lines.extend(PATHS[path])
    lines.append("clearstack fclearstack")
    lines.append("log-off")
    return "\n".join(lines) + "\n"


def reproducer(path: str, case) -> str:
    """One line: gforth inspect.fs -e '...' that replays this case."""
    data_cells, float_bits = case
    pushes = " ".join([f"${cell:X}" for cell in data_cells]
                      + [f"${bits:X} fb ! fb f@" for bits in float_bits])
    if path == "dotstacks":
        define, call = "", ".stacks"
    elif path == "tilde3":
        define, call = ": p ~~~ ; ", "p"
    else:
        define, call = "all-~~ : p ~~ ; ", "p"
    body = f"create fb 8 allot {define}log-on {pushes} {call} depth . fdepth . log-off bye"
    return f"gforth inspect.fs -e '{' '.join(body.split())}'"


# --- the Python side ----------------------------------------------------


def to_signed(cell: int) -> int:
    return cell - (1 << CELL_BITS) if cell >> (CELL_BITS - 1) else cell


def bits_to_float(bits: int) -> float:
    return struct.unpack("<d", struct.pack("<Q", bits))[0]


def float_to_bits(value: float) -> int:
    return struct.unpack("<Q", struct.pack("<d", value))[0]


def parse_reads(stdout: str):
    """[(data bottom-first, float bits bottom-first)] in output order."""
    reads = []
    for line in stdout.splitlines():
        if not line.startswith("#R "):
            continue
        match = READ_RE.match(line.rstrip())
        assert match, f"unparsable raw read: {line!r}"
        data_depth, data_text, float_depth, float_text = match.groups()
        data_top_first = [int(word, 16) for word in data_text.split()]
        float_top_first = [int(word, 16) for word in float_text.split()]
        assert len(data_top_first) == int(data_depth, 16)
        assert len(float_top_first) == int(float_depth, 16)
        reads.append((data_top_first[::-1], float_top_first[::-1]))
    return reads


class Outcome:
    """One gforth process over a batch: reads and records, paired per case."""

    def __init__(self, prop: str, path: str, engine: str, cases):
        self.path, self.engine, self.cases = path, engine, cases
        self.run = gforth_run.run(program(path, cases), engine=engine, timeout=30)
        assert self.run.returncode == 0, (
            f"gforth exited {self.run.returncode}\nstderr tail: {self.run.stderr[-800:]}")
        reads = parse_reads(self.run.stdout)
        self.lines = self.run.log_lines
        records = [json.loads(line) for line in self.lines]
        self.snapshots = [record for record in records if record.get("event") == "snapshot"]
        assert len(reads) == 2 * len(cases), (
            f"harness desync: {len(reads)} raw reads for {len(cases)} cases")
        assert len(self.snapshots) == len(cases), (
            f"harness desync: {len(self.snapshots)} snapshots for {len(cases)} cases")
        self.before = reads[0::2]
        self.after = reads[1::2]
        STATS[(prop, self.path, self.engine)] += len(cases)
        for record in self.snapshots:  # observed, not asserted: where/src are outside P2 (issue #2)
            WHERE_SRC[self.path][(record.get("where") is None, record.get("src") is None)] += 1

    def repro(self, index: int) -> str:
        return reproducer(self.path, self.cases[index])


STATS: Counter = Counter()
FLOAT_CLASSES: dict = defaultdict(Counter)
WHERE_SRC: dict = defaultdict(Counter)


def nonfinite_name(value: float) -> str:
    """The contract's string for a non-finite value (since 1.2, issue #66):
    protobuf's JSON spelling, any NaN as "NaN" whatever its sign or payload."""
    if math.isnan(value):
        return "NaN"
    return "Infinity" if value > 0 else "-Infinity"


def classify(expected_bits: int, logged) -> str | None:
    """None if the logged value is faithful, else sign / precision / non-finite.
    A non-finite value is faithful only as its exact string (null, what
    inspect < 0.4.0 wrote, or the other infinity's string is not)."""
    expected = bits_to_float(expected_bits)
    if not math.isfinite(expected):
        return None if isinstance(logged, str) and logged == nonfinite_name(expected) else "non-finite"
    if logged is None or not isinstance(logged, (int, float)) or isinstance(logged, bool):
        return "non-finite"
    try:
        logged = float(logged)
    except OverflowError:  # a JSON integer beyond binary64 range
        return "non-finite"
    if not math.isfinite(logged):  # a finite value whose literal decodes to inf
        return "non-finite"
    if float_to_bits(logged) == expected_bits:
        return None
    if logged == expected or logged == -expected:
        return "sign"
    return "precision"


# --- strategies ---------------------------------------------------------

EDGE_CELLS = [0, 1, 2, CELL_MASK, 1 << 63, (1 << 63) - 1, (1 << 63) + 1, 0xFF, 1 << 32]
cells = st.one_of(st.sampled_from(EDGE_CELLS), st.integers(0, CELL_MASK))

EDGE_FLOATS = [
    0x0000000000000000,  # +0
    0x8000000000000000,  # -0
    0x7FF0000000000000,  # +inf
    0xFFF0000000000000,  # -inf
    0x7FF8000000000000,  # quiet nan
    0xFFF8000000000000,  # negative nan
    0x7FF0000000000001,  # signalling nan, payload 1
    0x0000000000000001,  # least subnormal
    0x000FFFFFFFFFFFFF,  # greatest subnormal
    0x8000000000000001,  # -least subnormal
    0x0010000000000000,  # least normal
    0x7FEFFFFFFFFFFFFF,  # greatest finite
    0x3FF0000000000000,  # 1
    0x3FF0000000000001,  # 1 + ulp: needs 17 digits
    float_to_bits(0.1), float_to_bits(0.1 + 0.2), float_to_bits(1 / 3),
    float_to_bits(2 / 3), float_to_bits(math.pi), float_to_bits(-math.e),
]
float_bits = st.one_of(
    st.sampled_from(EDGE_FLOATS),
    st.floats(allow_nan=True, allow_infinity=True).map(float_to_bits),
    st.tuples(st.booleans(), st.integers(1, (1 << 52) - 1)).map(
        lambda signed_mantissa: (signed_mantissa[0] << 63) | signed_mantissa[1]),  # subnormals
    st.integers(0, CELL_MASK),  # any bit pattern
)
cases = st.tuples(
    st.lists(cells, max_size=MAX_DATA_DEPTH),
    st.lists(float_bits, max_size=MAX_FLOAT_DEPTH),
)
batches = st.lists(cases, min_size=1, max_size=MAX_BATCH)

PAIRS = [pytest.param(path, engine, id=f"{path}-{engine}") for path in PATHS for engine in ENGINES]


def property_test(test):
    wrapped = settings(database=None)(given(batch=batches)(test))
    if FALLBACK_SEED is not None:
        wrapped = seed(FALLBACK_SEED)(wrapped)
    return pytest.mark.parametrize("path,engine", PAIRS)(wrapped)


@pytest.fixture(scope="session", autouse=True)
def session_summary(request):
    yield
    reporter = request.config.pluginmanager.get_plugin("terminalreporter")
    if reporter is None:
        return
    _, provenance = gforth_run.inspect_source()
    if provenance.startswith("file:"):  # a planted copy in a temp dir: keep paths out of logs
        provenance = "file:<INSPECT_FS> " + provenance.split()[-1]
    cli_seed = request.config.getoption("--hypothesis-seed", default=None)
    if cli_seed is not None:
        seed_text = f"{cli_seed} (--hypothesis-seed)"
    elif FALLBACK_SEED is not None:
        seed_text = f"{FALLBACK_SEED} (PBT_SEED)"
    else:
        seed_text = "random (pass SEED=N to fix it)"
    reporter.write_line(f"001: inspect.fs {provenance}  seed {seed_text}")
    reporter.write_line("001: stack cases run per property (generate + shrink phases)")
    for (prop, path, engine), count in sorted(STATS.items()):
        reporter.write_line(f"001: cases {prop:12} {path:9} {engine:11} {count}")
    for path, counter in sorted(WHERE_SRC.items()):
        shown = {f"where{'=null' if where_is_null else ' set'} src{'=null' if src_is_null else ' set'}": count
                 for (where_is_null, src_is_null), count in sorted(counter.items())}
        reporter.write_line(f"001: observed {path:9} {shown}")
    for key, counter in sorted(FLOAT_CLASSES.items()):
        reporter.write_line(f"001: float corpus {key[0]:9} {key[1]:11} {dict(counter)}")


# --- P1 -----------------------------------------------------------------


@property_test
def test_p1_noninterference(path, engine, batch):
    outcome = Outcome("p1", path, engine, batch)
    for index, (before, after) in enumerate(zip(outcome.before, outcome.after)):
        note(f"reproducer: {outcome.repro(index)}")
        assert before[0] == after[0], (
            f"P1 data stack changed by {path} in {engine}: before {[hex(c) for c in before[0]]} "
            f"after {[hex(c) for c in after[0]]} | {outcome.repro(index)}")
        assert before[1] == after[1], (
            f"P1 float stack changed by {path} in {engine}: before {[hex(b) for b in before[1]]} "
            f"after {[hex(b) for b in after[1]]} | {outcome.repro(index)}")


# --- P2 -----------------------------------------------------------------


@property_test
def test_p2_data(path, engine, batch):
    outcome = Outcome("p2_data", path, engine, batch)
    for index, (before, record) in enumerate(zip(outcome.before, outcome.snapshots)):
        expected = [to_signed(cell) for cell in before[0]]
        assert record["data"] == expected, (
            f"P2 data mismatch in {path} {engine}: logged {record['data']} read {expected} "
            f"| {outcome.repro(index)}")


@property_test
def test_p2_float(path, engine, batch):
    outcome = Outcome("p2_float", path, engine, batch)
    for index, (before, record) in enumerate(zip(outcome.before, outcome.snapshots)):
        logged = record["float"]
        assert len(logged) == len(before[1]), (
            f"P2 float depth mismatch in {path} {engine}: logged {logged} read "
            f"{[hex(b) for b in before[1]]} | {outcome.repro(index)}")
        for bits, value in zip(before[1], logged):
            kind = classify(bits, value)
            assert kind is None, (
                f"P2 float {kind} mismatch in {path} {engine}: bits {bits:#018x} "
                f"({bits_to_float(bits)!r}) logged {value!r} | {outcome.repro(index)}")


@property_test
def test_p2_schema(path, engine, batch):
    outcome = Outcome("p2_schema", path, engine, batch)
    validator = jsonschema.Draft202012Validator(gforth_run.schema())
    for line in outcome.lines:
        errors = [error.message for error in validator.iter_errors(json.loads(line))]
        assert not errors, f"P2 schema violation in {path} {engine}: {errors[:3]} line {line[:300]}"


# --- a fixed float corpus, to classify every mismatch rather than the first ---


@pytest.mark.parametrize("path,engine", PAIRS)
def test_p2_float_corpus(path, engine):
    corpus = [([], [bits]) for bits in EDGE_FLOATS]
    outcome = Outcome("p2_corpus", path, engine, corpus)
    failures = []
    for index, (before, record) in enumerate(zip(outcome.before, outcome.snapshots)):
        expected_bits = before[1][0]
        logged = record["float"]
        if len(logged) != 1:
            kind, shown = "depth", f"{logged!r} (expected one value)"
        else:
            kind, shown = classify(expected_bits, logged[0]), repr(logged[0])
        FLOAT_CLASSES[(path, engine)][kind or "exact"] += 1
        if kind:
            failures.append(f"{kind}: {expected_bits:#018x} logged {shown}")
    assert not failures, f"P2 float corpus in {path} {engine}: " + "; ".join(failures)
