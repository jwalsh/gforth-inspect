#!/bin/sh
# 004 plant: json-f swaps "Infinity" and "-Infinity" (#66).  Unlike the other
# 004 plants this edits the inspect.fs and schema under test (under_test,
# ref-show.lib), not c0cab02, which still writes null.  The swapped strings
# validate, so only the comparison with the true value (fp@) catches it:
# breaking, not #66-nonfinite.
. "$(dirname "$0")/004.lib"
under_test env/inspect.fs > "$tmp/orig.fs" || exit 2
under_test contract/stacks-log.schema.json > "$tmp/orig.json" || exit 2
cp "$tmp/orig.json" "$tmp/schema.json"
plant_fs 's/fdup f0< IF s" -Infinity" ELSE fdup f0> IF s" Infinity" ELSE/fdup f0< IF s" Infinity" ELSE fdup f0> IF s" -Infinity" ELSE/'
expect_red 'breaking consumer=(jq|checker|server) field=(f|float)\[[0-9]+\] rec=[0-9]+ old=None new=.-?Infinity. true=-?inf'
