\ all-tilde-where.fs -- issue #2: after all-~~, a ~~ snapshot names the
\ word holding the ~~ and its file:line; a ~~ interpreted at the top level
\ (as typed at the prompt) has where/src null and no misnamed frame
: f1 ( -- ) 7 ~~ drop ;
: f2 ( -- ) f1 ;
: down ( n -- ) dup 0> IF 1- recurse ELSE ~~ drop THEN ;
all-~~
log-on
f2
2 down
3 ~~ drop
s" 4 ~~ drop" evaluate
log-off
depth 0 s" clean" assert=
