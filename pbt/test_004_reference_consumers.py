"""004 reference-consumers: do the frozen consumers read harden's records as
they read 18ebe2d's?  See experiments/004-reference-consumers/README.org.

The same generated programs run under both sides (_004_helpers: old is
18ebe2d, new is the runner's selection).  Each run's log goes to the three
consumers in pbt/consumers/, and their outputs are compared field by field.
Every difference gets one class:

  #1-float           a float that decodes to the true value (or closer to
                     it) where the old one did not; the true value is read
                     independently, as raw bits via fp@
  escape-fix         input.text equals the true source line where the old
                     text did not (control bytes kept, invalid UTF-8 as
                     U+FFFD), including old records a consumer could not
                     decode at all.  Not one of the brief's three classes:
                     it is reported so the verdict can rule on it
  fix-#2             where/src on the ~~ path: null in the old record, the
                     word and prog.fs:line of the ~~ in the new one (#2)
  ignorable-new-key  a key only the new record has (hello.inspect,
                     hello.contract)
  breaking           anything else

`t` (Unix seconds) is masked: it is a clock, not a stack.  The checker runs
with its version stop bypassed for the differential; the stop is its own
test.  Default location is checked by a direct gforth call with
GFORTH_INSPECT_LOG_DIR unset.
"""

from __future__ import annotations

import json
import math
import os
import re
import struct
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import pytest
from hypothesis import Phase, given, settings
from hypothesis import strategies as st

import _004_helpers as helpers

sys.path.insert(0, str(Path(__file__).parent / "consumers"))
import checker  # noqa: E402  (the frozen consumer, imported as written)

CONSUMERS = Path(__file__).parent / "consumers"
UNKNOWN = "x-unknown-004"
FLOAT_FIELDS = {"f", "float"}
ERROR_KEYS = {"jq-error", "error", "decode-error", "http"}

STATS: dict = {"programs": 0, "snapshots": 0, "runs": 0, "classes": Counter(),
               "examples": {}, "started": time.monotonic()}

# --- the summary, printed at the end of the pytest run ------------------


class _Summary:
    def pytest_terminal_summary(self, terminalreporter):
        write = terminalreporter.write_line
        write("== 004 reference-consumers summary")
        write(f"old: {helpers.provenance('old')}")
        write(f"new: {helpers.provenance('new')}")
        write(f"programs {STATS['programs']}  snapshots {STATS['snapshots']}  "
              f"gforth runs {STATS['runs']}  wall {time.monotonic() - STATS['started']:.1f}s")
        if not STATS["classes"]:
            write("differences: none")
        for (cls, consumer, field), count in sorted(STATS["classes"].items()):
            example = STATS["examples"][(cls, consumer, field)]
            write(f"  {cls:18} consumer={consumer:8} field={field:12} n={count:5}  e.g. {example}")
        for line in STATS.get("gate_lines", []):
            write(line)


@pytest.fixture(scope="module", autouse=True)
def _summary(request):
    plugin = _Summary()
    if request.config.pluginmanager.get_plugin("004-summary") is None:
        request.config.pluginmanager.register(plugin, "004-summary")
    yield


# --- consumers ---------------------------------------------------------

@pytest.fixture(scope="module")
def server():
    with tempfile.TemporaryDirectory(prefix="gfi-004-srv-") as tmp:
        served = Path(tmp) / "stacks.jsonl"
        proc = subprocess.Popen([sys.executable, str(CONSUMERS / "mock_server.py"), str(served)],
                                stdout=subprocess.PIPE, text=True)
        port_line = proc.stdout.readline()
        assert port_line.startswith("PORT "), port_line
        yield served, int(port_line.split()[1])
        proc.terminate()
        proc.wait(timeout=5)


def _reject_constant(name):
    raise ValueError(f"{name} is not JSON")


def _strict_json(raw: bytes):
    return json.loads(raw.decode("utf-8"), parse_constant=_reject_constant)


def _log_bytes(lines: list[str]) -> bytes:
    return b"".join(line.encode("utf-8", "surrogateescape") + b"\n" for line in lines)


