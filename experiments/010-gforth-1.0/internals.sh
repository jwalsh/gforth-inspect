#!/usr/bin/env bash
# internals.sh -- every system word the pinned inspect.fs names, and
# whether ENGINE's image has it: one line "word -1|0" per word.
#
#   internals.sh [-b BINDIR] [-e ENGINE] [-v] > table.txt
#     -v           search with `also see-voc` first (1.0 keeps debug.fs
#                  internals there); for the 1.0.x+see-voc column
#   INSPECT_REF   default v0.1.1
#
# Tokens are taken from inspect.fs with comments and string literals
# (s" ." abort" c" s\" .( ), any case) removed; a token still holding a
# quote is reported on stderr and skipped, so it cannot break check.fs; words inspect.fs defines itself are left out; numbers are left
# out.  The check is find-name in a plain image (no inspect.fs loaded),
# in an isolated temp dir.
set -u -o pipefail
here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/../.." && pwd)
bindir="" engine=gforth seevoc=""
while getopts "b:e:v" opt; do
  case $opt in b) bindir=$OPTARG ;; e) engine=$OPTARG ;; v) seevoc=1 ;; *) exit 2 ;; esac
done
[ -n "$bindir" ] && PATH="$bindir:$PATH"
ref=${INSPECT_REF:-v0.1.1}
tmp=$(mktemp -d "${TMPDIR:-/tmp}/gfi010.XXXXXX")
trap 'rm -rf "$tmp"' EXIT
git -C "$root" show "$ref:env/inspect.fs" > "$tmp/inspect.fs" || exit 1
perl -e '
    my (%own, @seen, %seen);
    while (<>) {
        s/(^|\s)\\(\s.*)?$//;                       # \ comment
        s/(^|\s)\((\s[^)]*)?\)/$1/g;                 # ( stack comment )
        s/(^|\s)s\\"\s(?:\\.|[^"\\])*"/$1/gi;      # s\" with escapes
        s/(^|\s)(s|\.|abort|c)"\s[^"]*"/$1/gi;     # string literals
        s/(^|\s)\.\(\s[^)]*\)/$1/g;                 # .( text )
        s/(^|\s)\[char\]\s+\S+/$1/gi;                # [char] x
        my @tok = split;
        for my $i (0 .. $#tok) {
            my $t = $tok[$i];
            if ($t =~ /^(:|variable|create|constant|defer)$/i && $i < $#tok) {
                $own{lc $tok[$i + 1]} = 1;
            }
            if ($t =~ /"/) { print STDERR "skipped token: $t\n"; next; }
            push @seen, $t unless $seen{lc $t}++;
        }
    }
    for my $t (@seen) {
        next if $own{lc $t};
        next if $t =~ /^-?(\$[0-9a-f]+|[0-9]+\.?|[0-9.]+e[0-9]*)$/i;
        print "$t\n";
    }' "$tmp/inspect.fs" > "$tmp/words" || exit 1
[ -s "$tmp/words" ] || { echo "internals.sh: no words from $ref:env/inspect.fs" >&2; exit 1; }
{
  [ -n "$seevoc" ] && echo "also see-voc"
  while read -r word; do
    printf 's" %s" 2dup type space find-name 0<> . cr\n' "$word"
  done < "$tmp/words"
  echo bye
} > "$tmp/check.fs"
(cd "$tmp" && HOME="$tmp" XDG_STATE_HOME="$tmp" XDG_CACHE_HOME="$tmp" XDG_DATA_HOME="$tmp" \
   XDG_CONFIG_HOME="$tmp" GFORTH_INSPECT_LOG_DIR="$tmp/log" \
   "$engine" check.fs </dev/null 2>&1)
