\ probe: stdin \n\n\n\n\n\n\n\n
\ dbg-fix, then step a colon word with Enter
: sq ( n -- n^2 ) dup * ;
: t ( -- n ) 3 sq 1+ ;
dbg-fix
dbg t
. cr
depth . fdepth . cr
