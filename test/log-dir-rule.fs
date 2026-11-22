\ log-dir-rule.fs -- the default log dir for many $PWDs, one process
\ ((log-dir-for) is what log-on uses for $PWD).  Fixture trees under
\ $FX; the hashes were checked against the Python reference in
\ contract/stacks-log.org.
\ test: load test/lib/log-dir.fs
\ test: env FX=$TMP/fx

\ a main checkout (.git a directory) with two linked worktrees, both named
\ wt, in different parents (.git files: one absolute gitdir, one relative)
s" mkdir -p $FX/m/.git/worktrees/wt $FX/m/.git/worktrees/wt1 $FX/p1/wt $FX/p2/wt" fx-sh
s\" printf '[remote \"origin\"]\\n\\turl = https://example.org/group/sub/acme/widget.git\\n' > $FX/m/.git/config" fx-sh
s" printf 'ref: refs/heads/main\n' > $FX/m/.git/HEAD" fx-sh
s" printf 'ref: refs/heads/feature/Parser\n' > $FX/m/.git/worktrees/wt/HEAD" fx-sh
s" printf 'ref: refs/heads/fix-1\n' > $FX/m/.git/worktrees/wt1/HEAD" fx-sh
s" printf '../..\n' > $FX/m/.git/worktrees/wt/commondir" fx-sh
s" printf '../..\n' > $FX/m/.git/worktrees/wt1/commondir" fx-sh
s" printf 'gitdir: %s/m/.git/worktrees/wt\n' $FX > $FX/p1/wt/.git" fx-sh
s" printf 'gitdir: ../../m/.git/worktrees/wt1\n' > $FX/p2/wt/.git" fx-sh
s" m" fx .log-dir-for
s" p1/wt" fx .log-dir-for
s" p2/wt" fx .log-dir-for

\ detached HEAD: _detached-<the worktree's name>, hashed
s" mkdir -p $FX/det/.git" fx-sh
s" printf '0123456789abcdef0123456789abcdef01234567\n' > $FX/det/.git/HEAD" fx-sh
s" det" fx .log-dir-for

\ no origin: _local/<the main worktree's name>, from a linked worktree too
s" mkdir -p $FX/Local.Repo/.git/worktrees/lw $FX/elsewhere/lw" fx-sh
s" printf '[core]\n\tbare = false\n' > $FX/Local.Repo/.git/config" fx-sh
s" printf 'ref: refs/heads/main\n' > $FX/Local.Repo/.git/HEAD" fx-sh
s" printf 'ref: refs/heads/topic\n' > $FX/Local.Repo/.git/worktrees/lw/HEAD" fx-sh
s" printf '../..\n' > $FX/Local.Repo/.git/worktrees/lw/commondir" fx-sh
s" printf 'gitdir: ../../Local.Repo/.git/worktrees/lw\n' > $FX/elsewhere/lw/.git" fx-sh
s" Local.Repo" fx .log-dir-for
s" elsewhere/lw" fx .log-dir-for

\ url forms: ssh:// with user and port, scp-like with one segment, an
\ upper-case owner, a quoted value and a [Remote "origin"] header
: url-fixture ( c-addr u -- ) \ $FX/u/.git with this config text, HEAD main
    s" mkdir -p $FX/u/.git && printf 'ref: refs/heads/main\n' > $FX/u/.git/HEAD" fx-sh
    s" printf '" pad place  pad +place  s" ' > $FX/u/.git/config" pad +place
    pad count fx-sh ;
s\" [remote \"origin\"]\\n\\turl = ssh://git@git.example.org:2222/team/tools.git\\n" url-fixture
s" u" fx .log-dir-for
s\" [remote \"origin\"]\\n\\turl = git@host:solo.git\\n" url-fixture
s" u" fx .log-dir-for
s\" [Remote \"origin\"]\\n\\tURL = \"https://example.org/Acme/Widget\"\\n" url-fixture
s" u" fx .log-dir-for
s\" [remote \"upstream\"]\\n\\turl = https://example.org/x/y\\n[remote \"origin\"]\\n\\turl = https://example.org/me/fork/\\n\\turl = https://example.org/no/second\\n" url-fixture
s" u" fx .log-dir-for

\ outside any repository: _nogit/<the directory's name>/_
s" mkdir -p $FX/plain/x" fx-sh
s" plain/x" fx .log-dir-for
s" /gforth-inspect-no-such-dir/My Proj" .log-dir-for
s" /gforth-inspect-no-such-dir/.hidden" .log-dir-for
\ an empty $PWD: the shared base
s" " .log-dir-for
depth 0 s" clean" assert=
