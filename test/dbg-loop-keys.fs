\ dbg-loop-keys.fs -- dbg-fix steps a do loop with if/else, then c
\ (continue) is not a key: anything but n s a d u ? steps; d = done
\ test: stdin \n\n\n\n\nd
: odd. ( n -- ) dup 1 and if . else drop then ;
: lp ( -- ) 4 0 do i odd. loop ;
dbg-fix
dbg lp
cr depth 0 s" clean" assert=
