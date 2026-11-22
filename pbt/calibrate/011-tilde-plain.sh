#!/bin/sh
# 011 plant: '~' allowed in a plain (pass-through) name
. "$(dirname "$0")/011.lib"
plant 's{^    bounds \?DO i c\@ \(safe\?\) 0= IF false UNLOOP EXIT THEN LOOP true ;}{    bounds ?DO i c\@ dup (safe?) swap [char] ~ = or 0= IF false UNLOOP EXIT THEN LOOP true ;}'
expect_red
