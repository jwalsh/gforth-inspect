#!/bin/sh
# Planted fault for experiment 003: in a temp copy of the model's words.json,
# dup's declared effect becomes ( x -- ).  The sweep must go red, and the only
# unclassified disagreement must be dup.  Exit 0 only in that case.
# Run from pbt/ (gmake -C pbt calibrate does).
set -u
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
ref=${MODEL_REF:-model}
git rev-parse --verify -q "$ref" >/dev/null || ref=origin/model
git show "$ref:model/data/words.json" | python3 -I -c '
import json, sys
model = json.load(sys.stdin)
planted = 0
for record in model["words"]:
    if (record.get("name") or "").lower() == "dup" and record.get("wordlist") == "Forth":
        record["stack"] = "x --"
        record["effect"] = {"data_in": ["x"]}
        planted += 1
assert planted, "no dup record to plant into"
json.dump(model, open(sys.argv[1], "w"))
' "$tmp/words.json" || { echo "calibrate 003: could not plant the fault"; exit 1; }

WORDS_JSON="$tmp/words.json" EFFECTS_REPORT="$tmp/report.json" \
    uv run --no-project --with hypothesis --with jsonschema --with pytest \
    pytest -q -p no:cacheprovider --hypothesis-profile=default test_003_declared_effects.py \
    > "$tmp/pytest.out" 2>&1
status=$?
if [ "$status" -eq 0 ]; then
    echo "calibrate 003: MISSED -- the test stayed green with dup declared ( x -- )"
    exit 1
fi
python3 -I -c '
import json, sys
report = json.load(open(sys.argv[1]))
unclassified, stale = report["unclassified"], report["classified_but_agree"]
if unclassified == ["dup"] and stale == []:
    print("calibrate 003: red as expected, on exactly: dup", report["disagree"]["dup"])
    sys.exit(0)
print("calibrate 003: red, but not on exactly dup:", unclassified, stale)
sys.exit(1)
' "$tmp/report.json"
