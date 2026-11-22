\ log-dir-project.fs -- the default log follows the project: from a
\ subdirectory of a checkout whose .git is a directory, the log is
\ <base>/<owner>/<repo>/<branch>, owner and repo from origin's url.
\ test: load test/lib/log-dir.fs
\ test: env FX=$TMP/fx
\ test: env PWD=$TMP/fx/widget/src/deep
s" mkdir -p $FX/widget/.git $FX/widget/src/deep" fx-sh
s" printf 'ref: refs/heads/main\n' > $FX/widget/.git/HEAD" fx-sh
s\" printf '[core]\\n\\tbare = false\\n[remote \"origin\"]\\n\\turl = git@host:acme/widget.git\\n' > $FX/widget/.git/config" fx-sh
log-where
log-on 1 .stacks drop log-off
s" PWD" getenv .log-dir-for
depth 0 s" clean" assert=
