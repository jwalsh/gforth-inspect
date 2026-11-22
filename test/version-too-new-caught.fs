\ version-too-new-caught.fs -- `include inspect.fs` on gforth 9.9.9 throws,
\ so a loader can catch it; the stacks are as before and no inspector
\ word exists.
\ test: noinspect
vocabulary fake-gforth  also fake-gforth definitions
: version-string ( -- c-addr u ) s" 9.9.9" ;
previous definitions
also fake-gforth
s" ../env/inspect.fs" ' included catch  previous
-1 s" include throws -1" assert=
2drop  depth 0 s" stack depth after the caught load" assert=
s" log-on" find-name 0= -1 s" no inspector word defined" assert=
