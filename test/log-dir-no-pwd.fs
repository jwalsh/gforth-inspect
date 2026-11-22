\ log-dir-no-pwd.fs -- without $PWD the log is the shared
\ ${XDG_STATE_HOME}/gforth-inspect/stacks.jsonl of 0.2.0 and before.
\ test: unset PWD
log-where
log-on log-off
