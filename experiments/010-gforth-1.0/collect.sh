#!/usr/bin/env bash
# collect.sh -- rerun every measurement and write the results/ tables in
# their committed format: probes.tsv, internals.tsv and repro.tsv.
#
#   collect.sh OUTDIR VERSION=BINDIR...
#     OUTDIR   where the raw probe.sh runs and the tables go
#     VERSION  a label (0.7.3, 1.0.0, 1.0.1); BINDIR is put first on PATH
#              for it, empty for the gforth already on PATH.  The first
#              VERSION is the reference the probes are judged against.
#
#   collect.sh out 0.7.3= 1.0.0=PREFIX0/bin 1.0.1=PREFIX1/bin
#
# 0.7.3 runs in its three engines, every other version also in
# gforth-ditc, plain and with shim-1.0.fs preloaded (run "<VERSION>-shim").
# internals.tsv has one column per version (engine gforth; the experiment
# found no engine difference) and "1.0.x+see-voc", filled only where the
# last version lacks a word: the same check with `also see-voc` first.
set -u -o pipefail
here=$(cd "$(dirname "$0")" && pwd)
[ $# -ge 2 ] || { echo "usage: collect.sh OUTDIR VERSION=BINDIR..." >&2; exit 2; }
out=$1; shift
mkdir -p "$out/runs"
labels=() runs=()
for spec in "$@"; do
  label=${spec%%=*} bindir=${spec#*=}
  labels+=("$label")
  bflag=(); [ -n "$bindir" ] && bflag=(-b "$bindir")
  if [ ${#labels[@]} -eq 1 ]; then engines="gforth gforth-fast gforth-itc"
  else engines="gforth gforth-fast gforth-itc gforth-ditc"; fi
  bash "$here/probe.sh" -o "$out/runs/$label" ${bflag[@]+"${bflag[@]}"} -e "$engines" > "$out/runs/$label.txt" || exit 1
  runs+=("$out/runs/$label")
  if [ ${#labels[@]} -gt 1 ]; then
    bash "$here/probe.sh" -o "$out/runs/$label-shim" ${bflag[@]+"${bflag[@]}"} -e "$engines" \
      -p "$here/shim-1.0.fs" > "$out/runs/$label-shim.txt" || exit 1
    runs+=("$out/runs/$label-shim")
  fi
  bash "$here/internals.sh" ${bflag[@]+"${bflag[@]}"} -e gforth | sed 's/ *$//' > "$out/internals-$label.txt" || exit 1
  [ ${#labels[@]} -gt 1 ] && { bash "$here/internals.sh" -v ${bflag[@]+"${bflag[@]}"} -e gforth | sed 's/ *$//' \
    > "$out/internals-see-voc.txt" || exit 1; }
  for engine in gforth gforth-fast gforth-itc; do
    bash "$here/repro.sh" ${bflag[@]+"${bflag[@]}"} -e "$engine" |
      LC_ALL=C sed -E "s/^(R[0-9]+) *\\| /$label\\t$engine\\t\\1\\t/"
  done >> "$out/repro.tsv.new" || exit 1
done
mv "$out/repro.tsv.new" "$out/repro.tsv"
bash "$here/summarize.sh" "${runs[0]}" "${runs[@]}" > "$out/probes.tsv" || exit 1
{
  printf 'word'; printf '\t%s' "${labels[@]}"; printf '\t1.0.x+see-voc\n'
  files=(); for label in "${labels[@]}"; do files+=("$out/internals-$label.txt"); done
  perl -e '
    my $sv = pop @ARGV; my (@order, %val, %see);
    open my $f, "<", $sv or die "$sv: $!"; while (<$f>) { my ($w, $v) = split; $see{$w} = $v } close $f;
    for my $i (0 .. $#ARGV) {
      open my $g, "<", $ARGV[$i] or die "$ARGV[$i]: $!";
      while (<$g>) { my ($w, $v) = split; push @order, $w if $i == 0; $val{$w}[$i] = $v }
    }
    for my $w (@order) {
      my @v = map { $_ // "" } @{$val{$w}};
      print join("\t", $w, @v, $v[-1] eq "0" ? $see{$w} // "" : ""), "\n";
    }' "${files[@]}" "$out/internals-see-voc.txt"
} > "$out/internals.tsv" || exit 1
echo "tables in $out: probes.tsv internals.tsv repro.tsv"
