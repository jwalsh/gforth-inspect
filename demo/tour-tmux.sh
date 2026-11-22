#!/usr/bin/env bash
# tour-tmux.sh -- start a detached tmux session for trying the inspector:
#   left:  gforth with inspect.fs and tour.fs loaded (the REPL is the pane's
#          command, never typed into)
#   right: the JSON log, followed through jq
# Attach with:  tmux attach -t gforth-inspect-tour   (or $TOUR_SESSION)
# Remove with:  gmake -C demo stop
# It never attaches or switches your client, and never touches another session.
set -euo pipefail

session=${TOUR_SESSION:-gforth-inspect-tour}
if tmux has-session -t "=$session" 2>/dev/null; then
    echo "session $session already exists: tmux attach -t $session"
    exit 0
fi

box=$("$(dirname "$0")/sandbox.sh")
filter='{e:.event, w:.where, d:.data, f:.float, id:.id}'

# pane commands run under bash explicitly: tmux would use the user's shell
repl_pane=$(tmux new-session -d -P -F '#{pane_id}' -s "$session" -x 200 -y 50 -c "$box" \
    "bash -c 'HOME=\"$box/home\" GFORTH_INSPECT_LOG_DIR=\"$box/log\" gforth inspect.fs tour.fs; echo; read -r -n 1 -p \"gforth exited; any key closes \"'")
tmux split-window -h -t "$repl_pane" -c "$box" -l 70 \
    "bash -c 'tail -n +1 -F log/stacks.jsonl | jq -c --unbuffered \"$filter\"'"
tmux select-pane -t "$repl_pane"
echo "started: tmux attach -t $session"
echo "sandbox: $box"
