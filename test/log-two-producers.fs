\ log-two-producers.fs -- issue #17: two producers on one stacks.jsonl.
\ Producer A logs A1, then a second gforth of the same engine (producer B,
\ test/lib/log-producer-b.fs) appends a hello and B1 while A's log is
\ still open, then A logs A2. Every record has to survive, each on its own
\ line: A2 must land after B1, not on top of B's hello. The runner
\ validates every line against the schema. Paced by SYSTEM, which waits
\ for B to exit, so the interleaving is the same on every run.
\ test: env XDG_STATE_HOME=$TMP/state
log-on s" A1" log-id 1 .stacks drop
s" $TEST_ENGINE env/inspect.fs test/lib/log-producer-b.fs -e bye >/dev/null 2>&1" system
$? 0 s" producer B exit status" assert=
s" A2" log-id 2 .stacks drop log-off
depth 0 s" clean" assert=
