#!/bin/sh
# 004 plant: rename the snapshot key data to stack (producer and schema alike)
. "$(dirname "$0")/004.lib"
plant_fs 's/s" data" jkey/s" stack" jkey/'
plant_schema 's/"data"/"stack"/g'
expect_red 'breaking consumer=(jq|checker|server) field=(d|data) '
