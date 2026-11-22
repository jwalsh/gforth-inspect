\ 13-empty-line: a snapshot taken while the input line is empty.  The word
\ refills the input buffer from the next line of the file, which is blank,
\ so input.text is "" and input.in is 0.
: next-line-stacks ( -- ) refill drop .stacks ;
log-on
next-line-stacks

bye
