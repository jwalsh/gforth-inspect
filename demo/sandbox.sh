#!/usr/bin/env bash
# sandbox.sh -- make an isolated directory for a demo run and print its path.
# Inside it: inspect.fs, tour.fs, home/ (gforth writes .gforth-history to
# HOME) and log/ (GFORTH_INSPECT_LOG_DIR).  Nothing outside it is touched, and
# because every command runs from inside it, no real path appears on screen
# or in the log.
#
# inspect.fs comes from INSPECT_FS, else env/inspect.fs in this checkout,
# else `git show ${INSPECT_REF:-harden}:env/inspect.fs`.
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
top=$(git -C "$here" rev-parse --show-toplevel)
box=$(mktemp -d "${TMPDIR:-/tmp}/gforth-inspect-demo.XXXXXX")
mkdir -p "$box/home" "$box/log"

if [ -n "${INSPECT_FS:-}" ]; then
    cp "$INSPECT_FS" "$box/inspect.fs"
elif [ -f "$top/env/inspect.fs" ]; then
    cp "$top/env/inspect.fs" "$box/inspect.fs"
else
    git -C "$top" show "${INSPECT_REF:-harden}:env/inspect.fs" > "$box/inspect.fs"
fi
cp "$here/tour.fs" "$box/tour.fs"
: > "$box/log/stacks.jsonl"
printf '%s\n' "$box"
