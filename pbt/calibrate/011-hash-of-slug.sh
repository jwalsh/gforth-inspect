#!/bin/sh
# 011 plant: the hash is taken over the slug, not the name
. "$(dirname "$0")/011.lib"
plant 's{^    >r 2dup \(fnv1a64\) -rot r> \(slug\+\)  }{    >r log-dir# \@ -rot r> (slug+)  log-dir over + log-dir# \@ rot - (fnv1a64)  }'
expect_red P3
