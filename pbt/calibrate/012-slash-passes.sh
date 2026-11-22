#!/bin/sh
# 012 plant: '/' passes through a slug unchanged
. "$(dirname "$0")/012.lib"
plant 's{^: \(safe\?\) \( c -- f \) dup \(alnum\?\) }{: (safe?) ( c -- f ) dup (alnum?) over [char] / = or }'
expect_red P1
