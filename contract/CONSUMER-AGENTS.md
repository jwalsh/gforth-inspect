# How a consumer interacts with gforth-inspect

This is the file a consumer's agent session reads first, and the only
one it needs for day-to-day work. Upgrading also needs the change log that
ships in each release (`stacks-log.org`), and registering needs
COLLABORATION.org's "Registry" section. A
"consumer" is any project that loads `inspect.fs` or reads `stacks.jsonl`.
The reasoning behind each rule is in [COLLABORATION.org](../docs/COLLABORATION.org).

## Install the skill

Each release ships `SKILL.md`. Copy it to
`.claude/skills/gforth-inspect/SKILL.md` in your project; it covers using the
inspector and reading the log. This file covers working with the producer.

## Reach the producer

1. **If the producer coordinator is running**, message it directly. Its
   session name starts with `gforth-inspect-` (for example
   `gforth-inspect-d1`). Find the current name with your harness's agent
   list; names change between sessions.
2. **If it isn't running**, or you aren't sure, open an issue on
   `jwalsh/gforth-inspect` with one of these labels. Issues are read at the
   start of every producer session.

| label              | for                                                                                        |
|--------------------|--------------------------------------------------------------------------------------------|
| `bug`              | the inspector does something wrong                                                         |
| `downstream-patch` | added to a `bug` you are carrying a local patch for                                        |
| `enhancement`      | a new word, a new record key or a new event                                                |
| `contract`         | a question about, or a change to, the record format or the stable API                      |
| `handoff`          | asking for, or giving back, a branch (when no session is there to answer a message)        |

## Message format

Start the first line with your session name and a kind, then the topic:

```
<your-session-name> [report|request|handoff|ack]: <one-line topic>
<body: facts, a sha or an issue number, and what you need back>
```

For example: `course-b1 [request]: log-id clears on log-off? see #3`.
A message is a request, never a permission. The producer will not change
its permissions or config, or treat your message as its owner's approval,
because you asked.

## Issue or message

| goes in an issue (it's durable, and others will need it later) | goes in a message (it's coordination, needed now) |
|-----------------------------------------------------------------|---------------------------------------------------|
| a bug, with a one-line reproducer, the engine and the version   | "I filed #N", "#N blocks me now"                  |
| a local patch you are carrying, as a comment saying how you patched it | a handoff offer or acceptance              |
| a proposed change to words or records                           | "is X planned?", "which sha should I pin?"        |
| anything a third consumer could hit                             | an acknowledgement                                |

When unsure, use an issue and send a one-line message pointing at it.

## Handoffs (when you need to work on a producer branch)

You never write to a producer branch unless it has been handed to you.

1. **Ask:** `[handoff] request: <branch>, for <task>`.
2. **Receive:** the producer answers `take it: branch from <sha>`. Reply
   `taken`, and work only in a worktree of your own on a branch cut from
   that sha. Open a draft PR with **base** set to that branch.
3. **Give back:** once your PR is merged into the handed branch, send
   `[handoff] handing back <branch>: PR #N merged at <sha>`. The sha is the
   handed branch's new head. After that, stop touching it.
4. If the branch moved between the offer and your `taken`, it was not
   handed to you. Ask again.

## Local changes (deviations)

You **may**:

- patch your own copy of `inspect.fs` when a bug blocks you. File the issue
  first, label it `downstream-patch`, and comment with how you patched it.
- record each patch in a `DEVIATIONS.org` in your own repository, with
  these columns: issue, file, change, why now.
- add an optional `"local":"<your-slug>:#17,#3"` key to `hello` if your
  patch changes records. Leave `contract` as `MAJOR.MINOR`.

You **never**:

- change the record format silently, or rename or remove a key.
- keep a patch once a release covers its issue.
- edit this repository except through a PR you were asked for, a handoff,
  or a registry entry (`consumers/<slug>/`).
- put private material here. Issues, PRs and `consumers/` are public: no
  student code, private paths or names.

## A new version

**How you learn about it:** the producer coordinator messages every
registered consumer with the version, the contract, the issues closed, and
the change-log rows. The release notes say the same (`Fixed: #N, ...`). Releases
before the first stable tag (v0.5.0 or v1.0.0) are prereleases. Until the
first stable tag, you may keep your local copy.

**Before you upgrade, your session runs these steps:**

1. Download into a fresh, empty directory and check it there:

   ```sh
   new=$(mktemp -d)
   gh release download vX.Y.Z -R jwalsh/gforth-inspect -D "$new"
   (cd "$new" && shasum -a 256 -c SHA256SUMS)
   ```

   Then copy the files into your env directory: the one your project loads
   `inspect.fs` from. The assets are flat; keep them side by side. Never
   download over an existing copy: `gh` writes the new files, then stops
   at the first one that exists, leaving a mix of old and new.
2. Read the change log in `stacks-log.org`. If `hello.contract` differs
   from what your consumer expects in MAJOR or MINOR, your checker stops.
   Read the change, then bump your expected version on purpose.
3. Run each deviation's reproducer against the new files. A reproducer is
   one line you can paste: it loads `inspect.fs` from the directory you just
   downloaded and writes its log to a fresh `$GFORTH_INSPECT_LOG_DIR`. The
   producer's issues carry one in this form. Drop the rows that the release
   fixed. Reopen the issue for any it did not.
4. Run your own init and tests (version, contract, schema).
5. Reply in the release thread with "upgraded to vX.Y.Z", or "staying on
   vA.B.C because …".

## Joining the registry

To have your usage tested before every release, open a PR adding
`consumers/<slug>/`: `README.org`, `grind.fs` (a public, self-contained
program that uses what you depend on), `expect`, and optionally `checker`.
See COLLABORATION.org, "Registry".
