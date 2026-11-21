\ dbg-demo.fs -- drive dbg non-interactively; keys come from stdin
\ printf '      ' | gforth env/inspect.fs test/dbg-demo.fs
: sq ( n -- n^2 )  dup * ;
: t ( -- )  3 sq 2.5e 2e f*  drop ;
dbg+
dbg t
cr .( after dbg: ) .s f.s cr
bye
