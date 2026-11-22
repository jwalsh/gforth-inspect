\ log-dir-cwd-not-pwd.fs -- a gforth started in worktree b/wt with $PWD
\ inherited from worktree a/wt (subprocess cwd=..., an editor's job runner)
\ logs to b's own dir, feature-b, not a's: the project is the current
\ directory (get-dir), never $PWD.
\ test: load test/lib/log-dir.fs
\ test: env FX=$TMP/fx
\ test: env PWD=$TMP/fx/a/wt
\ test: load test/lib/worktrees.fs
s" b/wt/src" fx set-dir throw
log-where .log-dir
log-on 1 .stacks drop log-off
s" m" fx set-dir throw  log-paths .log-dir
depth 0 s" clean" assert=
