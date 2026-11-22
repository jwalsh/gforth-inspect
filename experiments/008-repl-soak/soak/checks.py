"""The goal checks: per session (G1 G2 G3 G6 G7), across sessions (the
xref, G6), and on the user's real files (the leak guard, G4).

A session is checked from what it left: call.json (its manifest entry,
keyed by xrid), transcript.jsonl (every line typed, with the oracle's
answers), files.jsonl (every file linked into its sandbox) and its log.
The same function runs after every line (on the tail), when the session
ends, and in the hourly xref (on everything), so the three cannot disagree.

Pairing.  Each transcript line expects exactly one hello if it turned
logging on, then one snapshot per oracle marker it printed, in order.  The
log must hold exactly that sequence: a missing, extra, duplicated or
reordered record breaks the pairing (G2), and each paired snapshot must
equal its marker (G3).  Every snapshot carries the session's xrid as its
id (RD-2).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from pathlib import Path

from . import assets, config

ABSOLUTE_HINTS = ("/Users/", "/home/", "/var/folders", "/private/", "/tmp/", "/opt/")


def validator_for(schema_path: Path):
    import jsonschema
    schema = json.loads(schema_path.read_text())
    return jsonschema.Draft202012Validator(schema)


def violation(goal: str, xrid: str | None, detail: str) -> dict:
    return {"goal": goal, "xrid": xrid, "detail": detail[:400], "t": time.time()}


def same_json(left, right) -> bool:
    """Equal as JSON values; numbers compare by value (jq prints -0.0 as -0)."""
    if isinstance(left, bool) or isinstance(right, bool):
        return left is right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        if isinstance(left, int) and isinstance(right, int):
            return left == right
        return float(left) == float(right)
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(same_json(a, b) for a, b in zip(left, right))
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(same_json(left[key], right[key]) for key in left)
    return left == right


def read_jsonl(path: Path) -> list:
    if not path.exists():
        return []
    items = []
    for line in path.read_bytes().split(b"\n"):
        if line.strip():
            try:
                items.append(json.loads(line))
            except ValueError:
                pass  # a line the harness was writing when it stopped
    return items


def split_log(raw: bytes) -> tuple[list[bytes], bytes]:
    """(complete lines, trailing partial line).  Split on LF bytes only."""
    parts = raw.split(b"\n")
    return [part for part in parts[:-1]], parts[-1]


def private_markers() -> list[str]:
    home = os.environ.get("HOME", "")
    markers = [home, Path(home).name, os.environ.get("TMPDIR", "")]
    try:
        import pwd
        markers.append(pwd.getpwuid(os.getuid()).pw_name)
    except (ImportError, KeyError):
        pass
    return [marker.rstrip("/") for marker in markers if marker and len(marker) > 2]


def strings_in(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from strings_in(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from strings_in(item)


class FileTable:
    """The files a session linked, by sandbox-relative path, with their copies' lines."""

    def __init__(self, entries: list, pool):
        self.entries = {entry["path"]: entry for entry in entries}
        self.pool = pool
        self.lines: dict = {}

    def line(self, path: str, number: int) -> str | None:
        entry = self.entries.get(path)
        if entry is None:
            return None
        if path not in self.lines:
            self.lines[path] = self.pool.get(entry["copy_blob"]).split(b"\n")
        lines = self.lines[path]
        if not 1 <= number <= len(lines):
            return None
        # json-chars turns each invalid UTF-8 byte into U+FFFD
        return lines[number - 1].decode("utf-8", "replace")


