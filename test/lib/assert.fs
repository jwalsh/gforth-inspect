\ assert.fs -- loud assertions for test/*.fs (loaded by test/run.sh)
\ A failure prints "ASSERT FAIL: ..." and exits 1; the runner fails any
\ test whose output contains that text, golden or not.

: assert-fail ( c-addr u -- )
    ." ASSERT FAIL: " type cr  1 (bye) ;
: assert ( f c-addr u -- ) rot IF 2drop ELSE assert-fail THEN ;
: assert= ( actual expected c-addr u -- )
    2>r 2dup = IF 2drop 2rdrop EXIT THEN
    ." ASSERT FAIL: " 2r> type ."  got " swap . ." want " . cr  1 (bye) ;

\ out-path ( c-addr u -- c-addr' u' )  $TEST_OUT/name, for files a test writes
create out-buf 1024 allot  variable out#
: out-path ( c-addr u -- c-addr' u' )
    s" TEST_OUT" getenv dup 0= IF s" TEST_OUT unset" assert-fail THEN
    dup out# !  out-buf swap move  s" /" out-buf out# @ + swap move  1 out# +!
    dup >r out-buf out# @ + swap move  r> out# +!  out-buf out# @ ;
