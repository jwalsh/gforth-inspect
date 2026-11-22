\ log-dir-dotenv-refused.fs -- a .env comes with the clone, so it may not
\ point the log just anywhere: an absolute value outside $HOME or a ".."
\ segment is refused (one line on stderr) and the derived default is used;
\ a value too long for the log path likewise.  The environment variable
\ itself is not restricted.
\ test: load test/lib/log-dir.fs
\ test: env FX=$TMP/fx
s" mkdir -p $FX/tr/.git" fx-sh
s" printf 'ref: refs/heads/main\n' > $FX/tr/.git/HEAD" fx-sh
s\" printf '[remote \"origin\"]\\n\\turl = git@host:acme/tr.git\\n' > $FX/tr/.git/config" fx-sh
s" tr" fx set-dir throw
s" printf 'GFORTH_INSPECT_LOG_DIR=/tmp/collect\n' > $FX/tr/.env" fx-sh  log-where
s" printf 'GFORTH_INSPECT_LOG_DIR=../../up\n' > $FX/tr/.env" fx-sh  log-where
s" printf 'GFORTH_INSPECT_LOG_DIR=%04400d\n' 0 > $FX/tr/.env" fx-sh  log-where
s" printf 'GFORTH_INSPECT_LOG_DIR=%s/_inside\n' $HOME > $FX/tr/.env" fx-sh  log-where
s" printf 'GFORTH_INSPECT_LOG_DIR=~/_tilde\n' > $FX/tr/.env" fx-sh  log-where
