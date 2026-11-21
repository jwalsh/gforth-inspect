\ canvas-plot.fs -- corners, edges, and off-canvas points (ignored, no
\ memory written), lines that leave the canvas are clipped per pixel
\ test: load env/canvas.fs
5 3 canvas
0 0 plot  4 0 plot  0 2 plot  4 2 plot  .canvas cr
clear -1 0 plot  5 0 plot  0 3 plot  0 -1 plot  -100 -100 plot  100 1 plot
.canvas cr
clear -3 1 10 1 line  2 -5 2 10 line  .canvas
0 0 pixel@ 0 s" off-canvas plot wrote nothing" assert=
2 1 pixel@ 1 s" crossing set" assert=
