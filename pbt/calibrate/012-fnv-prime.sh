#!/bin/sh
# 012 plant: a wrong FNV prime
. "$(dirname "$0")/012.lib"
plant 's{^\$100000001b3 constant}{\$100000001b5 constant}'
expect_red
