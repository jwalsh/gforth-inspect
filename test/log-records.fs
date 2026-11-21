\ log-records.fs -- log-on writes hello once; .stacks ~~~ write snapshots
\ while on and nothing after log-off; log-on twice is harmless
\ test: env XDG_STATE_HOME=$TMP/state
: kk ( n -- n ) ~~~ ;
.stacks
log-on log-on
1 2 .stacks 2drop
3 kk drop
log-off log-off
4 .stacks drop
log-on 5 .stacks drop log-off
log-where
depth 0 s" clean" assert=
