#!/usr/bin/env bash
# check-guides.sh -- the guides exist, their relative links resolve, and
# README.org stays end-user only.  Part of `gmake verify`.
#
#   scripts/check-guides.sh              check the working tree
#   scripts/check-guides.sh --calibrate  plant each fault in a temp copy and
#                                        check it goes red with ITS message
set -u
set -f   # link targets are data: never glob-expand them

REQUIRED="README.org docs/CONTRIBUTING.org docs/RELEASING.org contract/CONSUMERS.org REVIEW.md AGENTS.md docs/COLLABORATION.org contract/CONSUMER-AGENTS.md contract/skill/SKILL.md contract/WORDS.org LICENSE"
# words that mark developer or release-engineering content
README_DEV='gmake|pbt/|experiments/|\.meta/|hypothesis|calibrat|worktree|code-review'

# print each relative link target in a doc, one per line, anchors stripped
links() {
    {
        # org: [[file:target][..]], [[file:target]], [[./target]], [[target.org]]
        grep -o -E '\[\[(file:)?[^]]+\]' "$1" | sed -E 's/^\[\[//; s/\]$//; s/^file://' |
            grep -E '^(file:|\./|\.\./|[^:]+\.(org|md|fs|json|sh|py|txt)(::|$))'
        # markdown: ](target) and ](target#anchor); a ':' means a URL
        grep -o -E '\]\([^): ]+\)' "$1" | sed -E 's/^\]\(//; s/\)$//'
    } 2>/dev/null | sed -E 's/::.*$//; s/#.*$//' | grep -v -E '^$|^/'
}

check() {
    root=$1
    status=0
    for guide in $REQUIRED; do
        [ -f "$root/$guide" ] || { echo "missing guide: $guide"; status=1; }
    done
    docs=$(cd "$root" && find . \( -path ./.git -o -path ./dist \) -prune -o -type f \( -name '*.org' -o -name '*.md' \) -print)
    broken=$(
        printf '%s\n' "$docs" | while IFS= read -r doc; do
            [ -n "$doc" ] || continue
            dir=$(dirname "$root/$doc")
            links "$root/$doc" | while IFS= read -r target; do
                [ -e "$dir/$target" ] || echo "broken link in ${doc#./}: $target"
            done
        done
    )
    if [ -n "$broken" ]; then printf '%s\n' "$broken"; status=1; fi
    if [ -f "$root/README.org" ] && grep -n -i -E "$README_DEV" "$root/README.org"; then
        echo "README.org has developer content (above): it is for end users only"
        status=1
    fi
    return $status
}

copy_tree() {  # tracked and untracked-but-not-ignored files, as in the working tree
    mkdir -p "$2"
    (cd "$1" && git ls-files -z --cached --others --exclude-standard |
        while IFS= read -r -d '' path; do [ -e "$path" ] && printf '%s\0' "$path"; done |
        tar --null -T - -cf -) | (cd "$2" && tar xf -)
}

if [ "${1:-}" = "--calibrate" ]; then
    top=$(git rev-parse --show-toplevel) || exit 2
    tmp=$(mktemp -d)
    fail=0
    copy_tree "$top" "$tmp/clean"
    if ! out=$(check "$tmp/clean"); then
        printf 'false positive on a clean copy:\n%s\n' "$out"; exit 1
    fi
    plant() {  # name, setup command, expected message
        copy_tree "$top" "$tmp/$1"
        (cd "$tmp/$1" && sh -c "$2")
        if out=$(check "$tmp/$1"); then echo "MISSED: $1"; fail=1
        elif printf '%s\n' "$out" | grep -q -F -- "$3"; then echo "red as expected: $1"
        else printf 'red for the wrong reason: %s\n%s\n' "$1" "$out"; fail=1; fi
    }
    plant missing-guide 'mv REVIEW.md REVIEW.md.away' 'missing guide: REVIEW.md'
    plant broken-org-link 'printf "\n[[file:no-such-file.org][x]]\n" >> docs/CONTRIBUTING.org' \
        'broken link in docs/CONTRIBUTING.org: no-such-file.org'
    plant broken-md-anchor-link 'printf "\n[x](CONTRIBUTING.md#style)\n" >> REVIEW.md' \
        'broken link in REVIEW.md: CONTRIBUTING.md'
    plant broken-link-with-space 'printf "\n[[file:design notes.org][x]]\n" >> AGENTS.md' \
        'broken link in AGENTS.md: design notes.org'
    plant broken-link-in-experiment-log \
        'printf "\n[[file:no-such-helper.py][x]]\n" >> experiments/001-stacks-roundtrip/README.org' \
        'broken link in experiments/001-stacks-roundtrip/README.org: no-such-helper.py'
    plant readme-dev 'printf "\nRun gmake -C pbt check.\n" >> README.org' 'README.org has developer content'
    exit $fail
fi

top=$(git rev-parse --show-toplevel) || exit 2
if check "$top"; then echo "check-guides: ok"; else echo "check-guides: failed" >&2; exit 1; fi
