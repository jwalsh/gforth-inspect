\ dbg-loop.fs -- dbg through a do loop and an if (two-breakpoint steps)
\ printf '%40s' | gforth env/inspect.fs test/dbg-loop.fs
: odd. ( n -- )  dup 1 and if . else drop then ;
: lp ( -- )  3 0 do  i odd.  loop ;
dbg-fix
dbg lp
cr .( after dbg: ) .s cr
bye
