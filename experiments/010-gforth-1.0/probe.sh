#!/usr/bin/env bash
# probe.sh -- run each probes/*.fs after a pinned inspect.fs, one process
# per probe, in every engine named, fully isolated (E-10).
#
#   probe.sh -o OUTDIR [-b BINDIR] [-e "gforth gforth-fast gforth-itc"] [probes/x.fs ...]
#     -b BINDIR    put BINDIR first on PATH (a gforth 1.0 prefix's bin/)
#     -p FILE      load FILE before inspect.fs (the diagnostic shim only)
#   INSPECT_REF    git ref the inspector comes from (default v0.1.1)
#
# Each run gets its own mktemp dir as cwd, HOME and every XDG_*_HOME, with
# GFORTH_INSPECT_LOG_DIR inside it; inspect.fs and the probe are copied in
# and loaded by relative name.  Stdin is the probe's "\ probe: stdin" keys.
# OUTDIR/<engine>/<probe>.out holds masked stdout, stderr, the log and the
# exit status (test/mask.pl); <probe>.jsonl is the log, unmasked.
set -u -o pipefail
here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/../.." && pwd)
outdir="" bindir="" preload="" engines="gforth gforth-fast gforth-itc"
while getopts "o:b:e:p:" opt; do
  case $opt in
    o) outdir=$OPTARG ;;
    b) bindir=$OPTARG ;;
    e) engines=$OPTARG ;;
    p) preload=$OPTARG ;;
    *) exit 2 ;;
  esac
done
shift $((OPTIND - 1))
[ -n "$outdir" ] || { echo "usage: probe.sh -o OUTDIR [-b BINDIR] [-e ENGINES] [probe.fs ...]" >&2; exit 2; }
if [ $# -gt 0 ]; then probes=("$@"); else probes=("$here"/probes/*.fs); fi
[ -n "$bindir" ] && PATH="$bindir:$PATH"
ref=${INSPECT_REF:-v0.1.1}
mkdir -p "$outdir"
git -C "$root" show "$ref:env/inspect.fs" > "$outdir/inspect.fs" || exit 1
blob=$(git -C "$root" rev-parse "$ref:env/inspect.fs") || exit 1
limit=(perl -e 'alarm shift; exec @ARGV or die "exec $ARGV[0]: $!\n"' 10)

{
  echo "inspect: ref:$ref blob:${blob:0:12}"
  for engine in $engines; do
    printf '%s: ' "$engine"
    if command -v "$engine" >/dev/null; then
      scratch=$(mktemp -d "${TMPDIR:-/tmp}/gfi010.XXXXXX")
      (cd "$scratch" && HOME="$scratch" XDG_STATE_HOME="$scratch" XDG_CACHE_HOME="$scratch" \
        XDG_DATA_HOME="$scratch" XDG_CONFIG_HOME="$scratch" "${limit[@]}" "$engine" -e 'version-string type cr bye' </dev/null 2>&1)
      rm -rf "$scratch"
    else echo "not built"; fi
  done
} > "$outdir/provenance.txt"

for engine in $engines; do
  command -v "$engine" >/dev/null || continue
  mkdir -p "$outdir/$engine"
  for probe in "${probes[@]}"; do
    name=$(basename "$probe" .fs)
    tmp=$(mktemp -d "${TMPDIR:-/tmp}/gfi010.XXXXXX"); tmp=${tmp//\/\//\/}
    mkdir -p "$tmp/home" "$tmp/state" "$tmp/cache" "$tmp/data" "$tmp/config"
    cp "$outdir/inspect.fs" "$tmp/inspect.fs"
    cp "$probe" "$tmp/probe.fs"
    files=(inspect.fs probe.fs)
    if [ -n "$preload" ]; then cp "$preload" "$tmp/preload.fs"; files=(preload.fs "${files[@]}"); fi
    keys=$(sed -n 's/^\\ probe: stdin *//p' "$probe")
    # shellcheck disable=SC2059
    printf -- "$keys" > "$tmp/stdin"
    (cd "$tmp" && env -u GFORTH_INSPECT_LOG_DIR HOME="$tmp/home" XDG_STATE_HOME="$tmp/state" \
        XDG_CACHE_HOME="$tmp/cache" XDG_DATA_HOME="$tmp/data" XDG_CONFIG_HOME="$tmp/config" \
        GFORTH_INSPECT_LOG_DIR="$tmp/state/gforth-inspect" \
        "${limit[@]}" "$engine" "${files[@]}" -e bye \
        < "$tmp/stdin" > "$tmp/stdout" 2> "$tmp/stderr")
    rc=$?
    log="$tmp/state/gforth-inspect/stacks.jsonl"
    # a failed mask would leave a section empty, and empty compares equal
    mask() { MASK_TMP=$tmp perl "$root/test/mask.pl" "$1" || { echo "mask.pl failed on $1" >&2; exit 1; }; }
    {
      echo "## stdout"; mask "$tmp/stdout"
      echo "## stderr"; mask "$tmp/stderr"
      if [ -f "$log" ]; then echo "## log"; mask "$log"; fi
      echo "## exit $rc"
    } | LC_ALL=C sed -E 's#/[^ :]*/share/gforth/#GFORTH/share/gforth/#g' > "$outdir/$engine/$name.out" || exit 1
    rm -f "$outdir/$engine/$name.jsonl"
    [ -f "$log" ] && cp "$log" "$outdir/$engine/$name.jsonl"
    stray=$(find "$tmp" -name stacks.jsonl ! -path "$log")
    [ -n "$stray" ] && echo "STRAY LOG $engine $name" >&2
    rm -rf "$tmp"
    echo "$engine $name exit $rc"
  done
done
