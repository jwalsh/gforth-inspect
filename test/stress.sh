#!/usr/bin/env bash
# test/stress.sh FILE... -- load real programs with and without the
# inspector and report any difference.  Read-only: each program runs with
# its own directory as cwd, stdin from /dev/null, a 10 s timeout, and a
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
ROOT=$(cd "$(dirname "$0")/.." && pwd)
ENGINES=${ENGINES:-gforth gforth-fast gforth-itc}
WORK=$(mktemp -d "${TMPDIR:-/tmp}"/gforth-inspect-stress.XXXXXX); WORK=${WORK//\/\//\/}
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/home" "$WORK/state" "$WORK/log"
# names the inspector defines
grep -Eo '^(: |variable |create |[0-9]+ constant |2variable )[^ ]+' \
    "$ROOT/env/inspect.fs" | awk '{print $NF}' | sort -u > "$WORK/names"

run() { # engine file mode
  local dir; dir=$(dirname "$2")
  local -a pre=()
  case $3 in
    inspect) pre=("$ROOT/env/inspect.fs") ;;
    logging) pre=("$ROOT/env/inspect.fs" -e "log-on all-~~") ;;
  esac
  (cd "$dir" && env HOME="$WORK/home" XDG_STATE_HOME="$WORK/state" \
      GFORTH_INSPECT_LOG_DIR="$WORK/log" timeout 10 "$1" "${pre[@]}" "$2" -e bye \
      < /dev/null 2>&1; echo "## exit $?") \
    | MASK_TMP=$WORK perl "$ROOT/test/mask.pl"
}

files=0 diffs=0 clashes=0
for f in "$@"; do
  files=$((files + 1))
  for e in $ENGINES; do
    run "$e" "$f" plain > "$WORK/a"
    for mode in inspect logging; do
      run "$e" "$f" $mode > "$WORK/b"
      grep -o 'redefined [^ ]*' "$WORK/b" | awk '{print $2}' | sort -u > "$WORK/redef"
      c=$(comm -12 "$WORK/redef" "$WORK/names" | tr '\n' ' ')
      if [ -n "$c" ]; then
        echo "CLASH $e $mode $f: redefines inspector word(s) $c"; clashes=$((clashes + 1))
      fi
      if ! cmp -s "$WORK/a" "$WORK/b"; then
        echo "DIFF $e $mode $f"; diff "$WORK/a" "$WORK/b" | head -12; diffs=$((diffs + 1))
      fi
    done
  done
done
echo "stress: $files file(s) x engines [$ENGINES] x 2 modes: $diffs diff(s), $clashes clash(es)"
[ $diffs = 0 ]
