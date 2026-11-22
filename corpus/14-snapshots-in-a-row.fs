\ 14-snapshots-in-a-row: several snapshots from one line, then log-off and
\ log-on again, which writes a second hello.  Only the newest hello counts.
log-on
1 .stacks 2 .stacks 3 .stacks clearstack
log-off
log-on
4 .stacks 5 .stacks clearstack
bye
