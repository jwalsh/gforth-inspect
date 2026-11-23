\ 18-log-id-63: log-id keeps at most 63 characters; a longer tag is cut to
\ its first 63, not refused, and every later snapshot carries the cut tag.
log-on
s" 0123456789012345678901234567890123456789012345678901234567890123456789-tail" log-id 8 .stacks drop
9 .stacks drop
bye
