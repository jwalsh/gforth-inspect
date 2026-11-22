#!/bin/sh
# 012 plant: the project is found from $PWD instead of the current directory
. "$(dirname "$0")/012.lib"
plant 's{^        2drop \(cwd\) \(log-dir-for\) THEN}{        2drop s" PWD" getenv (log-dir-for) THEN}'
NO_P4=1 expect_red P5
