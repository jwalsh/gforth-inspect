#!/usr/bin/env bash
# check-current-version.sh -- every "X.Y.Z, the current release" in the docs
# names the version in env/inspect.fs, so readers never guess which release a
# sentence is about.  Part of `gmake verify`.  README's Install section is
# scripts/readme-release.sh's (it names the latest *published* tag).
#
#   scripts/check-current-version.sh              check the working tree
#   scripts/check-current-version.sh --calibrate  plant each fault in a temp
#                                                 copy; each must go red
set -u

# the docs a user or consumer reads; history (experiments/, .meta/, logs) is not here
DOCS="README.org AGENTS.md REVIEW.md docs contract"

check() {
    root=$1
    current=$(sed -n 's/^\\ gforth-inspect v//p' "$root/env/inspect.fs")
    [ -n "$current" ] || { echo "check-current-version: no version line in env/inspect.fs"; return 1; }
    # perl -0777: the phrase may wrap across lines in prose
    found=$(cd "$root" && find $DOCS \( -name '*.org' -o -name '*.md' \) -type f -print0 2>/dev/null |
        xargs -0 perl -0777 -ne 'while (/(\d+\.\d+\.\d+),\s+the\s+current\s+release/g) { print "$ARGV $1\n" }')
    [ -n "$found" ] || { echo "check-current-version: no 'X.Y.Z, the current release' in $DOCS"; return 1; }
    stale=$(printf '%s\n' "$found" | awk -v cur="$current" '$2 != cur')
    if [ -n "$stale" ]; then
        printf '%s\n' "$stale" | while read -r file version; do
            echo "check-current-version: $file says $version, the current release; env/inspect.fs is $current"
        done
        return 1
    fi
    echo "check-current-version: $(printf '%s\n' "$found" | wc -l | tr -d ' ') mentions name $current"
}

calibrate() {
    top=$(git rev-parse --show-toplevel)
    status=0
    plant() {  # name, expected message, then a command that plants the fault in $work
        name=$1 want=$2; shift 2
        work=$(mktemp -d)
        (cd "$top" && tar cf - env/inspect.fs $DOCS 2>/dev/null) | (cd "$work" && tar xf -)
        (cd "$work" && "$@")
        out=$(check "$work" 2>&1); rc=$?
        if [ $rc -ne 0 ] && printf '%s' "$out" | grep -q -- "$want"; then
            echo "red as expected: $name"
        else
            echo "NOT red for the right reason: $name: $out"; status=1
        fi
        rm -r "$work"
    }
    bump() { perl -0pi -e 's/^\\ gforth-inspect v\d+\.\d+\.\d+/\\ gforth-inspect v99.0.0/' env/inspect.fs; }
    wrapped() { printf '\nOld text: 1.2.3, the current\nrelease, says so.\n' >> docs/RELEASING.org; }
    none() { find $DOCS \( -name '*.org' -o -name '*.md' \) -type f -exec perl -0pi -e 's/,(\s+)the(\s+)current(\s+)release/,$1the$2latest$3one/g' {} +; }
    plant "inspect.fs bumped, docs not" "env/inspect.fs is 99.0.0" bump
    plant "a stale mention wrapped across lines" "says 1.2.3, the current release" wrapped
    plant "no mention at all" "no 'X.Y.Z, the current release'" none
    out=$(check "$top" 2>&1) && echo "green as expected: the tree ($out)" || { echo "tree is red: $out"; status=1; }
    return $status
}

case "${1:-}" in
    --calibrate) calibrate ;;
    "") check "$(git rev-parse --show-toplevel)" ;;
    *) echo "usage: $0 [--calibrate]" >&2; exit 2 ;;
esac
