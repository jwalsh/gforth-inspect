\ 03-deep-data-stack: 300 cells on the data stack, bottom first in "data".
: push-count ( n -- 0 1 .. n-1 ) 0 ?DO i LOOP ;
log-on
300 push-count .stacks
bye
