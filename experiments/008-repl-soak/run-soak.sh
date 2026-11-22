#!/usr/bin/env bash
# run-soak.sh NAME HOURS [soak run options...] -- run the soak in the foreground
# (inside the tmux session gforth-inspect-soak, see the Makefile) and resume it
# if the harness dies: a crash stops the clock, it does not reset it.
#
# Status: ${XDG_STATE_HOME:-~/.local/state}/gforth-inspect-soak/status.txt
# Stop:   touch ${XDG_STATE_HOME:-~/.local/state}/gforth-inspect-soak/runs/NAME/STOP
set -u
name=${1:?usage: run-soak.sh NAME HOURS [options]}
hours=${2:?hours}
shift 2
cd "$(dirname "$0")" || exit 2
state=${XDG_STATE_HOME:-$HOME/.local/state}/gforth-inspect-soak/runs/$name
soak() { uv run --no-project --with jsonschema python3 -u -m soak "$@"; }

if [ -f "$state/run.json" ]; then soak resume "$name"; else soak run "$name" --hours "$hours" "$@"; fi
restarts=0
until grep -q '"done_utc"' "$state/state.json" 2>/dev/null || [ -f "$state/STOP" ]; do
    restarts=$((restarts + 1))
    echo "run-soak: harness exited without finishing; resume $restarts in 30 s" >&2
    [ "$restarts" -gt 20 ] && { echo "run-soak: giving up after 20 resumes" >&2; exit 1; }
    sleep 30
    soak resume "$name"
done
echo "run-soak: $name done"
