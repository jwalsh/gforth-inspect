\ version-too-old.fs -- gforth below 0.7.3 (0.7.0 here) fails the
\ dependency check like 1.0 does: one line on stderr, the load throws.
\ test: noinspect
\ test: exit 1
vocabulary fake-gforth  also fake-gforth definitions
: version-string ( -- c-addr u ) s" 0.7.0" ;
previous definitions
also fake-gforth  s" ../env/inspect.fs" included  previous
s" ASSERT FAIL: inspect.fs loaded on gforth 0.7.0" type cr
