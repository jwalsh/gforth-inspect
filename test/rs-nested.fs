\ rs-nested.fs -- .rs in nested words and inside do loops (loop params)
: c ( -- ) .rs ;
: b ( -- ) c ;
: a ( -- ) b ;
a
: lp ( -- ) 3 1 do i 2 = if .rs then loop ;
lp
: deep ( n -- ) dup 0> if 1- recurse else drop .rs then ;
3 deep
