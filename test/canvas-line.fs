\ canvas-line.fs -- Bresenham in all eight octants and degenerate lines
\ test: load env/canvas.fs
9 9 canvas
4 4 8 6 line  4 4 6 8 line  4 4 2 8 line  4 4 0 6 line
4 4 0 2 line  4 4 2 0 line  4 4 6 0 line  4 4 8 2 line
.canvas cr
clear 0 0 8 0 line  0 8 0 0 line  3 3 3 3 line  .canvas cr
clear 0 0 8 8 line  0 8 8 0 line .canvas
