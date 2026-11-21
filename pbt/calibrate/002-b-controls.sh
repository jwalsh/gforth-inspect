#!/bin/sh
# 002 (b): plant "json-str leaves control bytes raw" (0.1.0: the \u00XX
# branch emits the byte; 18ebe2d: no mapping to a space) and require the
# controls class to go red on every engine with json.loads rejecting a
# control character, while the ascii class stays green (the fault must
# be what turned it red).  Exit 0 only then.
set -eu
pbt=$(cd "$(dirname "$0")/.." && pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
git -C "$pbt" show "${INSPECT_REF:-harden}:env/inspect.fs" > "$tmp/clean.fs"
# the first -e is json-chars from inspect 0.1.0, the second json-str
# from harden@18ebe2d; one of them has to match (checked below)
sed -e 's/ELSE r@ bl < IF \[char\] u jesc r@ \.hex4 1/ELSE r@ bl < IF r@ emit 1/' \
    -e 's/dup bl < IF drop bl THEN //' \
    "$tmp/clean.fs" > "$tmp/inspect.fs"
if cmp -s "$tmp/clean.fs" "$tmp/inspect.fs"; then
    echo "002-b: sed planted nothing; json-str changed shape?"; exit 1
fi
cd "$pbt"
INSPECT_FS="$tmp/inspect.fs" uv run -q --no-project --with hypothesis --with jsonschema --with pytest \
    pytest -q -p no:cacheprovider --hypothesis-profile=default --junitxml="$tmp/junit.xml" \
    -k 'escaping_controls or escaping_ascii' test_002_escaping.py > "$tmp/pytest.out" 2>&1 || true
uv run -q --no-project --with hypothesis --with jsonschema python -c '
import sys
from _002_helpers import calibration_verdict
engines = ("gforth", "gforth_fast", "gforth_itc")
sys.exit(calibration_verdict(sys.argv[1],
    must_fail={f"test_escaping_controls_{e}": "Invalid control character" for e in engines},
    must_pass=[f"test_escaping_ascii_{e}" for e in engines]))' "$tmp/junit.xml"
