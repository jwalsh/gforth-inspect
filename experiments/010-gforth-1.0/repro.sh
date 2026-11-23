#!/usr/bin/env bash
# repro.sh -- the one-line reproducers of the 1.0 breaks, without inspect.fs
#
#   repro.sh [-b BINDIR] [-e ENGINE]
#   INSPECT_REF   ref that R15's env/brk.fs comes from (default v0.1.1)
#
# Each line runs plain ENGINE in a fresh temp dir (cwd, HOME and every
# XDG_*_HOME) and prints "ID | first line of output".  Run it once on
# 0.7.3 and once on 1.0.x and compare.
set -u -o pipefail
bindir="" engine=gforth
while getopts "b:e:" opt; do
  case $opt in b) bindir=$OPTARG ;; e) engine=$OPTARG ;; *) exit 2 ;; esac
done
[ -n "$bindir" ] && PATH="$bindir:$PATH"
here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/../.." && pwd)
ref=${INSPECT_REF:-v0.1.1}
brk=$(git -C "$root" show "$ref:env/brk.fs") || exit 1

run() { # id forth-source
  local id=$1 src=$2 tmp out
  tmp=$(mktemp -d "${TMPDIR:-/tmp}/gfi010.XXXXXX")
  printf '%s\n' "$brk" > "$tmp/brk.fs"   # loaded by relative name (R15)
  out=$(cd "$tmp" && HOME="$tmp" XDG_STATE_HOME="$tmp" XDG_CACHE_HOME="$tmp" \
        XDG_DATA_HOME="$tmp" XDG_CONFIG_HOME="$tmp" \
        perl -e 'alarm shift; exec @ARGV' 10 "$engine" -e "$src" </dev/null 2>&1)
  rm -rf "$tmp"
  # the first error or warning line if there is one, else the first line
  out=$(printf '%s\n' "$out" | grep -v -e '^$' | { grep -E 'error|warning' || printf '%s\n' "$out" | grep -v -e '^$'; } | head -1)
  printf '%-4s | %s\n' "$id" "${out:-(no output)}"
}

run R1  "' interpret1 drop .( defined) bye"
run R2  "' handler-intro, drop .( defined) bye"
run R3  "' .debugline-stderr drop .( defined) bye"
run R4  "s\" DebugLoop\" find-name 0<> . bye"
run R5  ": t ; ' t >head-noprim ' t = . bye"
run R6  ": t ; ' t @ docol: = . bye"
run R7  ": t 1+ ; ' t >body @ threaded>name 0<> . bye"
run R8  ": t ; dbg t .( stepped) bye"
run R9  ": t 1 2 + ; ' t >body here >r dp ! ' noop compile, r> dp ! .( patched) bye"
run R10 ": t 1 IF [ dup . ] THEN ; bye"
run R11 ": x 2drop ; ' x is .debugline : t 7 ~~ ; t depth . bye"
run R12 "s\" .stacks\" find-name 0<> . bye"
run R13 ": t ['] dup >name name>int drop ; bye"
run R14 ": t 0. 2drop ; bye"
run R15 "s\" brk.fs\" included brk .( returned) bye"
