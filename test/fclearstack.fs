\ fclearstack.fs -- empties the float stack, data stack untouched
7 1e 2e 3e fclearstack
fdepth 0 s" fclearstack empties" assert=
7 s" data stack untouched" assert=
fclearstack fdepth 0 s" fclearstack on empty" assert=
