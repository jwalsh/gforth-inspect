\ json-float.fs -- floats in the log round-trip: 17 significant digits,
\ correctly rounded (ties to even) in exact arithmetic, so the record is
\ the same on every platform (#62: under x86_64 glibc, fs. logged 22e as
\ 2.2000000000000002E1 and DBL_MAX as a number that parses as inf);
\ -0 keeps its sign (fs. dropped it), NaN and the infinities are the
\ strings "NaN", "Infinity" and "-Infinity" (#66), a NaN of either sign is "NaN";
\ regression: with 1 set-precision fs. printed "3.E0", invalid JSON
create fbits 1 floats allot
: bits>f ( u -- F: r ) fbits ! fbits f@ ;  \ a NaN of a sign and payload no division picks
log-on
0e 0e f/ fabs  1e 0e f/  -1e 0e f/  .stacks fclearstack
$FFF8000000000000 bits>f  $7FF0000000000001 bits>f  1e 0e f/ fnegate  .stacks fclearstack
\ f.s prints -0 as the C library does (glibc keeps the sign, macOS drops
\ it), so the human line shows no floats here; the record's -0.0 is ours
maxdepth-.s @  0 maxdepth-.s !  -0e 0e .stacks fclearstack  maxdepth-.s !
0.1e 1e-300 1.7976931348623157e308 -2.5e 1e 3e f/ .stacks fclearstack
\ #62's neighbours on x86_64 Linux; a tie (ties to even: ...02, not ...03);
\ the least subnormal, the greatest subnormal, the least normal
22e 23e 27e 28e 1000000000000000.25e .stacks fclearstack
$1 bits>f $FFFFFFFFFFFFF bits>f $10000000000000 bits>f .stacks fclearstack
1 set-precision  3e 0.5e .stacks fclearstack
precision 1 s" precision restored" assert=  15 set-precision
log-off
