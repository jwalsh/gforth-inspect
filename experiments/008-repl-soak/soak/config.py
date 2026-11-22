"""Where things live, and the local targets manifest.

Nothing in this repository names a target.  The targets, the release
candidate's worktree and this repository's own checkout are read from a
manifest outside it:

    ${XDG_CONFIG_HOME:-~/.config}/gforth-inspect-soak/targets

one tab-separated line per entry, `kind label path options`:

    candidate  -  <worktree of the release candidate>  blob=<inspect.fs blob>
    repo       -  <this repository's main checkout>   older=<sha>
    lib        L  <a directory of .fs files>           -
    course     C  <a git checkout>                     subdir=<dir>
    santa      S  <a git main worktree>                worktrees=yes
    inputs     R  <this repository>                    refs=a,CANDIDATE,b;dirs=corpus,test

Run state (status, manifests, transcripts) goes under
${XDG_STATE_HOME:-~/.local/state}/gforth-inspect-soak/, and the session
sandboxes under $TMPDIR.  The real inspector log and ~/.gforth-history are
only ever read, by the leak guard.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXPERIMENT = HERE.parent
REPO = EXPERIMENT.parent.parent
CONSUMERS = REPO / "pbt" / "consumers"          # the three frozen reference consumers
ENGINES = ("gforth", "gforth-fast", "gforth-itc")
CONTRACT_EXPECTED = "1.1"                       # what the soak's followers are written for

ASSET_SOURCES = (                               # RELEASING.org, "What a release is"
    "env/inspect.fs",
    "contract/stacks-log.schema.json",
    "contract/stacks-log.org",
    "contract/CONSUMERS.org",
    "contract/CONSUMER-AGENTS.md",
    "contract/skill/SKILL.md",
)
ASSET_NAMES = tuple(Path(source).name for source in ASSET_SOURCES)


def _home() -> Path:
    return Path(os.environ["HOME"])


def config_dir() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or _home() / ".config") / "gforth-inspect-soak"


def state_root() -> Path:
    return Path(os.environ.get("XDG_STATE_HOME") or _home() / ".local" / "state") / "gforth-inspect-soak"


def tmp_root() -> Path:
    return Path(os.environ.get("TMPDIR") or "/tmp")


def real_guarded_paths() -> list[Path]:
    """The user's real files the leak guard hashes (G4).  Read only, never written."""
    state = Path(os.environ.get("XDG_STATE_HOME") or _home() / ".local" / "state")
    return [
        state / "gforth-inspect" / "stacks.jsonl",
        state / "course-repo" / "stacks.jsonl",       # where pre-0.1 copies of inspect.fs log
        _home() / ".gforth-history",
    ]


def real_guarded_dirs() -> list[Path]:
    state = Path(os.environ.get("XDG_STATE_HOME") or _home() / ".local" / "state")
    return [state / "gforth-inspect", state / "course-repo"]


@dataclass
class Entry:
    kind: str
    label: str
    path: Path
    options: dict = field(default_factory=dict)


def read_manifest(path: Path | None = None) -> list[Entry]:
    path = path or config_dir() / "targets"
    entries = []
    for raw in path.read_text().splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        parts = raw.split("\t")
        if len(parts) < 3:
            raise ValueError(f"targets manifest: bad line {raw!r}")
        kind, label, location = parts[:3]
        options: dict = {}
        if len(parts) > 3 and parts[3] not in ("", "-"):
            for item in parts[3].split(";"):
                key, _, value = item.partition("=")
                options[key] = value
        entries.append(Entry(kind, label, Path(location), options))
    return entries


def one(entries: list[Entry], kind: str) -> Entry:
    found = [entry for entry in entries if entry.kind == kind]
    if len(found) != 1:
        raise ValueError(f"targets manifest: want exactly one {kind!r} line, have {len(found)}")
    return found[0]


def private_strings(entries: list[Entry]) -> list[str]:
    """Strings that must never reach a committed file: every target path and
    its last component, and the user's home and name."""
    strings = {str(_home()), _home().name}
    for entry in entries:
        if str(entry.path) in ("-", "."):
            continue                                # an entry with no local path (a release)
        strings.add(str(entry.path))
        if entry.kind in ("course", "santa"):
            strings.add(entry.path.name)            # the repository's name
            strings.add(entry.path.parent.name)     # and its owner's
    return sorted(strings, key=len, reverse=True)
