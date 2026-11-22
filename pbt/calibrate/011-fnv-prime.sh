#!/bin/sh
# 011 plant: a wrong FNV prime
. "$(dirname "$0")/011.lib"
plant 's{^\$100000001b3 constant}{\$100000001b5 constant}'
expect_red
