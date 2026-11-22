\ probe: stdin \n\n\n\n\n\n\n\n
\ dbg+, then step a colon word with Enter; D: F: R: at each step
: sq ( n -- n^2 ) dup * ;
: t ( -- n ) 3 sq 1+ ;
dbg+
dbg t
. cr
depth . fdepth . cr
