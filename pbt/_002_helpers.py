"""Helpers for experiment 002 (escaping): generate input lines, run them, check them.

Why there is a bytes-level runner here and not gforth_run.run():
gforth_run.run() decodes stacks.jsonl and splits it with str.splitlines(),
which also breaks on U+0085, U+2028, U+2029, \\x1c-\\x1e, \\x0b and \\x0c.
A record whose input.text holds U+2028 (valid UTF-8, legal raw in JSON)
would come back as two "lines".  That is a runner artefact, not an
inspector fault, so 002 reads the log as bytes and splits on b"\\n" only.
It reuses gforth_run.inspect_source() so INSPECT_FS / INSPECT_REF apply the
same way, and the same isolation (own XDG_STATE_HOME, relative file names).

Line-end facts about gforth 0.7.3 included files (probed, see the Log):
LF, CR and CRLF each end a line (CRLF counts once, LF CR twice).  No other
byte does.  So generated text never holds LF or CR; test_002 models CR
separately with fixed cases.  No per-line length limit was found up to
128 MiB.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from hypothesis import strategies as st

import gforth_run

LINE_ENDS = (0x0A, 0x0D)
CONTROL_BYTES = [b for b in range(0x20) if b not in LINE_ENDS]
CLASSES = ("ascii", "controls", "utf8", "invalid", "long")


# --- running -----------------------------------------------------------


@dataclass
class ByteRun:
    returncode: int
    stderr: bytes
    log_lines: list[bytes]  # raw stacks.jsonl lines, split on b"\n" only


def run_bytes(program: bytes, engine: str = "gforth", timeout: float = 60.0) -> ByteRun:
    """Same isolation as gforth_run.run(), but bytes in and bytes out."""
    if engine not in gforth_run.ENGINES:
        raise ValueError(engine)
    inspect_fs, _ = gforth_run.inspect_source()
    with tempfile.TemporaryDirectory(prefix="gfi-002-") as tmp:
        tmp_path = Path(tmp)
        (tmp_path / "prog.fs").write_bytes(program + b"\nbye\n")
        (tmp_path / "inspect.fs").write_bytes(inspect_fs.read_bytes())
        env = {
            **os.environ,
            "XDG_STATE_HOME": str(tmp_path / "state"),
            "GFORTH_INSPECT_LOG_DIR": str(tmp_path / "state" / "gforth-inspect"),
        }
        proc = subprocess.run(
            [engine, "inspect.fs", "prog.fs"],
            cwd=tmp_path, capture_output=True, env=env, timeout=timeout,
            stdin=subprocess.DEVNULL,
        )
        logs = sorted((tmp_path / "state").glob("*/stacks.jsonl"))
        if len(logs) > 1:
            raise RuntimeError(f"more than one stacks.jsonl: {[p.parent.name for p in logs]}")
        raw = logs[0].read_bytes() if logs else b""
        lines = raw.split(b"\n")
        if lines and lines[-1] == b"":
            lines.pop()
        return ByteRun(proc.returncode, proc.stderr, lines)


# --- building lines ----------------------------------------------------


@dataclass(frozen=True)
class Case:
    """One source line: optional text before .stacks, optional comment after."""

    line_class: str
    position: str  # comment | string | paren | string+comment | paren+comment
    before: bytes
    after: bytes

    def prefix(self) -> bytes:
        if self.position.startswith("string"):
            return b's" ' + self.before + b'" 2drop '
        if self.position.startswith("paren"):
            return b"( " + self.before + b" ) "
        return b""

    def suffix(self) -> bytes:
        return b" \\ " + self.after if self.position.endswith("comment") else b""

    def line(self) -> bytes:
        return self.prefix() + b".stacks" + self.suffix()

    def expected_in(self) -> int:
        """>IN at the snapshot: just past .stacks, plus its one delimiter if any."""
        return len(self.prefix()) + len(b".stacks") + (1 if self.suffix() else 0)

    def expected_text(self, oracle: str, errors: str = "strict") -> str:
        return ORACLES[oracle](self.line(), errors)


# --- the two text oracles ------------------------------------------------
# "legacy": the experiment's pre-registered oracle, which is what json-str
#   did at harden@b1c162e: bytes < 0x20 become a space, every other byte is
#   copied raw (so non-UTF-8 source gives a non-UTF-8 record).
# "contract": contract/stacks-log.org from inspect 0.1.0 on: control
#   characters are escaped (so they decode back to themselves) and each byte
#   that does not start a valid UTF-8 sequence becomes one U+FFFD.
# check_run picks the oracle from the hello record: 0.1.0 added "inspect".


def legacy_text(line: bytes, errors: str = "strict") -> str:
    return bytes(0x20 if byte < 0x20 else byte for byte in line).decode("utf-8", errors)


def _utf8_sequence_length(line: bytes, index: int) -> int:
    lead = line[index]
    length = 2 if 0xC2 <= lead < 0xE0 else 3 if 0xE0 <= lead < 0xF0 else 4 if 0xF0 <= lead < 0xF5 else 0
    if length == 0 or index + length > len(line):
        return 0
    try:
        line[index:index + length].decode("utf-8")  # strict: no overlong, surrogate, > U+10FFFF
    except UnicodeDecodeError:
        return 0
    return length


def contract_text(line: bytes, errors: str = "strict") -> str:
    characters, index = [], 0
    while index < len(line):
        if line[index] < 0x80:
            characters.append(chr(line[index]))
            index += 1
            continue
        length = _utf8_sequence_length(line, index)
        if length:
            characters.append(line[index:index + length].decode("utf-8"))
            index += length
        else:
            characters.append("\ufffd")
            index += 1
    return "".join(characters)


ORACLES = {"legacy": legacy_text, "contract": contract_text}


def oracle_for(hello: bytes) -> str:
    return "contract" if "inspect" in json.loads(hello.decode("utf-8")) else "legacy"


def program_for(cases: list[Case]) -> bytes:
    """log-on on line 1, then one .stacks line per case, then log-off."""
    return b"log-on\n" + b"".join(case.line() + b"\n" for case in cases) + b"log-off"


# --- checking ----------------------------------------------------------


class CaseFailure(AssertionError):
    pass


def check_record(case: Case, raw_record: bytes, expected_line_number: int, validator,
                 oracle: str, errors: str = "strict") -> None:
    """Every property of 002 for one snapshot line.  Raises CaseFailure tagged [kind].

    errors="surrogateescape" is only for the census, to ask whether a line
    that is not UTF-8 is otherwise right; the properties use "strict"."""
    try:
        decoded = raw_record.decode("utf-8", errors)
    except UnicodeDecodeError as error:
        raise CaseFailure(f"[utf8] snapshot line is not UTF-8: {error}") from None
    try:
        record = json.loads(decoded)  # strict=True is the default
    except json.JSONDecodeError as error:
        raise CaseFailure(f"[json] json.loads failed: {error}") from None
    schema_errors = sorted(validator.iter_errors(record), key=str)
    if schema_errors:
        raise CaseFailure(f"[schema] {schema_errors[0].message}")
    if record.get("event") != "snapshot":
        raise CaseFailure(f"[order] expected a snapshot, got {record.get('event')!r}")
    source_input = record["input"]
    if source_input["line"] != expected_line_number:
        raise CaseFailure(f"[order] input.line {source_input['line']} != {expected_line_number}")
    expected_text = case.expected_text(oracle, errors)
    if source_input["text"] != expected_text:
        raise CaseFailure(f"[text] {source_input['text']!r} != {expected_text!r}")
    if source_input["in"] != case.expected_in():
        raise CaseFailure(f"[in] input.in {source_input['in']} != {case.expected_in()}")


def check_run(cases: list[Case], result: ByteRun, validator,
              errors: str = "strict") -> list[tuple[Case, str | None]]:
    """(case, None) for a pass, (case, message) for a fail; raises if the run itself broke."""
    if result.returncode != 0:
        raise CaseFailure(f"[run] gforth exited {result.returncode}: {result.stderr[-400:]!r}")
    if len(result.log_lines) != len(cases) + 1:
        raise CaseFailure(f"[run] {len(result.log_lines)} records for {len(cases)} lines (+hello)")
    hello = result.log_lines[0]
    if not hello.startswith(b'{"v":1,"event":"hello"'):
        raise CaseFailure(f"[run] first record is not hello: {hello[:80]!r}")
    oracle = oracle_for(hello)
    outcomes = []
    for index, case in enumerate(cases):
        try:
            check_record(case, result.log_lines[index + 1], index + 2, validator, oracle, errors)
            outcomes.append((case, None))
        except CaseFailure as failure:
            outcomes.append((case, str(failure)))
    return outcomes


def reproducer(case: Case) -> str:
    """A one-line shell reproducer: printf the case into case.fs and load it."""
    program = b"log-on\n" + case.line() + b"\nlog-off\nbye\n"
    escaped = "".join(
        chr(byte) if 0x20 <= byte < 0x7F and chr(byte) not in "\\'%" else
        "%%" if byte == 0x25 else f"\\{byte:03o}"
        for byte in program
    )
    return (f"git show REF:env/inspect.fs > inspect.fs && printf '{escaped}' > case.fs && XDG_STATE_HOME=st GFORTH_INSPECT_LOG_DIR=st/gforth-inspect"
            " gforth inspect.fs case.fs >/dev/null && cat st/*/stacks.jsonl")


# --- generating --------------------------------------------------------

POSITIONS = ("comment", "string", "paren", "string+comment", "paren+comment")


def _printable_ascii() -> st.SearchStrategy[int]:
    # bias toward the two bytes json-str must escape, and DEL
    return st.one_of(
        st.sampled_from([ord('"'), ord("\\"), 0x7F]),
        st.integers(0x20, 0x7E),
    )


def _bytes_from(byte_strategy, max_size=40) -> st.SearchStrategy[bytes]:
    return st.lists(byte_strategy, max_size=max_size).map(bytes)


def _ascii() -> st.SearchStrategy[bytes]:
    return _bytes_from(_printable_ascii())


def _with_forced(body: st.SearchStrategy[list], forced: st.SearchStrategy) -> st.SearchStrategy[list]:
    """body with one element of `forced` inserted at a drawn index (no filter)."""
    return st.tuples(body, forced, st.integers(0, 1 << 16)).map(
        lambda parts: parts[0][: parts[2] % (len(parts[0]) + 1)] + [parts[1]]
        + parts[0][parts[2] % (len(parts[0]) + 1):]
    )


def _controls() -> st.SearchStrategy[bytes]:
    body = st.lists(st.one_of(st.sampled_from(CONTROL_BYTES), _printable_ascii()), max_size=40)
    return st.one_of(
        _with_forced(body, st.sampled_from(CONTROL_BYTES)).map(bytes),
        st.just(bytes(CONTROL_BYTES)),
    )


def _utf8() -> st.SearchStrategy[bytes]:
    non_ascii = st.characters(min_codepoint=0x80, exclude_categories=("Cs",))
    astral = st.characters(min_codepoint=0x10000, exclude_categories=("Cs",))
    line_like = st.sampled_from(["\u0085", "\u2028", "\u2029", "\ufeff", "\ufffd"])
    ascii_char = st.characters(min_codepoint=0x20, max_codepoint=0x7F)
    body = st.lists(st.one_of(non_ascii, astral, line_like, ascii_char), max_size=30)
    return _with_forced(body, st.one_of(non_ascii, astral, line_like)).map(
        lambda chars: "".join(chars).encode("utf-8")
    )


INVALID_SEQUENCES = [
    b"\x80", b"\xbf", b"\xc0\x80", b"\xc1\xbf", b"\xe0\x80\x80", b"\xed\xa0\x80",
    b"\xf4\x90\x80\x80", b"\xf5", b"\xfe", b"\xff", b"\xc3", b"\xe2\x82", b"\xf0\x9f\x98",
]


def _invalid() -> st.SearchStrategy[bytes]:
    pieces = st.one_of(
        st.integers(0x80, 0xFF).map(lambda byte: bytes([byte])),
        st.sampled_from(INVALID_SEQUENCES),
        _printable_ascii().map(lambda byte: bytes([byte])),
        st.sampled_from(["é", "€", "😀"]).map(lambda char: char.encode()),
    )
    # the forced piece is invalid on its own; the filter only catches the
    # rare draw where a lone lead byte pairs up with a lone continuation
    forced = st.sampled_from(INVALID_SEQUENCES)
    return _with_forced(st.lists(pieces, max_size=20), forced).map(b"".join).filter(_not_utf8)


def _not_utf8(chunk: bytes) -> bool:
    try:
        chunk.decode("utf-8")
    except UnicodeDecodeError:
        return True
    return False


def _long() -> st.SearchStrategy[bytes]:
    # Hypothesis cannot draw 64 KiB of entropy per line, so a drawn valid
    # chunk is repeated up to the drawn length (4 KiB .. 64 KiB)
    chunk = st.one_of(_ascii().map(lambda text: text or b"x"), _controls(), _utf8())
    return st.tuples(chunk, st.integers(4096, 65536)).map(
        lambda pair: (pair[0] * (pair[1] // len(pair[0]) + 1))[: pair[1]]
    ).map(_trim_partial_utf8)


def _trim_partial_utf8(chunk: bytes) -> bytes:
    # cutting a repeated chunk can split a multi-byte character at the end
    while chunk and _not_utf8(chunk):
        chunk = chunk[:-1]
    return chunk


TEXT_BY_CLASS = {
    "ascii": _ascii, "controls": _controls, "utf8": _utf8,
    "invalid": _invalid, "long": _long,
}


REPLACE_BEFORE = {"string": (ord('"'), ord("'")), "paren": (ord(")"), ord("]"))}


@st.composite
def cases(draw, line_class: str) -> Case:
    """A Case of one class.  Text before .stacks cannot hold the byte that
    ends its s\" or ( ), so that byte is replaced, not filtered (a filter
    rejects most long lines)."""
    text = TEXT_BY_CLASS[line_class]()
    position = draw(st.sampled_from(POSITIONS))
    kind = position.split("+")[0]
    before = b""
    if kind in REPLACE_BEFORE:
        forbidden, replacement = REPLACE_BEFORE[kind]
        before = draw(text).replace(bytes([forbidden]), bytes([replacement]))
    after = draw(text) if position.endswith("comment") else b""
    return Case(line_class, position, before, after)


def batches(line_class: str) -> st.SearchStrategy[list[Case]]:
    max_lines = 4 if line_class == "long" else 20
    return st.lists(cases(line_class), min_size=1, max_size=max_lines)


def mixed_batches() -> st.SearchStrategy[list[Case]]:
    return st.lists(st.sampled_from(CLASSES).flatmap(cases), min_size=1, max_size=20)


# --- calibration verdict -------------------------------------------------


def calibration_verdict(junit_path: str, must_fail: dict[str, str], must_pass: list[str]) -> int:
    """0 only if each test in must_fail failed with a message containing its
    marker, and each test in must_pass passed.  Prints what it saw."""
    import xml.etree.ElementTree as ElementTree

    seen = {}
    for testcase in ElementTree.parse(junit_path).getroot().iter("testcase"):
        failure = testcase.find("failure")
        if failure is None:
            failure = testcase.find("error")
        seen[testcase.get("name")] = None if failure is None else (failure.get("message") or "") + (failure.text or "")
    verdict = 0
    for name, marker in must_fail.items():
        message = seen.get(name, "<not run>")
        if message is None or message == "<not run>" or marker not in message:
            print(f"NOT RED as expected: {name} (want {marker!r}): {str(message)[:160]!r}")
            verdict = 1
        else:
            first = next(line for line in message.splitlines() if marker in line)
            print(f"red as expected: {name}: {first.strip()[:140]}")
    for name in must_pass:
        if name not in seen or seen[name] is not None:
            print(f"NOT GREEN as expected: {name}: {str(seen.get(name, '<not run>'))[:160]!r}")
            verdict = 1
        else:
            print(f"green as expected: {name}")
    return verdict
