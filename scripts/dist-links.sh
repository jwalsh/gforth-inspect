#!/usr/bin/env bash
# dist-links.sh --- make the prose assets in dist/ render standalone, then prove it.
#
#   scripts/dist-links.sh DIR REF SRC...   rewrite and check DIR/*.org and DIR/*.md
#   scripts/dist-links.sh --calibrate      plant bad links; each must be caught
#
# DIR holds the flat copies of the release assets; SRC... are their paths in
# the repository (RELEASE_FILES), so that DIR/$(basename SRC) came from SRC.
# REF is the tag (vX.Y.Z) or, in a dry run, the commit sha.
#
# Rewrite, for every relative link in an .org ([[file:T]], [[./T]], [[../T]])
# or .md ([text](T)) asset, resolved against that asset's SRC directory:
#   - T is another asset's SRC                   -> its basename (a sibling in DIR)
#   - T is any other existing path in the repo   -> https://github.com/jwalsh/gforth-inspect/blob/REF/PATH
#   - T is absolute, missing, or leaves the repo -> error; nothing is guessed
# A #anchor (md) or ::search (org) suffix is kept.
# Check: every relative link left in DIR/*.org and DIR/*.md names a file in DIR.
set -eu

repo_url=https://github.com/jwalsh/gforth-inspect/blob

