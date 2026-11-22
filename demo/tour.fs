\ tour.fs -- a guided tour of gforth-inspect.  Load after inspect.fs:
\   gforth inspect.fs tour.fs
\ Type the lines shown after each "try:" at the prompt.

: avg ( n1 n2 -- n3 )  + ~~~ 2/ ;
: sq ( n -- n' )  dup * ;
: sum-sq ( n1 n2 -- n3 )  sq swap sq + ~~~ ;
: deep ( -- )  .rs ;
: deeper ( -- )  deep ;
: fsq ( F: r -- F: r' )  fdup f* ;
: hyp ( F: r1 r2 -- F: r3 )  fsq fswap fsq f+ fsqrt ;
: classify ( n -- )
    dup 0< IF drop ." negative" EXIT THEN
    0= IF ." zero" EXIT THEN  ." positive" ;

: tour ( -- )
    cr ." gforth-inspect " inspect-version type ."   (log contract " contract-version type ." )"
    cr ." The pane on the right follows the JSON log."
    cr
    cr ." 1  every stack:          1 2 3  1.5e  .stacks"
    cr ." 2  inside a definition:  10 20 avg ."
    cr ." 3  nested calls:         3 4 sum-sq ."
    cr ." 4  return stack:         deeper"
    cr ." 5  floats:               3e 4e hyp f.   then   1e 0e f/ -0e .stacks fclearstack"
    cr ." 6  control flow at compile time:  : t 0 IF BEGIN .cs AGAIN THEN ;"
    cr ." 7  plain ~~ shows everything:     all-~~  : t2 ~~ ;  5 t2 drop"
    cr ." 8  tag the next snapshots:        s" [char] " emit ."  step-8" [char] " emit
       ."  log-id  7 .stacks drop  s" [char] " emit ."  " [char] " emit ."  log-id"
    cr ." 9  step through a word:           dbg+  dbg classify   (keys: Enter step, n nest, c continue)"
    cr
    cr ." tour  prints this again.  log-where  shows the log file.  bye  quits."
    cr ;

log-on
tour
