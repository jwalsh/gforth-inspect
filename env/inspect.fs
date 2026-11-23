\ gforth-inspect v0.3.1
\ stacks-log schema v1
\ SPDX-License-Identifier: GPL-3.0-or-later
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
\   log-id    ( c-addr u -- )  tag following snapshots with "id"; s" " log-id clears
\   inspect-version  ( -- c-addr u )  "0.3.1"
\ The hello record announces "contract":"1.1" (contract/stacks-log.org).
\
\ Works in gforth, gforth-fast and gforth-itc 0.7.3.  The words, their stack
\ effects and output formats: contract/WORDS.org.  None of these words
\ changes BASE or the float PRECISION.  Tests: test/, run with `gmake test'.

\ Dependency check, before any definition (contract/WORDS.org): a 64-bit
\ gforth >= 0.7.3, < 1.0.  Outside that range (version-string read as
\ MAJOR.MINOR.PATCH) or with cells under 8 bytes the load stops: one line
\ on stderr, then -1 throw, so `gforth inspect.fs` exits non-zero and
\ `include inspect.fs` throws.  Any other version that is not exactly
\ 0.7.3 (a 0.7.9 snapshot) gets a one-line notice and loads on.
base @ decimal  \ the load's own BASE: restored at the end of the file, and on a throw
version-string 0 0 2swap >number 2swap drop -rot  dup 0<> negate /string
0 0 2swap >number 2swap drop -rot  dup 0<> negate /string
0 0 2swap >number 2drop drop  swap 1000 * +  swap 1000000 * +
7003 1000000 within 0= [IF]
    s" gforth-inspect requires gforth 0.7.3 (>= 0.7.3, < 1.0); this is gforth "
    stderr write-file throw  version-string stderr write-line throw  base ! -1 throw
[THEN]
1 cells 8 < [IF]
    s" gforth-inspect requires a 64-bit gforth 0.7.3; this one has " stderr write-file throw
    1 cells 0 <# #s #> stderr write-file throw  s" -byte cells" stderr write-line throw
    base ! -1 throw
[THEN]
version-string s" 0.7.3" compare [IF]
    s" gforth-inspect: tested on gforth 0.7.3 only; this is gforth " stderr write-file throw
    version-string stderr write-line throw
[THEN]

\ ~~ (debugs.fs) and dbg (debug.fs) are already in the 0.7.3 image;
\ REQUIRE-ing them again would redefine half the system.

: inspect-version ( -- c-addr u ) s" 0.3.1" ;

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
\ <dir> is, first match wins (contract/stacks-log.org, "Files"):
\   $GFORTH_INSPECT_LOG_DIR, if set and non-empty;
\   <base> = ${XDG_STATE_HOME:-$HOME/.local/state}/gforth-inspect, if the
\     current directory cannot be read;
\   the GFORTH_INSPECT_LOG_DIR= line of <root>/.env, <root> being the
\     nearest ancestor of the current directory (get-dir, never $PWD: a
\     process started in one worktree with $PWD inherited from another must
\     log to its own) holding .git, else the current directory itself;
\   <base>/<owner>/<repo>/<worktree>, read from the files of .git (git is
\     never run), each part one ASCII path component, see (enc+); a
\     detached or reftable worktree is named by its directory's path.
\ It is computed at log-on, so changing the environment after loading is
\ honoured.  While on, .stacks, ~~~ and (after all-~~) ~~ also write a
\ snapshot record.

4096 constant log-max  \ the longest current directory read
log-max 256 + constant (room)  \ every path buffer: a directory plus what is appended
create log-dir (room) allot  variable log-dir#
create log-path (room) allot variable log-path#

: buf+ ( c-addr u buf len-var -- )
    \ append c-addr u to buf, whose length is in len-var
    >r over r@ @ + (room) > abort" inspect.fs: log path too long"
    r@ @ + swap dup r> +! move ;

create (one-char) 1 allot
: (buf-char+) ( c buf len-var -- ) rot (one-char) c! (one-char) 1 2swap buf+ ;
: (dir+) ( c-addr u -- ) log-dir log-dir# buf+ ;
: (dir-char+) ( c -- ) log-dir log-dir# (buf-char+) ;
: (dir/) ( -- ) [char] / (dir-char+) ;

\ --- strings and files for the default log directory --------------------

: (blank?) ( c -- f ) bl 1+ u< ;  \ a control character or a space
: (trim) ( c-addr u -- c-addr' u' ) \ without leading and trailing blanks
    BEGIN dup WHILE over c@ (blank?) WHILE 1 /string REPEAT THEN
    BEGIN dup WHILE 2dup + 1- c@ (blank?) WHILE 1- REPEAT THEN ;
: (index-of) ( c-addr u c -- n ) \ index of the first c, or -1
    >r 2dup r> scan nip dup IF - nip ELSE drop 2drop -1 THEN ;
: (slash-index) ( c-addr u -- n ) \ index of the last /, or -1
    BEGIN dup WHILE 1- 2dup + c@ [char] / = IF nip EXIT THEN REPEAT 2drop -1 ;
: (basename) ( c-addr u -- c-addr' u' ) 2dup (slash-index) 1+ /string ;
: (-slashes) ( c-addr u -- c-addr u' )
    BEGIN dup WHILE 2dup + 1- c@ [char] / = WHILE 1- REPEAT THEN ;
: (abs?) ( c-addr u -- f ) IF c@ [char] / = ELSE drop false THEN ;
: (lower) ( c -- c' ) dup [char] A [char] Z 1+ within IF bl or THEN ;
: (ci=) ( c-addr1 u1 c-addr2 u2 -- f ) \ c-addr1 u1, ASCII-lowercased, is c-addr2 u2
    rot over <> IF drop 2drop false EXIT THEN
    0 ?DO over i + c@ (lower) over i + c@ <> IF 2drop false UNLOOP EXIT THEN LOOP
    2drop true ;
: (unquote) ( c-addr u c -- c-addr' u' ) \ strip one pair of c around c-addr u
    >r dup 2 < IF rdrop EXIT THEN
    over c@ r@ = >r 2dup + 1- c@ r> r> rot = and IF 1 /string 1- THEN ;
: (line) ( c-addr u -- rest-a rest-u line-a line-u ) \ split at the first LF
    2dup 10 (index-of) dup 0< IF drop 2dup + 0 2swap EXIT THEN
    >r over r@ 2swap r> 1+ /string 2swap ;

create (probe) (room) allot  variable (probe#)
: (path/) ( c-addr1 u1 c-addr2 u2 -- c-addr u ) \ "<1>/<2>", built in (probe)
    2swap 0 (probe#) !  (probe) (probe#) buf+  [char] / (probe) (probe#) (buf-char+)
    (probe) (probe#) buf+  (probe) (probe#) @ ;
: (exists?) ( c-addr u -- f ) file-status nip 0= ;
: (dir?) ( c-addr u -- f ) open-dir IF drop false ELSE close-dir throw true THEN ;

variable (file-a)  0 (file-a) !  variable (file-u)  0 (file-u) !
: (slurp-fid) ( fid -- addr u ) \ the rest of the file, allocated; 0 0 (freed) on error
    >r r@ file-size IF 2drop rdrop 0 0 EXIT THEN drop
    dup allocate IF 2drop rdrop 0 0 EXIT THEN
    tuck swap r> read-file IF drop free drop 0 0 EXIT THEN ;
: (slurp) ( c-addr u -- addr u ) \ the whole file; 0 0 if it cannot be read, closed always
    r/o open-file IF drop 0 0 EXIT THEN  dup >r (slurp-fid)  r> close-file drop ;
: (file!) ( c-addr u -- ) \ read the whole file; empty when it cannot be read
    (slurp) (file-u) ! (file-a) ! ;
: (file@) ( -- c-addr u ) (file-a) @ (file-u) @ ;
: (file-free) ( -- ) (file-a) @ ?dup IF free throw THEN  0 (file-a) !  0 (file-u) ! ;

\ --- one path component: (enc+) ------------------------------------------
\ A name matching ^[a-z0-9][a-z0-9._-]{0,63}$ is used as it is.  Any other
\ becomes slug~hash: ASCII-lowercased, every other byte "-", leading "."
\ and "-" dropped, cut to 48 bytes ("_" if that leaves nothing), then "~"
\ and the first 12 hex digits of FNV-1a 64 over the name's own bytes.  A
\ plain name never holds "~", so two names never share a component.

$cbf29ce4 32 lshift $84222325 or constant (fnv-basis)
$100000001b3 constant (fnv-prime)
: (fnv1a64) ( c-addr u -- u' )
    (fnv-basis) -rot bounds ?DO i c@ xor (fnv-prime) * LOOP ;
: (hex12+) ( u -- ) \ the top 48 of u's 64 bits as 12 lower-case hex digits
    12 0 DO dup 60 i 4 * - rshift $f and s" 0123456789abcdef" drop + c@ (dir-char+) LOOP
    drop ;

: (alnum?) ( c -- f ) dup [char] a [char] z 1+ within swap [char] 0 [char] 9 1+ within or ;
: (safe?) ( c -- f ) dup (alnum?) over [char] . = or over [char] _ = or swap [char] - = or ;
: (plain?) ( c-addr u -- f ) \ a name (enc+) uses as it is
    dup 1 65 within 0= IF 2drop false EXIT THEN
    over c@ (alnum?) 0= IF 2drop false EXIT THEN
    bounds ?DO i c@ (safe?) 0= IF false UNLOOP EXIT THEN LOOP true ;
: (lead?) ( c -- f ) dup [char] . = swap [char] - = or ;  \ dropped from a slug's start
: (slug-byte) ( c -- c' ) (lower) dup (safe?) 0= IF drop [char] - THEN ;

variable (slug-room)  variable (slug#)
: (slug+) ( c-addr u room -- ) \ the slug of c-addr u, at most room bytes
    (slug-room) !  0 (slug#) !
    bounds ?DO i c@ (slug-byte)
        (slug#) @ 0= over (lead?) and  (slug#) @ (slug-room) @ = or
        IF drop ELSE (dir-char+) 1 (slug#) +! THEN
    LOOP  (slug#) @ 0= IF [char] _ (dir-char+) THEN ;
: (slug-hash+) ( name-a name-u key-a key-u room -- ) \ slug of name~hash of key
    >r (fnv1a64) -rot r> (slug+)  [char] ~ (dir-char+)  (hex12+) ;
: (hashed+) ( c-addr u room -- ) \ slug~hash of c-addr u, the slug at most room bytes
    >r 2dup r> (slug-hash+) ;
: (enc+) ( c-addr u -- ) 2dup (plain?) IF (dir+) ELSE 48 (hashed+) THEN ;

\ --- the project: its root, .env and git metadata ----------------------

: (git-root) ( c-addr u -- c-addr u' true | c-addr u false )
    \ the nearest ancestor of the path, itself included, holding .git (a
    \ directory, or the file of a linked worktree): a prefix of the path,
    \ "/" for the root directory; else the path itself and false
    2dup BEGIN
        2dup s" .git" (path/) (exists?) IF
            2swap 2drop dup 0= IF drop 1 THEN true EXIT THEN
        2dup (slash-index) dup 0< IF drop 2drop false EXIT THEN nip
    AGAIN ;

\ .env: [export] GFORTH_INSPECT_LOG_DIR = value, blanks allowed around;
\ "value" or 'value' taken inside the quotes, else cut at a # after a
\ blank and trimmed.  The last such line wins.
: (ws?) ( c -- f ) dup bl = swap 9 = or ;
: (skip-ws) ( c-addr u -- c-addr' u' ) BEGIN dup WHILE over c@ (ws?) WHILE 1 /string REPEAT THEN ;
: (-ws) ( c-addr u -- c-addr u' ) BEGIN dup WHILE 2dup + 1- c@ (ws?) WHILE 1- REPEAT THEN ;
: (-export) ( c-addr u -- c-addr' u' ) \ without a leading "export" and its blanks
    2dup s" export" string-prefix? 0= IF EXIT THEN
    dup 7 < IF EXIT THEN  over 6 + c@ (ws?) 0= IF EXIT THEN  6 /string (skip-ws) ;
: (-comment) ( c-addr u -- c-addr u' ) \ up to the first # that follows a blank
    dup 2 < IF EXIT THEN
    dup 1 DO over i + c@ [char] # = IF over i + 1- c@ (ws?) IF drop i LEAVE THEN THEN LOOP ;
: (quoted) ( c-addr u -- c-addr' u' true | c-addr u false ) \ inside a leading ' or " pair
    dup 2 < IF false EXIT THEN
    over c@ dup [char] " = over [char] ' = or 0= IF drop false EXIT THEN
    >r 2dup 1 /string r> (index-of) dup 0< IF drop false EXIT THEN
    >r drop 1+ r> true ;
: (env-line?) ( c-addr u -- raw-a raw-u true | false ) \ what follows = on our line
    dup IF 2dup + 1- c@ 13 = IF 1- THEN THEN  (skip-ws) (-export)
    2dup s" GFORTH_INSPECT_LOG_DIR" string-prefix? 0= IF 2drop false EXIT THEN
    22 /string (skip-ws)  dup 0= IF 2drop false EXIT THEN
    over c@ [char] = <> IF 2drop false EXIT THEN  1 /string true ;
: (env-value-of) ( raw-a raw-u -- c-addr u )
    2dup (skip-ws) (quoted) IF 2nip EXIT THEN 2drop  (-comment) (skip-ws) (-ws) ;
variable (env-a)  variable (env-u)
: (env-value) ( c-addr u -- c-addr' u' ) \ the value of the last such line, or empty
    0 (env-a) !  0 (env-u) !
    BEGIN dup WHILE (line) (env-line?) IF (env-u) ! (env-a) ! THEN REPEAT 2drop
    (env-a) @ (env-u) @ (env-value-of) ;
: (env-path+) ( root-a root-u c-addr u -- ) \ ~ and ~/ from $HOME, relative to root
    2dup s" ~" compare 0= IF 2drop 2drop s" HOME" getenv (dir+) EXIT THEN
    2dup s" ~/" string-prefix? IF 2swap 2drop s" HOME" getenv (dir+) 1 /string (dir+) EXIT THEN
    2dup (abs?) IF 2swap 2drop (dir+) EXIT THEN
    2swap (dir+) (dir/) (dir+) ;
: (dotdot?) ( c-addr u -- f ) \ the path has a ".." segment
    BEGIN dup WHILE 2dup [char] / (index-of) dup 0< IF drop s" .." compare 0= EXIT THEN
        >r over r@ s" .." compare 0= IF rdrop 2drop true EXIT THEN r> 1+ /string
    REPEAT 2drop false ;
variable (h-a)  variable (h-u)
: (under-home?) ( c-addr u -- f ) \ $HOME itself or below it; false without $HOME
    s" HOME" getenv dup 0= IF 2drop 2drop false EXIT THEN  (-slashes) (h-u) ! (h-a) !
    2dup (h-a) @ (h-u) @ compare 0= IF 2drop true EXIT THEN
    dup (h-u) @ > 0= IF 2drop false EXIT THEN
    over (h-u) @ (h-a) @ (h-u) @ compare IF 2drop false EXIT THEN
    drop (h-u) @ + c@ [char] / = ;
: (env-trusted?) ( c-addr u -- f ) \ a .env (committed, cloned) may not log just anywhere
    2dup (dotdot?) IF 2drop false EXIT THEN
    2dup (abs?) IF (under-home?) ELSE 2drop true THEN ;
: (env-warn) ( c-addr u -- ) \ one line on stderr
    s" gforth-inspect: ignoring .env GFORTH_INSPECT_LOG_DIR" stderr write-file drop
    stderr write-line drop ;
: (fits?) ( -- f ) log-dir# @ (room) 13 - <= ;  \ room left for /stacks.jsonl
: (dotenv+) ( root-a root-u -- f ) \ <root>/.env's value as a path; false if none or refused
    2dup s" .env" (path/) (file!)  (file@) (env-value)
    dup 0= IF 2drop 2drop false (file-free) EXIT THEN
    2dup (env-trusted?) 0= IF 2drop 2drop s"  outside $HOME" (env-warn) false (file-free) EXIT THEN
    log-dir# @ >r  ['] (env-path+) catch IF 2drop 2drop false ELSE (fits?) THEN
    dup 0= IF r@ log-dir# !  s" : too long" (env-warn) THEN  rdrop
    log-dir# @ 0<> and  (file-free) ;

create (git-dir) (room) allot  variable (git-dir#)
create (common) (room) allot   variable (common#)
: (git-dir+) ( c-addr u -- ) (git-dir) (git-dir#) buf+ ;
: (common+) ( c-addr u -- ) (common) (common#) buf+ ;
: (gitdir-line) ( c-addr u -- c-addr' u' true | false ) \ <path> of "gitdir: <path>"
    (trim) 2dup s" gitdir:" string-prefix? IF 7 /string (trim) true ELSE 2drop false THEN ;
: (in-root+) ( root-a root-u c-addr u -- ) \ the path, made absolute against root
    2dup (abs?) IF 2swap 2drop (git-dir+) EXIT THEN
    2swap (git-dir+) s" /" (git-dir+) (git-dir+) ;
: (git-dir!) ( root-a root-u -- ) \ the worktree's git dir: .git, or its gitdir: line
    0 (git-dir#) !  2dup s" .git" (path/) 2dup (dir?) IF (git-dir+) 2drop EXIT THEN
    (file!) (file@) (gitdir-line) IF (in-root+) ELSE s" .git" (in-root+) THEN (file-free) ;
: (common!) ( -- ) \ the common git dir: from the git dir's commondir file, else the git dir
    0 (common#) !  (git-dir) (git-dir#) @ s" commondir" (path/) (file!) (file@) (trim)
    dup IF 2dup (abs?) 0= IF (git-dir) (git-dir#) @ (common+) s" /" (common+) THEN (common+)
    ELSE 2drop (git-dir) (git-dir#) @ (common+) THEN (file-free) ;

create (norm) (room) allot  variable (norm#)
: (norm+) ( c-addr u -- ) \ one component onto (norm): "" and "." skipped, ".." drops one
    dup 0= IF 2drop EXIT THEN  2dup s" ." compare 0= IF 2drop EXIT THEN
    2dup s" .." compare 0= IF 2drop (norm) (norm#) @ (slash-index) 0 max (norm#) ! EXIT THEN
    s" /" (norm) (norm#) buf+  (norm) (norm#) buf+ ;
: (main-name) ( -- c-addr u ) \ basename of the common dir's parent, . and .. lexical
    0 (norm#) !  (common) (common#) @
    BEGIN dup WHILE 2dup [char] / (index-of) dup 0< IF drop (norm+) 0 0 ELSE
        >r over r@ (norm+) r> 1+ /string THEN REPEAT 2drop
    (norm) (norm#) @ 2dup (slash-index) 0 max nip (basename) ;

variable (in-origin)
: (origin-header?) ( c-addr u -- f ) \ [remote "origin"], "remote" in any case
    dup 17 <> IF 2drop false EXIT THEN
    over 8 s" [remote " (ci=) -rot 8 /string s\" \"origin\"]" compare 0= and ;
: (key-line?) ( c-addr u key-a key-u -- c-addr' u' true | false ) \ "key = <value>"
    2>r 2dup [char] = (index-of) dup 0< IF drop 2drop 2rdrop false EXIT THEN
    >r over r@ (trim) r> -rot 2r> (ci=) 0= IF drop 2drop false EXIT THEN
    1+ /string (trim) [char] " (unquote) true ;
: (url-line?) ( c-addr u -- c-addr' u' true | false ) s" url" (key-line?) ;
: (origin-url) ( c-addr u -- c-addr' u' true | false ) \ the first url of [remote "origin"]
    (in-origin) off
    BEGIN dup WHILE (line) (trim) dup IF
        over c@ [char] [ = IF (origin-header?) (in-origin) !
        ELSE (in-origin) @ IF (url-line?) IF 2nip true EXIT THEN ELSE 2drop THEN THEN
    ELSE 2drop THEN REPEAT 2drop false ;

variable (in-ext)
: (reftable?) ( c-addr u -- f ) \ config text says [extensions] refStorage = reftable
    (in-ext) off
    BEGIN dup WHILE (line) (trim) dup IF
        over c@ [char] [ = IF s" [extensions]" (ci=) (in-ext) !
        ELSE (in-ext) @ IF s" refstorage" (key-line?) IF
            s" reftable" (ci=) IF 2drop true EXIT THEN THEN ELSE 2drop THEN THEN
    ELSE 2drop THEN REPEAT 2drop false ;

: (url-path) ( c-addr u -- c-addr' u' ) \ after scheme://host/, or host: ; else all of it
    2dup s" ://" search IF 3 /string [char] / scan dup IF 1 /string THEN 2nip EXIT THEN
    2drop 2dup [char] : (index-of) >r 2dup [char] / (index-of)
    r@ 0< IF rdrop drop EXIT THEN
    dup 0< swap r@ > or IF r> 1+ /string ELSE rdrop THEN ;
: (last-segment) ( c-addr u -- c-addr u' seg-a seg-u ) \ u' = what is before it
    (-slashes) 2dup (basename) 2>r 2r@ nip - 2r> ;
: (-.git) ( c-addr u -- c-addr u' )
    dup 4 < IF EXIT THEN 2dup + 4 - 4 s" .git" compare 0= IF 4 - THEN ;
create (owner) (room) allot  variable (owner#)
: (owner-segment+) ( c-addr u -- ) \ a non-empty segment onto (owner), /-separated
    dup 0= IF 2drop EXIT THEN
    (owner#) @ IF [char] / (owner) (owner#) (buf-char+) THEN  (owner) (owner#) buf+ ;
: (owner!) ( c-addr u -- ) \ (owner) := the path's segments, empty ones dropped, joined by /
    0 (owner#) !
    BEGIN dup WHILE 2dup [char] / (index-of) dup 0< IF drop (owner-segment+) 0 0 ELSE
        >r over r@ (owner-segment+) r> 1+ /string THEN REPEAT 2drop ;
: (origin+) ( c-addr u -- f ) \ <owner>/<repo> from a remote url; false if it names no repo
    \ <repo> is the last segment, <owner> every segment before it, one component
    (url-path) (last-segment) dup 0= IF 2drop 2drop false EXIT THEN
    2>r (owner!) (owner#) @ IF (owner) (owner#) @ (enc+) ELSE [char] _ (dir-char+) THEN
    (dir/) 2r> (-.git) (enc+) true ;
variable (reftable)
: (owner-repo+) ( -- ) \ <owner>/<repo> of origin, else _local/<the main worktree's name>
    (common) (common#) @ s" config" (path/) (file!)  (file@) (reftable?) (reftable) !
    (file@) (origin-url) IF (origin+) ELSE false THEN
    0= IF s" _local/" (dir+) (main-name) (norm) (norm#) @ 48 (slug-hash+) THEN  (file-free) ;

: (head-branch) ( c-addr u -- c-addr' u' true | false ) \ of "ref: refs/heads/<branch>"
    (trim) 2dup s" ref: refs/heads/" string-prefix? IF 16 /string dup IF true EXIT THEN THEN
    2drop false ;
: (path-key+) ( root-a root-u prefix-a prefix-u -- ) \ prefix, root's name~hash of root
    (dir+) 2dup (basename) 2swap 36 (slug-hash+) ;
: (worktree+) ( root-a root-u -- ) \ the branch of HEAD; per root when detached or reftable
    (reftable) @ IF s" _wt-" (path-key+) EXIT THEN
    (git-dir) (git-dir#) @ s" HEAD" (path/) (file!)  (file@) (head-branch) IF
        2dup s" .invalid" compare 0= IF 2drop s" _wt-" (path-key+) ELSE (enc+) 2drop THEN
    ELSE s" _detached-" (path-key+) THEN  (file-free) ;

: (base+) ( -- ) \ ${XDG_STATE_HOME:-$HOME/.local/state}/gforth-inspect
    s" XDG_STATE_HOME" getenv dup IF (dir+) ELSE
        2drop s" HOME" getenv (dir+)  s" /.local/state" (dir+) THEN
    s" /gforth-inspect" (dir+) ;
: (project+) ( root-a root-u git? -- ) \ <base>/<owner>/<repo>/<worktree> of root
    (base+) (dir/) IF 2dup (git-dir!) (common!) (owner-repo+) (dir/) (worktree+)
    ELSE s" _nogit/" (dir+) 2dup (basename) 2swap 48 (slug-hash+) s" /_" (dir+) THEN ;
: (derive+) ( dir-a dir-u -- )
    (git-root) >r 2dup (dotenv+) IF 2drop rdrop EXIT THEN r> (project+) ;
: (log-dir-for) ( dir-a dir-u -- ) \ append the default log dir for this current directory
    \ <base> when there is none, it is longer than (room) - 64, or the
    \ derived dir leaves no room for /stacks.jsonl
    dup 0= over 64 + (room) > or IF 2drop (base+) EXIT THEN
    log-dir# @ >r  ['] (derive+) catch IF 2drop (file-free) r@ log-dir# ! (base+) THEN
    (fits?) 0= IF r@ log-dir# ! (base+) THEN  rdrop ;

create (cwd-buf) (room) allot
: (cwd) ( -- c-addr u ) (cwd-buf) log-max get-dir ;  \ 0 0 if it cannot be read

: log-paths ( -- )
    0 log-dir# !  0 log-path# !
    s" GFORTH_INSPECT_LOG_DIR" getenv dup IF (dir+) ELSE
        2drop (cwd) (log-dir-for) THEN
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

: contract-version ( -- c-addr u ) s" 1.1" ;  \ MAJOR.MINOR of the log contract

create snap-id 64 allot  0 snap-id c!
: log-id ( c-addr u -- )
    \ every following snapshot carries "id":"<tag>" (at most 63 chars,
    \ escaped like any JSON string); s" " log-id clears it and the key is
    \ left out.  Contract 1.1, issue #3.
    63 min snap-id place ;

: (snapshot) ( -- )
    s" snapshot" json-head
    snap-id c@ IF jc s" id" jkey snap-id count json-str THEN
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
    jc s" inspect" jkey inspect-version json-str
    jc s" contract" jkey contract-version json-str  [char] } emit cr ;

\ A record is built in memory, then handed to the log with one write-file
\ (#17).  0.7.3 has no append fam, so the seek to the end and the write are
\ separate calls, and write-file is a buffered fwrite: a record longer
\ than the stdio buffer can reach the file in more than one write.
\ Producers that take turns are safe; producers writing at the same
\ instant rarely, but possibly, interleave.
variable log-buf  0 log-buf !  variable log-buf#  0 log-buf# !
variable log-buf-max  0 log-buf-max !  create log-char 1 allot

: (log-room) ( u -- )
    \ grow log-buf to hold u more bytes; the new size is stored only
    \ once the block exists, so a failed resize leaves both unchanged
    log-buf# @ + dup log-buf-max @ <= IF drop EXIT THEN
    2* 256 max >r
    log-buf @ ?dup IF r@ resize ELSE r@ allocate THEN throw
    log-buf !  r> log-buf-max ! ;
: (log-free) ( -- )
    log-buf @ ?dup IF free throw THEN  0 log-buf !  0 log-buf-max ! ;
: (log-type) ( c-addr u -- )
    dup (log-room)  tuck log-buf @ log-buf# @ + swap move  log-buf# +! ;
: (log-emit) ( c -- ) log-char c!  log-char 1 (log-type) ;

: (log-capture) ( xt -- )
    \ run xt with type and emit appending to log-buf; both are restored
    action-of type >r  action-of emit >r
    ['] (log-type) is type  ['] (log-emit) is emit
    catch  r> is emit  r> is type  throw ;
: (log-append) ( -- )
    \ log-buf as one write at the current end: another producer may
    \ have appended since the last record
    log-fid @ file-size throw log-fid @ reposition-file throw
    log-buf @ log-buf# @ log-fid @ write-file throw
    log-fid @ flush-file throw ;

: log-write ( xt -- )
    \ build xt's record in memory, in decimal (BASE is restored after),
    \ then append it to the log
    0 log-buf# !  base @ >r decimal
    ['] (log-capture) catch
    r> base !  throw  (log-append) ;
: log-snapshot ( -- ) logging @ IF ['] (snapshot) log-write THEN ;

create (opened) (room) allot  variable (opened#)  0 (opened#) !
: log-on ( -- )
    logging @ IF EXIT THEN
    log-paths  log-path (opened) log-path# @ move  log-path# @ (opened#) !
    log-dir log-dir# @ $1ff mkdir-parents drop
    log-path log-path# @ r/w open-file IF
        drop log-path log-path# @ r/w create-file throw THEN
    >r r@ file-size throw r@ reposition-file throw r> log-fid !
    logging on  ['] (hello) log-write ;
: log-off ( -- )
    logging @ 0= IF EXIT THEN  logging off  log-fid @ close-file throw
    0 log-fid !  (log-free) ;
: log-where ( -- ) \ the open log while logging (fixed at log-on), else where log-on would open
    logging @ IF cr (opened) (opened#) @ type cr EXIT THEN
    log-paths cr log-path log-path# @ type cr ;

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

: ~~-where ( rp -- rp' xt|0 )
    \ the word containing the ~~ whose printer frames end at rp: the one
    \ the next return address points into, none at the interpreter.  ~~
    \ typed at the prompt runs a headerless word compiled right after
    \ .debugline-stderr, which the backwards scan would name: that frame
    \ is skipped and there is no word
    dup rp0 @ u< 0= IF 0 EXIT THEN
    dup @ dup interp-frame? IF drop 0 EXIT THEN
    enclosing dup ['] .debugline-stderr = IF drop cell+ 0 THEN ;

: ~~-line ( nfile nline -- )
    \ .debugline for all-~~: ~~'s own file:line and word, all stacks, and a
    \ snapshot with where/src filled (issue #2; null for ~~ at the prompt)
    snap-line !  snap-file !
    rp@ cell+ past-debugline ~~-where snap-xt !  snap-rp !
    cr snap-file @ snap-line @ .sourcepos ." :"
    snap-xt @ ?dup IF ."  in " >head-noprim .name THEN cr
    snap-rp @ .stacks-from  log-snapshot ;

: all-~~ ( -- )
    \ plain ~~ now prints all stacks; the return stack starts at the word
    \ that contains the ~~, not inside ~~'s printer
    ['] ~~-line IS .debugline ;

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

: special-xt? ( x -- f )
    \ x is the xt of a DEFER or DOES> word with a real header
    dup aligned over <> IF drop false EXIT THEN
    dup in-dictionary? 0= IF drop false EXIT THEN
    dup >head-noprim ['] ??? >head-noprim = IF drop false EXIT THEN
    dup >code-address dodefer: =  swap >does-code 0<>  or ;

: defer-target ( xt -- xt' true | false )
    \ follow a DEFER chain, at most 16 hops (a cycle would loop for ever);
    \ silent: the caller says "nesting defered..." once it can nest
    16 0 DO
        dup >code-address dodefer: <> IF true UNLOOP EXIT THEN
        >body @
    LOOP
    dup >code-address dodefer: <> IF true EXIT THEN
    drop false ;

: special-target ( xt -- xt | body xt | 0 )
    \ what to nest into for a DEFER or DOES> word: a colon word (headerless
    \ too), or a does> word with its body below; 0 when there is none
    dup >code-address dodefer: = IF
        defer-target 0= IF cr ." (defer chain too long: stepped over)" 0 EXIT THEN
        dup >code-address docol: = over >does-code or IF cr ." nesting defered..." THEN
    THEN
    dup >code-address docol: = IF EXIT THEN
    dup >does-code IF dup >body swap EXIT THEN
    drop cr ." (defer target cannot be debugged: stepped over)" 0 ;

: nestXT+ ( x -- true | body false )
    \ the n (nest) key.  Stock nestXT treats the threaded cell as an xt and
    \ runs xt-see on it; in direct-threaded engines that cell is engine code,
    \ so xt-see shells out to gdb and dies (even nesting a colon word).
    \ Here a colon call is the cell `call`'s code address followed by the
    \ target body; anything else (primitive, literal) steps instead.
    \ A DEFER or DOES> word with a real header (#39) nests into its target:
    \ the end of the defer chain, or a does> word with its body below.
    dup ['] call @ = IF drop ['] call THEN
    dup ['] call = over colon-xt? or IF
        nestXT-checkSpecial
    ELSE dup special-xt? IF
        special-target ?dup 0= IF true EXIT THEN
    ELSE
        drop cr ." (not a colon definition: stepped over)" true EXIT
    THEN THEN
    DebugMode c-pass ! C-Output off  xt-see  C-Output on
    c-pass @ DebugMode = dup IF cr ." Cannot debug!!" THEN ;

: runnable? ( xt -- f ) \ false for a defer chain longer than 16 hops
    dup >code-address dodefer: = IF defer-target dup IF nip THEN ELSE drop true THEN ;

: dbg2 ( "name" -- ) \ stock dbg, then clear any breakpoint left set
    \ a word it cannot debug is run, as its "stepped over" message says,
    \ unless it is a defer chain with no end (running it never returns)
    \ (the xt waits on the return stack: for a does> word NestXT leaves the
    \ body below the code to debug, as does> would)
    ' dup >r NestXT IF
        r> dup runnable? IF execute ELSE drop cr ." (not run)" THEN EXIT
    THEN r> drop (debug) restore-bp2 Leave-D ;

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

base !  \ the BASE the file was loaded in (saved at the top)
