#!/bin/sh
# 007 plant (b): the twin's validator loses its enum check
. "$(dirname "$0")/007.lib"
plant_sed '/(when (and (contains? schema "enum")/,/not one of/d'
expect_red generated 'disagree checker: mutation enum-[a-z-]*'
