#!/bin/sh
# 012 plant: no ASCII lowercasing in the slug
. "$(dirname "$0")/012.lib"
plant 's{^: \(slug-byte\) \( c -- c\x27 \) \(lower\) }{: (slug-byte) ( c -- c\x27 ) }'
expect_red
