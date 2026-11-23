\ shim-1.0.fs -- DIAGNOSTIC ONLY, not a port and not a fix.
\ Loaded before inspect.fs by `probe.sh -p shim-1.0.fs` to get past the
\ load error and see which words then work at run time.  It makes no
\ word behave correctly: it only lets names resolve.
also see-voc           \ 1.0 keeps debug.fs internals (DebugLoop, NestXT, ...) here
: interpret1 ( -- ) ;  \ gone in 1.0: a fresh word, never on the return stack
: handler-intro, ( -- ) ;  \ gone in 1.0: likewise
: .debugline-stderr ( -- ) ;  \ gone in 1.0 (.debugline-directed): likewise
