#!/bin/sh
# 004 plant: split each snapshot record across two lines (a newline after rs)
. "$(dirname "$0")/004.lib"
plant_fs 's/jc s" rs" jkey snap-rp @ json-rs/jc s" rs" jkey snap-rp @ json-rs cr/'
expect_red 'breaking consumer=(jq|checker|server) field=(parse|record-count) '
