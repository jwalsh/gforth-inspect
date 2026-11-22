\ demo.fs -- nested calls, a do loop, floats, an if/then, and brk points
\ needs env/brk.fs loaded first (gforth env/brk.fs test/demo.fs)
\ test: noinspect
\ test: load env/brk.fs
: inner ( n -- n' )  dup 2 mod 0= if 10 * brk then ;
: middle ( n -- sum )  0 swap 0 do i inner + loop ;
: fmix ( n -- ) ( F: -- r )  s>f 1.5e f* brk ;
: outer ( -- sum ) ( F: -- r )  11 22 33  3.25e  4 middle  dup fmix ;
outer . f. . . . cr
bye
