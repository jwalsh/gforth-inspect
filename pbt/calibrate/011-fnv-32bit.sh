#!/bin/sh
# 011 plant: FNV truncated to 32 bits
. "$(dirname "$0")/011.lib"
plant 's{i c\@ xor \(fnv-prime\) \* LOOP}{i c\@ xor (fnv-prime) * \$ffffffff and LOOP}'
expect_red
