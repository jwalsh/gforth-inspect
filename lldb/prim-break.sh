#!/bin/sh
# lldb/prim-break.sh [engine] [prim] -- stop at the first `brk` (to load the
# image), then break on the engine code of a primitive (default f*, which
# runs inside fmix) and inspect with no CALL-C help: heuristic mode.
set -eu
cd "$(dirname "$0")/.."
engine=${1:-gforth}; prim=${2:-f*}
bin=$(command -v "$engine-0.7.3" || command -v "$engine")
exec /usr/bin/lldb -b \
  -o "command script import lldb/gforth.py" \
  -o "fbrk" -o "run" -o "breakpoint disable 1" \
  -o "fbreak-prim $prim" -o "continue" \
  -o "fregs" -o "fstacks" -o "fip" \
  -o "kill" -- "$bin" env/brk.fs test/demo.fs
