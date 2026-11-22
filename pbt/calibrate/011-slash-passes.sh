#!/bin/sh
# 011 plant: '/' passes through a slug unchanged
. "$(dirname "$0")/011.lib"
plant 's{^: \(safe\?\) \( c -- f \) dup \(alnum\?\) }{: (safe?) ( c -- f ) dup (alnum?) over [char] / = or }'
expect_red P1
