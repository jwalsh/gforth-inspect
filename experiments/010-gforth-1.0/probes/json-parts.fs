\ json-parts: the record writer's pieces that do not walk the return stack
\ (internal words json-data json-float json-input), one JSON object to
\ stdout; on 1.0 a snapshot is never logged, because json-rs crashes first
: parts ( -- )
    ." JSON {" s" data" jkey json-data jc s" float" jkey json-float
    jc s" input" jkey json-input ." }" cr ;
1 -2 3 1.5e -0.25e 1e300 -0e 0.1e parts
2drop drop fdrop fdrop fdrop fdrop fdrop
depth . fdepth . cr
