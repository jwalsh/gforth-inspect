#!/bin/sh
# 012 plant: the owner is the next-to-last url segment only (subgroups merge)
. "$(dirname "$0")/012.lib"
plant 's{^    2>r \(owner!\) \(owner#\) \@ IF \(owner\) \(owner#\) \@ \(enc\+\) ELSE }{    2>r (last-segment) 2swap 2drop dup IF (enc+) ELSE 2drop }'
expect_red P3