class SessionAudit:
    """Checks one session's log against its transcript.  Feed it with
    `entries` (transcript lines) and `lines` (log lines); `final` says the
    session has ended, so missing or extra records are counted."""

    def __init__(self, call: dict, validator, files: FileTable):
        self.call, self.validator, self.files = call, validator, files
        self.xrid = call["xrid"]
        self.versions = {blob: tuple(pair) for blob, pair in call["inspect_versions"].items()}
        self.private = private_markers()
        self.violations: list = []
        self.cursor = 0         # records consumed
        self.entry_index = 0    # transcript lines consumed
        self.parsed: list = []  # records parsed so far (None for a line that is not a record)
        self.current_blob = None
        self.seen_inspect: list = []
        self.stats = {"records": 0, "snapshots": 0, "hellos": 0, "points": 0, "g1_bad": 0}

    def _flag(self, goal: str, detail: str) -> None:
        self.violations.append(violation(goal, self.xrid, detail))

    def _parse(self, raw: bytes, index: int):
        try:
            record = json.loads(raw.decode("utf-8"), parse_constant=_reject)
        except (UnicodeDecodeError, ValueError) as error:
            self.stats["g1_bad"] += 1
            self._flag("G1", f"line {index + 1} is not strict JSON ({type(error).__name__}): {raw[:120]!r}")
            return None
        if not isinstance(record, dict):
            self._flag("G1", f"line {index + 1} is not an object")
            return None
        errors = list(self.validator.iter_errors(record))
        if errors:
            self.stats["g1_bad"] += 1
            self._flag("G1", f"line {index + 1} fails the schema: {errors[0].message[:160]}")
            return None
        named = [record.get("src"), (record.get("input") or {}).get("file")]
        for text in strings_in(record):
            if (text in named and text.startswith("/")) or any(hint in text for hint in ABSOLUTE_HINTS) \
                    or any(marker in text for marker in self.private):
                self._flag("G7", f"line {index + 1} holds a path or name: {text[:120]!r}")
                break
        return record

    def feed(self, entries: list, lines: list[bytes], final: bool = False, rest: bool = False) -> None:
        """final: the session has ended.  rest: the log is at rest for every
        entry given (the driver checks after each line), so a record that is
        not there is missing; otherwise the audit waits for the log."""
        while len(self.parsed) < len(lines):
            index = len(self.parsed)
            self.parsed.append(self._parse(lines[index], index))
        self.stats["records"] = len(self.parsed)
        # A log shared with another session (calibration only) holds both
        # sessions' records: pair this session's own snapshots, by id, and
        # leave the sharing itself to the xref (G6).
        shared = self.call.get("log_mode") == "shared"
        sequence = [record for record in self.parsed if record and record.get("event") == "snapshot"
                    and record.get("id") == self.xrid] if shared else self.parsed
        while self.entry_index < len(entries):
            entry = entries[self.entry_index]
            hello = bool(entry.get("hello")) and not shared
            want = (1 if hello else 0) + len(entry.get("markers", []))
            if self.cursor + want > len(sequence) and not (final or rest):
                return  # the log has not caught up yet (live audit)
            self.entry_index += 1
            if entry.get("inspect"):
                self._inspect(entry)
            got = sequence[self.cursor:self.cursor + want]
            self.cursor += len(got)
            if len(got) < want:
                self._flag("G2", f"line {entry['n']} {entry['text'][:60]!r}: {want - len(got)} of {want} records missing")
            position = 0
            if hello and got:
                self._hello(entry, got[0])
                position = 1
            for marker, record in zip(entry.get("markers", []), got[position:]):
                self._snapshot(entry, marker, record)
        if final and self.cursor < len(sequence):
            extra = len(sequence) - self.cursor
            self._flag("G2", f"{extra} records in the log that no typed line accounts for "
                             f"(first: {json.dumps(sequence[self.cursor])[:120]})")
            self.cursor = len(sequence)

    def _inspect(self, entry: dict) -> None:
        blob = entry["inspect"]["blob"]
        plan = self.call["inspect_plan"]
        position = len(self.seen_inspect)
        if position >= len(plan) or plan[position]["blob"] != blob:
            want = plan[position]["blob"][:12] if position < len(plan) else "(none)"
            self._flag("G6", f"line {entry['n']} loaded inspect.fs blob {blob[:12]}, the manifest says {want}")
        self.seen_inspect.append(blob)
        self.current_blob = blob

    def _hello(self, entry: dict, record) -> None:
        if record is None:
            return
        if record.get("event") != "hello":
            self._flag("G2", f"line {entry['n']} {entry['text'][:40]!r}: expected hello, got {record.get('event')}")
            return
        self.stats["hellos"] += 1
        want = self.versions.get(self.current_blob)
        if want is None:
            self._flag("G6", f"hello at line {entry['n']} with no inspect.fs loaded from the manifest")
        elif (record.get("inspect"), record.get("contract")) != want:
            self._flag("G6", f"hello says inspect {record.get('inspect')} contract {record.get('contract')}; "
                             f"blob {self.current_blob[:12]} defines {want[0]} / {want[1]}")

    def _snapshot(self, entry: dict, marker: list, record) -> None:
        self.stats["points"] += 1
        if record is None:
            return
        if record.get("event") != "snapshot":
            self._flag("G2", f"line {entry['n']} {entry['text'][:40]!r}: expected a snapshot, got {record.get('event')}")
            return
        self.stats["snapshots"] += 1
        depth, fdepth, cells = marker[0], marker[1], marker[2]
        data, floats = record.get("data", []), record.get("float", [])
        if len(data) != depth or data != cells:
            self._flag("G3", f"line {entry['n']} {entry['text'][:50]!r}: data {data[:8]}..({len(data)}) "
                             f"where the REPL says depth {depth}, .s {cells[:8]}..")
        if len(floats) != fdepth:
            self._flag("G3", f"line {entry['n']} {entry['text'][:50]!r}: {len(floats)} floats where fdepth is {fdepth}")
        if record.get("id") != self.xrid:
            self._flag("G6", f"line {entry['n']}: snapshot id {record.get('id')!r}, the session's xrid is {self.xrid}")
        source = record.get("input", {})
        name, number, text = source.get("file"), source.get("line"), source.get("text")
        if name == "":
            if text != entry["text"]:
                self._flag("G6", f"line {entry['n']}: input.text {text[:60]!r} is not the typed line {entry['text'][:60]!r}")
        elif isinstance(name, str) and name.startswith("/"):
            self._flag("G6", f"line {entry['n']}: input.file is absolute, not in the sandbox: {name[:80]!r}")
        else:
            copy_line = self.files.line(name, number)
            if copy_line is None:
                self._flag("G6", f"line {entry['n']}: input.file {name!r}:{number} is no file this session linked")
            elif copy_line != text:
                self._flag("G6", f"line {entry['n']}: input.text {text[:60]!r} is not line {number} of {name}: {copy_line[:60]!r}")


