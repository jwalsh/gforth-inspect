\ tilde3-recursive.fs -- ~~~ at every level of a recursive word, and in a
\ :noname (no name: printed as such, logged as "where")
: fact ( n -- n! ) dup 1 > if dup 1- recurse * else ~~~ then ;
log-on
4 fact 24 s" fact" assert=
:noname ( -- ) 9 ~~~ drop ; execute
log-off
