\ 07-tilde2-after-all-tilde2: plain ~~ writes a snapshot once all-~~ is
\ on.  Inside a word it fills "where" / "src"; at the prompt both are null.
all-~~
: halve ( n -- n' ) ~~ 2/ ;
log-on
40 halve drop
1 2 ~~ 2drop
bye
