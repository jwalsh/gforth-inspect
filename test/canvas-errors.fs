\ canvas-errors.fs -- bad sizes abort; .canvas/save-* without a canvas
\ abort (it looped "forever" over 2^64 rows); regression: a failed
\ allocate left the freed pointer in place and the next canvas freed it
\ again, which macOS answers with abort() of the whole process
\ test: load env/canvas.fs
: must-fail ( xt -- ) catch 0<> s" expected an error" assert ;
' .canvas catch 0<> s" .canvas without canvas" assert
s" x.pbm" out-path ' save-pbm catch 0<> s" save without canvas" assert 2drop
: c00 ( -- ) 0 0 canvas ;  ' c00 must-fail
: cneg ( -- ) -3 4 canvas ; ' cneg must-fail
4 2 canvas  1 1 plot
: chuge ( -- ) -1 1 rshift 1 canvas ; ' chuge must-fail
' .canvas catch 0<> s" .canvas after failed canvas" assert
3 2 canvas  2 1 plot .canvas
depth 0 s" clean" assert=
