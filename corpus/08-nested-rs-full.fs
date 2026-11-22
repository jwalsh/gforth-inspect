\ 08-nested-rs-full: a ~~~ two calls deep, with rs-full on and then off.
\ On, "rs" runs all the way down through gforth's own frames to boot; off,
\ it stops at the text interpreter and shows only the caller.
: inner ( n -- n ) ~~~ 1+ ;
: outer ( n -- n ) inner 2* ;
log-on
rs-full on 3 outer drop
rs-full off 3 outer drop
bye
