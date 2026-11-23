#!/usr/bin/env bash
# summarize.sh -- one TSV row per (run, engine, probe) from probe.sh output
#
#   summarize.sh BASEDIR RUNDIR...
#     BASEDIR  probe.sh output of the reference (0.7.3)
#     RUNDIR   probe.sh output to judge; its basename names the run
#
# verdict: errors  exit status not 0, or stderr has an error: 1.0's
#                  "file:line:col: error:", or the ">>>word<<<" line and
#                  "Backtrace:" that both versions print after any error
#                  (0.7.3's "file:line: Stack underflow" has no "error")
#          nobase  no BASEDIR output for this probe and engine to compare with
#          wrong   exit 0, no error, and stdout, stderr or the log differs
#                  from BASEDIR's (same engine; gforth-ditc is compared with
#                  gforth-itc)
#          works   exit 0, no error, stdout, stderr and log identical to
#                  BASEDIR's
# Before comparing, version strings (0.7.3, 1.0.0, 1.0.1) are masked, and
# warning lines and blank lines are dropped from stderr (load warnings are
# reported in the last column, not judged).
set -u
base=$1; shift
section() { LC_ALL=C sed -n "/^## $2\$/,/^## /p" "$1" | LC_ALL=C sed '1d;$d'; }
unversion() { LC_ALL=C sed -E 's/(0\.7\.3|1\.0\.[0-9])/VERSION/g'; }
judged() { # out-file: the parts of a run that the verdict compares
  echo "## stdout"; section "$1" stdout
  echo "## stderr"; section "$1" stderr | LC_ALL=C grep -v -e 'warning: ' -e '^redefined ' -e '^ *$'
  echo "## log"; section "$1" log
}
errline='error|Undefined|Only works|exception|^Backtrace:|>>>.*<<<'
printf 'run\tengine\tprobe\texit\tverdict\tfirst error or warning\n'
for run in "$@"; do
  for dir in "$run"/*/; do
    engine=$(basename "$dir")
    ref=$engine; [ "$engine" = gforth-ditc ] && ref=gforth-itc
    for out in "$dir"*.out; do
      probe=$(basename "$out" .out)
      baseout="$base/$ref/$probe.out"
      rc=$(LC_ALL=C sed -n 's/^## exit //p' "$out")
      err=$(section "$out" stderr | LC_ALL=C grep -v 'warning: ' | LC_ALL=C grep -m1 -E "$errline" || true)
      warn=$(section "$out" stderr | LC_ALL=C grep -m1 -E 'warning|^redefined ' || true)
      if [ "$rc" != 0 ] || [ -n "$err" ]; then verdict=errors
      elif [ ! -f "$baseout" ]; then verdict=nobase
      elif cmp -s <(judged "$out" | unversion) <(judged "$baseout" | unversion)
      then verdict=works
      else verdict=wrong; fi
      note=${err:-$warn}
      printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$(basename "$run")" "$engine" "$probe" "$rc" "$verdict" "$note"
    done
  done
done
