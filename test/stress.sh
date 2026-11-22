#!/usr/bin/env bash
# test/stress.sh FILE... -- load real programs with and without the
# inspector and report any difference.  Read-only: each program runs with
# its own directory as cwd, stdin from /dev/null, a 10 s limit, and a
# throwaway HOME/XDG_STATE_HOME/GFORTH_INSPECT_LOG_DIR.
#
#   plain    gforth FILE -e bye
#   inspect  gforth env/inspect.fs FILE -e bye
#   logging  gforth env/inspect.fs -e "log-on all-~~" FILE -e bye
#
# Outputs are masked (addresses, temp paths) and must be identical; the
# only allowed extra output is a "redefined X" warning for a word the
# program itself defines twice.  A program redefining one of the
# inspector's own words is reported as a CLASH (harmless to the program,
# which sees its own definition, but it shadows the inspector word).
#   ENGINES="gforth gforth-fast gforth-itc"
set -u
[ $# -gt 0 ] || { echo "usage: test/stress.sh FILE..." >&2; exit 2; }
ROOT=$(cd "$(dirname "$0")/.." && pwd)
ENGINES=${ENGINES:-gforth gforth-fast gforth-itc}
WORK=$(mktemp -d "${TMPDIR:-/tmp}"/gforth-inspect-stress.XXXXXX); WORK=${WORK//\/\//\/}
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/home" "$WORK/state" "$WORK/log"
# the same 10 s limit as test/run.sh: stock macOS has no timeout(1)
if command -v timeout >/dev/null; then LIMIT=(timeout 10)
elif command -v gtimeout >/dev/null; then LIMIT=(gtimeout 10)
else LIMIT=(perl -e 'alarm shift; exec @ARGV or die "exec $ARGV[0]: $!\n"' 10); fi
# every name the inspector defines, wherever it sits on a line
grep -Eo '(: |variable |create |[0-9]+ constant |2variable |value |defer )[^ ]+' \
    "$ROOT/env/inspect.fs" | awk '{print $NF}' | sort -u > "$WORK/names"

run() { # engine program mode
  local engine=$1 program_dir program_name
  program_dir=$(cd "$(dirname "$2")" && pwd); program_name=$(basename "$2")
  local -a preload=()
  case $3 in
    inspect) preload=("$ROOT/env/inspect.fs") ;;
    logging) preload=("$ROOT/env/inspect.fs" -e "log-on all-~~") ;;
  esac
  (cd "$program_dir" && env HOME="$WORK/home" XDG_STATE_HOME="$WORK/state" \
      GFORTH_INSPECT_LOG_DIR="$WORK/log" "${LIMIT[@]}" "$engine" ${preload[@]+"${preload[@]}"} "$program_name" -e bye \
      < /dev/null 2>&1; echo "## exit $?") \
    | MASK_TMP=$WORK perl "$ROOT/test/mask.pl"
}

files=0 diffs=0 clashes=0
for program in "$@"; do
  [ -f "$program" ] || { echo "stress: no such file: $program" >&2; exit 2; }
  files=$((files + 1))
  for engine in $ENGINES; do
    run "$engine" "$program" plain > "$WORK/a"
    for mode in inspect logging; do
      run "$engine" "$program" $mode > "$WORK/b"
      grep -o 'redefined [^ ]*' "$WORK/b" | awk '{print $2}' | sort -u > "$WORK/redef"
      clashing_names=$(comm -12 "$WORK/redef" "$WORK/names" | tr '\n' ' ')
      if [ -n "$clashing_names" ]; then
        echo "CLASH $engine $mode $program: redefines inspector word(s) $clashing_names"; clashes=$((clashes + 1))
      fi
      if ! cmp -s "$WORK/a" "$WORK/b"; then
        echo "DIFF $engine $mode $program"; diff "$WORK/a" "$WORK/b" | head -12; diffs=$((diffs + 1))
      fi
    done
  done
done
echo "stress: $files file(s) x engines [$ENGINES] x 2 modes: $diffs diff(s), $clashes clash(es)"
[ $diffs = 0 ]
