\ log-dir-dotenv.fs -- a GFORTH_INSPECT_LOG_DIR= line in the project's .env
\ replaces the derived default; quotes are stripped and ~/ is $HOME/.
\ test: load test/lib/log-dir.fs
\ test: env FX=$TMP/fx
\ test: env PWD=$TMP/fx/shared-a/sub
s" mkdir -p $FX/shared-a/.git $FX/shared-a/sub" fx-sh
s" printf 'ref: refs/heads/main\n' > $FX/shared-a/.git/HEAD" fx-sh
s\" printf 'OTHER=1\\nGFORTH_INSPECT_LOG_DIR=\"~/.local/state/gforth-inspect/shared\"\\n' > $FX/shared-a/.env" fx-sh
log-where
log-on log-off
