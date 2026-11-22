#!/usr/bin/env bash
# dist-links.sh --- make the prose assets in dist/ render standalone, then prove it.
#
#   scripts/dist-links.sh DIR REF SRC...   rewrite and check DIR/*.org and DIR/*.md
#   scripts/dist-links.sh --calibrate      plant bad links; each must be caught
#
# DIR holds the flat copies of the release assets; SRC... are their paths in
# the repository (RELEASE_FILES), so that DIR/$(basename SRC) came from SRC.
# REF is the tag being released (vX.Y.Z), cut at HEAD, the commit being
# released; gmake release-check refuses a tag that exists elsewhere.
#
# Rewrite, for every relative link in an .org ([[file:T]], [[./T]], [[../T]])
# or .md ([text](T)) asset, resolved against that asset's SRC directory:
#   - T is another asset's SRC                    -> its basename (a sibling in DIR)
#   - T is any other path committed in HEAD        -> https://github.com/jwalsh/gforth-inspect/blob/REF/PATH
#   - T is absolute, uncommitted, or leaves the repo -> error; nothing is guessed
# A sibling keeps its #anchor (md) or ::search (org). A pinned URL keeps a
# markdown #anchor but drops an org ::search, which GitHub cannot resolve.
# Check: every relative link left in DIR/*.org and DIR/*.md names a file in DIR.
set -eu

repo_url=https://github.com/jwalsh/gforth-inspect/blob

