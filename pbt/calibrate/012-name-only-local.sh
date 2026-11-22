#!/bin/sh
# 012 plant: _local and _nogit named by the directory's name only, no path hash
. "$(dirname "$0")/012.lib"
plant 's{\(main-name\) \(norm\) \(norm#\) \@ 48 \(slug-hash\+\)}{(main-name) (enc+)}; s{\(dir\+\) 2dup \(basename\) 2swap 48 \(slug-hash\+\) s" /_"}{(dir+) (basename) (enc+) s" /_"}'
expect_red P3
