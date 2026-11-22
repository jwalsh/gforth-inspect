\ worktrees.fs -- for test/log-dir-cwd-*.fs: one repository, acme/widget,
\ under $FX: main checkout m (branch main) and linked worktrees a/wt
\ (feature-a, absolute gitdir:) and b/wt (feature-b, relative gitdir:).
s" mkdir -p $FX/m/.git/worktrees/wt $FX/m/.git/worktrees/wt1 $FX/a/wt $FX/b/wt/src" fx-sh
s\" printf '[remote \"origin\"]\\n\\turl = git@host:acme/widget.git\\n' > $FX/m/.git/config" fx-sh
s" printf 'ref: refs/heads/main\n' > $FX/m/.git/HEAD" fx-sh
s" printf 'ref: refs/heads/feature-a\n' > $FX/m/.git/worktrees/wt/HEAD" fx-sh
s" printf 'ref: refs/heads/feature-b\n' > $FX/m/.git/worktrees/wt1/HEAD" fx-sh
s" printf '../..\n' > $FX/m/.git/worktrees/wt/commondir" fx-sh
s" printf '../..\n' > $FX/m/.git/worktrees/wt1/commondir" fx-sh
s" printf 'gitdir: %s/m/.git/worktrees/wt\n' $FX > $FX/a/wt/.git" fx-sh
s" printf 'gitdir: ../../m/.git/worktrees/wt1\n' > $FX/b/wt/.git" fx-sh
