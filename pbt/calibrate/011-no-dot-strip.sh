#!/bin/sh
# 011 plant: leading dots are not stripped from a slug
. "$(dirname "$0")/011.lib"
plant 's{^: \(lead\?\) \( c -- f \) dup \[char\] \. = swap \[char\] - = or ;}{: (lead?) ( c -- f ) [char] - = ;}'
expect_red
