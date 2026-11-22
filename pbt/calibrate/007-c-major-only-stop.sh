#!/bin/sh
# 007 plant (c): the twin's version stop compares MAJOR only, ignoring MINOR
. "$(dirname "$0")/007.lib"
plant_sed 's/(= (vec (take 2 (py-split-dot announced))) \[expected-major expected-minor\])/(= (first (py-split-dot announced)) expected-major)/'
expect_red 'contract_minor or generated' '(version stop \[\]|disagree checker: hello contract-1\.2)[^:]*'
