#!/bin/sh
# 004 plant: hello announces contract 1.2 while c0cab02's schema states 1.1;
# test_version_stop wants the checker (expects 1.1) to accept, and it stops
. "$(dirname "$0")/004.lib"
plant_fs 's/: contract-version ( -- c-addr u ) s" 1.1"/: contract-version ( -- c-addr u ) s" 1.2"/'
expect_red 'contract 1\.2 from the producer, this consumer expects 1\.1 \(minor update\)'
