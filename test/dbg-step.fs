\ dbg-step.fs -- dbg+ steps a word with floats; Enter = step
\ test: stdin \n\n\n\n\n\n\n\n\n\n
: sq ( n -- n^2 ) dup * ;
: t ( -- n ) ( F: -- r ) 3 sq 2.5e 2e f* ;
dbg+
dbg t
9 s" result" assert=  5e f= s" float result" assert
t 9 s" t still works" assert= fdrop
