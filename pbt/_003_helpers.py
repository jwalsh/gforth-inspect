"""Experiment 003: declared stack effects (model words.json) vs measured deltas.

The model (words.json and live.tsv) is read at MODEL_REF: from
pbt/fixtures/refs/<ref>/ when it is pinned there, else from git.  The default
is 5e3eede, the `model` branch commit pinned there; the branch is not public,
and its words.json is pinned with machine paths replaced by $GFORTH and $WORK
(pbt/fixtures/refs/README.org).  MODEL_REF=model (or origin/model) reads the
branch tip where that ref exists.
WORDS_JSON (a path) replaces words.json; the calibration uses it.  Only names,
kinds, flags, effects and call edges are used; the source paths in the model
are never copied anywhere.

The harness runs plain gforth (no inspect.fs): per call it clears both stacks,
pushes typed inputs, records `depth fdepth`, runs the word under `catch`, and
records `depth fdepth` again.  Many words go into one process; a word that
kills gforth or breaks the harness is found from the last line printed, then
confirmed alone, and excluded with a reason.
"""

from __future__ import annotations

import json
import os
import random
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ENGINES = ("gforth", "gforth-fast", "gforth-itc")
SCRATCH_BYTES = 8192


# ----------------------------------------------------------------- the model

def _git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(REPO), *args], check=True,
                          capture_output=True, text=True).stdout


FIXTURES = REPO / "pbt" / "fixtures" / "refs"
MODEL_PINNED = "5e3eede"  # the model branch commit in FIXTURES; keep in step with calibrate/003


def _ref_show(ref: str, path: str) -> tuple[str, str]:
    """(PATH's text at REF, where it came from): fixtures/refs/REF/ first, as
    calibrate/ref-show.lib does, else git.  A file missing from a pinned
    REF/ dir is missing at REF (as 009's ledger.py takes it), not read from
    git, so one run never pairs a pinned file with an unpinned one."""
    pinned = FIXTURES / ref
    if pinned.is_dir():
        fixture = pinned / Path(path).name
        if not fixture.is_file():
            raise RuntimeError(f"{ref} is pinned in {pinned.relative_to(REPO)} without {fixture.name}")
        return fixture.read_text(), f"{ref}@fixture"
    return _git("show", f"{ref}:{path}"), f"{ref}@{_git('rev-parse', '--short', ref).strip()}"


def model_source() -> tuple[dict, str, str]:
    """(words.json as a dict, live.tsv text, provenance for the log)."""
    ref = os.environ.get("MODEL_REF") or MODEL_PINNED
    try:
        live_text, where = _ref_show(ref, "model/data/live.tsv")
        explicit = os.environ.get("WORDS_JSON")
        if explicit:
            return json.loads(Path(explicit).read_text()), live_text, f"WORDS_JSON (live.tsv from {where})"
        words_text, where = _ref_show(ref, "model/data/words.json")
    except subprocess.CalledProcessError:
        raise RuntimeError(f"no model at {ref} (pbt/fixtures/refs/{ref}/ or git); set MODEL_REF") from None
    return json.loads(words_text), live_text, where


def best_records(words: list[dict]) -> dict[str, dict]:
    """lower name -> the definition the Forth wordlist would find (latest,
    Forth/Root preferred): the same rule as model/src/emit.py."""
    best: dict[str, dict] = {}
    for record in words:
        if not record.get("name"):
            continue
        key = record["name"].lower()
        old = best.get(key)
        if old is None:
            best[key] = record
            continue
        old_forth = old.get("wordlist") in ("Forth", "Root")
        new_forth = record.get("wordlist") in ("Forth", "Root")
        if (new_forth and not old_forth) or (new_forth == old_forth and record.get("order", 0) >= old.get("order", 0)):
            best[key] = record
    return best


def live_words(live_text: str) -> list[dict]:
    """Unique (wordlist, name) rows of the model's live dump (2018)."""
    rows, seen = [], set()
    for line in live_text.splitlines()[1:]:
        cols = line.split("\t")
        if len(cols) < 5:
            continue
        wordlist, name = cols[0].strip(), cols[1]
        key = (wordlist, name.lower())
        if key in seen:
            continue
        seen.add(key)
        rows.append({"wordlist": wordlist, "name": name, "kind": cols[2],
                     "immediate": cols[3] == "1", "compile_only": cols[4] == "1"})
    return rows


# ----------------------------------------------------- reading the effect

# Items that are not stack items: alternatives and variadic markers.  They
# count 0 cells.  Everything else in the model's lists counts as written.
MARKERS = {"...", "..", "|", "/", "??", "i*x", "j*x", "k*x", "", "--"}
DOUBLE_BASES = {"d", "ud", "xd", "+d", "dquot", "udquot"}


