#!/bin/sh
# lldb/attach.sh [engine] -- start gforth on test/idle.fs in the background,
# attach lldb to the running pid while it sleeps inside MS, inspect, kill.
set -eu
cd "$(dirname "$0")/.."
engine=${1:-gforth}
bin=$(command -v "$engine-0.7.3" || command -v "$engine")
"$bin" test/idle.fs &
pid=$!
sleep 1
/usr/bin/lldb -b -p "$pid" \
  -o "command script import lldb/gforth.py" \
  -o "bt 4" -o "fregs" -o "fstacks" -o "fbt" -o "finput" \
  -o "process kill" || true
wait "$pid" 2>/dev/null || true
