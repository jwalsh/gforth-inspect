\ log-dir-dotenv-relative.fs -- a relative value in the project's .env is
\ relative to the project root (the directory holding the .env), not to
\ where gforth was started: from root/src/deep the log is root/logs.  The
\ line may carry export, blanks around = and a comment.
\ test: load test/lib/log-dir.fs
\ test: env FX=$TMP/fx
s" mkdir -p $FX/rel/.git $FX/rel/src/deep" fx-sh
s" printf 'ref: refs/heads/main\n' > $FX/rel/.git/HEAD" fx-sh
s" printf '# shared log\nexport GFORTH_INSPECT_LOG_DIR = logs   # one per checkout\n' > $FX/rel/.env" fx-sh
s" rel/src/deep" fx set-dir throw
log-where
log-on log-off
s" rel" fx set-dir throw  log-where