def _reject(name: str):
    raise ValueError(name)


def load_session(session_dir: Path, pool, validator):
    call = json.loads((session_dir / "call.json").read_text())
    files = FileTable(read_jsonl(session_dir / "files.jsonl"), pool)
    return call, files, SessionAudit(call, validator, files)


def audit_session(session_dir: Path, pool, validator, final: bool) -> tuple[list, dict]:
    """The whole session from disk: (violations, stats)."""
    call, files, audit = load_session(session_dir, pool, validator)
    entries = read_jsonl(session_dir / "transcript.jsonl")
    log = Path(call["log_path"])
    raw = log.read_bytes() if log.exists() else b""
    lines, partial = split_log(raw)
    audit.feed(entries, lines, final=final)
    if final and partial:
        audit._flag("G1", f"the log ends in a partial line at rest: {partial[:120]!r}")
    # the copies a session loaded are the originals outside their probe lines
    for entry in files.entries.values():
        if not entry.get("copy_ok", False):
            audit._flag("G6", f"{entry['path']}: copy differs from its origin outside the probe lines")
    return audit.violations, audit.stats


def copy_matches(pool, entry: dict) -> bool:
    def lines(data: bytes) -> list:
        return (data[:-1] if data.endswith(b"\n") else data).split(b"\n")
    original = lines(pool.get(entry["orig_blob"]))
    copy = lines(pool.get(entry["copy_blob"]))
    changed = set(entry.get("modified", []))
    for number, line in enumerate(copy, 1):
        if number in changed:
            continue
        if number > len(original) or original[number - 1] != line:
            return False
    return True


# --- across sessions: the xref -------------------------------------------


def xref(run_dir: Path, pool, validator, live_xrids: set, cache: dict | None = None) -> tuple[list, dict]:
    """Every record -> one manifest entry; every manifest entry -> its records.
    `cache` keeps the audit of an ended session whose files have not changed."""
    cache = {} if cache is None else cache
    violations: list = []
    sessions = sorted(path for path in (run_dir / "sessions").glob("*") if (path / "call.json").exists())
    calls = {}
    claims: dict = {}
    for session_dir in sessions:
        call = json.loads((session_dir / "call.json").read_text())
        calls[call["xrid"]] = (call, session_dir)
        claims.setdefault(os.path.realpath(call["log_path"]), []).append(call["xrid"])
    for log, owners in claims.items():
        if len(owners) > 1:
            violations.append(violation("G6", owners[0], f"one log claimed by {len(owners)} sessions: {', '.join(owners)}"))
    totals = {"sessions": len(calls), "records": 0, "logs": 0}
    seen_ids: dict = {}
    for xrid, (call, session_dir) in calls.items():
        final = xrid not in live_xrids
        log_path, transcript = Path(call["log_path"]), session_dir / "transcript.jsonl"
        key = (log_path.stat().st_size if log_path.exists() else -1,
               transcript.stat().st_size if transcript.exists() else -1, final)
        if final and cache.get(xrid, (None,))[0] == key:
            found, stats = cache[xrid][1]
        else:
            found, stats = audit_session(session_dir, pool, validator, final=final)
            if final:
                cache[xrid] = (key, (found, stats))
        violations += found
        totals["records"] += stats["records"]
        log = Path(call["log_path"])
        if not log.exists():
            if call.get("logged"):
                violations.append(violation("G6", xrid, "manifest entry with no log"))
            continue
        totals["logs"] += 1
        for raw in log.read_bytes().split(b"\n"):
            match = re.search(rb'"id":"((?:[^"\\]|\\.)*)"', raw)
            if match:
                seen_ids.setdefault(match.group(1).decode("utf-8", "replace"), set()).add(xrid)
        # each inspect.fs path must still hold the blob the session last
        # loaded from it (an upgrade reinstalls a path; one still pending has
        # not), or, before any load, the plan's first blob for that path
        expected = {}
        for plan in call["inspect_plan"]:
            expected.setdefault(plan["path"], plan["blob"])
        for entry in read_jsonl(session_dir / "transcript.jsonl"):
            if entry.get("inspect"):
                expected[entry["inspect"]["path"]] = entry["inspect"]["blob"]
        for relative, blob in expected.items():
            path = Path(call["sandbox"]) / relative
            if path.exists() and assets.blob_of(path) != blob:
                violations.append(violation("G6", xrid, f"{relative} in the sandbox is not blob {blob[:12]}"))
    for record_id, holders in seen_ids.items():
        if record_id not in calls:
            violations.append(violation("G6", sorted(holders)[0], f"records with id {record_id!r}: no manifest entry"))
        for holder in holders:
            if holder != record_id:
                violations.append(violation("G6", holder, f"records with id {record_id!r} in the log of {holder}"))
    # logs nobody claims, anywhere in the run's sandboxes
    tmp = Path(json.loads((run_dir / "run.json").read_text())["tmp"])
    for log in tmp.glob("*/**/stacks.jsonl"):
        if "pool" in log.parts:
            continue
        if os.path.realpath(log) not in claims:
            violations.append(violation("G6", None, f"a log no manifest entry claims: {log.relative_to(tmp)}"))
    return violations, totals