def run_jq(lines: list[str]) -> list[dict]:
    with tempfile.NamedTemporaryFile(suffix=".jsonl") as log:
        log.write(_log_bytes(lines))
        log.flush()
        proc = subprocess.run(["jq", "-c", "-f", str(CONSUMERS / "stacks.jq"), log.name],
                              capture_output=True)
    if proc.returncode != 0:
        first = proc.stderr.decode("utf-8", "replace").splitlines()[:1]
        # the kind of error, without its position (an injected key moves it)
        kind = re.sub(r" at line \d+, column \d+$", "", first[0]) if first else f"exit {proc.returncode}"
        return [{"jq-error": kind}]
    return [_strict_json(out) for out in proc.stdout.splitlines()]


def checker_check(path: Path, schema: dict, version_stop: bool) -> dict:
    """The frozen checker; a crash is recorded as its output (a real editor
    checker that throws shows the user nothing), so it gets classified."""
    try:
        return checker.check(path, schema, version_stop=version_stop)
    except Exception as error:  # noqa: BLE001
        return {"error": f"checker crashed: {type(error).__name__} {error}"}


def run_checker(lines: list[str], schema: dict, version_stop: bool = False) -> list[dict]:
    """The checker's output for every prefix of the log (it reads the last line)."""
    outputs = []
    with tempfile.NamedTemporaryFile(suffix=".jsonl") as log:
        for end in range(1, len(lines) + 1):
            log.seek(0)
            log.truncate()
            log.write(_log_bytes(lines[:end]))
            log.flush()
            outputs.append(checker_check(Path(log.name), schema, version_stop))
    return outputs


def run_server(lines: list[str], server) -> tuple[list[dict], list[str]]:
    """GET /stacks after each prefix.  Returns (outputs, contract violations)."""
    served, port = server
    outputs, violations = [], []
    for end in range(1, len(lines) + 1):
        served.write_bytes(_log_bytes(lines[:end]))
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/stacks", timeout=5) as resp:
                status, ctype, body = resp.status, resp.headers["Content-Type"], resp.read()
        except urllib.error.HTTPError as error:
            outputs.append({"http": error.code})
            continue
        expected_body = lines[end - 1].encode("utf-8", "surrogateescape")
        if body != expected_body or ctype != "application/json" or status != 200:
            violations.append(f"server did not serve line {end} as-is ({status} {ctype})")
        try:
            record = _strict_json(body)
        except ValueError as error:
            outputs.append({"decode-error": type(error).__name__})
            continue
        record.pop("t", None)
        outputs.append(record)
    return outputs, violations


# --- programs ----------------------------------------------------------

SPECIAL_FLOATS = [0.0, -0.0, math.inf, -math.inf, math.nan, 5e-324, -5e-324, 2.2250738585072014e-308,
                  1.7976931348623157e308, -1.7976931348623157e308, 0.1, 0.30000000000000004,
                  1 / 3, 123456789.12345679]
MIN_N, MAX_N = -(2**63), 2**63 - 1


def _bits(value: float) -> int:
    return struct.unpack("<q", struct.pack("<d", value))[0]


def _float(bits: int) -> float:
    return struct.unpack("<d", struct.pack("<q", bits))[0]


float_bits = st.one_of(
    st.sampled_from(SPECIAL_FLOATS).map(_bits),
    st.floats(allow_nan=True, allow_infinity=True, allow_subnormal=True).map(_bits),
    st.integers(MIN_N, MAX_N),  # any bit pattern: NaN payloads, subnormals
)
cells = st.one_of(st.sampled_from([0, 1, -1, MIN_N, MAX_N, MIN_N + 1, MAX_N - 1]),
                  st.integers(MIN_N, MAX_N), st.integers(-1000, 1000))
# input lines as in 002: any byte but LF and CR (CR would end the line)
line_text = st.binary(max_size=60).map(lambda raw: raw.replace(b"\n", b" ").replace(b"\r", b" "))


@dataclass
class Program:
    path: str           # stacks | tilde3 | tilde2
    data: list[int]
    floats: list[int]   # bit patterns, bottom first
    rs_cells: list[int]
    nested: bool
    text: bytes


