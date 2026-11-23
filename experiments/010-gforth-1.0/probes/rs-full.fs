\ rs-full on: the interpreter frames are listed too
: inner ( -- ) .rs ;
rs-full on inner rs-full off
rs-full @ . cr
depth . fdepth . cr
