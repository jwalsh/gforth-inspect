\ json-float.fs -- floats in the log round-trip: 17 significant digits,
\ -0 keeps its sign (fs. dropped it), NaN and the infinities are the
\ strings "NaN", "Infinity" and "-Infinity" (#66), a NaN of either sign is "NaN";
\ regression: with 1 set-precision fs. printed "3.E0", invalid JSON
create fbits 1 floats allot
: bits>f ( u -- F: r ) fbits ! fbits f@ ;  \ a NaN of a sign and payload no division picks
log-on
0e 0e f/ fabs  1e 0e f/  -1e 0e f/  .stacks fclearstack
$FFF8000000000000 bits>f  $7FF0000000000001 bits>f  1e 0e f/ fnegate  .stacks fclearstack
-0e 0e 0.1e 1e-300 1.7976931348623157e308 -2.5e 1e 3e f/ .stacks fclearstack
1 set-precision  3e 0.5e .stacks fclearstack
precision 1 s" precision restored" assert=  15 set-precision
log-off
