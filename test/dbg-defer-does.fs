\ dbg-defer-does.fs -- #39 and its review: after dbg-fix, dbg of a DEFER word
\ follows the chain (a colon word, a :noname word, or a DOES> word with its
\ body), dbg of a DOES> word steps its does> code, n still nests into a
\ headerless colon call, a cyclic DEFER stops after 16 hops and is not
\ run, and a word dbg cannot debug is run (as "stepped over" says).  n on a
\ compiled defer or does> call (lit-perform / does-exec in the threaded
\ code) steps over: stock dbg cannot nest there either (it shells out to gdb).
\ test: stdin \nnn\n\n\n\n\n\n\n\n\n\n\n\n\n\n\nn\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n
: sq ( n -- n^2 )  dup * ;
defer dsq  ' sq is dsq
: konst ( n "name" -- )  create , does> @ 1+ ;
41 konst kon
defer dkon  ' kon is dkon
:noname 2 * ; constant twice
defer dtwice  twice is dtwice
: usetwice ( -- n )  3 [ twice compile, ] 1+ ;
defer loopy  ' loopy is loopy
defer ddup  ' dup is ddup
: outer ( -- n )  3 dsq kon + ;
dbg-fix
dbg outer  51 s" dbg outer: n on defer and does> calls steps over" assert=
3 dbg dsq  9 s" dbg dsq: nests through the defer" assert=
dbg kon  42 s" dbg kon: steps the does> code" assert=
dbg dkon  42 s" dbg dkon: defer to a does> word nests with its body" assert=
3 dbg dtwice  6 s" dbg dtwice: defer to a :noname word nests" assert=
dbg usetwice  7 s" dbg usetwice: n nests into a headerless colon call" assert=
dbg loopy  depth 0 s" dbg loopy: a cyclic defer stops, runs nothing" assert=
3 dbg ddup  3 s" dbg ddup: a defer to a primitive is run" assert=  3 s" dbg ddup: both copies" assert=
outer 51 s" outer intact after dbg" assert=
