\ all-tilde.fs -- plain ~~ before and after all-~~, and its log record
: f1 ( -- ) 7 8 2.5e ~~ 2drop fdrop ;
: f2 ( -- ) f1 ;
f2
all-~~
log-on f2 log-off
depth 0 s" clean" assert=
