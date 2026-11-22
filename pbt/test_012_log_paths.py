"""Experiment 012: the per-project default log directory (experiments/012-log-paths/README.org).

The rule is contract/stacks-log.org, "Files"; its Python reference is the
block there, loaded by _012_helpers.  Properties:

  P1 safe        every encoded component is non-empty, has no "/" or NUL,
                 is not "." or "..", is ASCII and at most 64 bytes
  P2 determined  the same name always gives the same component
  P3 injective   different names give different components, also after
                 case-folding, across every generated set
  P4 reference   inspect.fs's (log-dir-for) equals the reference, on real
                 fixture trees (.git dirs and files, HEAD, config, .env)

P1-P3 run on the reference over arbitrary bytes and on git-valid branch
names (kept only when `git check-ref-format --branch` accepts them); P1,
P3 and P4 also run on what gforth prints.  pbt/calibrate/012-*.sh plant
faults in a copy of inspect.fs; each must turn P4 (and, where the fault
breaks them, P1 or P3) red.

Pin-on-find: a shrunk counterexample becomes an @example below, with the
date it was found.
"""

from __future__ import annotations

import errno
import os
import unicodedata

from hypothesis import Phase, example, given, note, reject, settings
from hypothesis import strategies as st

import _012_helpers as helpers
import gforth_run

ref = helpers.reference
Fixture = helpers.Fixture

# --- generators --------------------------------------------------------------

# git refuses control characters, space ~ ^ : ? * [ \\, "..", "@{", a
# component starting with ".", a name starting with "-" or ending with "."
# or ".lock"; everything else, Unicode included, is a valid branch name
GIT_OK = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_+#!,=%&"
GIT_ODD = ".@{}'`$<>|\";()"
GIT_REFUSED = "~^:?*[\\ \t" + "".join(chr(code) for code in list(range(1, 32)) + [127])
UNICODE = st.characters(min_codepoint=0x80, max_codepoint=0x10FFFF, exclude_categories=("Cs",))


def _segments(alphabet, min_size=1, max_size=24):
    return st.text(alphabet=alphabet, min_size=min_size, max_size=max_size)


likely = st.one_of(*[st.sampled_from(GIT_OK)] * 6, st.sampled_from(GIT_ODD), UNICODE)
wide = st.one_of(st.sampled_from(GIT_OK), st.sampled_from(GIT_ODD), st.sampled_from(GIT_REFUSED), UNICODE)

# (1) branch names: generated wide (Unicode, "/", ".", "@", "{", control
# characters, long names), kept only when real git accepts them
branch_candidates = st.one_of(
    st.lists(_segments(likely), min_size=1, max_size=5).map("/".join),
    st.lists(_segments(likely), min_size=1, max_size=5).map("/".join),
    st.lists(_segments(likely, 8, 30), min_size=6, max_size=14).map("/".join),
    st.lists(_segments(wide, 1, 8), min_size=1, max_size=3).map("/".join),
).map(lambda text: text.encode("utf-8"))
branch_names = branch_candidates.filter(helpers.git_accepts)

# (2) owner and repo: arbitrary bytes (no "/": it separates them; no LF:
# the config is read by line), plus a few that sit next to a plain name
names = st.one_of(
    st.binary(min_size=0, max_size=80).filter(lambda raw: b"/" not in raw and b"\n" not in raw),
    st.from_regex(rb"\A[a-z0-9][a-z0-9._-]{0,70}\Z"),
    st.from_regex(rb"\A[A-Za-z0-9._~-]{1,66}\Z"),
)
for_paths = names.filter(lambda raw: b"\r" not in raw)


# (3) remote urls in every accepted form
@st.composite
def urls(draw):
    owner, repo = draw(for_paths), draw(for_paths)
    host = draw(st.sampled_from([b"github.com", b"git.example.org", b"10.0.0.1", b"h"]))
    prefix = b"".join(draw(st.lists(st.sampled_from([b"group/", b"a/b/", b"x/"]), max_size=2)))
    path = prefix + owner + b"/" + repo + draw(st.sampled_from([b"", b".git", b"/", b".git/"]))
    form = draw(st.sampled_from(["scp", "ssh", "https", "one-segment"]))
    if form == "scp":
        return b"git@" + host + b":" + path
    if form == "ssh":
        user = draw(st.sampled_from([b"", b"git@"]))
        port = draw(st.sampled_from([b"", b":22", b":2222"]))
        return b"ssh://" + user + host + port + b"/" + path
    if form == "https":
        return b"https://" + host + b"/" + path
    return b"git@" + host + b":" + repo + b".git"


@st.composite
def configs(draw):
    url = draw(urls())
    header = draw(st.sampled_from([b'[remote "origin"]', b'[Remote "origin"]', b'[REMOTE "origin"]']))
    key = draw(st.sampled_from([b"\turl = ", b"url=", b"  URL =  "]))
    value = b'"' + url + b'"' if draw(st.booleans()) else url
    before = draw(st.sampled_from([b"", b"[core]\n\tbare = false\n", b'[remote "upstream"]\n\turl = https://h/u/p\n']))
    return before + header + b"\n" + key + value + b"\n"


