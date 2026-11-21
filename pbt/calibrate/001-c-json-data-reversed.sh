#!/bin/sh
# 001 calibration (c): json-data emits the data stack top first -> P2 data red on every path
. "$(dirname "$0")/001-lib.inc"
calibrate_001 "001(c) json-data reversed" \
    '/^: json-data /,/;/ s/n# @ 1- i - pick/i pick/' \
    "p2_data" \
    "$(for p in dotstacks tilde3 tilde2all; do for e in gforth gforth-fast gforth-itc; do printf 'test_p2_data[%s-%s] ' $p $e; done; done)" \
    "P2 data mismatch"
