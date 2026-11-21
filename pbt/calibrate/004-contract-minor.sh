#!/bin/sh
# 004 plant: hello announces contract 1.2; the checker (expects 1.1) must stop
. "$(dirname "$0")/004.lib"
plant_fs 's/: contract-version ( -- c-addr u ) s" 1.1"/: contract-version ( -- c-addr u ) s" 1.2"/'
expect_red 'contract 1\.2 from the producer, this consumer expects 1\.1 \(minor update\)'