programs = st.builds(
    Program,
    path=st.sampled_from(["stacks", "tilde3", "tilde2"]),
    data=st.lists(cells, max_size=20),
    floats=st.lists(float_bits, max_size=8),
    rs_cells=st.lists(cells, max_size=3),
    nested=st.booleans(),
    text=line_text,
)

HEADER = b"""create fbuf 8 allot
: .fbits ( -- ) base @ hex fdepth 0 ?DO fp@ i floats + @ u. LOOP base ! ;
: .mark ( n -- ) cr ." @@T " 0 .r space .fbits cr ;
all-~~
log-on
"""


def build(batch: list[Program]) -> tuple[str, list[bytes], list[tuple]]:
    """Forth source for a batch, each program's snapshot line (the true
    input.text), and its true (where, src) for the colon paths."""
    source = [HEADER]
    snapshot_lines, places = [], []
    for index, prog in enumerate(batch):
        call = b".stacks"
        places.append((None, None))
        if prog.path != "stacks":
            line_number = b"".join(source).count(b"\n") + 1
            places[-1] = (f"w{index}", f"prog.fs:{line_number}")
            probe = b"~~~" if prog.path == "tilde3" else b"~~"
            pushes = b" ".join(b"%d >r" % cell for cell in prog.rs_cells)
            pops = b" r> drop" * len(prog.rs_cells)
            source.append(b": w%d %s %s%s ;\n" % (index, pushes, probe, pops))
            call = b"w%d" % index
            if prog.nested:
                source.append(b": c%d w%d ;\n" % (index, index))
                call = b"c%d" % index
        floats = b" ".join(b"%d fbuf ! fbuf f@" % bits for bits in prog.floats)
        data = b" ".join(b"%d" % cell for cell in prog.data)
        source.append(b"%s %s %d .mark\n" % (floats, data, index))
        line = call + b" \\ " + prog.text
        snapshot_lines.append(line)
        source.append(line + b"\n")
        source.append(b"clearstack fclearstack\n")
    source.append(b"log-off\n")
    return b"".join(source).decode("utf-8", "surrogateescape"), snapshot_lines, places


def true_floats(stdout: str, count: int) -> list[list[int]]:
    """Raw float bits per program, bottom first, from the @@T markers."""
    marks = {}
    for line in stdout.splitlines():
        if line.startswith("@@T "):
            fields = line.split()
            bits = [int(word, 16) for word in fields[2:]]
            marks[int(fields[1])] = [b - 2**64 if b >= 2**63 else b for b in reversed(bits)]
    return [marks[index] for index in range(count)]


def contract_text(raw: bytes) -> str:
    """The source line as the contract says input.text decodes: valid UTF-8
    kept, each byte of an invalid sequence as U+FFFD."""
    out, pos = [], 0
    while pos < len(raw):
        lead = raw[pos]
        width = 1 if lead < 0x80 else 2 if 0xC2 <= lead < 0xE0 else 3 if 0xE0 <= lead < 0xF0 \
            else 4 if 0xF0 <= lead < 0xF5 else 0
        try:
            if width == 0:
                raise UnicodeDecodeError("utf-8", raw, pos, pos + 1, "lead")
            out.append(raw[pos:pos + width].decode("utf-8"))
            pos += width
        except UnicodeDecodeError:
            out.append("\ufffd")
            pos += 1
    return "".join(out)


# --- comparison --------------------------------------------------------

def _same(left, right) -> bool:
    if isinstance(left, float) or isinstance(right, float):
        if isinstance(left, bool) or isinstance(right, bool):
            return False
        if not isinstance(left, (int, float)) or not isinstance(right, (int, float)):
            return False
        return struct.pack("<d", float(left)) == struct.pack("<d", float(right))
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(map(_same, left, right))
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(_same(left[k], right[k]) for k in left)
    return type(left) is type(right) and left == right


