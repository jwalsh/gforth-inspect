\ base-hex-load.fs -- inspect.fs loaded while BASE is hex reads its own
\ literals in decimal, restores hex afterwards, and still derives the
\ per-project log dir.
\ test: noinspect
\ test: env FX=$TMP/fx
hex  s" ../env/inspect.fs" included
base @ $10 = -1 s" BASE is hex again after the load" assert=
decimal  s" lib/log-dir.fs" included
s" mkdir -p $FX/hx/.git" fx-sh
s" printf 'ref: refs/heads/main\n' > $FX/hx/.git/HEAD" fx-sh
s\" printf '[remote \"origin\"]\\n\\turl = git@host:acme/hx.git\\n' > $FX/hx/.git/config" fx-sh
s" hx" fx set-dir throw  log-where
