#!/bin/sh
# 001 calibration (d): json-f writes null again for NaN and the infinities, as
# inspect < 0.4.0 did (#66) -> P2 float red on every path, in the property and
# in the fixed corpus.  null still validates, so only the classifier catches it.
. "$(dirname "$0")/001-lib.inc"
calibrate_001 "001(d) non-finite logged as null" \
    's/^        fdrop json-str EXIT THEN$/        2drop fdrop ." null" EXIT THEN/' \
    "p2_float" \
    "$(for test in p2_float p2_float_corpus; do for path in dotstacks tilde3 tilde2all; do for engine in gforth gforth-fast gforth-itc; do printf 'test_%s[%s-%s] ' "$test" "$path" "$engine"; done; done; done)" \
    "P2 float (non-finite mismatch|corpus in .*non-finite: )"
