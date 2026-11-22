#!/bin/sh
# 011 plant: no ASCII lowercasing in the slug
. "$(dirname "$0")/011.lib"
plant 's{^: \(slug-byte\) \( c -- c\x27 \) \(lower\) }{: (slug-byte) ( c -- c\x27 ) }'
expect_red
