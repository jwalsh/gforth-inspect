#!/usr/bin/perl -p
# mask.pl -- remove per-run noise from test output before diffing
#   $TMP is the test's temp dir (env MASK_TMP, and MASK_TMP_REAL its physical
#   path); OWNER/REPO/WORKTREE the checkout's own log components (MASK_PROJECT)
BEGIN { $tmp = $ENV{MASK_TMP} // "\0none"; $real = $ENV{MASK_TMP_REAL} || "\0none";
        $project = $ENV{MASK_PROJECT} || "\0none"; }
s/\Q$real\E/\$TMP/g;
s/\Q$tmp\E/\$TMP/g;
s{gforth-inspect/\Q$project\E/}{gforth-inspect/OWNER/REPO/WORKTREE/}g;  # the checkout's own default log dir
s/\$[0-9A-F]{5,}/\$ADDR/g;                       # hex. addresses
s/^[0-9A-F]{8,} [0-9A-F]{8,} /ADDR ADDR /;       # dbg: ip and cell
s/<-?[0-9]{9,}>/<CA>/g;                          # see: undecodable code address
s/"t":[0-9]+/"t":T/g;                            # log timestamps
s/(?<![0-9.E])-?[0-9]{10,}(?![0-9.E])/BIG/g;     # addresses printed as numbers
$_ .= "
" if eof && !/
\z/;  # keep section markers on their own line
