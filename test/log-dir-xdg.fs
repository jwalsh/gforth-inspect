\ log-dir-xdg.fs -- XDG_STATE_HOME/gforth-inspect; an empty
\ GFORTH_INSPECT_LOG_DIR counts as unset
\ test: env GFORTH_INSPECT_LOG_DIR=
\ test: env XDG_STATE_HOME=$TMP/xdg
log-where
log-on log-off
