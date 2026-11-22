\ dbg+ then n (nest) into a colon word, Enter to step; stock dbg dies here
\ in gforth/gforth-fast (xt-see on engine code -> gdb -> invalid address)
\ test: stdin \nn\n\n\n\n\n\n\n
: inner ( -- ) 1 2 + drop ;
: outer ( -- ) 5 inner drop ;
dbg+
dbg outer
.( nest-ok ) cr
