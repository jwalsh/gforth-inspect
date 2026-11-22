#!/bin/sh
# 012 plant: the hash is left off: slug only
. "$(dirname "$0")/012.lib"
plant 's{^    >r \(fnv1a64\) -rot r> \(slug\+\)  \[char\] ~ \(dir-char\+\)  \(hex12\+\) ;}{    >r 2drop r> (slug+) ;}'
expect_red P3