# The link grammar, shared by rewrite and check. Org: [[file:T]...] or
# [[./T]...] / [[../T]...]; markdown: ](T) where T has no scheme and is not
# a bare #anchor. Code spans are not exempt: a false alarm is safer than a
# missed link.
links_perl='
  sub is_relative { my $target = shift; return $target !~ m{^([a-z][a-z0-9+.-]*:|#)}i }
  sub each_link {   # (text, callback(kind, target) -> replacement or undef)
    my ($text, $callback) = @_;
    $text =~ s{\[\[(file:|(?=\.\.?/))([^\]\[]+)\]}{
      my ($prefix, $target) = ($1, $2); my $replacement = $callback->("org", $target);
      defined $replacement ? "[[$replacement]" : "[[$prefix$target]"
    }ge;
    $text =~ s{\]\(([^()\s]+)\)}{
      my $target = $1; my $replacement = is_relative($target) ? $callback->("md", $target) : undef;
      defined $replacement ? "]($replacement)" : "]($target)"
    }ge;
    return $text;
  }
  sub split_target {   # (kind, target) -> (path, suffix)
    my ($kind, $target) = @_;
    return $kind eq "org" ? ($target =~ /^(.*?)((?:::.*)?)$/) : ($target =~ /^([^#]*)((?:#.*)?)$/);
  }
'

rewrite() { # DIR REF SRC...
  local dir=$1 ref=$2; shift 2
  perl -e "$links_perl"'
    use strict; use warnings;
    my ($dir, $url, @source_paths) = @ARGV;
    my %asset_name;   # repo path -> basename in DIR
    for my $source_path (@source_paths) { (my $basename = $source_path) =~ s{.*/}{}; $asset_name{$source_path} = $basename }
    my $bad = 0;
    sub normalise {   # repo-relative path, or undef when it leaves the repo
      my @parts;
      for my $part (split m{/}, shift) {
        next if $part eq "" || $part eq ".";
        if ($part eq "..") { return undef unless @parts; pop @parts } else { push @parts, $part }
      }
      return join "/", @parts;
    }
    sub committed { my $repo_path = shift; return system("git", "cat-file", "-e", "HEAD:$repo_path") == 0 }
    for my $source_path (@source_paths) {
      next unless $source_path =~ /\.(org|md)$/;
      my $basename = $asset_name{$source_path}; my $file = "$dir/$basename";
      (my $source_dir = $source_path) =~ s{[^/]*$}{};
      open my $in, "<", $file or die "dist-links: $file: $!\n";
      my $text = do { local $/; <$in> }; close $in;
      $text = each_link($text, sub {
        my ($kind, $target) = @_;
        my ($path, $suffix) = split_target($kind, $target);
        if ($path =~ m{^/}) { warn "dist-links: $basename: $target is an absolute path\n"; $bad = 1; return undef }
        my $repo_path = normalise($source_dir . $path);
        if (!defined $repo_path) { warn "dist-links: $basename: $target leaves the repository\n"; $bad = 1; return undef }
        if ($repo_path eq "") { warn "dist-links: $basename: $target names the repository root\n"; $bad = 1; return undef }
        if (exists $asset_name{$repo_path}) {
          my $sibling = "$asset_name{$repo_path}$suffix";
          return $kind eq "org" ? "file:$sibling" : $sibling;
        }
        if (!committed($repo_path)) { warn "dist-links: $basename: $target -> $repo_path is not committed in HEAD\n"; $bad = 1; return undef }
        return "$url/$repo_path" . ($kind eq "org" ? "" : $suffix);
      });
      open my $out, ">", $file or die "dist-links: $file: $!\n";
      print $out $text; close $out;
    }
    exit $bad;
  ' "$dir" "$repo_url/$ref" "$@"
}

check() { # DIR -> 0 when every relative link in DIR/*.org and DIR/*.md names a file in DIR
  perl -e "$links_perl"'
    use strict; use warnings;
    my $dir = shift; my $bad = 0;
    for my $file (glob("$dir/*.org"), glob("$dir/*.md")) {
      open my $in, "<", $file or die "dist-links: $file: $!\n";
      my $text = do { local $/; <$in> }; close $in;
      each_link($text, sub {
        my ($kind, $target) = @_;
        my ($path) = split_target($kind, $target);
        if ($path =~ m{/}) { warn "dist-links: $file: $target leaves dist/\n"; $bad = 1 }
        elsif ($path ne "" && !-f "$dir/$path") { warn "dist-links: $file: $target not in dist/\n"; $bad = 1 }
        return undef;
      });
    }
    exit $bad;
  ' "$1"
}

if [ "${1:-}" = --calibrate ]; then
  tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
  script_path=$(cd "$(dirname "$0")" && pwd)/$(basename "$0")
  fail=0
  miss() { echo "dist-links: calibrate: $1" >&2; fail=1; }
  # plant LABEL WANT CMD...: CMD must fail, and its stderr must contain WANT
  plant() {
    local label=$1 want=$2 output; shift 2
    if output=$("$@" 2>&1); then miss "$label NOT caught"
    elif printf '%s\n' "$output" | grep -qF -- "$want"; then echo "red as expected: dist-links $label"
    else miss "$label red for the wrong reason: $output"; fi
  }

  # a clean dist/ passes the check
  printf '* t\n[[file:ok.org][ok]] [x](ok.org#top) [[file:ok.org::*ok][s]]\n' > "$tmp/a.org"; printf '* ok\n' > "$tmp/ok.org"
  check "$tmp" || { echo "dist-links: calibrate: clean dist/ failed" >&2; exit 1; }

  # the check refuses links that leave dist/, in either syntax
  for planted in '[[file:../CONSUMERS.org][p]]' '[[file:../docs/RELEASING.org][p]]' \
                 '[p](../docs/COLLABORATION.org)' '[[file:/etc/hosts][p]]'; do
    mkdir "$tmp/c"; cp "$tmp/a.org" "$tmp/ok.org" "$tmp/c/"
    printf '%s\n' "$planted" >> "$tmp/c/a.org"
    plant "check: $planted" "leaves dist/" check "$tmp/c"
    rm -r "$tmp/c"
  done
  mkdir "$tmp/c"; cp "$tmp/a.org" "$tmp/ok.org" "$tmp/c/"
  printf '[[file:missing.org][p]]\n' >> "$tmp/c/a.org"
  plant "check: [[file:missing.org][p]]" "not in dist/" check "$tmp/c"
  rm -r "$tmp/c"
  mkdir "$tmp/c"; cp "$tmp/ok.org" "$tmp/c/"; printf '[p](../docs/REVIEW.md)\n' > "$tmp/c/x.md"
  plant "check: [p](../docs/REVIEW.md) in .md" "leaves dist/" check "$tmp/c"
  rm -r "$tmp/c"

  # the rewrite, run inside a throwaway repo shaped like this one
  repo=$tmp/repo; mkdir -p "$repo/contract/skill" "$repo/docs" "$repo/dist"
  printf '* r\n' > "$repo/docs/RELEASING.org"; printf '* c\n' > "$repo/docs/COLLABORATION.org"
  printf '[[file:CONSUMERS.org::*Parties][s]] [[file:../docs/RELEASING.org::*Gate][r]] [[https://example.org][u]]\n' \
    > "$repo/contract/stacks-log.org"
  printf '[[file:CONSUMER-AGENTS.md][a]]\n' > "$repo/contract/CONSUMERS.org"
  printf '[c](../docs/COLLABORATION.org#top) [s](CONSUMERS.org)\n' > "$repo/contract/CONSUMER-AGENTS.md"
  printf '[k](../CONSUMERS.org) [r](../../docs/RELEASING.org)\n' > "$repo/contract/skill/SKILL.md"
  srcs="contract/stacks-log.org contract/CONSUMERS.org contract/CONSUMER-AGENTS.md contract/skill/SKILL.md"
  # shellcheck disable=SC2086
  (cd "$repo" && git init -q . && git add docs contract \
     && git -c user.name=calibrate -c user.email=calibrate@localhost commit -q -m calibrate \
     && printf '* u\n' > docs/uncommitted.org && cp $srcs dist/ && rewrite dist REF $srcs && check dist) \
    || { echo "dist-links: calibrate: rewrite of a clean tree failed" >&2; exit 1; }
  want() { grep -qF -- "$2" "$repo/dist/$1" || miss "$1 lacks $2"; }
  before=$fail
  want stacks-log.org '[[file:CONSUMERS.org::*Parties][s]]'
  want stacks-log.org "[[$repo_url/REF/docs/RELEASING.org][r]]"
  want stacks-log.org '[[https://example.org][u]]'
  want CONSUMERS.org '[[file:CONSUMER-AGENTS.md][a]]'
  want CONSUMER-AGENTS.md "[c]($repo_url/REF/docs/COLLABORATION.org#top)"
  want CONSUMER-AGENTS.md '[s](CONSUMERS.org)'
  want SKILL.md '[k](CONSUMERS.org)'
  want SKILL.md "[r]($repo_url/REF/docs/RELEASING.org)"
  [ "$fail" = "$before" ] && echo "green as expected: dist-links rewrite flattens siblings and pins ../docs/ to REF"

  # the rewrite refuses what it cannot pin, each for its own reason
  refuse() { # LINK WANT
    cp "$repo/contract/CONSUMERS.org" "$repo/dist/CONSUMERS.org"
    printf '%s\n' "$1" >> "$repo/dist/CONSUMERS.org"
    # shellcheck disable=SC2086
    plant "rewrite: $1" "$2" bash -c 'cd "$1" && shift && bash "$@"' _ "$repo" "$script_path" --rewrite-only dist REF $srcs
  }
  refuse '[[file:../../outside.org][p]]' 'leaves the repository'
  refuse '[[file:../docs/no-such.org][p]]' 'is not committed in HEAD'
  refuse '[[file:../docs/uncommitted.org][p]]' 'is not committed in HEAD'
  refuse '[p](/etc/hosts)' 'is an absolute path'
  exit $fail
fi

if [ "${1:-}" = --rewrite-only ]; then   # for --calibrate: the rewrite step alone
  shift; dir=$1 ref=$2; shift 2; rewrite "$dir" "$ref" "$@"; exit
fi

dir=${1:?usage: dist-links.sh DIR REF SRC... | --calibrate}; ref=${2:?ref}; shift 2
[ $# -gt 0 ] || { echo "dist-links: no SRC paths given" >&2; exit 2; }
rewrite "$dir" "$ref" "$@"
check "$dir"
echo "dist-links: every relative link in $dir/*.org and $dir/*.md resolves inside $dir"
