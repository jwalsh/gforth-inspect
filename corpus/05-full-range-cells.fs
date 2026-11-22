\ 05-full-range-cells: the 64-bit cell range, logged while BASE is hex.
\ "data" is always decimal and always signed; BASE is restored afterwards.
log-on
0 1 -1 -1 1 rshift -1 1 rshift invert 255 -256
hex .stacks decimal
bye
