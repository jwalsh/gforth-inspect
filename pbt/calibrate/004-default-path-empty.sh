#!/bin/sh
# 004 plant: move the default log dir, so the documented default path is empty.
# Planted on the inspect.fs under test (INSPECT_FS, else INSPECT_REF, else
# this checkout's), not on 004.lib's NEW_REF: since 0.3.0 the default is per project
# (contract/stacks-log.org, "Files") and c0cab02's shared default would be
# red without any plant.
. "$(dirname "$0")/004.lib"
under_test env/inspect.fs > "$tmp/orig.fs" || exit 2
under_test contract/stacks-log.schema.json > "$tmp/orig.json" || exit 2
cp "$tmp/orig.json" "$tmp/schema.json"
plant_fs 's|s" /gforth-inspect" (dir+)|s" /gforth-inspect-moved" (dir+)|'
expect_red 'breaking default-location: documented default state/gforth-inspect/[^ ]*stacks.jsonl is empty'