def base_name(item: str) -> str:
    """`c_addr1` -> `c-addr`, `w2'` -> `w`, `+n1` -> `+n`."""
    return re.sub(r"(\d+|')+$", "", item.replace("_", "-").lower())


def cells(item: str) -> int:
    if item.lower() in MARKERS:
        return 0
    return 2 if base_name(item) in DOUBLE_BASES else 1


def declared_delta(effect: dict) -> tuple[int, int]:
    """(data delta, float delta) as the model's lists say, read literally."""
    data = sum(cells(i) for i in effect.get("data_out", [])) - sum(cells(i) for i in effect.get("data_in", []))
    flt = sum(1 for i in effect.get("float_out", []) if i.lower() not in MARKERS) \
        - sum(1 for i in effect.get("float_in", []) if i.lower() not in MARKERS)
    return data, flt


def has_alternatives(effect: dict) -> bool:
    items = [i for k in ("data_in", "data_out", "float_in", "float_out") for i in effect.get(k, [])]
    return any(i in ("|", "/") or ("|" in i) or (i.endswith("/") and len(i) > 1) for i in items)


def has_variadic(effect: dict) -> bool:
    items = [i.lower() for k in ("data_in", "data_out", "float_in", "float_out") for i in effect.get(k, [])]
    return any(i in ("...", "..", "??", "i*x", "j*x") for i in items)


# --------------------------------------------------------------- typing

CELL_COUNT = {"n", "u", "+n", "len", "count", "ucount", "cnt", "size", "length", "offset", "index"}
CELL_ANY = {"w", "x", "y", "z"}
FLAG = {"f", "flag"}
CHAR = {"c", "char", "xc", "c-char"}
ADDR = {"addr", "a-addr", "c-addr", "f-addr", "df-addr", "sf-addr", "xc-addr", "c-from",
        "c-to", "adr", "caddr", "xcaddr", "u8addr", "u8-addr"}
DOUBLE = {"d", "ud", "xd", "+d"}
TOKEN = {"xt": "' noop", "nt": "s\" noop\" find-name", "wid": "forth-wordlist"}
ANY_VALUES = [0, 1, -1, 2, 3, 7, 100, -100, 12345, 0x7fff]
FLOAT_VALUES = ["0.5e0", "1e0", "1.5e0", "2e0", "3.25e0", "0.125e0", "10e0", "4e0"]
COUNT_MAX = 8  # counts (n u len ...) are 1..COUNT_MAX
# A `...` input at the bottom of its stack (pick's `S:... u`, fpick's
# `f:... u`) is typed as COUNT_MAX + 1 items there, so a count after it
# indexes in range; a `...` anywhere else is untypable (select).
# Typed as nothing, `pick` read below the empty stack: garbage on macOS arm64,
# where gforth 0.7.3's stacks are malloc'd, and -4 (-45 for fpick) on Linux,
# where they sit between guard pages (#72).  Constant, so it draws nothing
# from rng and the word's other inputs are unchanged.
DATA_FILLER = " ".join(["0"] * (COUNT_MAX + 1))
FLOAT_FILLER = " ".join(["0e0"] * (COUNT_MAX + 1))


def data_generator(item: str):
    """item -> function(rng) giving Forth source that pushes it; None if untypable."""
    base = base_name(item)
    if item == "...":
        return lambda rng: DATA_FILLER
    if item.lower() in MARKERS:
        return lambda rng: ""
    if base in CELL_COUNT:
        return lambda rng: str(rng.randint(1, COUNT_MAX))
    if base in CELL_ANY:
        return lambda rng: str(rng.choice(ANY_VALUES))
    if base in FLAG:
        return lambda rng: rng.choice(["0", "-1"])
    if base in CHAR:
        return lambda rng: str(rng.randint(33, 126))
    if base in ADDR:
        return lambda rng: f"(base) {16 * rng.randint(0, 63)} +"
    if base in DOUBLE:
        return lambda rng: f"{rng.randint(0, 1000)} 0"
    if base in TOKEN:
        source = TOKEN[base]
        return lambda rng: source
    return None


def float_generator(item: str):
    if item == "...":
        return lambda rng: FLOAT_FILLER
    if item.lower() in MARKERS:
        return lambda rng: ""
    if base_name(item).startswith("r"):
        return lambda rng: rng.choice(FLOAT_VALUES)
    return None


# ------------------------------------------------------------- selection

