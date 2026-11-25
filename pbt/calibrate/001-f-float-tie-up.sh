#!/bin/sh
# 001 calibration (f): json-f rounds a tie at the 17th digit up, not to even,
# so 1000000000000000.25 logs 1.0000000000000003E15 where %.16e (and macOS's
# fs.) give ...02E15.  Both parse back to the same double, so only the text
# check sees it.  Ties are rare in random floats, so only the fixed corpus,
# which holds this one, is selected: red there in every path and engine.
. "$(dirname "$0")/001-lib.inc"
calibrate_001 "001(f) float tie rounded up, not to even" \
    's/^    dup 0= IF drop (f-dig) 16 + c@ 1 and ELSE 0> THEN IF (f-up) THEN ;$/    dup 0= IF drop 1 ELSE 0> THEN IF (f-up) THEN ;/' \
    "p2_float_corpus" \
    "$(for path in dotstacks tilde3 tilde2all; do for engine in gforth gforth-fast gforth-itc; do printf 'test_p2_float_corpus[%s-%s] ' "$path" "$engine"; done; done)" \
    "P2 float corpus in [^:]*: digits: 0x430c6bf526340002 logged 1.0000000000000003E15 want 1.0000000000000002E15\$"
