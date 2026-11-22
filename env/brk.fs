\ brk.fs -- a Forth-side breakpoint that lldb can stop on with exact VM state
\
\ `brk` calls the C function getpid() through gforth's CALL-C primitive.
\ CALL-C stores the VM registers into the C globals gforth_SP, gforth_FP,
\ gforth_RP and gforth_LP immediately before the call (engine/prim, call-c),
\ so a breakpoint on getpid sees exact stack pointers in every engine
\ (gforth, gforth-fast, gforth-itc).  Without a debugger attached it is a
\ harmless getpid() and costs one syscall.

s" libc.dylib" open-lib dup 0= [IF] drop s" libc.so.6" open-lib [THEN]
constant brk-libc
s" getpid" brk-libc lib-sym constant brk-getpid
brk-getpid 0= [IF] .( brk.fs: lib-sym getpid failed ) cr bye [THEN]

: brk ( -- ) \ stop here when run under lldb with lldb/gforth.py imported
    brk-getpid call-c ;
