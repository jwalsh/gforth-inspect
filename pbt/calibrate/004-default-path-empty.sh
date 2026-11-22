#!/bin/sh
# 004 plant: move the default log dir, so the documented default path is empty
. "$(dirname "$0")/004.lib"
plant_fs 's|s" /gforth-inspect" log-dir|s" /gforth-inspect-moved" log-dir|'
expect_red 'breaking default-location: documented default state/gforth-inspect/stacks.jsonl is empty'