heads = st.one_of(
    branch_names.map(lambda name: b"ref: refs/heads/" + name + b"\n"),
    st.just(b"0123456789abcdef0123456789abcdef01234567\n"),
    st.just(b""),
    st.none(),
)

dir_names = st.text(
    alphabet=st.characters(max_codepoint=0xFFFF, exclude_characters="/\x00", exclude_categories=("Cs", "Cn", "Co")),
    min_size=1, max_size=40,
).filter(lambda name: name not in (".", "..", ".git", ".env", "wt", "sub")
         and len(name.encode()) <= 200).map(lambda name: unicodedata.normalize("NFC", name))

dotenvs = st.one_of(
    st.none(), st.none(), st.none(),
    st.sampled_from([b"OTHER=1\n", b"GFORTH_INSPECT_LOG_DIR=\n", b"GFORTH_INSPECT_LOG_DIR=~/shared\n",
                     b"GFORTH_INSPECT_LOG_DIR='~/q'\r\n", b'GFORTH_INSPECT_LOG_DIR="rel dir"\n',
                     b"GFORTH_INSPECT_LOG_DIR=a\nGFORTH_INSPECT_LOG_DIR=b\n"]),
)


@st.composite
def fixtures(draw):
    kind = draw(st.sampled_from(["main", "main", "linked-abs", "linked-rel", "nogit"]))
    config = draw(st.one_of(configs(), configs(), st.none(), st.just(b"[core]\n\tbare = false\n")))
    return Fixture(kind=kind, name=draw(dir_names), main=draw(dir_names), config=config,
                   head=draw(heads), dotenv=draw(dotenvs), depth=draw(st.integers(0, 2)))


batches = st.lists(fixtures(), min_size=1, max_size=8)
engines = st.sampled_from(gforth_run.ENGINES)

# calibrate/012.lib sets PBT_012_EXAMPLES: a few examples, no shrinking,
# enough to say which properties a planted fault turns red
_CAL_EXAMPLES = int(os.environ.get("PBT_012_EXAMPLES", "0"))
calibration = (settings(max_examples=_CAL_EXAMPLES, phases=[Phase.explicit, Phase.generate])
               if _CAL_EXAMPLES else (lambda test: test))

# --- checks ----------------------------------------------------------------------


def safe_component(component: bytes) -> list[str]:
    problems = []
    if not component:
        problems.append("empty")
    if b"/" in component or b"\0" in component:
        problems.append("holds / or NUL")
    if component in (b".", b".."):
        problems.append(". or ..")
    if any(byte >= 0x80 for byte in component):
        problems.append("not ASCII")
    if len(component) > 64:
        problems.append(f"{len(component)} bytes")
    return problems


def assert_injective(pairs) -> None:
    """pairs: (source, encoded); distinct sources must give distinct encodings, case-folded too."""
    seen: dict[bytes, object] = {}
    for source, encoded in pairs:
        folded = encoded.lower()
        if folded in seen and seen[folded] != source:
            raise AssertionError(f"P3 injective: {seen[folded]!r} and {source!r} both give {encoded!r}")
        seen[folded] = source


# --- P1-P3 on the reference -------------------------------------------------


@example(b"")
@example(b"a")
@example(b"A")
@example(b".")
@example(b"..")
@example(b"~")
@example(b"a~b")
@example(b"x" * 64)
@example(b"x" * 65)
@example(b"\xff\xfe")
@given(names)
def test_reference_component_safe(name):
    encoded = ref.enc(name)
    assert not safe_component(encoded), (name, encoded, safe_component(encoded))
    assert ref.enc(name) == encoded  # P2


@given(branch_names)
def test_reference_branch_safe(name):
    note(f"branch {name!r}")
    encoded = ref.enc(name)
    assert not safe_component(encoded), (name, encoded)
    detached = ref.hashed(b"_detached-", name, 36)
    assert not safe_component(detached), (name, detached)


@example([b"A", b"a"])
@example([b"Acme", b"ACME", b"acme"])
@example([b"a b", b"a!b", b"a-b"])
@example([b".x", b"x", b"-x"])
@example([b"x" * 64 + b"1", b"x" * 64 + b"2"])
@example([b"feature/x", b"feature-x", b"Feature/X"])
@given(st.lists(st.one_of(names, branch_names), min_size=2, max_size=20, unique=True))
def test_reference_injective(sources):
    assert_injective((source, ref.enc(source)) for source in sources)


@given(st.lists(st.one_of(names, branch_names), min_size=1, max_size=10, unique=True),
       st.lists(dir_names.map(str.encode), min_size=1, max_size=5, unique=True))
