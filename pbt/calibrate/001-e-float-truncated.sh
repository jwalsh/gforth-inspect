#!/bin/sh
# 001 calibration (e): json-f keeps its 17 digits but drops the rounding step,
# so the last digit is truncated, not rounded: a stand-in for #62, where
# x86_64 glibc's ecvt gave 17 digits that were not correctly rounded (22e as
# 2.2000000000000002E1).  The old fs. path itself is correct on macOS, so it
# cannot be the plant here.  -> P2 float red on every path, in the property
# and in the fixed corpus (0.1 logs 1.0000000000000000E-1).
. "$(dirname "$0")/001-lib.inc"
calibrate_001 "001(e) float digits truncated, not rounded" \
    's/^    dup 0= IF drop (f-dig) 16 + c@ 1 and ELSE 0> THEN IF (f-up) THEN ;$/    drop ;/' \
    "p2_float" \
    "$(for test in p2_float p2_float_corpus; do for path in dotstacks tilde3 tilde2all; do for engine in gforth gforth-fast gforth-itc; do printf 'test_%s[%s-%s] ' "$test" "$path" "$engine"; done; done; done)" \
    "P2 float ((digits|precision) mismatch|corpus in .*(digits|precision): )"
