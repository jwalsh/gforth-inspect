\ tilde3-nested.fs -- ~~~ in nested words: position, word, all stacks
\ (~~~ writes to stderr); the data stack is unchanged by ~~~
: inner ( n -- n' ) 2* ~~~ ;
: middle ( n -- n' ) 1+ inner ;
: outer ( -- n ) ( F: -- r ) 2.5e 5 middle ;
outer 12 s" result" assert=  fdrop
depth 0 s" clean" assert=
