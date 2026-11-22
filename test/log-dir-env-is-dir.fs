\ log-dir-env-is-dir.fs -- a .env that is a directory is read as no .env,
\ and reading it leaks nothing: under a limit of 64 open files, the log
\ dir computed 300 times (log-on and log-where both do it), log-on log-off
\ 20 times, and a snapshot still lands.
\ test: ulimit-files 64
\ test: load test/lib/log-dir.fs
\ test: env FX=$TMP/fx
s" mkdir -p $FX/envdir/.git $FX/envdir/.env" fx-sh
s" printf 'ref: refs/heads/main\n' > $FX/envdir/.git/HEAD" fx-sh
s\" printf '[remote \"origin\"]\\n\\turl = git@host:acme/envdir.git\\n' > $FX/envdir/.git/config" fx-sh
s" envdir" fx set-dir throw
: rounds ( n -- ) 0 ?DO log-paths LOOP ;
300 rounds
: on-off ( n -- ) 0 ?DO log-on log-off LOOP ;
20 on-off
log-paths .log-dir
s" r1" log-id log-on 1 .stacks drop log-off
depth 0 s" clean" assert=
