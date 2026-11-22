\ dbg-nest-n.fs -- n nests into a colon word, its steps, back out; then the
\ words must still compute the same (no breakpoint left behind).  In
\ gforth-fast `2 +' is a superinstruction see cannot decode: the step over
\ it is skipped (known limit) but code must not be corrupted (regression).
\ test: stdin \nn\n\n\n\n\n\n\n\n\n
: inner ( -- n ) 1 2 + ;
: outer ( -- n ) 5 inner + ;
dbg+
dbg outer
8 s" dbg outer result" assert=
inner 3 s" inner intact after dbg" assert=
outer 8 s" outer intact after dbg" assert=
