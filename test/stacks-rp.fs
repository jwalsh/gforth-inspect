\ stacks-rp.fs -- regression: .stacks once printed a copy of its own rp
\ (it computed rp@ inside the printer).  Top of the return stack must be
\ the caller of the word that called .stacks, never .stacks itself.
: w ( -- ) .stacks ;
: w2 ( -- ) w ;
w2
: r1 ( -- ) .rs ;
: r2 ( -- ) r1 ;
r2
