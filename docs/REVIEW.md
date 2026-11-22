# Reviewing your own branch before it leaves draft

Every pull request here opens as a draft. The author runs the verify
baseline, then a code review of the author's own branch. Only after both
does it come out of draft. This holds for people and for agents. The
coordinators merge, and only pull requests that are out of draft.

This guide is for coding agents in particular (Claude Code and others).
[CONTRIBUTING.org](CONTRIBUTING.org) has the rules the review checks
against, and [RELEASING.org](RELEASING.org) has the contract that a
change must not break.

## The loop

1. **Open as a draft.**

   ```sh
   gh pr create --draft --base main --head <branch> --title "<type>(<scope>): ..."
   ```

   Cut the branch from `main`, never from another unmerged branch.

2. **Run the verify baseline.**

   ```sh
   gmake verify
   ```

   It runs the privacy scan (calibrated first), the golden tests in all
   three engines, the property tests and the planted-fault calibration, and
   checks that the guides are intact (`scripts/check-guides.sh`). It must
   be green.

   The root Makefile, `env/` and `contract/` arrive with the `harden` PR.
   Until it merges, run the parts that exist on `main` by hand:

   ```sh
   scripts/privacy-scan.sh --calibrate && scripts/privacy-scan.sh
   scripts/check-guides.sh --calibrate && scripts/check-guides.sh
   gmake -C pbt check && gmake -C pbt calibrate
   ``` Paste its summary line into the PR body: engines, golden
   count, Hypothesis examples, seed.

3. **Review your own branch.** In Claude Code:

   ```
   /code-review high <PR number or branch>
   ```

   Use `high` for code (`env/`, `pbt/`, `scripts/`, the Makefile) and
   `medium` for documentation-only changes. Do not use `max` or `ultra`
   unless the owner asks for one: they start many reviewers and cost the
   most. Other agents should run their own review tool at the same depth,
   against the same diff (`git fetch origin && git diff origin/main...HEAD`).

4. **Deal with every finding.** Fix it, or answer it in the PR body with a
   reason. A finding is not skipped silently, and a test is not weakened
   to make a finding go away. If the review finds a bug in `env/inspect.fs`
   and your branch is not the one fixing the inspector, file an issue with
   a one-line reproducer instead.

5. **Verify again** after the fixes. `gmake verify` is green on the head
   you are about to mark ready, not on an earlier commit.

6. **Record the review** in the PR body:

   ```markdown
   ## Review
   - `gmake verify`: green on <sha>: <summary line>
   - `/code-review high`: <n> findings
     - fixed: <finding> (<sha>)
     - not fixed: <finding>, because <reason>
   ```

7. **Mark it ready.**

   ```sh
   gh pr ready <number>
   ```

## What a review here checks for

The checklist lives in [AGENTS.md](../AGENTS.md), "What `/code-review` checks
here": `/code-review` counts only CLAUDE.md rules; `.claude/CLAUDE.md` imports
AGENTS.md, and this file is never read.

## Anti-goals

- The self-review does not replace the coordinators' review. It means
  they are not the first to find what a tool would have found.
- Do not mark a pull request ready with `gmake verify` red, even if the
  red is "someone else's". Say so in the PR and leave it as a draft.
- Do not merge your own pull request.
