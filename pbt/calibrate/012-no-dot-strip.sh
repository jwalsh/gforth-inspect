#!/bin/sh
# 012 plant: leading dots are not stripped from a slug
. "$(dirname "$0")/012.lib"
plant 's{^: \(lead\?\) \( c -- f \) dup \[char\] \. = swap \[char\] - = or ;}{: (lead?) ( c -- f ) [char] - = ;}'
expect_red
