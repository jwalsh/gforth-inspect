#!/usr/bin/env bash
# calibrate.sh -- plant faults in 0.7.3 probe output and check that
# summarize.sh turns each one into the verdict it should (gate 3: a
# harness that cannot say "fails" on 0.7.3 cannot say it on 1.0 either).
#
#   calibrate.sh            stock gforth on PATH (0.7.3); exit 0 = all as expected
#
# One real run (probe.sh, engine gforth) is the base.  Each planted run is
# a copy of one base output with one change:
#   same       unchanged                                       -> works
#   warning    a 1.0-style warning line added to stderr        -> works
#   underflow  0.7.3's "probe.fs:3: Stack underflow", >>>t<<< and
#              Backtrace: added to stderr, exit status left 0  -> errors
#   exit       exit status 1                                   -> errors
#   stdout     one stdout digit changed                        -> wrong
#   stderr     ~~'s "in inner" on stderr made "in outer"       -> wrong
#   log        one log value changed                           -> wrong
#   nobase     a probe the base does not have                  -> nobase
# plus one real planted probe, a stack underflow in a word     -> errors
set -u -o pipefail
here=$(cd "$(dirname "$0")" && pwd)
work=$(mktemp -d "${TMPDIR:-/tmp}/gfi010cal.XXXXXX")
trap 'rm -rf "$work"' EXIT
printf ': t drop ;\nt\n' > "$work/underflow-real.fs"
bash "$here/probe.sh" -o "$work/base" -e gforth \
  "$here/probes/tilde3.fs" "$here/probes/log.fs" > /dev/null || exit 1
bash "$here/probe.sh" -o "$work/underflow-real" -e gforth "$work/underflow-real.fs" > /dev/null || exit 1
plant() { # run probe perl-expression
  mkdir -p "$work/$1/gforth"
  perl -0pe "$3" "$work/base/gforth/$2.out" > "$work/$1/gforth/$2.out" || exit 1
}
plant same      tilde3 ''
plant warning   tilde3 's/^## stderr\n/## stderr\ninspect.fs:40:5: warning: name>int is obsolete\n/m'
plant underflow tilde3 's/^## stderr\n/## stderr\nprobe.fs:3: Stack underflow\n>>>t<<<\nBacktrace:\n/m'
plant exit      tilde3 's/^## exit 0$/## exit 1/m'
plant stdout    tilde3 's/^10 $/11 /m'
plant stderr    tilde3 's/ in inner / in outer /'
plant log       log    's/"data":\[1,2\]/"data":[1,3]/'
mkdir -p "$work/nobase/gforth"
cp "$work/base/gforth/tilde3.out" "$work/nobase/gforth/new-probe.out"
for f in "$work"/*/gforth/*.out; do cmp -s "$f" "$work/base/gforth/$(basename "$f")" || continue
  case $f in */same/*|*/base/*) ;; *) echo "plant had no effect: $f" >&2; exit 1 ;; esac
done
expect="same works
warning works
underflow errors
exit errors
stdout wrong
stderr wrong
log wrong
nobase nobase
underflow-real errors"
got=$(bash "$here/summarize.sh" "$work/base" \
        "$work"/{same,warning,underflow,exit,stdout,stderr,log,nobase,underflow-real} |
      awk -F'\t' 'NR > 1 { print $1, $5 }') || exit 1
if [ "$got" = "$expect" ]; then
  echo "calibrated: $(printf '%s\n' "$expect" | wc -l | tr -d ' ') planted runs, each with its expected verdict"
else
  echo "MISCALIBRATED"; diff <(printf '%s\n' "$expect") <(printf '%s\n' "$got"); exit 1
fi