# The link grammar, shared by rewrite and check. Org: [[file:T]...] or
# [[./T]...] / [[../T]...]; markdown: ](T) where T has no scheme and is not
# a bare #anchor. Code spans are not exempt: a false alarm is safer than a
# missed link.
links_perl='
  sub is_relative { my $t = shift; return $t !~ m{^([a-z][a-z0-9+.-]*:|#)}i }
  sub each_link {   # (text, callback(kind, target) -> replacement or undef)
    my ($text, $cb) = @_;
    $text =~ s{\[\[(file:|(?=\.\.?/))([^\]\[]+)\]}{
      my ($pre, $t) = ($1, $2); my $r = $cb->("org", $t);
      defined $r ? "[[$r]" : "[[$pre$t]"
    }ge;
    $text =~ s{\]\(([^()\s]+)\)}{
      my $t = $1; my $r = is_relative($t) ? $cb->("md", $t) : undef;
      defined $r ? "]($r)" : "]($t)"
    }ge;
    return $text;
  }
'

rewrite() { # DIR REF SRC...
  local dir=$1 ref=$2 root; shift 2
  root=$(git rev-parse --show-toplevel)
  perl -e "$links_perl"'
    use strict; use warnings;
    my ($dir, $url, $root, @src) = @ARGV;
    my %asset;   # repo path -> basename in DIR
    for my $s (@src) { (my $b = $s) =~ s{.*/}{}; $asset{$s} = $b }
    my $bad = 0;
    sub norm {   # repo-relative path, or undef when it leaves the repo
      my @out;
      for my $part (split m{/}, shift) {
        next if $part eq "" || $part eq ".";
        if ($part eq "..") { return undef unless @out; pop @out } else { push @out, $part }
      }
      return join "/", @out;
    }
    for my $s (@src) {
      next unless $s =~ /\.(org|md)$/;
      my $base = $asset{$s}; my $file = "$dir/$base";
      (my $srcdir = $s) =~ s{[^/]*$}{};
      open my $in, "<", $file or die "dist-links: $file: $!\n";
      my $text = do { local $/; <$in> }; close $in;
      $text = each_link($text, sub {
        my ($kind, $t) = @_;
        my ($path, $suffix) = $kind eq "org" ? ($t =~ /^(.*?)((?:::.*)?)$/) : ($t =~ /^([^#]*)((?:#.*)?)$/);
        if ($path =~ m{^/}) { warn "dist-links: $base: $t is an absolute path\n"; $bad = 1; return undef }
        my $p = norm($srcdir . $path);
        if (!defined $p) { warn "dist-links: $base: $t leaves the repository\n"; $bad = 1; return undef }
        if ($p eq "") { warn "dist-links: $base: $t names the repository root\n"; $bad = 1; return undef }
        if (exists $asset{$p}) { my $r = "$asset{$p}$suffix"; return $kind eq "org" ? "file:$r" : $r }
        if (!-e "$root/$p") { warn "dist-links: $base: $t -> $p does not exist\n"; $bad = 1; return undef }
        return "$url/$p$suffix";
      });
      open my $out, ">", $file or die "dist-links: $file: $!\n";
      print $out $text; close $out;
    }
    exit $bad;
  ' "$dir" "$repo_url/$ref" "$root" "$@"
}

check() { # DIR -> 0 when every relative link in DIR/*.org and DIR/*.md names a file in DIR
  perl -e "$links_perl"'
    use strict; use warnings;
    my $dir = shift; my $bad = 0;
    for my $file (glob("$dir/*.org"), glob("$dir/*.md")) {
      open my $in, "<", $file or die "dist-links: $file: $!\n";
      my $text = do { local $/; <$in> }; close $in;
      each_link($text, sub {
        my ($kind, $t) = @_;
        my ($path) = $kind eq "org" ? ($t =~ /^(.*?)(?:::.*)?$/) : ($t =~ /^([^#]*)/);
        if ($path =~ m{/}) { warn "dist-links: $file: $t leaves dist/\n"; $bad = 1 }
        elsif ($path ne "" && !-f "$dir/$path") { warn "dist-links: $file: $t not in dist/\n"; $bad = 1 }
        return undef;
      });
    }
    exit $bad;
  ' "$1"
}

if [ "${1:-}" = --calibrate ]; then
  tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
  fail=0
  red() { echo "red as expected: dist-links $1"; }
  miss() { echo "dist-links: calibrate: $1 NOT caught" >&2; fail=1; }

  # a clean dist/ passes the check
  printf '* t\n[[file:ok.org][ok]] [x](ok.org#top)\n' > "$tmp/a.org"; printf '* ok\n' > "$tmp/ok.org"
  check "$tmp" || { echo "dist-links: calibrate: clean dist/ failed" >&2; exit 1; }

  # the check refuses links that leave dist/, in either syntax
  for planted in '[[file:../CONSUMERS.org][p]]' '[[file:../docs/RELEASING.org][p]]' \
                 '[p](../docs/COLLABORATION.org)' '[[file:/etc/hosts][p]]' '[[file:missing.org][p]]'; do
    mkdir "$tmp/c"; cp "$tmp/a.org" "$tmp/ok.org" "$tmp/c/"
    printf '%s\n' "$planted" >> "$tmp/c/a.org"
    if check "$tmp/c" 2>/dev/null; then miss "planted $planted"; else red "check: $planted"; fi
    rm -r "$tmp/c"
  done
  printf '[p](../docs/REVIEW.md)\n' > "$tmp/x.md"
  if check "$tmp" 2>/dev/null; then miss "planted ../docs/ link in .md"; else red "check: [p](../docs/REVIEW.md) in .md"; fi
  rm "$tmp/x.md"

  # the rewrite, run inside a throwaway repo shaped like this one
  repo=$tmp/repo; mkdir -p "$repo/contract/skill" "$repo/docs" "$repo/dist"
  printf '* r\n' > "$repo/docs/RELEASING.org"; printf '* c\n' > "$repo/docs/COLLABORATION.org"
  printf '[[file:CONSUMERS.org][s]] [[file:../docs/RELEASING.org::*Gate][r]] [[https://example.org][u]]\n' \
    > "$repo/contract/stacks-log.org"
  printf '[[file:CONSUMER-AGENTS.md][a]]\n' > "$repo/contract/CONSUMERS.org"
  printf '[c](../docs/COLLABORATION.org#top) [s](CONSUMERS.org)\n' > "$repo/contract/CONSUMER-AGENTS.md"
  printf '[k](../CONSUMERS.org) [r](../../docs/RELEASING.org)\n' > "$repo/contract/skill/SKILL.md"
  srcs="contract/stacks-log.org contract/CONSUMERS.org contract/CONSUMER-AGENTS.md contract/skill/SKILL.md"
  # shellcheck disable=SC2086
  (cd "$repo" && git init -q . && cp $srcs dist/ && rewrite dist REF $srcs && check dist) \
    || { echo "dist-links: calibrate: rewrite of a clean tree failed" >&2; exit 1; }
  want() { grep -qF -- "$2" "$repo/dist/$1" || { echo "dist-links: calibrate: $1 lacks $2" >&2; fail=1; }; }
  before=$fail
  want stacks-log.org '[[file:CONSUMERS.org][s]]'
  want stacks-log.org "[[$repo_url/REF/docs/RELEASING.org::*Gate][r]]"
  want stacks-log.org '[[https://example.org][u]]'
  want CONSUMERS.org '[[file:CONSUMER-AGENTS.md][a]]'
  want CONSUMER-AGENTS.md "[c]($repo_url/REF/docs/COLLABORATION.org#top)"
  want CONSUMER-AGENTS.md '[s](CONSUMERS.org)'
  want SKILL.md '[k](CONSUMERS.org)'
  want SKILL.md "[r]($repo_url/REF/docs/RELEASING.org)"
  [ "$fail" = "$before" ] && echo "green as expected: dist-links rewrite flattens siblings and pins ../docs/ to REF"

  # the rewrite refuses what it cannot pin
  for planted in '[[file:../../outside.org][p]]' '[[file:../docs/no-such.org][p]]' '[p](/etc/hosts)'; do
    cp "$repo/contract/CONSUMERS.org" "$repo/dist/CONSUMERS.org"
    printf '%s\n' "$planted" >> "$repo/dist/CONSUMERS.org"
    # shellcheck disable=SC2086
    if (cd "$repo" && rewrite dist REF $srcs) 2>/dev/null; then miss "rewrite of $planted"; else red "rewrite: $planted"; fi
  done
  exit $fail
fi

dir=${1:?usage: dist-links.sh DIR REF SRC... | --calibrate}; ref=${2:?ref}; shift 2
[ $# -gt 0 ] || { echo "dist-links: no SRC paths given" >&2; exit 2; }
rewrite "$dir" "$ref" "$@"
check "$dir"
echo "dist-links: every relative link in $dir/*.org and $dir/*.md resolves inside $dir"
