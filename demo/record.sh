#!/usr/bin/env bash
# record.sh -- the self-driving part of the recorded demo.  asciinema runs
# this; it types the tour's steps into one gforth (stdin is a pipe, and gforth
# echoes each line), then shows the log through jq.  Run it alone to watch it.
set -euo pipefail

box=$("$(dirname "$0")/sandbox.sh")
cd "$box"
export HOME="$box/home" GFORTH_INSPECT_LOG_DIR="$box/log"
pause=${DEMO_PAUSE:-1.4}

steps=(
    '1 2 3  1.5e  .stacks  clearstack fclearstack'
    '10 20 avg .'
    '3 4 sum-sq .'
    'deeper'
    '1e 0e f/  -0e  .stacks  fclearstack'
    ': t 0 IF BEGIN .cs AGAIN THEN ;'
    's" step-8" log-id  7 .stacks drop  s" " log-id'
)

{
    sleep "$pause"
    for step in "${steps[@]}"; do
        printf '%s\n' "$step"
        sleep "$pause"
    done
    printf 'bye\n'
} | gforth inspect.fs tour.fs

printf '\n$ jq -c %s log/stacks.jsonl\n' "'{e:.event,w:.where,d:.data,f:.float,id:.id}'"
sleep "$pause"
jq -c '{e:.event,w:.where,d:.data,f:.float,id:.id}' log/stacks.jsonl
sleep "$pause"
