\ probe: stdin \nn\n\n\n\n\n\n\n\n\n
\ dbg+ with n: nest into a colon word
: sq ( n -- n^2 ) dup * ;
: t ( -- n ) 3 sq 1+ ;
dbg+
dbg t
. cr
depth . fdepth . cr