def _flatten(record: dict) -> dict:
    flat = {}
    for key, value in record.items():
        if key == "input" and isinstance(value, dict):
            for sub_key, sub_value in value.items():
                flat[f"input.{sub_key}"] = sub_value
        else:
            flat[key] = value
    return flat


@dataclass
class Context:
    floats: list[int]
    text: str
    invalid_utf8: bool
    path: str = "stacks"
    where: str | None = None
    src: str | None = None
    earlier_invalid_utf8: bool = False  # some line before this one is not UTF-8


def _float_exact(value, truth_bits: int) -> bool:
    truth = _float(truth_bits)
    if not math.isfinite(truth):
        return value is None
    return isinstance(value, (int, float)) and not isinstance(value, bool) \
        and struct.pack("<d", float(value)) == struct.pack("<d", truth)


def _classify_floats(old, new, ctx: Context | None):
    if ctx is None or not isinstance(old, list) or not isinstance(new, list) \
            or len(old) != len(new) or len(new) != len(ctx.floats):
        return [("breaking", "", old, new)]
    found = []
    for index, (old_value, new_value, truth_bits) in enumerate(zip(old, new, ctx.floats)):
        if _same(old_value, new_value) or (old_value is None and new_value is None):
            continue
        truth = _float(truth_bits)
        if _float_exact(new_value, truth_bits) and not _float_exact(old_value, truth_bits):
            cls = "#1-float"
        elif (math.isfinite(truth) and isinstance(new_value, (int, float))
              and isinstance(old_value, (int, float))
              and abs(new_value - truth) < abs(old_value - truth)):
            cls = "#1-float"
        else:
            cls = "breaking"
        found.append((cls, f"[{index}]", old_value, f"{new_value!r} true={truth!r}"))
    return found


def compare_record(old: dict, new: dict, ctx: Context | None):
    """[(class, field, old, new)] for one record as one consumer saw it."""
    old_error = ERROR_KEYS & old.keys()
    new_error = ERROR_KEYS & new.keys()
    if old_error or new_error:
        if _same(old, new):
            return []
        if old_error and not new_error and ctx is not None and (
                (ctx.invalid_utf8 and _flatten(new).get("input.text") == ctx.text)
                # the checker decodes the whole file, so one old line that is
                # not UTF-8 makes every later read of the old log fail
                or (old.get("error") == "not UTF-8" and ctx.earlier_invalid_utf8)):
            return [("escape-fix", "error", old, "decoded")]
        return [("breaking", "error", old, new)]
    old_flat, new_flat = _flatten(old), _flatten(new)
    found = []
    for key in sorted(old_flat.keys() | new_flat.keys()):
        if key not in old_flat:
            found.append(("ignorable-new-key", key, None, new_flat[key]))
        elif key not in new_flat:
            found.append(("breaking", key, old_flat[key], None))
        elif _same(old_flat[key], new_flat[key]):
            continue
        elif key in FLOAT_FIELDS:
            found += [(cls, key + sub, o, n) for cls, sub, o, n in
                      _classify_floats(old_flat[key], new_flat[key], ctx)]
        elif (key in ("where", "src", "w") and ctx is not None and ctx.path == "tilde2"
              and old_flat[key] is None
              and new_flat[key] == getattr(ctx, {"w": "where"}.get(key, key))):
            found.append(("fix-#2", key, None, new_flat[key]))
        elif key == "input.text" and ctx is not None:
            cls = "escape-fix" if new_flat[key] == ctx.text and old_flat[key] != ctx.text else "breaking"
            found.append((cls, key, old_flat[key], new_flat[key]))
        else:
            found.append(("breaking", key, old_flat[key], new_flat[key]))
    return found


def compare(consumer: str, old_outputs, new_outputs, contexts):
    """contexts[i] is the Context of record i (None for hello)."""
    if len(old_outputs) != len(new_outputs):
        found = [("breaking", "record-count" if not any("jq-error" in o for o in new_outputs) else "parse",
                  len(old_outputs), f"{len(new_outputs)} {new_outputs[0] if len(new_outputs) == 1 else ''}")]
        return [(cls, consumer, field, None, o, n) for cls, field, o, n in found]
    result = []
    for index, (old, new) in enumerate(zip(old_outputs, new_outputs)):
        ctx = contexts[index] if index < len(contexts) else None
        for cls, field, o, n in compare_record(old, new, ctx):
            result.append((cls, consumer, field, index, o, n))
    return result


