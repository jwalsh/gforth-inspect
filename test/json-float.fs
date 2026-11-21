\ json-float.fs -- floats in the log round-trip: 17 significant digits,
\ -0 keeps its sign (fs. dropped it), NaN and infinities are null;
\ regression: with 1 set-precision fs. printed "3.E0", invalid JSON
log-on
0e 0e f/  1e 0e f/  -1e 0e f/  .stacks fclearstack
-0e 0e 0.1e 1e-300 1.7976931348623157e308 -2.5e 1e 3e f/ .stacks fclearstack
1 set-precision  3e 0.5e .stacks fclearstack
precision 1 s" precision restored" assert=  15 set-precision
log-off
