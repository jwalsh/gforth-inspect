\ gforth-inspect v0.1.0
\
\ canvas.fs -- a 1-bit image in memory, for the picture language (SICP 2.2.4)
\
\   canvas      ( w h -- )          allocate a w x h canvas, all clear
\   clear       ( -- )              erase it
\   plot        ( x y -- )          set one pixel; off-canvas points are ignored
\   line        ( x0 y0 x1 y1 -- )  Bresenham line, integer pixel coordinates
\   .canvas     ( -- )              print it: # set, . clear
\   save-pbm    ( c-addr u -- )     write a plain PBM (P1); sips/magick -> PNG
\   save-xbm    ( c-addr u -- )     write an XBM (C source bitmap)
\   save-ppm    ( c-addr u -- )     write a plain PPM (P3): set = black, clear = white
\
\ Coordinates follow SICP frames: (0,0) is bottom-left, y grows upward.
\ One byte per pixel: simple to read, cheap at 16x16 or 256x256.
\ w and h must be positive; .canvas and save-* abort without a canvas.
\ Files are written in decimal whatever BASE is.

variable cw  variable ch  variable pixels  0 pixels !  0 cw !  0 ch !

: ?canvas ( -- ) pixels @ 0= abort" canvas: none yet (w h canvas)" ;
: clear ( -- ) pixels @ IF pixels @ cw @ ch @ * erase THEN ;
: canvas ( w h -- )
    2dup min 1 < abort" canvas: w and h must be positive"
    \ forget the old one first: a failed allocate must not leave a freed
    \ pointer behind, or the next canvas frees it again (macOS aborts)
    pixels @ ?dup IF 0 pixels !  0 cw !  0 ch !  free throw THEN
    2dup * allocate throw pixels !  ch ! cw !  clear ;

: on-canvas? ( x y -- f ) 0 ch @ within  swap 0 cw @ within  and ;
: pixel ( x y -- addr ) cw @ * + pixels @ + ;
: pixel@ ( x y -- 0|1 ) pixel c@ ;
: plot ( x y -- ) 2dup on-canvas? IF pixel 1 swap c! ELSE 2drop THEN ;

: line { x0 y0 x1 y1 -- }
    x1 x0 - abs { dx }  y1 y0 - abs negate { dy }
    x0 x1 < IF 1 ELSE -1 THEN { sx }  y0 y1 < IF 1 ELSE -1 THEN { sy }
    dx dy + { err }
    BEGIN
        x0 y0 plot
        x0 x1 = y0 y1 = and 0=
    WHILE
        err 2*
        dup dy >= IF dy err + to err  x0 sx + to x0 THEN
        dx <= IF dx err + to err  y0 sy + to y0 THEN
    REPEAT ;

: row>y ( row -- y ) ch @ 1- swap - ;  \ rows are printed top first

: .canvas ( -- )
    ?canvas
    ch @ 0 ?DO
        cw @ 0 ?DO i j row>y pixel@ IF [char] # ELSE [char] . THEN emit LOOP cr
    LOOP ;

\ --- files -------------------------------------------------------------

variable fid
: n>s ( n -- c-addr u ) base @ >r decimal  s>d <# #s #>  r> base ! ;
: out-type ( c-addr u -- ) fid @ write-file throw ;
: out-line ( c-addr u -- ) fid @ write-line throw ;
: open-out ( c-addr u -- ) ?canvas w/o create-file throw fid ! ;
: close-out ( -- ) fid @ close-file throw ;

: save-pbm ( c-addr u -- )
    open-out  s" P1" out-line
    cw @ n>s out-type  s"  " out-type  ch @ n>s out-line
    ch @ 0 ?DO
        cw @ 0 ?DO i j row>y pixel@ IF s" 1 " ELSE s" 0 " THEN out-type LOOP  s" " out-line
    LOOP  close-out ;

: save-ppm ( c-addr u -- )
    open-out  s" P3" out-line
    cw @ n>s out-type  s"  " out-type  ch @ n>s out-line  s" 255" out-line
    ch @ 0 ?DO
        cw @ 0 ?DO i j row>y pixel@ IF s" 0 0 0 " ELSE s" 255 255 255 " THEN out-type LOOP  s" " out-line
    LOOP  close-out ;

: hex2 ( u -- c-addr u ) base @ >r hex  s>d <# # # #> r> base ! ;
: row-byte ( y x0 -- u )   \ 8 pixels from x0, least significant bit first
    0 8 0 DO
        over i + cw @ < IF  over i + 3 pick pixel@ i lshift or  THEN
    LOOP nip nip ;

: save-xbm ( c-addr u -- )
    open-out
    s" #define img_width " out-type  cw @ n>s out-line
    s" #define img_height " out-type  ch @ n>s out-line
    s" static unsigned char img_bits[] = {" out-line
    ch @ 0 ?DO
        cw @ 7 + 8 / 0 ?DO  s"  0x" out-type  j row>y i 8 * row-byte hex2 out-type  s" ," out-type  LOOP  s" " out-line
    LOOP
    s" };" out-line  close-out ;