TERMINAL_IO = {"type", "emit", "key", "key?", "ekey", "ekey?", "accept", "cr", "page", "at-xy",
               "(type)", "(emit)", "(key)", "(key?)", "emit-file", "form", "edit-line", "xkey",
               "xemit", "ekey>char", "infile-id", "outfile-id", "stdout", "stderr", "stdin"}
FILE_ROOTS = {"open-file", "create-file", "close-file", "read-file", "read-line", "write-file",
              "write-line", "reposition-file", "file-position", "file-size", "resize-file",
              "delete-file", "rename-file", "file-status", "flush-file", "open-dir", "read-dir",
              "close-dir", "include-file", "included", "open-fpath-file", "block", "buffer"}
HEAP_ROOTS = {"allocate", "free", "resize"}
DICT_ROOTS = {"allot", ","}
PARSE_ROOTS = {"parse", "parse-name", "parse-word", "word", "sword", "refill", "evaluate",
               "interpret", "(parse-white)"}
SYSTEM = {"system", "sh", "$?", "bye", "(bye)", "cold", "boot", "ms", "quit", "(quit)",
          "abort", "throw", "(throw)", "bounce", "dump", "see", "words", "order",
          "rethrow", "cstring>sstring", "getenv"}
STATE_MUTATORS = {"]", "[", "sp!", "rp!", "fp!", "lp!", "up!", "vp!", "only", "also", "previous",
                  "forth", "definitions", "seal", "set-order", "set-current", "vocabulary",
                  "perform", "execute-parsing", "reveal", "hide", "restore-input", "save-input",
                  "push-file", "pop-file", "input-start-line", "clearstack", "clearstacks",
                  "is", "defer!", "<is>", "[is]", "to", "<to>", "+to", "call-c", "jump",
                  "flush-icache", "code-address!", "does-code!", "does-handler!", "set-next-code"}
DEFINING_KINDS = {"interpret/compile"}
# Parsing found by measurement, not visible in the call graph (the model does
# not follow POSTPONE edges): `assertn` with n > assert-level runs the
# compilation semantics of `(` and skips input up to the next `)`.
PARSES_AT_RUN_TIME = {"assertn"}
TOKEN_EXCLUDE = {"loop-sys", "nest-sys", "colon-sys", "do-sys", "orig", "dest", "sys",
                 "struct-sys", "case-sys", "of-sys", "return-stack-item"}


def compile_time(record: dict | None) -> bool:
    """An immediate or compile-only callee runs when its caller is compiled,
    not when the caller runs, so the call graph is not followed into it."""
    flags = (record or {}).get("flags") or {}
    return bool(flags.get("immediate") or flags.get("compile_only"))


def closure(roots: set[str], best: dict[str, dict], stop: set[str]) -> set[str]:
    """Names (lower) whose call graph reaches a root; `stop` is not traversed."""
    callees: dict[str, set[str]] = {}
    for name, record in best.items():
        targets = {c["name"].lower() for c in record.get("calls") or [] if c.get("name")
                   and c.get("how") in ("call", "defers", "[']", "'")}
        targets |= {c["xt"].lower() for c in record.get("is") or [] if c.get("xt")}
        for alias in record.get("alias_chain") or []:
            targets.add(alias.lower())
        callees[name] = {t for t in targets - stop if not compile_time(best.get(t))}
    reached = {r.lower() for r in roots}
    changed = True
    while changed:
        changed = False
        for name, targets in callees.items():
            if name not in reached and targets & reached:
                reached.add(name)
                changed = True
    return reached


@dataclass
class Selection:
    tested: list[dict] = field(default_factory=list)   # {name, effect, declared}
    excluded: dict[str, list[str]] = field(default_factory=dict)  # reason -> names
    universe: int = 0

    def exclude(self, reason: str, name: str) -> None:
        self.excluded.setdefault(reason, []).append(name)


