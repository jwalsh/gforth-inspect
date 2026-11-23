#!/bin/sh
# 002 (a): plant "json-str does not escape \" and require the ascii class
# to go red on every engine with a JSON or text failure.  Exit 0 only then.
. "$(dirname "$0")/ref-show.lib"
set -eu
pbt=$(cd "$(dirname "$0")/.." && pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
ref_show "${INSPECT_REF:-HEAD}" env/inspect.fs > "$tmp/clean.fs"
# the first -e is json-chars from inspect 0.1.0, the second json-str
# from harden@b1c162e; one of them has to match (checked below)
sed -e 's/r@ \[char\] " = r@ \[char\] \\ = or IF r@ jesc 1/r@ [char] " = IF r@ jesc 1/' \
    -e 's/ over \[char\] \\ = or IF \[char\] \\ emit THEN/ IF [char] \\ emit THEN/' \
    "$tmp/clean.fs" > "$tmp/inspect.fs"
if cmp -s "$tmp/clean.fs" "$tmp/inspect.fs"; then
    echo "002-a: sed planted nothing; json-str changed shape?"; exit 1
fi
cd "$pbt"
INSPECT_FS="$tmp/inspect.fs" uv run -q --no-project --with hypothesis --with jsonschema --with pytest \
    pytest -q -p no:cacheprovider --hypothesis-profile=default --junitxml="$tmp/junit.xml" \
    -k 'escaping_ascii' test_002_escaping.py > "$tmp/pytest.out" 2>&1 || true
uv run -q --no-project --with hypothesis --with jsonschema python -c '
import sys
from _002_helpers import calibration_verdict
sys.exit(calibration_verdict(sys.argv[1],
    must_fail={f"test_escaping_ascii_{e}": "[json]" for e in ("gforth", "gforth_fast", "gforth_itc")},
    must_pass=[]))' "$tmp/junit.xml"
