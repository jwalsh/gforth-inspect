\ gforth-inspect v0.1.0
\ stacks-log schema v1
\
\ inspect.fs -- see all of gforth 0.7.3's stacks from inside gforth
\
\   .rs       return stack, top first, with word+offset for return addresses;
\             stops at the interpreter unless rs-full is on
\   .input    current input line, file:line, and a caret at >IN
\   .stacks   .s  f.s  .rs  .input
\   fclearstack  empty the float stack (missing from 0.7.3)
\   log-on / log-off / log-where  JSON records (contract/stacks-log.org)
\   ~~~       like ~~ (file:line to stderr) but prints .stacks; the return
\             stack is taken at the ~~~ itself, not inside the printer
\   .cs       IMMEDIATE: decode the compile-time control-flow stack
\   all-~~    make plain ~~ print .stacks (via the printdebugdata hook)
\   dbg-fix   make stock dbg work in gforth/gforth-fast (it is ITC-only),
\             including n (nest) into colon words
\   dbg+      dbg-fix, and print .s f.s and return words at every step
\   inspect-version  ( -- c-addr u )  "0.1.0"
\
\ Works in gforth, gforth-fast and gforth-itc 0.7.3.  None of these words
\ changes BASE or the float PRECISION.  Tests: test/, run with `gmake test'.

\ ~~ (debugs.fs) and dbg (debug.fs) are already in the 0.7.3 image;
\ REQUIRE-ing them again would redefine half the system.

: inspect-version ( -- c-addr u ) s" 0.1.0" ;

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
    \ print name+offset if addr is inside a colon definition (offset in
    \ decimal bytes, whatever BASE is)
    dup enclosing ?dup IF
        dup >head-noprim .name ." +" - 0 dec.r
    ELSE drop THEN ;

: stack-region? ( x -- f )
    dup sp0 @ 4096 cells - sp0 @ 1+ within
    over rp0 @ 4096 cells - rp0 @ 1+ within or
    over fp0 @ 4096 floats - fp0 @ 1+ within or
    swap lp@ 4096 cells - lp@ 4096 cells + within or ;

\ --- return stack ----------------------------------------------------

variable rs-full  rs-full off
\ rs-full on   list the whole return stack, interpreter frames included

: interp-frame? ( addr -- f )
    \ a return into gforth's text interpreter or its exception frames
    enclosing dup 0= IF EXIT THEN
    dup ['] interpret1 = over ['] interpret = or over ['] handler-intro, = or
    over ['] (quit) = or swap ['] quit = or ;

: .rs-from ( a-addr -- )
    \ print return-stack cells from a-addr (top) up to rp0; unless rs-full,
    \ stop at the text interpreter (interpret1): below it is gforth's own.
    \ Depth and offsets in decimal, addresses in hex, plain values in BASE.
    rp0 @ over - cell / 0 max ." <R:" 0 dec.r ." > top first" cr
    rp0 @ swap ?DO
        rs-full @ 0= i @ interp-frame? and IF
            ."   ... interpreter (rs-full on to see it)" cr UNLOOP EXIT THEN
        2 spaces i @ dup hex.
        dup enclosing IF ." = " .where
        ELSE dup stack-region? IF drop ." (stack pointer)"
        ELSE ." = " . THEN THEN cr
    cell +LOOP ;

: .rs ( -- ) \ return stack of the caller of .rs
    rp@ cell+ .rs-from ;

\ --- input stream ----------------------------------------------------

: .input ( -- )
    \ the caret is placed under >IN; tabs before it are echoed as tabs
    \ so it lines up on a terminal
    sourcefilename type ." :" sourceline# 0 dec.r
    ."  >in=" >in @ 0 dec.r cr
    source type cr
    source >in @ min bounds ?DO
        i c@ 9 = IF 9 ELSE bl THEN emit
    LOOP ." ^" cr ;

\ --- structured log: contract/stacks-log.org (schema v1) --------------
\   log-on    ( -- )  append JSON records to <dir>/stacks.jsonl
\   log-off   ( -- )  stop and close
\   log-where ( -- )  print the log file's path
\ <dir> is $GFORTH_INSPECT_LOG_DIR if set and non-empty, else
\ ${XDG_STATE_HOME:-$HOME/.local/state}/gforth-inspect.  It is computed at
\ log-on, so changing the environment after loading is honoured.
\ While on, .stacks, ~~~ and (after all-~~) ~~ also write a snapshot record.

1024 constant log-max
create log-dir log-max allot  variable log-dir#
create log-path log-max allot variable log-path#

: buf+ ( c-addr u buf len-var -- )
    \ append c-addr u to buf, whose length is in len-var
    >r over r@ @ + log-max > abort" inspect.fs: log path too long"
    r@ @ + swap dup r> +! move ;

: log-paths ( -- )
    0 log-dir# !  0 log-path# !
    s" GFORTH_INSPECT_LOG_DIR" getenv dup IF log-dir log-dir# buf+ ELSE
        2drop s" XDG_STATE_HOME" getenv dup IF log-dir log-dir# buf+ ELSE
            2drop s" HOME" getenv log-dir log-dir# buf+
            s" /.local/state" log-dir log-dir# buf+ THEN
        s" /gforth-inspect" log-dir log-dir# buf+ THEN
    log-dir log-dir# @ log-path log-path# buf+
    s" /stacks.jsonl" log-path log-path# buf+ ;

variable logging  logging off   variable log-fid  0 log-fid !
variable snap-file  variable snap-line  variable snap-xt  variable snap-rp
variable n#  variable first?

: q ( -- ) [char] " emit ;
: jc ( -- ) [char] , emit ;  \ a JSON comma
: jkey ( c-addr u -- ) q type q [char] : emit ;

: .hex4 ( u -- ) \ four lower-case hex digits, BASE untouched
    base @ >r hex  0 <# # # # # #> r> base !
    bounds ?DO i c@ dup [char] A [char] G within IF bl or THEN emit LOOP ;

: utf8-cont? ( c-addr -- f ) c@ $80 $C0 within ;

: utf8-len ( c-addr u -- n )
    \ length of the valid UTF-8 sequence at c-addr (u bytes left), or 0;
    \ rejects overlongs, surrogates and code points above U+10FFFF
    over c@ >r
    r@ $C2 $E0 within IF 2 ELSE
    r@ $E0 $F0 within IF 3 ELSE
    r@ $F0 $F5 within IF 4 ELSE  rdrop 2drop 0 EXIT THEN THEN THEN
    ( c-addr u n ) tuck < IF rdrop 2drop 0 EXIT THEN
    ( c-addr n ) over 1+ c@
    r@ $E0 = IF dup $A0 < IF rdrop drop 2drop 0 EXIT THEN THEN
    r@ $ED = IF dup $9F > IF rdrop drop 2drop 0 EXIT THEN THEN
    r@ $F0 = IF dup $90 < IF rdrop drop 2drop 0 EXIT THEN THEN
    r> $F4 = IF dup $8F > IF drop 2drop 0 EXIT THEN THEN
    drop
    dup 1 ?DO over i + utf8-cont? 0= IF 2drop 0 UNLOOP EXIT THEN LOOP
    nip ;

: jesc ( c -- ) [char] \ emit emit ;  \ a backslash escape

: json-chars ( c-addr u -- )
    \ the body of a JSON string: escape " and \, control characters as
    \ \n \t \r \b \f or \u00XX, invalid UTF-8 bytes as \ufffd.  The
    \ backslash is emitted on its own: gforth 0.7.3's ." turns a literal
    \ \ufffd into the UTF-8 character itself
    BEGIN dup WHILE
        over c@ >r
        r@ [char] " = r@ [char] \ = or IF r@ jesc 1
        ELSE r@ 10 = IF [char] n jesc 1 ELSE r@ 9 = IF [char] t jesc 1
        ELSE r@ 13 = IF [char] r jesc 1 ELSE r@ 8 = IF [char] b jesc 1
        ELSE r@ 12 = IF [char] f jesc 1
        ELSE r@ bl < IF [char] u jesc r@ .hex4 1
        ELSE r@ $80 < IF r@ emit 1
        ELSE 2dup utf8-len ?dup IF >r over r@ type r>
        ELSE [char] u jesc ." fffd" 1
        THEN THEN THEN THEN THEN THEN THEN THEN THEN
        rdrop /string
    REPEAT 2drop ;
: json-str ( c-addr u -- ) q json-chars q ;

: json-f ( r -- )
    \ finite floats in fs. notation at 17 significant digits, which
    \ round-trips every binary64 (and always gives digits after the point,
    \ which JSON requires); -0 keeps its sign; NaN and infinities -> null
    fdup fdup f- f0= 0= IF fdrop ." null" EXIT THEN
    fdup f0= IF 1e fswap f/ f0< IF ." -0.0" ELSE ." 0.0" THEN EXIT THEN
    precision >r 17 set-precision fs. r> set-precision ;
: sep ( -- ) first? @ IF first? off ELSE jc THEN ;

: json-data ( -- )
    [char] [ emit  depth n# !  first? on
    n# @ 0 ?DO sep n# @ 1- i - pick 0 .r LOOP  [char] ] emit ;
: json-float ( -- )
    [char] [ emit  fdepth n# !  first? on
    n# @ 0 ?DO sep n# @ 1- i - fpick json-f LOOP  [char] ] emit ;
: json-rs ( a-addr -- )
    [char] [ emit  first? on
    rp0 @ swap ?DO
        rs-full @ 0= i @ interp-frame? and IF LEAVE THEN
        sep i @ dup enclosing ?dup IF
            [char] { emit  s" word" jkey dup >head-noprim name>string json-str
            jc s" off" jkey - 0 .r [char] } emit
        ELSE dup stack-region? IF drop s" sp" json-str ELSE 0 .r THEN THEN
    cell +LOOP  [char] ] emit ;
: json-input ( -- )
    [char] { emit  s" file" jkey sourcefilename json-str
    jc s" line" jkey sourceline# 0 .r
    jc s" in" jkey >in @ 0 .r
    jc s" text" jkey source json-str  [char] } emit ;
: json-head ( c-addr u -- )
    [char] { emit  s" v" jkey 1 0 .r  jc s" event" jkey json-str
    jc s" t" jkey utime 1000000 um/mod nip 0 .r ;

: (snapshot) ( -- )
    s" snapshot" json-head
    jc s" where" jkey snap-xt @ ?dup IF >head-noprim name>string json-str ELSE ." null" THEN
    jc s" src" jkey snap-xt @ IF
        q snap-file @ loadfilename#>str json-chars [char] : emit snap-line @ 0 .r q
    ELSE ." null" THEN
    jc s" data" jkey json-data
    jc s" float" jkey json-float
    jc s" rs" jkey snap-rp @ json-rs
    jc s" input" jkey json-input  [char] } emit cr ;
: (hello) ( -- )
    s" hello" json-head  jc s" gforth" jkey version-string json-str
    jc s" inspect" jkey inspect-version json-str  [char] } emit cr ;

: log-write ( xt -- )
    \ run xt with output to the log, in decimal; BASE is restored after
    base @ >r decimal
    log-fid @ ['] outfile-execute catch
    r> base !  throw
    log-fid @ flush-file throw ;
: log-snapshot ( -- ) logging @ IF ['] (snapshot) log-write THEN ;

: log-on ( -- )
    logging @ IF EXIT THEN
    log-paths
    log-dir log-dir# @ $1ff mkdir-parents drop
    log-path log-path# @ r/w open-file IF
        drop log-path log-path# @ r/w create-file throw THEN
    >r r@ file-size throw r@ reposition-file throw r> log-fid !
    logging on  ['] (hello) log-write ;
: log-off ( -- )
    logging @ 0= IF EXIT THEN  logging off  log-fid @ close-file throw
    0 log-fid ! ;
: log-where ( -- ) log-paths cr log-path log-path# @ type cr ;

\ --- everything ------------------------------------------------------

: .stacks-from ( rp -- )
    >r ." data   " .s cr
    ." float  " f.s cr
    ." return " r> .rs-from
    ." input  " .input ;

: .stacks ( -- )
    \ rp is stored before printing: computing it inside .stacks-from
    \ would show .stacks-from's own frame
    rp@ cell+ snap-rp !  snap-rp @ .stacks-from
    0 snap-xt !  log-snapshot ;

[undefined] fclearstack [IF]
: fclearstack ( F: r1 .. rn -- ) \ gforth 0.7.3 has clearstack but no float twin
    fdepth 0 ?DO fdrop LOOP ;
[THEN]

: .~~~ ( nfile nline xt -- )
    cr -rot .sourcepos ."  in " >head-noprim .name cr ;

: (~~~) ( nfile nline xt rp -- )
    snap-rp !  snap-xt !  snap-line !  snap-file !
    snap-file @ snap-line @ snap-xt @ ['] .~~~ stderr outfile-execute
    snap-rp @ ['] .stacks-from stderr outfile-execute
    log-snapshot ;

: ~~~ ( compilation: -- ; run-time: -- ) \ ~~ with all stacks
    compile-sourcepos latestxt postpone literal
    postpone rp@ postpone (~~~) ; immediate compile-only

: past-debugline ( a-addr -- a-addr' )
    \ skip ~~'s own printer frames (outfile-execute, .debugline-stderr):
    \ start just above the .debugline-stderr return; unchanged if absent
    rp0 @ over ?DO
        i @ enclosing ['] .debugline-stderr = IF drop i cell+ UNLOOP EXIT THEN
    cell +LOOP ;

: ~~-stacks ( -- )
    cr rp@ cell+ past-debugline snap-rp !  snap-rp @ .stacks-from
    0 snap-xt !  log-snapshot ;

: all-~~ ( -- )
    \ plain ~~ now prints all stacks; the return stack starts at the word
    \ that contains the ~~, not inside ~~'s printer
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
    \ until the colon-sys (type 0); addresses are relative to `here'.
    \ Never reads below the bottom of the stack.
    cr ." CS: here=" here hex.
    depth 0 ?DO
        i 2 + depth 1- < 0= IF LEAVE THEN  \ depth counts the i+2 itself
        i pick dup 1 6 within 0= IF
            0= IF ."  | colon-sys" THEN LEAVE
        THEN
        cr 2 spaces .cs-type space
        i 1+ pick dup hex.
        here swap - cell / ."  (" 0 dec.r ."  cells back)"
    3 +LOOP cr ; immediate

