\ dbg-defer-does.fs -- #39: after dbg-fix, dbg of a DEFER word follows the
\ chain into the colon word, and dbg of a DOES> word steps its does> code,
\ in every engine (as stock dbg does in gforth-itc).  n on a compiled call
\ of either (lit-perform / does-exec in the threaded code) steps over: stock
\ dbg cannot nest there either (it shells out to gdb).
\ test: stdin \nnn\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n
: sq ( n -- n^2 )  dup * ;
defer dsq  ' sq is dsq
: konst ( n "name" -- )  create , does> @ 1+ ;
41 konst kon
: outer ( -- n )  3 dsq kon + ;
dbg-fix
dbg outer  51 s" dbg outer: n on defer and does> calls" assert=
3 dbg dsq  9 s" dbg dsq: nests through the defer" assert=
dbg kon  42 s" dbg kon: steps the does> code" assert=
outer 51 s" outer intact after dbg" assert=
