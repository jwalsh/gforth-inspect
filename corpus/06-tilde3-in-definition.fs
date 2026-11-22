\ 06-tilde3-in-definition: ~~~ compiled into a word.  "where" names the
\ word, "src" is file:line of the ~~~, and "input" is the line that ran it.
: scale ( n -- n' ) ( F: r -- r' ) ~~~ 10 * 2e f* ;
log-on
7 1.25e scale .stacks
bye
