\ canvas-files.fs -- P1, P3 and XBM output; width 10 is not a multiple of 8
\ (XBM pads each row to bytes); regression: written in hex when BASE was 16
\ test: load env/canvas.fs
10 3 canvas
0 0 9 2 line  0 2 plot  9 0 plot
hex
s" c.pbm" out-path save-pbm
s" c.ppm" out-path save-ppm
s" c.xbm" out-path save-xbm
base @ decimal 16 s" BASE kept" assert=