def _record(diffs) -> None:
    for cls, consumer, field, index, old, new in diffs:
        base_field = re.sub(r"\[\d+\]$", "", field)
        key = (cls, consumer, base_field)
        STATS["classes"][key] += 1
        STATS["examples"].setdefault(key, f"rec={index} old={str(old)[:60]} new={str(new)[:80]}")


def _inject(line: str) -> str:
    line = line.replace("{", '{"%s":{"k":[1,"s",null]},' % UNKNOWN, 1)
    return line.replace('"input":{', '"input":{"%s":0,' % UNKNOWN, 1)


def _strip_unknown(outputs: list[dict]) -> list[dict]:
    stripped = []
    for output in outputs:
        output = dict(output)
        output.pop(UNKNOWN, None)
        if isinstance(output.get("input"), dict):
            output["input"] = {k: v for k, v in output["input"].items() if k != UNKNOWN}
        stripped.append(output)
    return stripped


# --- the differential ---------------------------------------------------

_no_shrink = os.environ.get("PBT_004_NO_SHRINK")
_phases = settings(phases=[Phase.explicit, Phase.reuse, Phase.generate]) if _no_shrink else (lambda f: f)


@_phases
@given(batch=st.lists(programs, min_size=2, max_size=8))
def test_consumers_read_both_refs_alike(batch, server):
    source, snapshot_lines, places = build(batch)
    runs = {side: helpers.run(side, source) for side in ("old", "new")}
    STATS["runs"] += 2
    STATS["programs"] += len(batch)
    for side, result in runs.items():
        assert result.returncode == 0, f"{side} gforth exit {result.returncode}: {result.stderr[-400:]}"
    truth = true_floats(runs["old"].stdout, len(batch))
    assert truth == true_floats(runs["new"].stdout, len(batch)), "fp@ reads differ between runs"
    assert truth == [prog.floats for prog in batch], "a float did not land with its bits"
    contexts = [None] + [Context(bits, contract_text(line), not _valid_utf8(line), prog.path, *place)
                         for bits, line, prog, place in zip(truth, snapshot_lines, batch, places)]
    for index in range(2, len(contexts)):
        contexts[index].earlier_invalid_utf8 = any(ctx.invalid_utf8 for ctx in contexts[1:index])
    STATS["snapshots"] += len(batch)

    schemas = {side: helpers.schema(side) for side in runs}
    outputs, violations, unknown_key_failures = {}, [], []
    for side, result in runs.items():
        lines = result.log_lines
        injected = [_inject(line) for line in lines]
        jq_plain, jq_injected = run_jq(lines), run_jq(injected)
        checker_plain = run_checker(lines, schemas[side])
        checker_injected = run_checker(injected, schemas[side])
        stop_plain = checker_check(_tmp_log(lines), schemas[side], True)
        stop_injected = checker_check(_tmp_log(injected), schemas[side], True)
        server_plain, plain_violations = run_server(lines, server)
        server_injected, injected_violations = run_server(injected, server)
        violations += plain_violations + injected_violations
        for consumer, plain, with_key in [("jq", jq_plain, jq_injected),
                                          ("checker", checker_plain, checker_injected),
                                          ("checker-stop", [stop_plain], [stop_injected]),
                                          ("server", server_plain, _strip_unknown(server_injected))]:
            if not _same(plain, with_key):
                unknown_key_failures.append(f"unknown-key consumer={consumer} side={side}: "
                                            f"{str(plain)[:120]} != {str(with_key)[:120]}")
        outputs[side] = {"jq": jq_plain, "checker": checker_plain, "server": server_plain}

    diffs = []
    for consumer in ("jq", "checker", "server"):
        diffs += compare(consumer, outputs["old"][consumer], outputs["new"][consumer], contexts)
    _record(diffs)
    breaking = [f"breaking consumer={c} field={f} rec={i} old={str(o)[:80]} new={str(n)[:100]}"
                for cls, c, f, i, o, n in diffs if cls == "breaking"]
    failures = breaking[:12] + unknown_key_failures + violations
    assert not failures, "\n".join(failures)


