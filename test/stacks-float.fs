\ stacks-float.fs -- the float stack in .stacks, bottom first
1.5e -2.25e 1e10 .stacks
fdepth 3 s" .stacks keeps the float stack" assert=
fdrop fdrop 1.5e f= s" bottom float intact" assert
fdepth 0 s" clean" assert=
