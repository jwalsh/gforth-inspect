#!/usr/bin/env bash
# dist-links.sh --- make dist/*.org render standalone, then prove it.
#
#   scripts/dist-links.sh DIR VERSION     rewrite and check DIR/*.org
#   scripts/dist-links.sh --calibrate     plant a ../ link; the check must fail
#
# Rewrite: [[file:../NAME]] or [[file:NAME]] where NAME is in DIR -> [[file:NAME]];
# any other file: link -> https://github.com/jwalsh/gforth-inspect/blob/vVERSION/PATH.
# Check: every [[file:...]] left in DIR/*.org names a file inside DIR.
set -eu

repo_url=https://github.com/jwalsh/gforth-inspect/blob

check() { # DIR -> 0 when every file: link resolves inside DIR
  local dir=$1 bad=0 org link target
  for org in "$dir"/*.org; do
    while IFS= read -r link; do
      target=${link#file:}
      case $target in
        /*|../*|*/*) echo "dist-links: $org: $link leaves dist/" >&2; bad=1 ;;
        *) [ -f "$dir/$target" ] || { echo "dist-links: $org: $link not in dist/" >&2; bad=1; } ;;
      esac
    done < <(grep -o '\[\[file:[^]]*\]' "$org" | sed 's/^\[\[//; s/\]$//')
  done
  return $bad
}

rewrite() { # DIR VERSION
  local dir=$1 version=$2 org
  for org in "$dir"/*.org; do
    perl -i -pe '
      BEGIN { ($dir, $url) = @ARGV[0,1]; @ARGV = @ARGV[2..$#ARGV] }
      s{\[\[file:([^\]]+)\]}{
        my $p = $1; (my $base = $p) =~ s{.*/}{};
        (-f "$dir/$base") ? "[[file:$base]" : "[[$url/" . ($p =~ s{^(\.\./)+}{}r) . "]"
      }ge;
    ' "$dir" "$repo_url/v$version" "$org"
  done
}

if [ "${1:-}" = --calibrate ]; then
  tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
  printf '* t\n[[file:ok.org][ok]]\n' > "$tmp/a.org"; printf '* ok\n' > "$tmp/ok.org"
  check "$tmp" || { echo "dist-links: calibrate: clean tree failed" >&2; exit 1; }
  printf '[[file:../CONSUMERS.org][planted]]\n' >> "$tmp/a.org"
  if check "$tmp" 2>/dev/null; then echo "dist-links: calibrate: planted ../ link NOT caught" >&2; exit 1; fi
  echo "red as expected: dist-links planted ../ link"
  exit 0
fi

dir=${1:?usage: dist-links.sh DIR VERSION | --calibrate}; version=${2:?version}
rewrite "$dir" "$version"
check "$dir"
echo "dist-links: every file: link in $dir/*.org resolves inside $dir"
