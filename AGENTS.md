# Agents working in this repository

These rules are for coding agents (Claude Code and others) and for the
people directing them. They come in addition to
[CONTRIBUTING.org](CONTRIBUTING.org): Forth style, gforth 0.7.3 only, all
three engines, and no private data.

Agents working for a project that *consumes* the inspector read
[CONSUMER-AGENTS.md](CONSUMER-AGENTS.md) instead. How producer and
consumers change things together is in [COLLABORATION.org](COLLABORATION.org).

## Start every piece of work in the open

Several agents work on this repository at once. They see each other's
work through branches and draft pull requests, not through chat. So every
feature, issue or experiment gets these steps at the start, before the
first real edit, even when the work is speculative:

1. **Look at what is already in flight.**

   ```sh
   gh pr list --state open        # drafts included
   git worktree list
   ```

   If an open PR already touches the files you are about to change,
   coordinate with it or build on it. Do not start a parallel copy.

2. **Make a worktree and a branch, cut from `main`.** The worktree is a
   sibling of the main checkout:

   ```sh
   git fetch origin
   git worktree add ../gforth-inspect-<slug> -b <type>/<slug> origin/main
   cd ../gforth-inspect-<slug>
   ```

   Use `<type>` = `feat`, `fix`, `docs`, `test` or `exp`, the last for an
   experiment (`exp/NNN-slug`). Never work in the main checkout, and never
   cut from another unmerged branch.

3. **Push it and open a draft PR at once.** That is fine with only one
   commit, and fine if you may abandon it:

   ```sh
   git commit --allow-empty -m "<type>(<scope>): <intent>"
   git push -u origin <type>/<slug>
   gh pr create --draft --base main --title "<type>(<scope>): <intent>" \
     --body "Intent: ... Files expected to change: ... Status: speculative"
   ```

   The draft is the announcement. Its body names the files you expect to
   change, so another agent can see the overlap before it starts.

4. **Push as you go.** Results that exist only in a local worktree are lost
   when the session ends, and nobody else can see them.

5. **Close what you abandon.** If the idea doesn't work out, close the
   draft with a sentence on what was learned. Keep the branch: a negative
   result is a result.

## Leaving draft

A PR comes out of draft only through [REVIEW.md](REVIEW.md): `gmake verify`
green, a `/code-review` of your own branch, every finding answered, and the
review recorded in the PR body. Coordinators merge. Agents never merge
their own PRs.

## What an agent owns

- Its own worktree and branch, and the files its draft PR names.
- For an experiment: its `experiments/NNN-slug/` log. Append to the log.
  Never edit the gate.

Unless the draft PR says so, an agent does not touch:

- `main` directly. Only coordinators commit there, and only coordination
  documents.
- `env/` or `contract/`, unless the PR is a producer or contract change
  that follows RELEASING.org's checklist.
- `pbt/gforth_run.py`, `pbt/Makefile` and `pbt/conftest.py`, which are
  shared. Changes to them go in a PR of their own.
- Another agent's branch, worktree or experiment.

## Talking to other agents

- Through the PR, in its body and comments. Other agents read those.
- GitHub writes (issues, PRs, comments) only in this repository's own
  organisation. A bug in gforth itself, or in any other project, is drafted
  as text and handed to a human to file.
- Never type into another session's terminal or tmux pane. Read the logs
  it writes instead.