# --- G4: the leak guard ---------------------------------------------------


def _digest(path: Path) -> list:
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        return [False, 0, None]
    return [True, len(data), hashlib.sha256(data).hexdigest()]


SOAK_MARKS = re.compile(rb'"id":"s\d+"|gforth-inspect-soak-|soak-o\b|soak-u\d+|soak-[dmtrq]\d+')


class LeakGuard:
    """Hashes the user's real log(s) and ~/.gforth-history, and lists their
    directories, at start, every `period` seconds and at the end.

    A change is judged by its content (owner's ruling, 2026-11-22: the
    course writes the real log itself).  New bytes that carry a soak mark (a
    snapshot id of the soak's xrid form, a soak sandbox path, or a word only
    the soak types) are a G4 violation; any other change is an external
    writer, recorded and reported, but not a violation."""

    def __init__(self, files: list[Path], dirs: list[Path], period: float = 600.0, report=None, external=None):
        self.files, self.dirs, self.period = files, dirs, period
        self.report = report or (lambda item: None)
        self.external = external or (lambda item: None)
        self.baseline = self.snapshot()
        self.last_check = time.time()
        self.checks = 0
        self.changes = 0          # G4: changes a soak session wrote
        self.external_changes = 0  # changes by someone else (the course)
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None

    def snapshot(self) -> dict:
        state = {str(path): _digest(path) for path in self.files}
        for directory in self.dirs:
            try:
                state[f"{directory}/"] = sorted(os.listdir(directory))
            except FileNotFoundError:
                state[f"{directory}/"] = None
        return state

    def check(self) -> list:
        now = self.snapshot()
        found = []
        for key, before in self.baseline.items():
            after = now.get(key)
            if after == before:
                continue
            new = self._new_bytes(key, before, after)
            ours = SOAK_MARKS.search(new)
            detail = (f"{key} changed: {before} -> {after}; {len(new)} new bytes, "
                      + (f"WRITTEN BY A SOAK SESSION ({ours.group(0)[:40]!r})" if ours else "no soak mark in them"))
            item = violation("G4" if ours else "G4-external", None, detail)
            if ours:
                found.append(item)
                self.report(item)
            else:
                self.external_changes += 1
                self.external(item)
        self.checks += 1
        self.changes += len(found)
        self.last_check = time.time()
        self.baseline = now  # report each change once
        return found

    def _new_bytes(self, key: str, before, after) -> bytes:
        """What appeared: the appended tail of a file that grew, all of a file
        that was replaced, the contents of new files in a directory."""
        try:
            if key.endswith("/"):
                directory = Path(key)
                added = set(after or []) - set(before or [])
                return b"".join((directory / name).read_bytes()[:2_000_000] for name in sorted(added)
                                if (directory / name).is_file())
            if not isinstance(after, list) or not after[0]:
                return b""
            start = before[1] if isinstance(before, list) and before[0] and after[1] >= before[1] else 0
            with open(key, "rb") as handle:
                handle.seek(start)
                return handle.read(2_000_000)
        except OSError:
            return b""

    def start(self) -> None:
        def loop():
            while not self.stop_event.wait(self.period):
                self.check()
        self.thread = threading.Thread(target=loop, name="leak-guard", daemon=True)
        self.thread.start()

    def alive(self) -> bool:
        return self.thread is not None and self.thread.is_alive() and time.time() - self.last_check < self.period + 60

    def stop(self) -> list:
        self.stop_event.set()
        return self.check()
