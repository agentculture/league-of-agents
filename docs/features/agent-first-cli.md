# Agent-first CLI

The whole arena is driven by a thin, **agent-first** argparse CLI cited from
[teken](https://github.com/agentculture/teken)'s `python-cli` reference. "Agent-first"
is a concrete contract, not a slogan — it is what lets a model drive matches
reliably and what the `teken cli doctor . --strict` rubric gate enforces in CI.

## The contract

- **Dry-run by default.** Every write verb (`team register`, `match new/act/tick/
  rematch`, `harness run`, `play start`) previews by default and only commits with
  `--apply` — a stray call never silently mutates the game.
- **`--json` everywhere.** Every read verb takes `--json` and returns structured
  output, so a caller never has to scrape human text.
- **No third-party runtime dependencies.** `dependencies = []` — installing the
  arena never drags in a dependency tree.

## The error contract (a stable interface)

Failures are structured, never a leaked Python traceback:

- `league/cli/_errors.py` defines `CliError{code, message, remediation}` and the
  exit-code policy: **`0`** success, **`1`** user error, **`2`** environment
  error, **`3+`** reserved. Agents parse against this.
- `league/cli/__init__.py` routes even *argparse-level* failures (unknown verb,
  bad flag) through the same structured path — never argparse's default
  `prog: error:` / exit 2 — and wraps any stray exception into a `CliError` so no
  traceback ever escapes.

## Clean streams

`league/cli/_output.py` enforces the split: **results to stdout, diagnostics and
errors to stderr, never mixed.** Text-mode errors render as `error: …` followed
by `hint: …`; JSON mode routes structured payloads to the same streams. A caller
can pipe stdout as data and watch stderr for problems.

## Introspection built in

```bash
league whoami            # identity from culture.yaml
league learn             # a structured self-teaching prompt (add --json)
league explain <path>    # markdown docs for any noun/verb path, addressable
league overview          # descriptive snapshot of the agent
league doctor            # check the agent-identity invariants
league cli overview      # describe the CLI surface itself
```

`explain` is global and **addressable by path** (unlike terse, positional
`--help`), and every registered command path is required to resolve — a test
(`test_every_catalog_path_resolves`) fails CI if a verb ships without its
`explain` entry.

## How the arena grows: noun groups

New functionality is added as a **noun group**, registered exactly like the
existing verbs (`arena`, `team`, `match`, `standings`, `harness`, `play`) — a
`register(sub)` in `league/cli/_commands/<noun>.py`, an `explain` catalog entry,
and tests. The arena is built by adding noun groups, never by bolting features
onto the side; the recipe is in the repo's root `CLAUDE.md`.

## See also

- [Harness & drivers](harness-and-drivers.md) — the harness rides this exact
  public surface.
- [Identity & mesh](identity-and-mesh.md) — `whoami`/`doctor` and the invariants
  they check.
