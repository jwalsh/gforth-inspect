#!/bin/sh
# check-guides.sh -- the guides exist, their relative links resolve, and
# README.org stays end-user only.  Part of `gmake verify`.
#
#   scripts/check-guides.sh              check the repository
#   scripts/check-guides.sh --calibrate  plant each fault in a temp copy and
#                                        check that the scan goes red on every one
set -u

REQUIRED="README.org CONTRIBUTING.org RELEASING.org CONSUMERS.org REVIEW.md AGENTS.md LICENSE"
# words that mark developer or release-engineering content
README_DEV='gmake|pbt/|experiments/|\.meta/|hypothesis|calibrat|worktree|code-review'

check() {
    root=$1
    status=0
    for guide in $REQUIRED; do
        [ -f "$root/$guide" ] || { echo "missing guide: $guide"; status=1; }
    done
    # org links [[file:target][...]] and markdown links ](target), relative only
    for doc in "$root"/*.org "$root"/*.md "$root"/.meta/*.org "$root"/experiments/*.org "$root"/contract/*.org; do
        [ -f "$doc" ] || continue
        dir=$(dirname "$doc")
        targets=$( { grep -o -E '\[\[file:[^]]+\]' "$doc" | sed -E 's/^\[\[file://; s/\]$//'
                     grep -o -E '\]\([^)#: ]+\)' "$doc" | sed -E 's/^\]\(//; s/\)$//'; } 2>/dev/null)
        for target in $targets; do
            case $target in /*|http*|mailto*) continue ;; esac
            target=${target%%::*}
            [ -e "$dir/$target" ] || { echo "broken link in ${doc#$root/}: $target"; status=1; }
        done
    done
    if [ -f "$root/README.org" ] && grep -n -i -E "$README_DEV" "$root/README.org"; then
        echo "README.org has developer content (above): it is for end users only"
        status=1
    fi
    return $status
}

if [ "${1:-}" = "--calibrate" ]; then
    top=$(git rev-parse --show-toplevel) || exit 2
    tmp=$(mktemp -d)
    fail=0
    plant() {  # name, then a command run inside a fresh copy
        copy="$tmp/$1"
        mkdir -p "$copy"
        (cd "$top" && git ls-files -z | xargs -0 tar cf - ) | (cd "$copy" && tar xf -)
        (cd "$copy" && sh -c "$2")
        if check "$copy" >/dev/null; then echo "MISSED: $1"; fail=1
        else echo "red as expected: $1"; fi
    }
    plant missing-guide 'mv REVIEW.md REVIEW.md.away'
    plant broken-org-link 'printf "\n[[file:no-such-file.org][x]]\n" >> CONTRIBUTING.org'
    plant broken-md-link 'printf "\n[x](no-such-file.md)\n" >> REVIEW.md'
    plant readme-dev 'printf "\nRun gmake -C pbt check.\n" >> README.org'
    mkdir -p "$tmp/clean"
    (cd "$top" && git ls-files -z | xargs -0 tar cf - ) | (cd "$tmp/clean" && tar xf -)
    if ! check "$tmp/clean" >/dev/null; then echo "false positive on a clean copy"; fail=1; fi
    echo "leaving planted copies in $tmp for inspection"
    exit $fail
fi

top=$(git rev-parse --show-toplevel) || exit 2
if check "$top"; then echo "check-guides: ok"; else echo "check-guides: failed" >&2; exit 1; fi
