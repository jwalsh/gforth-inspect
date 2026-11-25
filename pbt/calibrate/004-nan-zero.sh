#!/bin/sh
# 004 plant: log NaN as 0 instead of null (infinities stay null).  Plants
# c0cab02, which wrote null for every non-finite value (inspect < 0.4.0, #66)
. "$(dirname "$0")/004.lib"
plant_fs 's/fdup fdup f- f0= 0= IF fdrop ." null" EXIT THEN/fdup fdup f= 0= IF fdrop ." 0" EXIT THEN  fdup fdup f- f0= 0= IF fdrop ." null" EXIT THEN/'
expect_red 'breaking consumer=(jq|checker|server) field=(f|float)\[[0-9]+\]'
