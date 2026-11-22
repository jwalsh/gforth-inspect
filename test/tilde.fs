\ tilde.fs -- plain ~~ before and after all-~~ (output goes to stderr)
: f1 ( -- )  7 8  2.5e  ~~  2drop fdrop ;
f1
all-~~
f1
bye
