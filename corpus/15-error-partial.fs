\ 15-error-partial: the program aborts on an undefined word.  The log just
\ stops: no log-off, no closing record.  A consumer cannot tell a crashed
\ producer from a paused one by reading the log.
log-on
1 .stacks
2 no-such-word .stacks
3 .stacks
bye
