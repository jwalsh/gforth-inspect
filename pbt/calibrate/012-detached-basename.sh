#!/bin/sh
# 012 plant: a detached worktree hashed by its name only, not its path
. "$(dirname "$0")/012.lib"
plant 's{^    \(dir\+\) 2dup \(basename\) 2swap 36 \(slug-hash\+\) ;}{    (dir+) (basename) 2dup 36 (slug-hash+) ;}'
expect_red P3
