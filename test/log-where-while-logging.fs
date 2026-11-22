\ log-where-while-logging.fs -- while logging, log-where prints the file
\ log-on opened, fixed until log-off: a branch switch (HEAD rewritten) does
\ not move it.  After log-off it names the new branch's log.
\ test: load test/lib/log-dir.fs
\ test: env FX=$TMP/fx
s" mkdir -p $FX/sw/.git" fx-sh
s" printf 'ref: refs/heads/before\n' > $FX/sw/.git/HEAD" fx-sh
s\" printf '[remote \"origin\"]\\n\\turl = git@host:acme/sw.git\\n' > $FX/sw/.git/config" fx-sh
s" sw" fx set-dir throw
log-on
s" printf 'ref: refs/heads/after\n' > $FX/sw/.git/HEAD" fx-sh
log-where  1 .stacks drop
log-off
log-where
