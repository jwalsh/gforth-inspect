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
   be green. Paste its summary line into the PR body: engines, golden
   count, Hypothesis examples, seed.

3. **Review your own branch.** In Claude Code:

   ```
   /code-review high <PR number or branch>
   ```

   Use `high` for code (`env/`, `pbt/`, `scripts/`, the Makefile) and
   `medium` for documentation-only changes. Do not use `max` or `ultra`
   unless the owner asks for one: they start many reviewers and cost the
   most. Other agents should run their own review tool at the same depth,
   against the same diff (`git diff main...HEAD`).

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

On top of correctness, these are the faults this repository has actually
had:

- **An inspector word that moves what it reports.** Any word that reads a
  stack must leave every stack bit-identical. `.stacks` once printed its
  own return-stack frame.
- **Words that are not in 0.7.3.** `{: :}`, `[: ;]` and `[{:` are gforth
  1.0. Check every new word with
  `gforth -e 's" WORD" find-name 0<> . bye'`.
- **One engine only.** A change to threaded-code handling (`dbg`, `see`,
  return addresses) has to be tested in `gforth`, `gforth-fast` and
  `gforth-itc`.
- **A change to the record format** without an issue, a schema change and
  a change-log row (RELEASING.org, "Changing the contract or the
  tooling"), or one that would break a reference consumer.
- **An uncalibrated gate.** A new check needs a planted fault that turns
  it red, and the red has to be for the right reason.
- **Private data.** Absolute paths, names, addresses, tokens, other
  people's code, or session transcripts, in files or in test output.
  `scripts/privacy-scan.sh` catches the common forms. The review catches
  the rest.
- **Developer notes in README.org.** The README is for end users only.

## Anti-goals

- The self-review does not replace the coordinators' review. It means
  they are not the first to find what a tool would have found.
- Do not mark a pull request ready with `gmake verify` red, even if the
  red is "someone else's". Say so in the PR and leave it as a draft.
- Do not merge your own pull request.
