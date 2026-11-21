#!/bin/sh
# 004 plant: print one integer (the bottom data cell) in hex
. "$(dirname "$0")/004.lib"
plant_fs 's/n# @ 1- i - pick 0 \.r LOOP/n# @ 1- i - pick i 0= IF base @ >r hex 0 .r r> base ! ELSE 0 .r THEN LOOP/'
expect_red 'breaking consumer=(jq|checker|server) field=(d|data|parse|error) '
