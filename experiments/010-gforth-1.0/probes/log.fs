\ log-on, log-id, a snapshot, log-off, log-where; the log is checked after
: inner ( -- ) .stacks ;
log-on
s" p1" log-id
1 2 1.5e inner 2drop fdrop
s" " log-id
-3 inner drop
log-off
log-where
depth . fdepth . cr
