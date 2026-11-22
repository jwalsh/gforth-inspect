#!/usr/bin/env bash
# sandbox.sh -- make an isolated directory for a demo run and print its path.
# Inside it: inspect.fs, tour.fs, home/ (gforth writes .gforth-history to
# HOME) and log/ (GFORTH_INSPECT_LOG_DIR).  Nothing outside it is touched, and
# because every command runs from inside it, no real path appears on screen
# or in the log.  The OS clears $TMPDIR; nothing here deletes anything.
#
# inspect.fs comes from INSPECT_FS, else env/inspect.fs in this checkout,
# else `git show REF:env/inspect.fs` for REF = ${INSPECT_REF:-harden}, then
# origin/REF (a fresh clone has only the remote branch).
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
box=$(mktemp -d "${TMPDIR:-/tmp}/gforth-inspect-demo.XXXXXX")
mkdir -p "$box/home" "$box/log"

if [ -n "${INSPECT_FS:-}" ]; then
    cp "$INSPECT_FS" "$box/inspect.fs"
else
    top=$(git -C "$here" rev-parse --show-toplevel)
    ref=${INSPECT_REF:-harden}
    if [ -f "$top/env/inspect.fs" ]; then
        cp "$top/env/inspect.fs" "$box/inspect.fs"
    elif git -C "$top" show "$ref:env/inspect.fs" > "$box/inspect.fs" 2>/dev/null; then
        :
    elif git -C "$top" show "origin/$ref:env/inspect.fs" > "$box/inspect.fs" 2>/dev/null; then
        :
    else
        echo "sandbox.sh: no inspect.fs (set INSPECT_FS, or fetch $ref)" >&2
        exit 1
    fi
fi
cp "$here/tour.fs" "$box/tour.fs"
: > "$box/log/stacks.jsonl"
printf '%s\n' "$box"
