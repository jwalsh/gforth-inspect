#!/bin/sh
# 005 calibration: test_concurrent_producers on harden's inspect.fs, unpatched
# (the fault is the one in issue #17, already there) must go red on every
# engine with a parse failure or a lost record; on a copy with the proposed
# seek-before-write fix it must go green.  --runxfail lifts the #17 xfail so
# the red is visible.  Exit 0 only if all of that holds.
set -f  # test ids hold [...]; never let the shell glob them
name="005 no seek per write"
pbt_dir=$(cd "$(dirname "$0")/.." && pwd)
ref=${INSPECT_REF:-harden}
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
uv_run="uv run --no-project --with hypothesis --with jsonschema --with pytest"
cd "$pbt_dir" || exit 1

git show "$ref:env/inspect.fs" > "$work/unpatched.fs" || exit 1
fix_sed=$($uv_run python -c 'import _005_helpers; print(_005_helpers.FIX_SED)') || exit 1
sed "$fix_sed" "$work/unpatched.fs" > "$work/patched.fs"
changed=$(diff "$work/unpatched.fs" "$work/patched.fs" | grep -c '^>')
if [ "$changed" -ne 1 ]; then
    echo "$name: the fix sed changed $changed lines of $ref:env/inspect.fs, expected exactly 1"
    echo "  (if $ref already seeks before every write, retire this calibration)"; exit 1
fi

if ! INSPECT_FS="$work/patched.fs" $uv_run pytest -q -p no:cacheprovider \
        test_005_concurrent_producers.py -k test_concurrent_producers > "$work/patched.txt" 2>&1; then
    echo "$name: the patched copy is red, so a red unpatched run proves nothing"
    grep -E '^(FAILED|E +AssertionError)' "$work/patched.txt" | cut -c1-240; exit 1
fi
if ! grep -q 'seeks before every write' "$work/patched.txt"; then
    echo "$name: the patched copy was not detected as fixed (xfail still applied?)"; exit 1
fi

if INSPECT_FS="$work/unpatched.fs" $uv_run pytest -q -p no:cacheprovider --runxfail \
        test_005_concurrent_producers.py -k test_concurrent_producers > "$work/unpatched.txt" 2>&1; then
    echo "$name: MISSED, unpatched $ref left the tests green"; exit 1
fi
failed=$(grep -E '^FAILED ' "$work/unpatched.txt" | sed 's/^FAILED [^:]*::\([^ ]*\).*/\1/' | sort)
wanted=$(printf '%s\n' "test_concurrent_producers[gforth]" "test_concurrent_producers[gforth-fast]" \
    "test_concurrent_producers[gforth-itc]" | sort)
if [ "$failed" != "$wanted" ]; then
    echo "$name: red, but on the wrong tests"
    echo "  expected: $(echo $wanted)"; echo "  got:      $(echo $failed)"; exit 1
fi
asserts=$(grep -E '^E +AssertionError: ' "$work/unpatched.txt" | sed 's/^E *//')
expect='AssertionError: 005 producer obligation 1 broken on .* (parse failures [1-9][0-9]*|.* lost [1-9][0-9]*) '
bad=$(printf '%s\n' "$asserts" | grep -v -E "$expect")
if [ -z "$asserts" ] || [ -n "$bad" ]; then
    echo "$name: red, but not with a parse failure or a lost record:"
    printf '%s\n' "${bad:-<no AssertionError line>}" | cut -c1-240; exit 1
fi
echo "$name: red as expected on $(echo "$failed" | wc -l | tr -d ' ') tests: $(echo $failed); green on the patched copy"
printf '%s\n' "$asserts" | sort -u | cut -c1-200 | sed 's/^/  /'
exit 0
