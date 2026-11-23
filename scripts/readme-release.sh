#!/usr/bin/env bash
# readme-release.sh vX.Y.Z -- after a release is published, rewrite README.org's
# Install section for that exact version.  The README never carries a version
# placeholder: before the first release it shows only what works (main), and
# after each release this script writes the real tag, read back from GitHub.
#
# Refuses unless the tag exists as a published (not draft) release with every
# asset of RELEASING.org's table, and every name SHA256SUMS lists, so the
# README cannot point at something that is not there.
# Commit the result as:  docs(readme): install vX.Y.Z [skip ci]
set -euo pipefail

tag=${1:?usage: readme-release.sh vX.Y.Z}
[[ $tag =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "not a version tag: $tag" >&2; exit 2; }
repo=jwalsh/gforth-inspect
top=$(git rev-parse --show-toplevel)

is_draft=$(gh release view "$tag" -R "$repo" --json isDraft -q '.isDraft')
[ "$is_draft" = false ] || { echo "release $tag is a draft" >&2; exit 1; }
assets=$(gh release view "$tag" -R "$repo" --json assets -q '.assets[].name')
for required in inspect.fs stacks-log.schema.json stacks-log.org CONSUMERS.org \
                CONSUMER-AGENTS.md SKILL.md WORDS.org SHA256SUMS; do
    grep -qxF "$required" <<<"$assets" || { echo "release $tag has no $required" >&2; exit 1; }
done
scratch=$(mktemp -d); trap 'rm -r "$scratch"' EXIT
gh release download "$tag" -R "$repo" -D "$scratch" -p SHA256SUMS -p inspect.fs
while read -r _ listed_name; do
    grep -qxF "$listed_name" <<<"$assets" || { echo "release $tag: SHA256SUMS lists $listed_name, not an asset" >&2; exit 1; }
done < "$scratch/SHA256SUMS"
header_version=$(sed -n 's/^\\ gforth-inspect v//p' "$scratch/inspect.fs")
[ "v$header_version" = "$tag" ] || { echo "release $tag: inspect.fs says v$header_version" >&2; exit 1; }

python3 -I - "$top/README.org" "$tag" "$repo" <<'PY'
import pathlib, re, sys
path, tag, repo = pathlib.Path(sys.argv[1]), sys.argv[2], sys.argv[3]
text = path.read_text()
install = re.search(r"^\* Install\n", text, re.M)
usage = re.search(r"^\* Usage\n", text, re.M)
if not install or not usage or install.start() > usage.start():
    sys.exit("readme-release: README.org needs a top-level * Install heading before * Usage")
section = f"""* Install

#+begin_src sh
curl -fsSLO https://github.com/{repo}/releases/download/{tag}/inspect.fs
gforth inspect.fs
#+end_src

To check the download, fetch =SHA256SUMS= the same way and run
=shasum -a 256 -c --ignore-missing SHA256SUMS=. =inspect-version type=
prints {tag[1:]}. Within one MAJOR version the words and the log format do
not break. It needs a 64-bit gforth 0.7.3.

** As a dependency of your project

*Vendored.* Keep the release files in the project and swap them only after
the checksums pass:

#+begin_src sh
new=$(mktemp -d) && gh release download {tag} -R {repo} -D "$new" \\
  && (cd "$new" && shasum -a 256 -c SHA256SUMS) \\
  && mkdir -p vendor && rm -rf vendor/gforth-inspect && mv "$new" vendor/gforth-inspect
#+end_src

Load it with =s" vendor/gforth-inspect/inspect.fs" included=. To upgrade, run
the same lines with the new tag.

*fmix.* In =package.4th=:

#+begin_example
key-list dependencies gforth-inspect git https://github.com/{repo} tag {tag}
#+end_example

Then =fmix packages.get=, and load
=require ./forth-packages/gforth-inspect/{tag}/env/inspect.fs=. To upgrade,
change the tag in both lines and run =fmix packages.get= again; the old tag's
directory stays until you remove it. fmix checks no checksums: compare
=env/inspect.fs= with the release's =SHA256SUMS= yourself. With gforth 0.7.3
use fmix 0.9.0 or earlier.

*f (theforth.net).* Not available: gforth-inspect is not published on
theforth.net.

*Upgrading to 0.3.0 or later* without =GFORTH_INSPECT_LOG_DIR= moves the log
to a per-project directory; =log-where= prints it.

"""
path.write_text(text[:install.start()] + section + text[usage.start():])
PY
echo "README.org: Install now names $tag"
