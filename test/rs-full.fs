\ rs-full.fs -- rs-full on lists interpreter frames; off stops at them
: w ( -- ) .rs ;
rs-full @ 0= s" rs-full off by default" assert
w
rs-full on w rs-full off
w
