#!/usr/bin/env bash
# test/selftest.sh -- the runner must fail loudly: each fixture in
# test/selftest/ must make test/run.sh exit non-zero, even with -u (which
# refuses to bless a problem), and a passing test with a corrupted golden
# must fail too.
set -u
cd "$(dirname "$0")/.."
exp=$(mktemp -d "${TMPDIR:-/tmp}"/gforth-inspect-selftest.XXXXXX)
trap 'rm -rf "$exp"' EXIT
bad=0
for t in test/selftest/assert-fails.fs test/selftest/bad-log.fs \
         test/selftest/error-exit.fs test/selftest/redefines.fs; do
  if EXPECTED=$exp test/run.sh -u -e gforth "$t" > "$exp/log" 2>&1; then
    echo "selftest: $t passed, but must fail"; bad=1
  else
    echo "selftest: $t fails as it must: $(grep -m1 '^FAIL' "$exp/log" | cut -c1-90)"
  fi
done
EXPECTED=$exp test/run.sh -u -e gforth test/selftest/pass.fs > "$exp/log" 2>&1 \
  || { echo "selftest: pass.fs should pass"; cat "$exp/log"; bad=1; }
echo "tampered" >> "$exp/pass.out"
if EXPECTED=$exp test/run.sh -e gforth test/selftest/pass.fs > "$exp/log" 2>&1; then
  echo "selftest: a corrupted golden passed"; bad=1
else
  echo "selftest: corrupted golden fails as it must"
fi
# The checkout's own .env must not reach the goldens (run.sh runs every
# test in a fixture checkout under its temp dir): a copy of the tree with
# a .env opt-out still passes, and nothing appears where that .env points.
copy=$exp/checkout
mkdir -p "$copy"
git ls-files -z | tar --null -T - -cf - | (cd "$copy" && tar xf -)
printf 'GFORTH_INSPECT_LOG_DIR=logs-from-dotenv\n' > "$copy/.env"
if (cd "$copy" && test/run.sh -e gforth test/version.fs test/log-records.fs test/log-dir-home.fs) > "$exp/log" 2>&1 \
   && [ ! -e "$copy/logs-from-dotenv" ]; then
  echo "selftest: a .env in the checkout does not move the goldens' logs"
else
  echo "selftest: a .env in the checkout reached the goldens"; tail -5 "$exp/log"; bad=1
fi
exit $bad
