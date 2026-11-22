#!/bin/sh
# 012 plant: the hash is taken over the slug, not the name
. "$(dirname "$0")/012.lib"
plant 's{^    >r \(fnv1a64\) -rot r> \(slug\+\)  \[char\] ~}{    >r 2drop r> log-dir# \@ >r (slug+)  log-dir r\@ + log-dir# \@ r> - (fnv1a64)  [char] ~}'
expect_red P3
