#!/usr/bin/env bash
# readme-release.sh vX.Y.Z -- after a release is published, rewrite README.org's
# Install section for that exact version.  The README never carries a version
# placeholder: before the first release it shows only what works (main), and
# after each release this script writes the real tag, read back from GitHub.
#
# Refuses unless the tag exists as a published release with the expected
# assets, so the README cannot point at something that is not there.
# Commit the result as:  docs(readme): install vX.Y.Z [skip ci]
set -euo pipefail

tag=${1:?usage: readme-release.sh vX.Y.Z}
case $tag in v[0-9]*.[0-9]*.[0-9]*) ;; *) echo "not a version tag: $tag" >&2; exit 2 ;; esac
repo=jwalsh/gforth-inspect
top=$(git rev-parse --show-toplevel)

assets=$(gh release view "$tag" -R "$repo" --json assets -q '.assets[].name')
for required in inspect.fs stacks-log.schema.json SHA256SUMS; do
    grep -qx "$required" <<<"$assets" || { echo "release $tag has no $required" >&2; exit 1; }
done

python3 -I - "$top/README.org" "$tag" "$repo" <<'PY'
import pathlib, sys
path, tag, repo = pathlib.Path(sys.argv[1]), sys.argv[2], sys.argv[3]
text = path.read_text()
start, end = text.index("* Install\n"), text.index("* Usage\n")
section = f"""* Install

#+begin_src sh
gh release download {tag} -R {repo} -D forth-env/
(cd forth-env && shasum -a 256 -c SHA256SUMS) && gforth forth-env/inspect.fs
#+end_src

=inspect-version type= prints {tag[1:]}. Within one MAJOR version the words
and the log format do not break.

"""
path.write_text(text[:start] + section + text[end:])
PY
echo "README.org: Install now names $tag"
