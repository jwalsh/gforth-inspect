---
name: gforth-inspect
description: Use gforth-inspect to see a gforth 0.7.3 program's stacks and input, and to read the log it streams, instead of guessing from source or typing into someone's REPL. Use when debugging a Forth word, explaining what a definition leaves on the stack, checking a stack effect, watching a REPL session, or reading stacks.jsonl; and before upgrading a pinned gforth-inspect release.
---

# gforth-inspect

This skill ships with each gforth-inspect release, next to `inspect.fs`,
`stacks-log.schema.json`, `stacks-log.org`, `CONSUMERS.org`,
`CONSUMER-AGENTS.md` and `WORDS.org` (every word, its stack effect and what
it prints). To install it, copy it to
`.claude/skills/gforth-inspect/SKILL.md` in the consuming project.

## Look, don't guess

To find out what a word leaves on the stack, run it and look:

```sh
gforth inspect.fs your-file.fs -e '10 20 avg .stacks bye'
```

| want | use |
|---|---|
| every stack at a point | `.stacks` |
| the stacks inside a definition | put `~~~` in the definition |
| plain `~~` to show everything | `all-~~` once, then `~~` |
| who called whom | `.rs` (`rs-full on` includes interpreter frames) |
| the control-flow stack while compiling | `.cs`, inside the definition |
| step through a word | `dbg+ dbg word` (works in every engine) |

A declared stack effect is documentation, not evidence. Measure it with
`depth` and `fdepth` before and after.

## Read the log, never the user's terminal

`log-on` appends one JSON object per line to `stacks.jsonl` in
`$GFORTH_INSPECT_LOG_DIR`, else in a directory per project and worktree
under `${XDG_STATE_HOME:-~/.local/state}/gforth-inspect/`, one encoded path
component each for owner, repository and branch (`feat/x` becomes
`feat-x~<12 hex>`; the rule is `stacks-log.org`, "Files"). Don't build the
path by hand: `gforth inspect.fs -e 'log-where bye'`, run in the project,
prints it, and in a REPL that is logging `log-where` prints the open file. To
learn what a REPL holds, read that file. Requires a 64-bit gforth
`>= 0.7.3, < 1.0`: otherwise `inspect.fs` stops at load with a one-line
message.

- **Never type into a tmux pane or REPL that someone else is using.** It
  changes their state and can kill their gforth. (`send-keys` reads a
  trailing `;` as a separator and `-3` as a flag, and keys sent before the
  shell is ready make gforth exit.)
- Split the file on LF bytes only. A record can contain U+2028 and other
  Unicode line separators.
- Check the newest `hello` first. Its `contract` (`MAJOR.MINOR`) must be
  the one you were written for. If it differs, stop and say so. Don't
  guess.
- Non-finite floats are `null`. `-0.0` and 17-digit values are exact.
- Run one producer per log directory. Several gforths writing to one log is
  best-effort, and lines can be lost.

## Run it isolated

When you run gforth yourself, use a fresh temp dir as the working
directory, set `HOME` to it (gforth writes `.gforth-history` there), and
set `GFORTH_INSPECT_LOG_DIR` inside it. Then the log holds no real paths,
and the user's state is untouched.

## Upgrading

Follow `CONSUMER-AGENTS.md`, "A new version": verify `SHA256SUMS`, read the
change log in `stacks-log.org`, run each local deviation's reproducer, run
your own checks, then report.

## Anti-goals

- Don't patch `inspect.fs` without an issue upstream first (see
  CONSUMER-AGENTS.md, "Local changes").
- Don't use gforth 1.0 words (`{: :}`, `[: ;]`) in code that loads with it.
  Check any word with `gforth -e 's" WORD" find-name 0<> . bye'`.
- Don't treat `.s` or `f.s` output as data. They round and truncate. Use
  the log.
