# Review instructions

These apply to every review of a change to gforth-inspect.

## Flag, on top of correctness

| fault | rule |
|---|---|
| an inspector word moves what it reports | every stack is bit-identical after any word that reads one (`.stacks` once printed its own return-stack frame) |
| a word not in 0.7.3 | `{: :}`, `[: ;]`, `[{:` are gforth 1.0; check with `gforth -e 's" WORD" find-name 0<> . bye'` |
| one engine only | threaded-code changes (`dbg`, `see`, return addresses) are tested in `gforth`, `gforth-fast` and `gforth-itc` |
| a record-format change | needs an issue, a schema change and a change-log row (docs/RELEASING.org, "Changing the contract or the tooling"), and must not break a reference consumer |
| an uncalibrated gate | a new check has a planted fault that turns it red, for the right reason |
| private data | absolute paths, names, addresses, tokens, other people's code or session transcripts, in files or test output |
| developer notes in README.org | README is for end users only |
| a gate piped without `pipefail` | `gate \| tail` reports tail's exit status, not the gate's |

## Severity

- **Important:** a fault in the table, or a bug in `env/` or `contract/`.
- **Nit:** naming and wording. Nits go to issues and don't hold a PR in draft.

## Skip

Recorded output and generated files, unless the change is to how they are made:

- `test/expected/`
- `pbt/fixtures/`
- `demo/tour.cast`
- `demo/tour.gif`
- `dist/`
