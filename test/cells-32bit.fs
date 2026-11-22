\ cells-32bit.fs -- a gforth with 4-byte cells fails the dependency check:
\ the log-dir hash (FNV-1a 64) needs 64-bit cells.  The cell size is faked
\ in its own wordlist (cells); the check throws before any definition.
\ test: noinspect
\ test: exit 1
vocabulary fake-gforth  also fake-gforth definitions
: cells ( n -- n' ) 4 * ;
previous definitions
also fake-gforth  s" ../env/inspect.fs" included  previous
s" ASSERT FAIL: inspect.fs loaded with 4-byte cells" type cr
