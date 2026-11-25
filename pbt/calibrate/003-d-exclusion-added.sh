#!/bin/sh
# Planted fault for experiment 003 (#72), the other direction from 003-c: in
# a temp copy of the model's words.json, @ is declared ( w -- w ) instead of
# ( a-addr -- w ), so it is given 0, 1, -1, 100 ... as addresses and throws
# (-9) on every platform measured.  The measured `threw` set is then one
# larger than this platform's, the shape #72 took, and the exact comparison
# must go red on exactly that: threw with @ extra, nothing else.  A superset
# or union check would stay green.  Exit 0 only in that case.
# Run from pbt/ (gmake -C pbt calibrate does).
. "$(dirname "$0")/ref-show.lib"
set -u
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
ref=${MODEL_REF:-5e3eede}  # pinned in fixtures/refs/5e3eede/, as _003_helpers.MODEL_PINNED
ref_show "$ref" model/data/words.json | python3 -I -c '
import json, sys
model = json.load(sys.stdin)
planted = 0
for record in model["words"]:
    if record.get("name") == "@" and record.get("wordlist") == "Forth":
        record["stack"] = "w -- w"
        record["effect"] = {"data_in": ["w"], "data_out": ["w"]}
        planted += 1
assert planted, "no @ record to plant into"
json.dump(model, open(sys.argv[1], "w"))
' "$tmp/words.json" || { echo "calibrate 003-d: could not plant the fault"; exit 1; }

MODEL_REF="$ref" WORDS_JSON="$tmp/words.json" EFFECTS_REPORT="$tmp/report.json" \
    uv run --no-project --with hypothesis --with jsonschema --with pytest \
    pytest -q -p no:cacheprovider --hypothesis-profile=default -rf test_003_declared_effects.py \
    > "$tmp/pytest.out" 2>&1
status=$?
if [ "$status" -eq 0 ]; then
    echo "calibrate 003-d: MISSED -- the test stayed green with @ given non-addresses"
    exit 1
fi
python3 -I -c '
import json, re, sys
report, out = json.load(open(sys.argv[1])), open(sys.argv[2]).read()
failed = sorted(set(re.findall(r"^FAILED \S+::(\w+)", out, re.M)))
want = {"threw": {"extra": ["@"], "missing": []}}
if report["exclusions_diff"] == want and failed == ["test_measured_exclusions_are_known"]:
    print("calibrate 003-d: red as expected, on exactly:", report["platform"], "threw with @ extra")
    sys.exit(0)
print("calibrate 003-d: red, but not on exactly @:", report["platform"],
      report["exclusions_diff"], failed)
sys.exit(1)
' "$tmp/report.json" "$tmp/pytest.out"