def test_reference_injective_with_markers(sources, roots):
    """Plain names, hashed names, the detached form and the markers never meet."""
    pairs = [(("name", source), ref.enc(source)) for source in sources]
    pairs += [(("detached", root), ref.hashed(b"_detached-", root, 36)) for root in roots]
    pairs += [(("marker", marker), marker) for marker in (b"_", b"_local", b"_nogit")]
    assert_injective(pairs)


# --- P1, P3, P4 on inspect.fs ---------------------------------------------------

# fixed batches the calibration relies on: each planted fault is caught on
# one of them whatever Hypothesis draws
TRICKY = [
    Fixture("main", "Acme", "m", b'[remote "origin"]\n\turl = git@h:Acme/widget.git\n',
            b"ref: refs/heads/feature/Parser\n", None, 1),
    Fixture("main", "acme", "m", b'[remote "origin"]\n\turl = git@h:ACME/a~b.git\n',
            b"ref: refs/heads/.hidden\n", None, 0),
    Fixture("linked-rel", "wt1", "Main Repo", None, b"0123456789abcdef0123456789abcdef01234567\n", None, 0),
    Fixture("linked-abs", "w2", "m", b'[remote "origin"]\n\turl = https://h/g/acme/repo\n',
            b"ref: refs/heads/" + b"l" * 70 + b"\n", None, 2),
    Fixture("nogit", "-dash.dot", "m", None, None, None, 0),
    Fixture("main", "e", "m", None, b"ref: refs/heads/main\n", b"GFORTH_INSPECT_LOG_DIR='~/shared'\n", 0),
]


def _run(batch, engine):
    try:
        result = helpers.forth_dirs(batch, engine)
    except OSError as error:  # a name this file system refuses (APFS: EILSEQ)
        if error.errno != errno.EILSEQ:
            raise
        reject()
    note(f"engine {engine}; pwds {result.pwds}")
    note(f"forth    {result.forth}")
    note(f"expected {result.expected}")
    assert result.returncode == 0, (result.returncode, result.stderr[-400:])
    assert b"redefined" not in result.stderr, result.stderr[-400:]
    return result


# pinned 2026-11-22: a directory named CR; the first driver read $PWDs with
# read-line, which ends a line at CR as well (a harness bug, not the rule)
@example([Fixture("main", "\r", "0", None, b"ref: refs/heads/0\n", None, 0)], "gforth")
@example(TRICKY, "gforth")
@given(batches, engines)
@calibration
def test_forth_matches_reference(batch, engine):
    """P4: (log-dir-for) is the reference, byte for byte."""
    result = _run(batch, engine)
    for pwd, forth, expected in zip(result.pwds, result.forth, result.expected):
        assert forth == expected, f"P4 reference: $PWD {pwd!r}: forth {forth!r}, reference {expected!r}"


@example(TRICKY, "gforth")
@given(batches, engines)
@calibration
def test_forth_components_safe(batch, engine):
    """P1 on what gforth prints: three safe components below <base>."""
    result = _run(batch, engine)
    for pwd, forth, expected in zip(result.pwds, result.forth, result.expected):
        if not expected.startswith(result.base + b"/"):
            continue  # a .env value: taken literally
        components = forth[len(result.base) + 1:].split(b"/") if forth.startswith(result.base + b"/") else [forth]
        assert len(components) == 3, f"P1 safe: $PWD {pwd!r} gives {len(components)} components: {forth!r}"
        for component in components:
            problems = safe_component(component)
            assert not problems, f"P1 safe: $PWD {pwd!r}: {component!r}: {problems}"


@example(TRICKY, "gforth")
@given(batches, engines)
@calibration
def test_forth_injective(batch, engine):
    """P3 on what gforth prints: each position maps distinct sources to distinct components."""
    result = _run(batch, engine)
    for position in range(3):
        pairs = []
        for forth, expected, raw in zip(result.forth, result.expected, result.raw):
            if not expected.startswith(result.base + b"/"):
                continue
            components = forth[len(result.base) + 1:].split(b"/")
            if len(components) == 3:
                pairs.append((raw[position], components[position]))
        assert_injective(pairs)


def test_reference_matches_goldens():
    """The worked examples in stacks-log.org and test/expected/log-dir-rule.out."""
    assert ref.enc(b"feature/Parser") == b"feature-parser~eb9f8a4eb252"
    assert ref.enc(b"Acme") == b"acme~84d1d48b0b85"
    assert ref.enc(b"My Proj") == b"my-proj~c0571c5e0b05"
    assert ref.hashed(b"_detached-", b"w", 36) == b"_detached-w~af63ea4c8602"
    assert ref.fnv1a64(b"a") == 0xaf63dc4c8601ec8c  # the published FNV-1a 64 vector
    assert ref.owner_repo(b"ssh://git@git.example.org:2222/team/tools.git") == (b"team", b"tools")


def test_git_filter_is_live():
    """The branch filter asks real git: it accepts a plain name, refuses an invalid one."""
    assert helpers.git_accepts(b"feature/x")
    assert not helpers.git_accepts(b"a..b")
    assert not helpers.git_accepts(b"-x")
