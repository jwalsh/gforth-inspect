#!/bin/sh
# 004 plant: the schema states contract 1.2 but hello still announces 1.1.
# test_version_stop then expects today's checker (1.1) to stop with a minor
# update and it does not; the checker bumped to 1.2 stops instead (#66)
. "$(dirname "$0")/004.lib"
plant_schema 's/"x-contract": "1.1"/"x-contract": "1.2"/'
cp "$tmp/orig.fs" "$tmp/inspect.fs"
expect_red "want 'contract 1\.2 from the producer, this consumer expects 1\.1 \(minor update\)', got 'accepted'"
