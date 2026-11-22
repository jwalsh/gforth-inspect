\ log-dir.fs -- helpers for test/log-dir-*.fs (loaded with `\ test: load').
\ Fixture trees are built with sh under $FX (a test sets FX=$TMP/fx), and
\ .log-dir-for prints the default log dir inspect.fs computes for a given
\ $PWD, $XDG_STATE_HOME/gforth-inspect shown as <base> and $HOME as ~, so
\ the golden shows the owner/repo/worktree components unmasked.

: fx-sh ( c-addr u -- ) system $? 0 s" sh exit status" assert= ;

create fx-buf 8192 allot  variable fx#  \ the upper half keeps a copy
: fx ( c-addr u -- c-addr' u' ) \ $FX/<c-addr u>
    0 fx#  !  s" FX" getenv fx-buf fx# buf+  s" /" fx-buf fx# buf+
    fx-buf fx# buf+  fx-buf fx# @ ;

: .prefixed ( c-addr u prefix-a prefix-u name-a name-u -- c-addr' u' )
    \ print name and drop the prefix if c-addr u starts with it
    2>r 2over 2over string-prefix? IF nip /string 2r> type ELSE 2drop 2rdrop THEN ;
create base-buf 4096 allot  variable base#
: (.log-dir) ( -- ) \ log-dir, with <base> and ~ for the test's own dirs
    0 base# !  s" XDG_STATE_HOME" getenv base-buf base# buf+
    s" /gforth-inspect" base-buf base# buf+
    log-dir log-dir# @  base-buf base# @ s" <base>" .prefixed
    s" HOME" getenv s" ~" .prefixed  type ;
: .log-dir ( -- ) (.log-dir) cr ;
: .log-dir-for ( pwd-a pwd-u -- ) \ the default log dir for this $PWD
    0 log-dir# !  depth >r  (log-dir-for)  depth r> 2 - s" (log-dir-for) stack" assert=
    .log-dir ;


\ for a component hashed over a temp path (_detached-, _wt-): the hash
\ differs per run, so its 12 hex digits print as HASH
: .log-dir-for-hash ( dir-a dir-u -- )
    0 log-dir# !  (log-dir-for)  log-dir# @ 12 - log-dir# !  (.log-dir) ." HASH" cr ;

create first-dir 4400 allot  variable first#
: distinct-dirs ( dir1-a dir1-u dir2-a dir2-u -- ) \ their log dirs differ
    2swap 0 log-dir# !  (log-dir-for)  log-dir first-dir log-dir# @ move  log-dir# @ first# !
    0 log-dir# !  (log-dir-for)  log-dir log-dir# @ first-dir first# @ compare 0<>
    s" two worktrees share a log dir" assert ;
