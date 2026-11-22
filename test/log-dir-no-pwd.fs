\ log-dir-no-pwd.fs -- an unset $PWD changes nothing: in worktree b/wt the
\ log is b's (feature-b); outside any repository it is _nogit/<dir>/_.
\ test: load test/lib/log-dir.fs
\ test: env FX=$TMP/fx
\ test: unset PWD
\ test: tmp-outside-git
\ test: load test/lib/worktrees.fs
s" b/wt" fx set-dir throw
log-where .log-dir
log-on log-off
s" mkdir -p $FX/plain/Not-A-Repo" fx-sh
s" plain/Not-A-Repo" fx set-dir throw  log-paths .log-dir-hashed
