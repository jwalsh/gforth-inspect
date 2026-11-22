\ 04-floats: the float values JSON cannot carry, and the edges it can.
\ -0e is written -0.0; +inf, -inf and NaN are null; DBL_MAX, the smallest
\ normal and the smallest subnormal round-trip at 17 significant digits.
\ gforth's fs. pads a mantissa with a trailing space: legal JSON whitespace.
log-on
-0e 0e 1e 0e f/ -1e 0e f/ 0e 0e f/
1.7976931348623157e308 -1.7976931348623157e308
2.2250738585072014e-308 2.2250738585072009e-308 4.9406564584124654e-324
0.1e 1e 3e f/ .stacks
bye
