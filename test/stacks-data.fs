\ stacks-data.fs -- .stacks shows the data stack bottom first, leaves it alone
: three ( -- a b c ) 1 -2 3 ;
three .stacks
depth 3 s" .stacks keeps the data stack" assert=
3 = swap -2 = and swap 1 = and s" values intact" assert
: w ( n -- n ) .stacks ;
42 w 42 s" .stacks inside a word" assert=
depth 0 s" clean" assert=
