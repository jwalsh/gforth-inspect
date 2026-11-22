# 001-lib.inc -- shared by calibrate/001-*.sh (not itself a calibration: no .sh)
#
# plant SED_EXPR into inspect.fs from ${INSPECT_REF:-harden}, run the selected
# 001 tests on the clean copy (control: must pass) and on the planted copy
# (must fail, on exactly EXPECT_FAILED test ids, each message matching
# EXPECT_MESSAGE).  Exit 0 only if all of that holds.

calibrate_001() {
    set -f  # test ids hold [...]; never let the shell glob them
    name=$1 sed_expr=$2 selection=$3 expect_failed=$4 expect_message=$5
    pbt_dir=$(cd "$(dirname "$0")/.." && pwd)
    ref=${INSPECT_REF:-harden}
    work=$(mktemp -d)
    trap 'rm -rf "$work"' EXIT
    git -C "$pbt_dir" show "$ref:env/inspect.fs" > "$work/clean.fs" || return 1
    sed "$sed_expr" "$work/clean.fs" > "$work/planted.fs"
    if cmp -s "$work/clean.fs" "$work/planted.fs"; then
        echo "$name: fault not planted (sed matched nothing in $ref:env/inspect.fs)"; return 1
    fi
    # exactly one line may change: a range that re-opens would over-plant
    changed=$(diff "$work/clean.fs" "$work/planted.fs" | grep -c '^>')
    if [ "$changed" -ne 1 ]; then
        echo "$name: sed changed $changed lines, expected exactly 1"; return 1
    fi
    uv_run="uv run --no-project --with hypothesis --with jsonschema --with pytest"
    cd "$pbt_dir" || return 1
    if ! INSPECT_FS="$work/clean.fs" $uv_run pytest -q -p no:cacheprovider \
            test_001_stacks_roundtrip.py -k "$selection" > "$work/control.txt" 2>&1; then
        echo "$name: control run on the clean copy is red, so a red planted run proves nothing"
        grep -E '^FAILED' "$work/control.txt"; return 1
    fi
    if INSPECT_FS="$work/planted.fs" $uv_run pytest -q -p no:cacheprovider \
            test_001_stacks_roundtrip.py -k "$selection" > "$work/planted.txt" 2>&1; then
        echo "$name: MISSED, the planted fault left the tests green"; return 1
    fi
    failed=$(grep -E '^FAILED ' "$work/planted.txt" | sed 's/^FAILED [^:]*::\([^ ]*\).*/\1/' | sort)
    wanted=$(printf '%s\n' $expect_failed | sort)
    if [ "$failed" != "$wanted" ]; then
        echo "$name: red, but on the wrong tests"
        echo "  expected: $(echo $wanted)"; echo "  got:      $(echo $failed)"; return 1
    fi
    # every assertion that fired must be the expected one, and one must have fired
    asserts=$(grep -E '^E +AssertionError: ' "$work/planted.txt" | sed 's/^E *//')
    bad=$(printf '%s\n' "$asserts" | grep -v -E "AssertionError: $expect_message")
    if [ -z "$asserts" ] || [ -n "$bad" ]; then
        echo "$name: red, but not with the expected message ($expect_message):"
        printf '%s\n' "${bad:-<no AssertionError line>}" | cut -c1-220; return 1
    fi
    echo "$name: red as expected on $(echo "$failed" | wc -l | tr -d ' ') tests: $(echo $failed)"
    printf '%s\n' "$asserts" | sort -u | cut -c1-240 | sed 's/^/  /'
    return 0
}
