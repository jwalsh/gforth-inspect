#!/bin/sh
# Planted fault for experiment 003 (#72): the sweep runs as if on a platform
# with no measured exclusion set (EFFECTS_PLATFORM).  The exclusion test must
# go red saying there is no set for it, rather than fall back to another
# platform's, and the other four tests must stay green.  Exit 0 only then.
# Run from pbt/ (gmake -C pbt calibrate does).
set -u
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
planted=calibrate-unmeasured-platform
EFFECTS_PLATFORM="$planted" EFFECTS_REPORT="$tmp/report.json" \
    uv run --no-project --with hypothesis --with jsonschema --with pytest \
    pytest -q -p no:cacheprovider --hypothesis-profile=default -rf test_003_declared_effects.py \
    > "$tmp/pytest.out" 2>&1
status=$?
if [ "$status" -eq 0 ]; then
    echo "calibrate 003-b: MISSED -- the test stayed green on platform $planted"
    exit 1
fi
python3 -I -c '
import json, re, sys
report, out, planted = json.load(open(sys.argv[1])), open(sys.argv[2]).read(), sys.argv[3]
failed = sorted(set(re.findall(r"^FAILED \S+::(\w+)", out, re.M)))
said = f"no measured exclusion set for platform {planted!r}" in out
if report["platform"] == planted and report["exclusions_diff"] is None \
        and failed == ["test_measured_exclusions_are_known"] and said \
        and re.search(r"^1 failed, 4 passed\b", out, re.M):
    print(f"calibrate 003-b: red as expected, on exactly: no exclusion set for {planted}")
    sys.exit(0)
print("calibrate 003-b: red, but not for the planted platform:", report["platform"],
      report["exclusions_diff"], failed, "message seen" if said else "message missing")
sys.exit(1)
' "$tmp/report.json" "$tmp/pytest.out" "$planted"
