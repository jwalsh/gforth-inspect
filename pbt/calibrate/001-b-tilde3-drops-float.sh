#!/bin/sh
# 001 calibration (b): ~~~ drops one float -> P1 red on ~~~ only
. "$(dirname "$0")/001-lib.inc"
calibrate_001 "001(b) ~~~ drops a float" \
    '/^: (~~~) /,/;/ s/log-snapshot ;/log-snapshot fdepth IF fdrop THEN ;/' \
    "p1_noninterference" \
    "test_p1_noninterference[tilde3-gforth] test_p1_noninterference[tilde3-gforth-fast] test_p1_noninterference[tilde3-gforth-itc]" \
    "P1 float stack changed by tilde3"
