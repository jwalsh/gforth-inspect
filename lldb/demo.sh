#!/bin/sh
# lldb/demo.sh [gforth|gforth-fast|gforth-itc] -- run test/demo.fs under lldb,
# stop at the first two `brk`s and print every view.  Needs to run outside
# any sandbox that forbids task_for_pid (debugserver must attach).
set -eu
cd "$(dirname "$0")/.."
engine=${1:-gforth}
bin=$(command -v "$engine-0.7.3" || command -v "$engine")
exec /usr/bin/lldb -b \
  -o "command script import lldb/gforth.py" \
  -o "fbrk" -o "run" \
  -o "fregs" -o "fstacks" -o "finput" -o "fip" -o "fbt" \
  -o "continue" -o "fstacks" \
  -o "kill" -- "$bin" env/brk.fs test/demo.fs
