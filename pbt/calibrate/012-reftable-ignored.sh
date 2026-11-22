#!/bin/sh
# 012 plant: reftable not recognised: the stub HEAD .invalid is taken as a branch
. "$(dirname "$0")/012.lib"
plant 's{^    \(reftable\) \@ IF s" _wt-" \(path-key\+\) EXIT THEN}{}; s{^        2dup s" \.invalid" compare 0= IF}{        false IF}'
expect_red P3
