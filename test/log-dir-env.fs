\ log-dir-env.fs -- $GFORTH_INSPECT_LOG_DIR wins over XDG_STATE_HOME;
\ the directory and its parents are created
\ test: env GFORTH_INSPECT_LOG_DIR=$TMP/custom/a/b
log-where
log-on 1 .stacks drop log-off