\ --- dbg: show all stacks at every step -------------------------------

: patch-colon ( xt-new xt-old -- )
    \ overwrite the start of xt-old's body with "call xt-new ; exit";
    \ xt-old's body must be at least 3 cells long
    >body here >r dp ! compile, postpone exit r> dp ! ;


\ --- dbg on direct-threaded engines ----------------------------------
\ Stock 0.7.3 dbg is ITC-only (debug.fs: "!!! dependency: ITC"): set-bp
\ stores the xt of BREAKER into one threaded-code cell.  In gforth and
\ gforth-fast a threaded-code cell is a code address, so the first step
\ jumps into data and dies with "Address alignment exception".  dbg-fix
\ replaces the breakpoint with the two-cell sequence COMPILE, produces for
\ a colon call (call <body>), which is valid threaded code in every
\ engine, saving both cells of both breakpoints before writing any.
\
\ Two-cell breakpoints need care that one-cell ones did not:
\ - adjacent targets (IF x THEN with a one-cell x: next = a, branch
\   target = a+cell) would overlap, the second write clobbering the first
\   breakpoint's operand (crash).  Then only the later one is set: both
\   paths reach it, the fall-through path one instruction later.
\ - in gforth-fast `see' cannot decode static superinstructions (2 + is
\   one instruction with an inline 2), so get-next names the operand cell
\   as the next instruction.  A breakpoint written there corrupted the
\   word for good (it was never hit, so never restored).  Now a target
\   must hold a recognised instruction; otherwise the first one after it
\   (up to 16 cells) is used, and a step is skipped rather than code lost.
\ - whatever happens, dbg restores any breakpoint still set when it ends.

create bp2 0 , 0 ,
create dt2 4 cells allot
create bp-code 2 cells allot
variable bp-a  variable bp-b

: breaker2 ( R:ret -- )  r> 2 cells - dbg-ip !  DebugLoop @ jump ;

\ the threaded code of bp-template starts with exactly "call <breaker2>"
\ (interpretive COMPILE, followed by rolling back DP breaks the next
\ definition in the direct-threaded engines, so copy it from a real one)
: bp-template ( -- )  breaker2 ;
' bp-template >body bp-code 2 cells move

: instruction? ( x -- f )
    \ does threaded-code cell content x name a primitive or a word?
    dup threaded>name IF drop true EXIT THEN  look nip ;

: bp-site ( addr -- addr' | 0 )
    \ addr, or the first cell after it holding a recognised instruction
    16 0 DO dup @ instruction? IF UNLOOP EXIT THEN cell+ LOOP drop 0 ;

: save-bp ( addr slot -- )
    2dup cells bp2 + !  2* cells dt2 + 2 cells move ;

: set-bp2 ( 0 n | 0 n n -- )
    \ n on top = fall-through (bp-a), the one below = branch target (bp-b)
    0. bp2 2!  0 bp-b !
    bp-a !  ?dup IF bp-b ! drop THEN
    bp-a @ dup IF bp-site THEN bp-a !
    bp-b @ dup IF bp-site THEN bp-b !
    bp-a @ bp-b @ and IF
        bp-a @ bp-b @ =             IF 0 bp-b ! THEN
        bp-a @ cell+ bp-b @ =       IF 0 bp-a ! THEN
        bp-b @ ?dup IF cell+ bp-a @ = IF 0 bp-b ! THEN THEN
    THEN
    bp-a @ ?dup IF 0 save-bp THEN
    bp-b @ ?dup IF 1 save-bp THEN
    bp2 @       ?dup IF bp-code swap 2 cells move THEN
    bp2 cell+ @ ?dup IF bp-code swap 2 cells move THEN ;

: restore-bp2 ( -- ) \ idempotent: clears bp2
    bp2 cell+ @ ?dup IF dt2 2 cells + swap 2 cells move THEN
    bp2 @       ?dup IF dt2 swap 2 cells move THEN
    0. bp2 2! ;

: nestXT+ ( x -- true | body false )
    \ the n (nest) key.  Stock nestXT treats the threaded cell as an xt and
    \ runs xt-see on it; in direct-threaded engines that cell is engine code,
    \ so xt-see shells out to gdb and dies (even nesting a colon word).
    \ Here a colon call is the cell `call`'s code address followed by the
    \ target body; anything else (primitive, literal) steps instead.
    dup ['] call @ = IF drop ['] call THEN
    dup ['] call = over colon-xt? or 0= IF
        drop cr ." (not a colon definition: stepped over)" true EXIT THEN
    nestXT-checkSpecial
    DebugMode c-pass ! C-Output off  xt-see  C-Output on
    c-pass @ DebugMode = dup IF cr ." Cannot debug!!" THEN ;

: dbg2 ( "name" -- ) \ stock dbg, then clear any breakpoint left set
    ' NestXT IF EXIT THEN (debug) restore-bp2 Leave-D ;

: dbg-fix ( -- )
    ['] set-bp2 ['] set-bp patch-colon
    ['] restore-bp2 ['] restore-bp patch-colon
    ['] nestXT+ ['] nestXT patch-colon
    ['] dbg2 ['] dbg patch-colon ;

: dbg-frame? ( xt -- f ) \ the debugger's own words
    dup ['] (_debug) = over ['] (debug) = or over ['] dbg = or swap ['] dbg2 = or ;

: dbg-stacks ( -- )
    \ D: data  F: float  R: the colon words on the return stack (callers
    \ of the word being stepped), debugger frames left out; stops at the
    \ text interpreter unless rs-full
    cr ." D: " .s ."  F: " f.s ." R:" 0
    rp0 @ rp@ cell+ ?DO
        rs-full @ 0= i @ interp-frame? and IF LEAVE THEN
        i @ enclosing ?dup IF
            dup dbg-frame? rs-full @ 0= and IF drop ELSE
                space >head-noprim .name 1+ dup 8 = IF ." ..." LEAVE THEN
            THEN
        THEN
    cell +LOOP 0= IF ."  -" THEN ;

: dbg+ ( -- )
    \ dbg that works in every engine and shows D: F: R: at each step
    dbg-fix ['] dbg-stacks ['] d.s patch-colon ;