def _valid_utf8(raw: bytes) -> bool:
    try:
        raw.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


_TMP = tempfile.mkdtemp(prefix="gfi-004-chk-")


def _tmp_log(lines: list[str]) -> Path:
    path = Path(_TMP) / "stop.jsonl"
    path.write_bytes(_log_bytes(lines))
    return path


def test_zz_volume():
    """Gate 2 asks for at least 200 programs (runs after the differential)."""
    assert STATS["programs"] >= 200, f"only {STATS['programs']} programs ran"


# --- version stop (CONSUMERS.org consumer obligation 2) -------------------

def test_version_stop():
    """The checker as it is today (expects contract 1.1) refuses a producer
    that announces no contract, and accepts one announcing 1.1.  Expected:
    18ebe2d refused, fc283da accepted.  The differential above runs with
    the stop bypassed, so this asymmetry is not counted as a difference."""
    messages = {}
    for side in ("old", "new"):
        result = helpers.run(side, "log-on 1 2 .stacks log-off")
        out = checker_check(_tmp_log(result.log_lines), helpers.schema(side), True)
        messages[side] = out.get("stopped", "accepted")
    STATS.setdefault("gate_lines", []).append(
        f"version stop (checker expects {checker.EXPECTED_CONTRACT}): old -> {messages['old']}; "
        f"new -> {messages['new']}")
    assert messages["old"].startswith("contract (none) from the producer"), messages["old"]
    assert messages["new"] == "accepted", f"version stop on new: {messages['new']}"


# --- default location (gate 4, the moved-log plant) -----------------------

DEFAULT_PROGRAM = "log-on 1 2 .stacks log-off"
OLD_DEFAULT = "state/sicpminus/stacks.jsonl"         # 18ebe2d, where today's consumers look
CONTRACT_DEFAULT = "state/gforth-inspect/stacks.jsonl"  # RELEASING.org "Log location"


class DefaultLocationBreak(AssertionError):
    pass


def _jq_on(raw: bytes) -> list[dict]:
    return run_jq(raw.decode("utf-8", "surrogateescape").splitlines())


def test_default_location_old_precondition():
    written = [path for path in helpers.run_default_location("old", DEFAULT_PROGRAM)
               if path.startswith("state/")]
    assert written == [OLD_DEFAULT], f"18ebe2d wrote {written}"


def test_default_location_contract():
    written = helpers.run_default_location("new", DEFAULT_PROGRAM)
    STATS.setdefault("gate_lines", []).append(
        f"default location, GFORTH_INSPECT_LOG_DIR unset: new wrote {list(written)}")
    if not written.get(CONTRACT_DEFAULT):
        raise AssertionError(f"breaking default-location: documented default {CONTRACT_DEFAULT} "
                             f"is empty; written: {list(written)}")
    assert _jq_on(written[CONTRACT_DEFAULT])[-1]["d"] == [1, 2]


@pytest.mark.xfail(strict=True, raises=DefaultLocationBreak,
                   reason="breaking default-location: harden 9b92746 moved the default from "
                          "sicpminus/ to gforth-inspect/ (004 verdict); strict, so restoring "
                          "the old default turns this XPASS and red")
def test_default_location_reference_consumer():
    old_written = helpers.run_default_location("old", DEFAULT_PROGRAM)
    new_written = helpers.run_default_location("new", DEFAULT_PROGRAM)
    if not new_written.get(OLD_DEFAULT):
        raise DefaultLocationBreak(f"breaking default-location: {OLD_DEFAULT} (18ebe2d's default, "
                                   f"where today's consumers look) is empty; new wrote {list(new_written)}")
    old_jq, new_jq = _jq_on(old_written[OLD_DEFAULT]), _jq_on(new_written[OLD_DEFAULT])
    assert _same(old_jq, new_jq)
