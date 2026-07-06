# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is (and is not, yet)

Two things are true at once — keep them separate:

- **What it is today:** an *agent-first CLI scaffold* for an AgentCulture mesh
  agent, cloned from the culture-agent-template. The runtime is a small,
  dependency-free Python package (`league/`) exposing introspection verbs
  (`whoami`, `learn`, `explain`, `overview`, `doctor`, `cli overview`) plus a
  mesh identity, a vendored skill kit, and a build/deploy baseline. **None of the
  arena/game domain is implemented.**
- **What it is meant to become:** *League of Agents* — a strategic team arena
  where AI agent teams complete missions, control objectives, manage resources,
  and out-coordinate opposing teams. The product requirements live in
  [issue #1](https://github.com/agentculture/league-of-agents/issues/1) and are
  summarized under [Project intent](#project-intent-issue-1) below.

So this is a **greenfield build on a working scaffold**. New domain work is added
as CLI noun groups following the pattern in
[Architecture](#architecture) — not by bolting a game engine onto the side.

## Project intent (issue #1)

Issue #1 is a *requirements* document — deliberately no engine design, map
format, protocol, agent API, or UI. It is the north star for what to build; do
not treat its absence of implementation detail as a gap to fill arbitrarily.

The arena must eventually support scenarios where:

- A team of agents shares a clear mission and **must coordinate** — individual
  intelligence alone is insufficient; team coherence changes the outcome.
- **Roles/specialization matter** (tools, memory, visibility, strategic
  function), and **communication quality, delegation, and timing** influence
  success.
- The environment forces **tradeoffs** between exploration, execution, defense,
  support, and objective control, with **decisions having visible consequences
  over multiple turns/phases**.
- The system **scores both mission outcome and cooperation quality**, and
  **logs/replays make it inspectable** — why a team succeeded or failed.
- Different teams, models, and role compositions can be **compared fairly**, and
  the game can evolve into **cooperative and competitive modes** without changing
  the core purpose.

The core question the arena answers: *Can this group of agents become a coherent,
strategic, cooperative team under constraint?* Favor designs that make
coordination legible and replayable over designs that maximize single-agent
scores.

## Commands

Python 3.12+, managed with **uv**. Runtime has **no third-party dependencies**
(`dependencies = []`); `teken` and the test/lint tools are dev-only.

```bash
uv sync                                    # install (incl. dev group)
uv run pytest -n auto                      # full suite (xdist parallel)
uv run pytest tests/test_cli.py::test_whoami_text   # a single test
uv run pytest -n auto --cov=league --cov-report=term # with coverage (gate: fail_under=60)
```

Lint (each is a separate CI gate — all must pass):

```bash
uv run black --check league tests          # line length 100
uv run isort --check-only league tests     # black profile
uv run flake8 league tests
uv run bandit -c pyproject.toml -r league
markdownlint-cli2 "**/*.md" "#node_modules" "#.local" "#.claude/skills" "#.teken"
uv run teken cli doctor . --strict         # the agent-first rubric gate (7 bundles)
```

Run the CLI. **`league-of-agents` is the project (what you install/publish);
`league` is the command it exposes.**

```bash
uv tool install league-of-agents           # installs the dist → provides the `league` command
uv run league whoami                        # or: python -m league whoami
uv run league learn --json
uv run league doctor                        # checks the agent-identity invariants
```

> The two names are intentionally distinct — `league-of-agents` is the
> **distribution name** (`[project.name]`, `uv tool install`, PyPI), while
> `league` is the **console command** (`[project.scripts]`). Argparse's
> `prog="league-of-agents"` is just the display name in `--help`/`explain`. So
> `uv run league-of-agents …` doesn't resolve — there's no script by that name,
> and that's by design, not a bug. (One stale spot: the README quickstart writes
> `uv run league-of-agents <verb>`, which should be `uv run league <verb>`.)

## Architecture

### CLI dispatch and the error contract

The whole CLI is a thin, agent-first argparse app. The pieces that matter across
files:

- **`league/cli/__init__.py`** — builds the parser and dispatches. Every
  subparser is a `_CliArgumentParser`, whose `.error()` is overridden to route
  *argparse-level* failures (unknown verb, bad flag) through the same structured
  error path as runtime failures — never argparse's default `prog: error:` /
  exit 2. Because parse errors fire *before* `args.json` exists, `main()`
  pre-scans raw argv for `--json` and stashes it in the class-level `_json_hint`.
  `_dispatch()` wraps any non-`CliError` exception into a `CliError` so **no
  Python traceback ever leaks**.
- **`league/cli/_errors.py`** — `CliError{code, message, remediation}` and the
  exit-code policy: `0` success, `1` user error, `2` environment error, `3+`
  reserved. This is a **stable contract** agents parse against.
- **`league/cli/_output.py`** — the stdout/stderr split: **results to stdout,
  diagnostics and errors to stderr, never mixed.** Text-mode errors render as
  `error: …` + `hint: …` (the `hint:` prefix is required by the rubric). JSON
  mode routes structured payloads to the same streams.

### Adding a noun group (this is how the arena gets built)

New functionality is a *noun group* registered the same way the existing verbs
are. Follow this pattern end to end:

1. Add `league/cli/_commands/<noun>.py` with a `register(sub)` that calls
   `sub.add_parser(...)` and `p.set_defaults(func=…)`. If the noun has
   action-verbs, it **must also expose `overview`** (the rubric's
   `overview_cli_noun_exists` check — see `cli.py` for the minimal shape).
2. Call your `register()` from `_build_parser()` in `league/cli/__init__.py`
   (there's a marked "Register your own noun groups here" spot).
3. Every handler takes `argparse.Namespace`, returns `int | None`, honors
   `--json`, and emits via `_output`. Raise `CliError` on failure — never print
   errors yourself.
4. Add an `explain` catalog entry for each new path in
   `league/explain/catalog.py` (`ENTRIES` is keyed by command-path tuples).
   `tests/test_cli.py::test_every_catalog_path_resolves` **enforces** that every
   registered path resolves, so a new verb without a catalog entry fails CI.
5. Add tests under `tests/` (see the existing smoke + introspection tests for
   the capsys/JSON-shape patterns).

Keep the runtime dependency-free where you can — pushing third-party deps into
`dependencies` changes the install story for every consumer.

### Identity and the `doctor` invariants

- **`whoami.py`** parses `culture.yaml` *without a YAML dependency* (hand-rolled
  line scan of the first agent block) and locates the file by walking up from
  `__file__` — so identity is always *this agent's own*, not whatever
  `culture.yaml` sits in the caller's CWD. A wheel install (no bundled
  `culture.yaml`) falls back to literal defaults.
- **`doctor.py`** mirrors the invariants `steward doctor` checks:
  *prompt-file-present*, *backend-consistency* (`_PROMPT_FILE` maps backend →
  prompt file), and *skills-present*. If you change the declared backend in
  `culture.yaml`, teach `doctor` the matching prompt file or
  `test_doctor_recognizes_declared_backend` fails.

## Mesh identity

`culture.yaml` declares this agent to the AgentCulture IRC mesh:

- `suffix: league-of-agents`, `backend: colleague`, `model:` a pinned Qwen.
- **Backend is `colleague`, not `claude`.** The resident mesh prompt file for a
  colleague backend is **`AGENTS.colleague.md`** (the daemon reads that, not this
  `CLAUDE.md`). This `CLAUDE.md` is for *Claude Code* operating the repo
  interactively. The backend→prompt-file mapping is load-bearing for
  `doctor`/`steward doctor` — keep `culture.yaml`, the prompt file on disk, and
  the mapping in sync.

## Skills (cite-don't-import)

`.claude/skills/` is vendored **cite-don't-import** — copies you own, not a
dependency. Provenance and the re-sync procedure live in
[`docs/skill-sources.md`](docs/skill-sources.md); consult it before touching a
vendored skill.

- Most skills come from **guildmaster** (the skills supplier); `think`,
  `spec-to-plan`, `assign-to-workforce` originate in **devague** (re-broadcast);
  `ask-colleague` is vendored **directly from colleague**; `remember`/`recall`
  from **eidetic-cli**. Two tracked local divergences exist (`agex`→`devex`
  rename; `outsource`→`ask-colleague`) — see the ledger.
- **Every vendored `SKILL.md` must carry `type: command`** in its frontmatter —
  the culture backend's `core.skill_loader` silently skips any that lacks it. Add
  it after re-vendoring even when upstream omits it.
- When re-syncing, re-apply only the *consumer-identifying* prose swaps
  (`guildmaster` → `league-of-agents`) — never where a skill cites its true
  upstream/origin — and never edit script bodies.

Skills to reach for reflexively:

- **`ask-colleague`** — hand a scoped task to a *different* model for a diverse
  second opinion. `review` (a committed diff) and `explore` (an unfamiliar area)
  are read-only and always safe to run before presenting work; `write --apply` /
  `write --pr` mutate and need the user's go-ahead.
- **`cicd`** — the PR lane (layered on `devex pr`): create PRs, address review
  feedback, poll SonarCloud + unresolved threads, gate on the quality gate.
- **`version-bump`** — bump semver + prepend a CHANGELOG entry (see below).
- **`remember`/`recall`** — shared eidetic memory across sessions.
- **`communicate`** — file issues on sibling repos / message mesh channels.

## Git and PR workflow

- **Every PR bumps the version — even docs/config/CI-only PRs.** CI's
  `version-check` job compares `pyproject.toml` against `main` and fails the PR
  if unchanged. Use the `version-bump` skill (updates `pyproject.toml` +
  `CHANGELOG.md`) before opening a PR.
- Branch → implement → bump version → open PR via the `cicd` skill → address
  review threads → merge. Don't commit or push to `main` unless asked.
- **Publish:** `.github/workflows/publish.yml` publishes to PyPI (Trusted
  Publishing / OIDC) on push to `main` when `pyproject.toml` or `league/**`
  changes; PRs get a TestPyPI dev build. CI also gates on the SonarCloud quality
  gate when `SONAR_TOKEN` is set (token-less repos and fork PRs stay green).
- **Signing posts:** inside this AgentCulture repo, the `cicd` scripts append the
  signature automatically (resolved from `culture.yaml` → `- league-of-agents
  (Claude)`) — write PR-reply bodies unsigned. For posts the scripts don't author
  (a manual `gh pr create --body …`, issue bodies), sign explicitly as
  `- league-of-agents (Claude)`.

## Renaming the scaffold

The name `league-of-agents` / `league` is hard-coded in ~100 places (package,
CLI files, tests, `_ISSUES_URL`, `sonar-project.properties`, README). If you
re-template this repo, enumerate every occurrence first rather than renaming by
hand:

```bash
git grep -n -E 'league[-_]of[-_]agents|league-of-agents|\bleague\b'
```
