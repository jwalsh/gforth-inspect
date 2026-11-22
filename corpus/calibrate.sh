#!/bin/sh
# calibrate.sh -- the corpus gates go red on a planted fault, for the right reason.
#
#   sh corpus/calibrate.sh      (or gmake -C corpus calibrate)
#
# Every plant goes into a temp copy of corpus/, never into the tree:
#   0. control: the unplanted copy's `check` is green (so a red below is the plant's)
#   1. one field changed in a committed .jsonl: `check` is red and names that file only
#   2. a scenario whose log holds $HOME: `record` refuses and leaves the files alone
#   3. the same with a temp path ($TMPDIR, or /tmp/)
# Exits 0 only if every plant was caught.
set -u

corpus=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$corpus/.." && pwd)
scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT
fail=0

fresh_copy() {  # a copy of the corpus without its scratch directories
    rm -rf "$scratch/corpus"
    mkdir "$scratch/corpus"
    (cd "$corpus" && cp Makefile record.py PROVENANCE ./*.fs ./*.jsonl ./*.expect.json "$scratch/corpus/")
}

run_make() {  # target -> output in $scratch/out, status returned
    gmake --no-print-directory -C "$scratch/corpus" "$1" REPO="$repo" > "$scratch/out" 2>&1
}

fingerprint() {
    (cd "$scratch/corpus" && cat ./*.jsonl ./*.expect.json PROVENANCE | git hash-object --stdin)
}

# 0. control
fresh_copy
if run_make check; then echo "control: unplanted copy reproduces"
else echo "CONTROL FAILED: the unplanted copy does not reproduce"; cat "$scratch/out"; exit 1; fi

# 1. a changed field in one recording
fresh_copy
sed 's/"float":\[-0\.0,/"float":[0.0,/' "$corpus/04-floats.jsonl" > "$scratch/corpus/04-floats.jsonl"
if cmp -s "$corpus/04-floats.jsonl" "$scratch/corpus/04-floats.jsonl"; then
    echo "PLANT DID NOT APPLY: 04-floats.jsonl unchanged"; fail=1
elif run_make check; then
    echo "MISSED: check passed with a changed field in 04-floats.jsonl"; fail=1
elif named=$(grep '^check: DIFFERS: ' "$scratch/out") && [ "$named" = "check: DIFFERS: 04-floats.jsonl" ]; then
    echo "red as expected: check names 04-floats.jsonl, and only it"
else
    echo "RED FOR THE WRONG REASON: expected 'check: DIFFERS: 04-floats.jsonl', got:"
    cat "$scratch/out"; fail=1
fi

# 2 and 3. a private path in a recording
plant_path() {  # label path
    fresh_copy
    before=$(fingerprint)
    printf 'log-on\n.stacks \\ %s/planted.fs\nbye\n' "$2" > "$scratch/corpus/99-planted.fs"
    if run_make record; then
        echo "MISSED: record accepted a log holding the $1"; fail=1
    elif ! grep -q '^record: REFUSED' "$scratch/out" || ! grep -q '99-planted.jsonl' "$scratch/out"; then
        echo "RED FOR THE WRONG REASON ($1):"; cat "$scratch/out"; fail=1
    elif [ "$(fingerprint)" != "$before" ] || [ -e "$scratch/corpus/99-planted.jsonl" ]; then
        echo "REFUSED BUT WROTE: record changed the committed files ($1)"; fail=1
    else
        echo "red as expected: record refuses the $1 and leaves the recordings alone"
    fi
}
plant_path "home directory" "$HOME"
temp_dir=${TMPDIR:-/tmp/}
plant_path "temp path" "${temp_dir%/}"

if [ $fail -eq 0 ]; then echo "calibrate: every plant caught"; fi
exit $fail
