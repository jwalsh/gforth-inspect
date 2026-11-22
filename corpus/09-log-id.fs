\ 09-log-id: s" ..." log-id tags every later snapshot with "id"; s" "
\ log-id clears it and the key is omitted again.  Tags are JSON-escaped.
log-on
1 .stacks drop
s" step-1" log-id 2 .stacks drop
s\" tag \"quoted\"" log-id 3 .stacks drop
s" " log-id 4 .stacks drop
bye
