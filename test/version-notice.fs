\ version-notice.fs -- loaded by a gforth whose version-string is not 0.7.3,
\ inspect.fs prints one line on stderr and loads on.  The other version is
\ faked in its own wordlist, so nothing is redefined.
\ test: noinspect
vocabulary fake-gforth  also fake-gforth definitions
: version-string ( -- c-addr u ) s" 9.9.9" ;
previous definitions
also fake-gforth  s" ../env/inspect.fs" included  previous
s" .stacks" find-name 0<> -1 s" inspect.fs loaded on after the notice" assert=
