"""privacy_check.py -- fail if a tracked or staged file of this repository
names a local target: any path, repository name or owner listed in the
targets manifest, the home directory or the user name.  Complements
scripts/privacy-scan.sh, which cannot know the target names.  The strings
themselves are never printed."""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from soak import config  # noqa: E402

strings = config.private_strings(config.read_manifest())
top = Path(subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True,
                          check=True).stdout.strip())
# what this branch adds: files changed since main, staged or not, and new ones
# (main's own documents are the coordinators', and already reviewed)
def git_names(*args: str) -> set:
    return set(subprocess.run(["git", "-C", str(top), *args], capture_output=True, text=True,
                              check=True).stdout.split())
names = sorted(git_names("diff", "--name-only", "origin/main...HEAD") | git_names("diff", "--name-only", "HEAD")
               | git_names("ls-files", "--others", "--exclude-standard"))
hits = 0
for name in names:
    path = top / name
    if not path.is_file():
        continue
    text = path.read_bytes().decode("utf-8", "replace")
    for number, string in enumerate(strings):
        if string in text:
            hits += 1
            print(f"privacy_check: {name} holds private string #{number}")
log = subprocess.run(["git", "-C", str(top), "log", "origin/main..HEAD", "--format=%B"], capture_output=True,
                     text=True).stdout
for number, string in enumerate(strings):
    if string in log:
        hits += 1
        print(f"privacy_check: a recent commit message holds private string #{number}")
print(f"privacy_check: {'clean' if not hits else str(hits) + ' hits'} ({len(names)} files, {len(strings)} strings)")
sys.exit(1 if hits else 0)
