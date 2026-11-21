\ demo-env.fs -- the same program, instrumented from the Forth side
\ gforth env/inspect.fs test/demo-env.fs
: inner ( n -- n' )  dup 2 mod 0= if 10 * ~~~ then ;
: middle ( n -- sum )  0 swap 0 do i inner + loop ;
: fmix ( n -- ) ( F: -- r )  s>f 1.5e f* ~~~ ;
: outer ( -- sum ) ( F: -- r )  11 22 33  3.25e  4 middle  dup fmix ;
: cs-demo ( n -- )  0 ?do  i 2 > if  [ .cs ] begin  [ .cs ] dup while repeat then  loop ;
outer . f. . . . cr
