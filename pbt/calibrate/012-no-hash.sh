#!/bin/sh
# 012 plant: the hash is left off: slug only
. "$(dirname "$0")/012.lib"
plant 's{^    >r 2dup \(fnv1a64\) -rot r> \(slug\+\)  \[char\] ~ \(dir-char\+\)  \(hex12\+\) ;}{    (slug+) ;}'
expect_red P3
