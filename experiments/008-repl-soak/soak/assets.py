"""The release candidate's seven assets: built as a release builds them, and
installed as a consumer installs them (G8).

Build (RELEASING.org, "Cutting one", by hand): copy the six sources out of
the candidate worktree into a dist directory, run the worktree's own
scripts/dist-links.sh on it with REF = the candidate's commit (the dry-run
form), then SHA256SUMS over the six.  The worktree is only read: git is run
there read-only, and every write goes to the dist directory.

Install (CONSUMER-AGENTS.md): the seven files into the project's env
directory, `shasum -a 256 -c SHA256SUMS` there, and SKILL.md copied to
.claude/skills/gforth-inspect/SKILL.md.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path

from . import config


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          capture_output=True, text=True).stdout


def blob_of(path: Path) -> str:
    """The git blob id of a file's bytes (what `git hash-object` prints)."""
    data = path.read_bytes()
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def blob_of_bytes(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(candidate: Path, pinned_blob: str, dist: Path) -> dict:
    """Build dist/ from the candidate worktree.  Returns provenance."""
    commit = git(candidate, "rev-parse", "HEAD").strip()
    head_blob = git(candidate, "rev-parse", "HEAD:env/inspect.fs").strip()
    work_blob = blob_of(candidate / "env" / "inspect.fs")
    if not (head_blob == work_blob == pinned_blob):
        raise RuntimeError(f"candidate inspect.fs is not the pinned blob: HEAD {head_blob[:12]}, "
                           f"worktree {work_blob[:12]}, pinned {pinned_blob[:12]}")
    # every source as committed (compared by blob: `git status` would refresh
    # the worktree's index, and the worktree is not ours to write)
    for source in config.ASSET_SOURCES:
        if blob_of(candidate / source) != git(candidate, "rev-parse", f"HEAD:{source}").strip():
            raise RuntimeError(f"candidate worktree: {source} differs from its commit")
    if dist.exists():
        shutil.rmtree(dist)
    dist.mkdir(parents=True)
    for source in config.ASSET_SOURCES:
        shutil.copyfile(candidate / source, dist / Path(source).name)
    subprocess.run(["bash", str(candidate / "scripts" / "dist-links.sh"), str(dist), commit,
                    *config.ASSET_SOURCES], cwd=candidate, check=True, capture_output=True, text=True)
    sums = "".join(f"{sha256(dist / name)}  {name}\n" for name in config.ASSET_NAMES)
    (dist / "SHA256SUMS").write_text(sums)
    names = sorted(path.name for path in dist.iterdir())
    if names != sorted(config.ASSET_NAMES + ("SHA256SUMS",)):
        raise RuntimeError(f"dist is not exactly the seven assets: {names}")
    return {
        "commit": commit,
        "inspect_blob": pinned_blob,
        "assets": {name: blob_of(dist / name) for name in names},
        "sha256sums": sha256(dist / "SHA256SUMS"),
    }


def install(dist: Path, project: Path, env_dir: str = "env") -> dict:
    """Install the assets into a consumer project; returns what was checked."""
    target = project / env_dir
    target.mkdir(parents=True, exist_ok=True)
    for name in config.ASSET_NAMES + ("SHA256SUMS",):
        shutil.copyfile(dist / name, target / name)
    check = subprocess.run(["shasum", "-a", "256", "-c", "SHA256SUMS"], cwd=target,
                           capture_output=True, text=True)
    skill = project / ".claude" / "skills" / "gforth-inspect" / "SKILL.md"
    skill.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(target / "SKILL.md", skill)
    return {
        "sha256sums_ok": check.returncode == 0,
        "sha256sums_output": check.stdout.strip().splitlines(),
        "skill_ok": skill.read_bytes() == (dist / "SKILL.md").read_bytes(),
        "inspect_blob": blob_of(target / "inspect.fs"),
    }


def version_of(source: bytes) -> tuple[str | None, str | None]:
    """(inspect-version, contract-version) as the source defines them; None if absent."""
    import re
    inspect = re.search(rb': inspect-version \( -- c-addr u \) s" ([^"]*)" ;', source)
    contract = re.search(rb': contract-version \( -- c-addr u \) s" ([^"]*)" ;', source)
    return (inspect.group(1).decode() if inspect else None,
            contract.group(1).decode() if contract else None)


def download(tag: str, repo: Path, pinned_blob: str, dest: Path, github: str = "jwalsh/gforth-inspect") -> dict:
    """A published release, fetched as CONSUMER-AGENTS.md says: `gh release
    download` into a directory, then `shasum -a 256 -c SHA256SUMS` there."""
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    subprocess.run(["gh", "release", "download", tag, "-R", github, "-D", str(dest)], check=True,
                   capture_output=True, text=True)
    check = subprocess.run(["shasum", "-a", "256", "-c", "SHA256SUMS"], cwd=dest, capture_output=True, text=True)
    names = sorted(path.name for path in dest.iterdir())
    if names != sorted(config.ASSET_NAMES + ("SHA256SUMS",)):
        raise RuntimeError(f"release {tag} is not exactly the seven assets: {names}")
    if check.returncode != 0:
        raise RuntimeError(f"release {tag}: SHA256SUMS does not check: {check.stdout} {check.stderr}")
    blob = blob_of(dest / "inspect.fs")
    if blob != pinned_blob:
        raise RuntimeError(f"release {tag}: inspect.fs is blob {blob[:12]}, pinned {pinned_blob[:12]}")
    commit = git(repo, "rev-parse", f"{tag}^{{commit}}").strip()
    tag_blob = git(repo, "rev-parse", f"{tag}:env/inspect.fs").strip()
    tag_schema = git(repo, "rev-parse", f"{tag}:contract/stacks-log.schema.json").strip()
    return {
        "release": tag, "commit": commit, "inspect_blob": blob,
        "inspect_is_tag_file": tag_blob == blob,
        "schema_is_tag_file": tag_schema == blob_of(dest / "stacks-log.schema.json"),
        "sha256sums_check": check.stdout.strip().splitlines(),
        "assets": {name: blob_of(dest / name) for name in names},
        "sha256sums": sha256(dest / "SHA256SUMS"),
    }
