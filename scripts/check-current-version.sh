#!/usr/bin/env bash
# check-current-version.sh -- the docs name the release and the contract they
# describe, and verify keeps them true.  Part of `gmake verify`.
#
# A sentence about the current release marks it "X.Y.Z (this release)"; one
# about the current contract marks it "M.N (this release)".  The marker stays
# true in a vendored copy of a shipped asset, where "current" would not.  Each
# X.Y.Z must equal env/inspect.fs's version (its header line, its doc comment
# and inspect-version, which must agree), and each M.N its contract-version and
# the schema's x-contract (which must agree).  README's Install section is
# scripts/readme-release.sh's: it names the latest *published* tag.
#
#   scripts/check-current-version.sh              check the working tree
#   scripts/check-current-version.sh --calibrate  plant each fault in a temp
#                                                 copy; each must go red with
#                                                 its own message
set -u -o pipefail

# the docs a user or consumer reads; history (experiments/, .meta/, logs) is not here
DOCS="README.org AGENTS.md REVIEW.md docs contract"

one() {  # name, then values: all must be one non-empty value, printed once
    name=$1; shift
    uniq=$(printf '%s\n' "$@" | sort -u)
    if [ -z "$uniq" ] || [ "$(printf '%s\n' "$uniq" | wc -l)" -ne 1 ]; then
        echo "check-current-version: $name disagree or are missing: $*" >&2; return 1
    fi
    printf '%s\n' "$uniq"
}

check() {
    root=$1
    fs=$root/env/inspect.fs schema=$root/contract/stacks-log.schema.json
    [ -f "$fs" ] && [ -f "$schema" ] || { echo "check-current-version: no $fs or $schema"; return 1; }
    release=$(one "inspect.fs's version (header, doc comment, inspect-version)" \
        "$(sed -n 's/^\\ gforth-inspect v//p' "$fs")" \
        "$(sed -n 's/^\\   inspect-version  ( -- c-addr u )  "\(.*\)"$/\1/p' "$fs")" \
        "$(sed -n 's/^: inspect-version ( -- c-addr u ) s" \(.*\)" ;$/\1/p' "$fs")") || return 1
    contract=$(one "the contract version (contract-version, schema x-contract)" \
        "$(sed -n 's/^: contract-version ( -- c-addr u ) s" \([0-9.]*\)" ;.*/\1/p' "$fs")" \
        "$(sed -n 's/^ *"x-contract": "\(.*\)",*$/\1/p' "$schema")") || return 1
    for doc in $DOCS; do
        [ -e "$root/$doc" ] || { echo "check-current-version: $doc is gone; update DOCS"; return 1; }
    done
    # one line per marker: file TAB value-or-? ; perl -0777 because prose wraps
    found=$(cd "$root" && find $DOCS \( -name '*.org' -o -name '*.md' \) -type f -print0 |
        xargs -0 perl -0777 -ne '
            while (/(\S*)\s+\(this\s+release\)/gi) {
                my $token = $1;
                next if $token =~ /^["=~`]*(X\.Y\.Z|M\.N)$/;  # the template, in the release steps
                my $value = $token =~ /^[=~`]?v?(\d+\.\d+(?:\.\d+)?)[=~`]?$/ ? $1 : "?$token";
                print "$ARGV\t$value\n";
            }') || { echo "check-current-version: could not read the docs"; return 1; }
    [ -n "$found" ] || { echo "check-current-version: no 'X.Y.Z (this release)' in $DOCS"; return 1; }
    bad=$(printf '%s\n' "$found" | awk -F'\t' -v rel="$release" -v con="$contract" '
        $2 ~ /^\?/                          { print $1 ": (this release) after " substr($2, 2) ", not a version"; next }
        $2 ~ /^[0-9]+\.[0-9]+\.[0-9]+$/ && $2 != rel { print $1 ": says " $2 " (this release); inspect.fs is " rel; next }
        $2 ~ /^[0-9]+\.[0-9]+$/ && $2 != con         { print $1 ": says contract " $2 " (this release); the contract is " con }')
    if [ -n "$bad" ]; then
        printf '%s\n' "$bad" | sed 's/^/check-current-version: /'
        return 1
    fi
    echo "check-current-version: $(printf '%s\n' "$found" | wc -l | tr -d ' ') mentions name $release / contract $contract"
}

calibrate() {
    top=$(git rev-parse --show-toplevel) || exit 2
    status=0
    plant() {  # name, expected message, then a command that plants the fault in $work
        name=$1 want=$2; shift 2
        work=$(mktemp -d)
        (cd "$top" && tar cf - env/inspect.fs $DOCS) | (cd "$work" && tar xf -) || { echo "calibrate: copy failed"; exit 2; }
        (cd "$work" && "$@")
        out=$(check "$work" 2>&1); rc=$?
        if [ $rc -ne 0 ] && printf '%s' "$out" | grep -qF -- "$want"; then
            echo "red as expected: $name"
        else
            echo "NOT red for the right reason: $name: $out"; status=1
        fi
        rm -r "$work"
    }
    bump_all() { perl -pi -e 's/(?<![\d.])\d+\.\d+\.\d+(?![\d.])/99.0.0/ if /gforth-inspect v|inspect-version/' env/inspect.fs; }
    bump_word() { perl -pi -e 's/s" \d+\.\d+\.\d+"/s" 99.0.0"/ if /^: inspect-version/' env/inspect.fs; }
    bump_contract() { perl -pi -e 's/"x-contract": "[\d.]+"/"x-contract": "1.9"/' contract/stacks-log.schema.json; }
    wrapped() { printf '\nOld text: =v1.2.3= (this\nrelease).\n' >> docs/RELEASING.org; }
    stale_contract() { printf '\nIt announces contract 1.0 (this release).\n' >> contract/CONSUMERS.org; }
    unparsed() { printf '\nThe newest one (this release).\n' >> docs/RELEASING.org; }
    none() { find $DOCS \( -name '*.org' -o -name '*.md' \) -type f -exec perl -0pi -e 's/\(this(\s+)release\)/(that$1one)/g' {} +; }
    gone() { rm REVIEW.md; }
    spaced() { printf 'Notes: 1.2.3 (this release).\n' > "docs/release notes.org"; }
    plant "inspect.fs bumped, docs not" "inspect.fs is 99.0.0" bump_all
    plant "inspect-version bumped alone" "inspect.fs's version (header, doc comment, inspect-version) disagree" bump_word
    plant "schema x-contract bumped alone" "the contract version (contract-version, schema x-contract) disagree" bump_contract
    plant "a stale =v1.2.3= marker wrapped across lines" "says 1.2.3 (this release)" wrapped
    plant "a stale contract marker" "says contract 1.0 (this release)" stale_contract
    plant "a marker after a word, not a version" "(this release) after one, not a version" unparsed
    plant "no marker at all" "no 'X.Y.Z (this release)'" none
    plant "a DOCS entry removed" "REVIEW.md is gone" gone
    plant "a stale marker in a file name with a space" "docs/release notes.org: says 1.2.3 (this release)" spaced
    out=$(check "$top" 2>&1) && echo "green as expected: the tree ($out)" || { echo "tree is red: $out"; status=1; }
    return $status
}

case "${1:-}" in
    --calibrate) calibrate ;;
    "") top=$(git rev-parse --show-toplevel) || exit 2; check "$top" ;;
    *) echo "usage: $0 [--calibrate]" >&2; exit 2 ;;
esac
