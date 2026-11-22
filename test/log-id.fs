\ log-id.fs -- contract 1.1 (#3): log-id tags following snapshots with
\ "id" right after the head; escaped; at most 63 chars; s" " clears it and
\ the key is left out
: kk ( -- ) ~~~ ;
log-on
.stacks
s" step-1" log-id  .stacks  kk
s\" say \"hi\" \\ back" log-id .stacks
s" abcdefghi-abcdefghi-abcdefghi-abcdefghi-abcdefghi-abcdefghi-abcdefghi-" log-id .stacks
s" " log-id .stacks
log-off
depth 0 s" clean" assert=
