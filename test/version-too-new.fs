\ version-too-new.fs -- loaded by gforth 1.0 or later, inspect.fs fails its
\ dependency check: one line on stderr, then the load throws (gforth
\ reports it and exits 1), before any word is defined.  The other version
\ is faked in its own wordlist, so nothing is redefined.
\ test: noinspect
\ test: exit 1
vocabulary fake-gforth  also fake-gforth definitions
: version-string ( -- c-addr u ) s" 1.0.1" ;
previous definitions
also fake-gforth  s" ../env/inspect.fs" included  previous
s" ASSERT FAIL: inspect.fs loaded on gforth 1.0.1" type cr