def select(model: dict, live_text: str) -> Selection:
    best = best_records(model["words"])
    io = closure(TERMINAL_IO, best, stop=SYSTEM)
    files = closure(FILE_ROOTS, best, stop=SYSTEM)
    heap = closure(HEAP_ROOTS, best, stop=SYSTEM)
    dictionary = closure(DICT_ROOTS, best, stop=SYSTEM)
    # `char` in a colon body is the cross-compiler's `[char]`: compile time
    parsing = closure(PARSE_ROOTS, best, stop=SYSTEM | {"char"})
    defining = {n.lower() for n in model.get("defining_words", {})}
    selection = Selection()
    rows = live_words(live_text)
    selection.universe = len(rows)
    seen_names: set[str] = set()
    for row in rows:
        name, key = row["name"], row["name"].lower()
        if key in seen_names:
            selection.exclude("same-name-in-root", name)
            continue
        seen_names.add(key)
        record = best.get(key)
        stack = (record or {}).get("stack")
        effect = (record or {}).get("effect") or {}
        flags = (record or {}).get("flags") or {}
        items = [i for k in ("data_in", "data_out", "float_in", "float_out") for i in effect.get(k, [])]
        reason = None
        if row["wordlist"] not in ("Forth", "Root"):
            reason = "not-in-search-order"
        elif record is None or stack is None:
            reason = "no-declared-effect"
        elif row["immediate"] or flags.get("immediate"):
            reason = "immediate"
        elif row["compile_only"] or flags.get("compile_only"):
            reason = "compile-only"
        elif key in defining or record.get("is_defining_word") or record["kind"] in DEFINING_KINDS:
            reason = "defining-or-dual-semantics"
        elif '"' in stack or any(i.startswith("'") for i in items) or key in parsing \
                or key in PARSES_AT_RUN_TIME:
            reason = "parsing"
        elif effect.get("inline"):
            reason = "inline-argument"
        elif effect.get("return_in") or effect.get("return_out") or \
                any(base_name(i) in TOKEN_EXCLUDE for i in items) or effect.get("phases"):
            reason = "return-stack-or-compile-time"
        elif key in SYSTEM:
            reason = "system-or-throws"
        elif key in files or "file" in (record.get("wordset") or "") or "block" in (record.get("wordset") or ""):
            reason = "file"
        elif key in heap or key in dictionary:
            reason = "allocates"
        elif key in io:
            reason = "io"
        elif key in STATE_MUTATORS:
            reason = "mutates-interpreter-state"
        if reason is None:
            gens = [data_generator(i) for i in effect.get("data_in", [])]
            fgens = [float_generator(i) for i in effect.get("float_in", [])]
            # the filler goes under the word's inputs, never between them
            inner_rest = "..." in effect.get("data_in", [])[1:] or "..." in effect.get("float_in", [])[1:]
            if any(g is None for g in gens) or any(g is None for g in fgens) or inner_rest:
                reason = "untypable-input"
            else:
                selection.tested.append({"name": name, "effect": effect, "stack": stack,
                                         "declared": declared_delta(effect),
                                         "gens": gens, "fgens": fgens})
                continue
        selection.exclude(reason, name)
    return selection


# --------------------------------------------------------------- harness

PRELUDE = f"""
create (scratch) {SCRATCH_BYTES + 32} allot
variable (d0) variable (f0) variable (d1) variable (f1) variable (err)
: (base) ( -- a-addr ) (scratch) 15 + -16 and ;
: (fclear) ( F: ... -- ) begin fdepth while fdrop repeat ;
\\ <# resets the pictured-output area: without it, 200 calls of hold or <<#
\\ overflow it and gforth exits (found in the ci profile)
: (pre) ( ... -- ) decimal clearstack (fclear) (base) {SCRATCH_BYTES} erase <# ;
: (snap) ( -- ) depth (d0) ! fdepth (f0) ! ;
: (post) ( ... err -- ) (err) ! depth (d1) ! fdepth (f1) ! decimal clearstack (fclear) ;
: (line) ( idx -- ) ." @@R " 0 .r space (d0) @ . (f0) @ . (d1) @ . (f1) @ . (err) @ . cr
  outfile-id flush-file drop ;
"""


def case_line(index: int, name: str, inputs: str) -> str:
    return f"(pre) {inputs} (snap) ' {name} catch (post) {index} (line)"


def make_cases(word: dict, count: int, seed: int) -> list[str]:
    """`count` input strings for one word, seeded by (seed, name) only, so a
    change to one word's declaration leaves every other word's inputs alone."""
    rng = random.Random(f"{seed}:{word['name']}")
    out = []
    for _ in range(count):
        parts = [g(rng) for g in word["gens"]] + [g(rng) for g in word["fgens"]]
        out.append(" ".join(p for p in parts if p))
    return out


@dataclass
class BatchResult:
    lines: dict[int, tuple[int, int, int, int, int]]
    wrote: set[int]          # case indices that printed something themselves
    returncode: int | None  # None: timed out


