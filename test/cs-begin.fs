\ cs-begin.fs -- .cs on begin/while/repeat, begin/until, begin/again
: w ( n -- ) begin [ .cs ] dup while [ .cs ] 1- repeat [ .cs ] drop ;
: u ( n -- ) begin 1- dup 0= [ .cs ] until drop ;
: a ( -- ) begin [ .cs ] exit again [ .cs ] ;
3 w 3 u a
