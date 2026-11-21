#!/bin/sh
# lldb/check.sh -- rerun every claim in lldb/README.org, transcripts to lldb/log/
# Must run where debugserver may attach (not inside a task_for_pid sandbox).
set -u
cd "$(dirname "$0")/.."
log=lldb/log; mkdir -p "$log"
for e in gforth gforth-fast gforth-itc; do
  lldb/demo.sh "$e"        > "$log/brk-$e.txt" 2>&1
  lldb/prim-break.sh "$e"  > "$log/prim-$e.txt" 2>&1
  lldb/attach.sh "$e"      > "$log/attach-$e.txt" 2>&1
  "$e" env/inspect.fs test/demo-env.fs -e bye > "$log/env-$e.txt" 2>&1
  printf '%20s' | "$e" env/inspect.fs test/dbg-demo.fs > "$log/dbgplus-$e.txt" 2>&1
  printf '%20s' | "$e" -e ': sq dup * ; : t 3 sq 2.5e 2e f* drop ; dbg t cr .s f.s bye' \
      > "$log/dbg-stock-$e.txt" 2>&1
done
for b in g O0; do
  G=vendor/build-$b
  [ -x "$G/gforth" ] || continue
  /usr/bin/lldb -b -o "command script import lldb/gforth.py" -o "fbrk" -o "run" \
    -o "breakpoint disable 1" -o "fbreak-prim f*" -o "continue" \
    -o "frame variable sp fp ip lp" -o "fregs" -o "fstacks" -o "kill" \
    -- "$G/gforth" -p ".:$G:vendor/gforth-0.7.3" -i "$G/gforth.fi" \
    env/brk.fs test/demo.fs > "$log/build-$b.txt" 2>&1
done
# addresses are ASLR'd and kept; machine paths are not (the repo is public):
# checkout-relative paths, ~ for $HOME, $GFORTH_PREFIX for the keg
for f in "$log"/*.txt; do
  sed -E -i.bak -e "s#$PWD/##g" -e "s#$HOME#~#g" \
      -e 's#/opt/homebrew/Cell[a]r/gforth/[^/]*#$GFORTH_PREFIX#g' "$f" && rm -f "$f.bak"
done
ls -l "$log"
