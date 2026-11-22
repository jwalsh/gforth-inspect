\ dbg-adjacent.fs -- regression: IF x THEN with a one-cell x gives two
\ adjacent breakpoint sites; two-cell breakpoints overlapped and the
\ fall-through crashed (Invalid memory address) in every engine
\ test: stdin \n\nn\n\n\n\n\n\n\n\n\nn\n\n\n\n\n\n\n
: t ( n f -- ) if drop then ;
: u ( -- ) 5 true t ;
: v ( -- n ) 5 false t ;
dbg+
dbg u
depth 0 s" u took the IF branch" assert=
dbg v
5 s" v skipped it" assert=
9 true t depth 0 s" t intact (true)" assert=
9 false t 9 s" t intact (false)" assert=
