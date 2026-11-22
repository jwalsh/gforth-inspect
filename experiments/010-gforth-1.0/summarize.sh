#!/usr/bin/env bash
# summarize.sh -- one TSV row per (run, engine, probe) from probe.sh output
#
#   summarize.sh BASEDIR RUNDIR...
#     BASEDIR  probe.sh output of the reference (0.7.3)
#     RUNDIR   probe.sh output to judge; its basename names the run
#
# verdict: errors  exit status not 0, or stderr has an error
#          wrong   exit 0, no error, stdout differs from BASEDIR's (same
#                  engine; gforth-ditc is compared with gforth-itc)
#          works   exit 0, no error, stdout identical to BASEDIR's
# Version strings (0.7.3, 1.0.0, 1.0.1) are masked before comparing.
set -u
base=$1; shift
section() { LC_ALL=C sed -n "/^## $2\$/,/^## /p" "$1" | LC_ALL=C sed '1d;$d'; }
unversion() { LC_ALL=C sed -E 's/(0\.7\.3|1\.0\.[0-9])/VERSION/g'; }
printf 'run\tengine\tprobe\texit\tverdict\tfirst error or warning\n'
for run in "$@"; do
  for dir in "$run"/*/; do
    engine=$(basename "$dir")
    ref=$engine; [ "$engine" = gforth-ditc ] && ref=gforth-itc
    for out in "$dir"*.out; do
      probe=$(basename "$out" .out)
      rc=$(LC_ALL=C sed -n 's/^## exit //p' "$out")
      err=$(section "$out" stderr | LC_ALL=C grep -m1 -E 'error|Undefined|Only works|exception' || true)
      warn=$(section "$out" stderr | LC_ALL=C grep -m1 -E 'warning' || true)
      if [ "$rc" != 0 ] || [ -n "$err" ]; then verdict=errors
      elif cmp -s <(section "$out" stdout | unversion) <(section "$base/$ref/$probe.out" stdout | unversion)
      then verdict=works
      else verdict=wrong; fi
      note=${err:-$warn}
      printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$(basename "$run")" "$engine" "$probe" "$rc" "$verdict" "$note"
    done
  done
done
