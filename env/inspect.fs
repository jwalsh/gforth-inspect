\ inspect.fs -- see all of gforth 0.7.3's stacks from inside gforth
\
\   .rs       return stack, top first, with word+offset for return addresses
\   .input    current input line, file:line, and a caret at >IN
\   .stacks   .s  f.s  .rs  .input
\   ~~~       like ~~ (file:line to stderr) but prints .stacks; the return
\             stack is taken at the ~~~ itself, not inside the printer
\   .cs       IMMEDIATE: decode the compile-time control-flow stack
\   all-~~    make plain ~~ print .stacks (via the printdebugdata hook)
\   dbg-fix   make stock dbg work in gforth/gforth-fast (it is ITC-only)
\   dbg+      dbg-fix, and print .s f.s and return words at every step
\
\ Works in gforth, gforth-fast and gforth-itc 0.7.3.

\ ~~ (debugs.fs) and dbg (debug.fs) are already in the 0.7.3 image;
\ REQUIRE-ing them again would redefine half the system.

\ --- naming addresses ------------------------------------------------

: colon-xt? ( addr -- f )
    \ is addr the code field of a colon definition with a real header?
    dup aligned over <> IF drop false EXIT THEN
    dup in-dictionary? 0= IF drop false EXIT THEN
    dup @ docol: <> IF drop false EXIT THEN
    dup >head-noprim dup ['] ??? >head-noprim = IF 2drop false EXIT THEN
    name>int = ;

: enclosing ( addr -- xt | 0 )
    \ the colon definition whose threaded code contains addr; scans back
    \ at most 2048 cells for a code field holding docol:
    dup in-dictionary? 0= IF drop 0 EXIT THEN
    dup aligned over <> IF drop 0 EXIT THEN
    2048 0 DO
        cell - dup forthstart u< IF drop 0 UNLOOP EXIT THEN
        dup colon-xt? IF UNLOOP EXIT THEN
    LOOP drop 0 ;

: .where ( addr -- )
    \ print name+offset if addr is inside a colon definition
    dup enclosing ?dup IF
        dup >head-noprim .name ." +" - 0 .r
    ELSE drop THEN ;

: stack-region? ( x -- f )
    dup sp0 @ 4096 cells - sp0 @ 1+ within
    over rp0 @ 4096 cells - rp0 @ 1+ within or
    over fp0 @ 4096 floats - fp0 @ 1+ within or
    swap lp@ 4096 cells - lp@ 4096 cells + within or ;

\ --- return stack ----------------------------------------------------

: .rs-from ( a-addr -- )
    \ print return-stack cells from a-addr (top) up to rp0
    rp0 @ over - cell / 0 max ." <R:" 0 .r ." > top first" cr
    rp0 @ swap ?DO
        2 spaces i @ dup hex. decimal
        dup enclosing IF ." = " .where
        ELSE dup stack-region? IF drop ." (stack pointer)"
        ELSE ." = " . THEN THEN cr
    cell +LOOP ;

: .rs ( -- ) \ return stack of the caller of .rs
    rp@ cell+ .rs-from ;

\ --- input stream ----------------------------------------------------

: .input ( -- )
    sourcefilename type ." :" sourceline# 0 .r
    ."  >in=" >in @ 0 .r cr
    source type cr
    >in @ source nip min spaces ." ^" cr ;

\ --- everything ------------------------------------------------------

: .stacks-from ( rp -- )
    >r ." data   " .s cr
    ." float  " f.s cr
    ." return " r> .rs-from
    ." input  " .input ;

: .stacks ( -- )  rp@ cell+ .stacks-from ;

: .~~~ ( nfile nline xt -- )
    cr -rot .sourcepos ."  in " >head-noprim .name cr ;

: (~~~) ( nfile nline xt rp -- )
    >r ['] .~~~ stderr outfile-execute
    r> ['] .stacks-from stderr outfile-execute ;

: ~~~ ( compilation: -- ; run-time: -- ) \ ~~ with all stacks
    compile-sourcepos latestxt postpone literal
    postpone rp@ postpone (~~~) ; immediate compile-only

: ~~-stacks ( -- )  cr rp@ cell+ .stacks-from ;

: all-~~ ( -- )
    \ plain ~~ now prints all stacks (the return stack includes ~~'s own
    \ printer frames on top: .debugline-stderr, outfile-execute, catch)
    ['] ~~-stacks IS printdebugdata ;

\ --- compile-time control-flow stack ---------------------------------

: .cs-type ( n -- )
    CASE
        0 OF ." colon-sys" ENDOF
        1 OF ." orig (live)" ENDOF
        2 OF ." orig (dead)" ENDOF
        3 OF ." dest" ENDOF
        4 OF ." do-dest" ENDOF
        5 OF ." scope" ENDOF
        ." ?" dup .
    ENDCASE ;

: .cs ( -- ) \ IMMEDIATE; use inside a definition
    \ walk the data stack from the top in 3-cell items (locals addr type)
    \ until the colon-sys (type 0); addresses are relative to `here'
    cr ." CS: here=" here hex. decimal
    depth 0 ?DO
        i pick dup 1 6 within 0= IF
            0= IF ."  | colon-sys" THEN LEAVE
        THEN
        cr 2 spaces .cs-type space
        i 1+ pick dup hex. decimal
        here swap - cell / ."  (" 0 .r ."  cells back)"
    3 +LOOP cr ; immediate

\ --- dbg: show all stacks at every step -------------------------------

: dbg-stacks ( -- )
    cr ." D: " .s ."  F: " f.s ." R: " rp0 @ rp@ cell+ - cell / 0 .r
    ."  cells:" 0
    rp0 @ rp@ cell+ ?DO i @ enclosing ?dup IF
            space >head-noprim .name 1+ dup 6 = IF ." ..." LEAVE THEN
        THEN
    cell +LOOP drop ;

: patch-colon ( xt-new xt-old -- )
    \ overwrite the start of xt-old's body with "call xt-new ; exit"
    >body here >r dp ! compile, postpone exit r> dp ! ;


\ --- dbg on direct-threaded engines ----------------------------------
\ Stock 0.7.3 dbg is ITC-only (debug.fs: "!!! dependency: ITC"): set-bp
\ stores the xt of BREAKER into one threaded-code cell.  In gforth and
\ gforth-fast a threaded-code cell is a code address, so the first step
\ jumps into data and dies with "Address alignment exception".  dbg-fix
\ replaces the breakpoint with the two-cell sequence COMPILE, produces for
\ a colon call (call <body>), which is valid threaded code in every
\ engine, saving both cells of both breakpoints before writing any.

create bp2 0 , 0 ,
create dt2 4 cells allot
create bp-code 2 cells allot

: breaker2 ( R:ret -- )  r> 2 cells - dbg-ip !  DebugLoop @ jump ;

\ the threaded code of bp-template starts with exactly "call <breaker2>"
\ (interpretive COMPILE, followed by rolling back DP breaks the next
\ definition in the direct-threaded engines, so copy it from a real one)
: bp-template ( -- )  breaker2 ;
' bp-template >body bp-code 2 cells move

: save-bp ( addr slot -- )
    2dup cells bp2 + !  2* cells dt2 + 2 cells move ;

: set-bp2 ( 0 n | 0 n n -- )
    0. bp2 2!
    ?dup IF 0 save-bp ?dup IF 1 save-bp drop THEN THEN
    bp2 @       ?dup IF bp-code swap 2 cells move THEN
    bp2 cell+ @ ?dup IF bp-code swap 2 cells move THEN ;

: restore-bp2 ( -- )
    bp2 cell+ @ ?dup IF dt2 2 cells + swap 2 cells move THEN
    bp2 @       ?dup IF dt2 swap 2 cells move THEN ;

: dbg-fix ( -- )
    ['] set-bp2 ['] set-bp patch-colon
    ['] restore-bp2 ['] restore-bp patch-colon ;

: dbg+ ( -- )
    \ dbg that works in every engine and shows D: F: R: at each step
    dbg-fix ['] dbg-stacks ['] d.s patch-colon ;
