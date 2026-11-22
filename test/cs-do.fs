\ cs-do.fs -- .cs on do/loop, ?do/loop, do/+loop, and nested loops
: d1 ( -- ) 3 0 do [ .cs ] loop [ .cs ] ;
: d2 ( n -- ) 0 ?do [ .cs ] loop ;
: d3 ( -- ) 10 0 do [ .cs ] 2 +loop ;
: d4 ( -- ) 2 0 do 2 0 do [ .cs ] loop loop ;
d1 3 d2 d3 d4
