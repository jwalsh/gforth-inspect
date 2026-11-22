\ log-dir-env-dotenv.fs -- $GFORTH_INSPECT_LOG_DIR in the environment wins
\ over the project's .env.
\ test: load test/lib/log-dir.fs
\ test: env FX=$TMP/fx
\ test: env GFORTH_INSPECT_LOG_DIR=$TMP/from-env
\ test: env PWD=$TMP/fx/p
s" mkdir -p $FX/p/.git" fx-sh
s" printf 'GFORTH_INSPECT_LOG_DIR=~/from-dotenv\n' > $FX/p/.env" fx-sh
log-where
log-on log-off
