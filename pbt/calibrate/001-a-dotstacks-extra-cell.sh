#!/bin/sh
# 001 calibration (a): .stacks leaves an extra cell on the data stack -> P1 red on .stacks only
. "$(dirname "$0")/001-lib.inc"
calibrate_001 "001(a) .stacks extra cell" \
    '/^: \.stacks ( -- )/,/;/ s/log-snapshot ;/log-snapshot 0 ;/' \
    "p1_noninterference" \
    "test_p1_noninterference[dotstacks-gforth] test_p1_noninterference[dotstacks-gforth-fast] test_p1_noninterference[dotstacks-gforth-itc]" \
    "P1 data stack changed by dotstacks"
