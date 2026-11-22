#!/usr/bin/env bash
# tour-tmux.sh -- start a detached tmux session for trying the inspector:
#   left:  gforth with inspect.fs and tour.fs loaded (the REPL is the pane's
#          command, never typed into)
#   right: the JSON log, followed through jq
# Attach with:  tmux attach -t gforth-inspect-tour
# Remove with:  tmux kill-session -t gforth-inspect-tour
# It never attaches or switches your client, and never touches another session.
set -euo pipefail

session=${TOUR_SESSION:-gforth-inspect-tour}
if tmux has-session -t "=$session" 2>/dev/null; then
    echo "session $session already exists: tmux attach -t $session"
    exit 0
fi

box=$("$(dirname "$0")/sandbox.sh")
env_vars="HOME=$box/home GFORTH_INSPECT_LOG_DIR=$box/log"
filter='{e:.event, w:.where, d:.data, f:.float, id:.id}'

tmux new-session -d -s "$session" -x 200 -y 50 -c "$box" \
    "env $env_vars gforth inspect.fs tour.fs; echo; echo 'gforth exited; any key closes'; read -r -n 1"
tmux split-window -h -t "$session" -c "$box" -l 70 \
    "tail -n +1 -F log/stacks.jsonl | jq -c --unbuffered '$filter'"
tmux select-pane -t "$session:0.0"
echo "started: tmux attach -t $session"
echo "sandbox: $box"