def run_program(cases: list[tuple[int, str, str]], engine: str, timeout: float) -> BatchResult:
    program = PRELUDE + "\n".join(case_line(i, n, s) for i, n, s in cases) + "\nbye\n"
    with tempfile.TemporaryDirectory(prefix="gfi003-") as tmp:
        tmp_path = Path(tmp)
        (tmp_path / "prog.fs").write_text(program)
        env = {**os.environ, "XDG_STATE_HOME": str(tmp_path / "state")}
        try:
            proc = subprocess.run([engine, "prog.fs"], cwd=tmp_path, env=env, capture_output=True,
                                  timeout=timeout, stdin=subprocess.DEVNULL)
            stdout, returncode = proc.stdout, proc.returncode
        except subprocess.TimeoutExpired as expired:
            stdout, returncode = expired.stdout or b"", None
    lines, wrote, previous_end = {}, set(), 0
    text = stdout.decode("utf-8", "replace")
    for match in re.finditer(r"@@R (\d+) (-?\d+) (-?\d+) (-?\d+) (-?\d+) (-?\d+) \n", text):
        idx, *vals = (int(v) for v in match.groups())
        lines[idx] = tuple(vals)
        if text[previous_end:match.start()]:
            wrote.add(idx)
        previous_end = match.end()
    return BatchResult(lines, wrote, returncode)


@dataclass
class WordOutcome:
    name: str
    declared: tuple[int, int]
    measured: set = field(default_factory=set)   # {(ddelta, fdelta)}
    threw: set = field(default_factory=set)      # throw codes
    wrote: bool = False                          # printed to stdout
    crashed: bool = False
    crash_detail: str = ""

    @property
    def agrees(self) -> bool:
        return self.measured == {self.declared} and not (self.crashed or self.threw or self.wrote)


def measure(words: list[dict], engine: str, per_word: int, seed: int,
            batch_words: int = 150, timeout: float = 3.0) -> dict[str, WordOutcome]:
    """Run every word on `per_word` inputs; bisect crashed batches."""
    outcomes = {w["name"]: WordOutcome(w["name"], w["declared"]) for w in words}
    cases_of = {w["name"]: make_cases(w, per_word, seed) for w in words}

    last_failure = {"detail": ""}

    def attempt(group: list[dict]) -> tuple[list[dict], dict | None]:
        """Run group; return (words fully reported, first word not reported)."""
        cases, owner, idx = [], [], 0
        for w in group:
            for inputs in cases_of[w["name"]]:
                cases.append((idx, w["name"], inputs))
                owner.append(w)
                idx += 1
        result = run_program(cases, engine, timeout + len(cases) / 5000)
        missing = [i for i in range(len(cases)) if i not in result.lines]
        if not missing and result.returncode is not None:
            for i, w in enumerate(owner):
                record(w, result.lines[i], i in result.wrote)
            return group, None
        first = missing[0] if missing else len(cases) - 1
        if result.returncode is None:
            last_failure["detail"] = "hang (timeout)"
        elif result.returncode < 0:
            last_failure["detail"] = f"killed by signal {-result.returncode}"
        elif result.returncode != 0:
            last_failure["detail"] = f"gforth exit {result.returncode}"
        else:
            last_failure["detail"] = "harness broken (no report line)"
        done_words = []
        for w in group:
            if w is owner[first]:
                break
            done_words.append(w)
        for i in range(first):
            record(owner[i], result.lines[i], i in result.wrote)
        return done_words, owner[first]

    def record(w: dict, vals: tuple, wrote: bool) -> None:
        d0, f0, d1, f1, err = vals
        out = outcomes[w["name"]]
        out.wrote |= wrote
        if err:
            out.threw.add(err)
        else:
            out.measured.add((d1 - d0, f1 - f0))

    def reset(w: dict) -> None:
        name = w["name"]
        outcomes[name] = WordOutcome(name, w["declared"])

    pending = list(words)
    while pending:
        group, pending = pending[:batch_words], pending[batch_words:]
        while group:
            done, culprit = attempt(group)
            if culprit is None:
                break
            position = group.index(culprit)
            reset(culprit)
            _, solo_culprit = attempt([culprit])
            if solo_culprit is not None:
                outcomes[culprit["name"]] = WordOutcome(culprit["name"], culprit["declared"], crashed=True,
                                                        crash_detail=last_failure["detail"])
                group = group[position + 1:]
                continue
            # alone it passes: an earlier word in the batch broke the harness.
            # Bisect the prefix for the word that makes `culprit` fail.
            prefix = group[:position]
            breaker = None
            while prefix:
                half = prefix[len(prefix) // 2:]
                _, seen = attempt(half + [culprit])
                if seen is not None and len(half) == 1:
                    breaker = half[0]
                    break
                prefix = half if seen is not None else prefix[:len(prefix) // 2]
            for w in group[:position]:
                reset(w)
            if breaker is None:
                breaker = culprit  # batch-only failure: blame the reporter
            outcomes[breaker["name"]] = WordOutcome(breaker["name"], breaker["declared"], crashed=True,
                                                    crash_detail="breaks a later word in the same process")
            group = [w for w in group if w is not breaker]
    return outcomes
