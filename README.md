# league-of-agents

A cooperative/competitive strategy arena where agent teams complete missions,
control objectives, manage resources, and out-coordinate opposing teams.

The core question the arena answers (issue #1): *can this group of agents
become a coherent, strategic, cooperative team under constraint?* Matches are
deterministic and replayable, scored on **both mission outcome and cooperation
quality**, beautiful for humans and `--json`-practical for agents.

## Features

Everything the arena offers, grouped. Each feature has a deep-dive page under
[`docs/features/`](docs/features/) with the full mechanism, but the substance is
here — you shouldn't have to leave this page to understand what League of Agents
does.

### The engine

- **Deterministic engine (grid lane)** — Match state is immutable frozen
  dataclasses with a stable `state_hash`; an append-only event log is the single
  source of truth (the tick never edits state — it emits events and folds them,
  so replaying a log reproduces the outcome exactly); resolution is
  canonical-order, sorted by `(team_id, unit_id)`, so submission order never
  matters. A CI determinism gate replays a scripted match against a committed
  hash. [Deep dive →](docs/features/deterministic-engine.md)
- **Continuous engine lane (real-time)** — A second engine that resolves an
  *event timeline* instead of turns: integer milliunit positions (no floats),
  initiative decided by who finishes first with a canonical
  `(time, team_id, unit_id)` tie-break, and first-class race semantics (the
  slower taker of a contested point fails with `post taken by a faster agent`).
  Provably independent of the grid lane, with its own determinism hash.
  [Deep dive →](docs/features/continuous-lane.md)
- **Scenarios & roles** — The boards a match runs on (grid, objectives, economy,
  roster). Scenarios force coordination *by construction*: lopsided role stats
  and a turn limit below the best solo run (proven by arithmetic in tests) mean a
  team that won't divide labour loses. Roles are engine-enforced capability
  contracts — `move`/`carry`/`vision` plus `can_gather`/`can_capture` — never
  prompt conventions; if a role can't do something, the tick rejects it and
  `legal_actions` never offers it. [Deep dive →](docs/features/scenarios-and-roles.md)

### Scoring & inspection

- **Scoring & grades** — Every match is graded on more than who won: mission
  outcome, a **cooperation-quality** heuristic (delegation, communication, plan
  coherence, discipline), a published **tempo** axis (per-substrate calibrated,
  raw latency always shown), a **span-of-control probe** (how many subagents a
  mind actually fielded and how well it commanded them), and per-unit
  **role-purpose scorecards** that name an MVP and LVP. All computed from the log
  alone; deliberately no ELO or cross-match ranking.
  [Deep dive →](docs/features/scoring-and-grades.md)
- **Fog of war & vision** — Per-role vision radii plus an accumulating knowledge
  fold turn a match into an information game: under fog a team sees only what it
  has witnessed or been told, never the full board. Fog is a projection in the
  harness/CLI, never an engine mutation. Orchestrator mode adds declared
  `map-read` and `unit-comms` levers. [Deep dive →](docs/features/fog-of-war.md)
- **Standings & history** — Two read-only trend verbs computed straight from the
  match logs: per-team W/L/D and cooperation trend, and per-agent records. The
  one place cross-match aggregation lives — and only ever over recorded results.
  [Deep dive →](docs/features/standings-and-history.md)

### Watching a match

- **Replay & faces** — One log, many faces, all derived from the same fold so
  they can't disagree: a **self-contained HTML replay** (one file, both themes,
  no external requests; a full play/pause/scrub transport in the continuous
  face), a **markdown briefing** (the agents' face, with `--json` parity), a
  **terminal view**, **offline GIF/MP4 video** (pure-stdlib GIF, `ffmpeg` MP4
  with a seeded soundtrack), and **generative ambient audio**.
  [Deep dive →](docs/features/replay-and-faces.md)

### Playing the arena

- **Agent-first CLI** — Dry-run by default (`--apply` commits), `--json` on every
  read verb, a stable error contract (`CliError{code, message, remediation}` +
  exit codes `0/1/2/3+`, no leaked tracebacks), a clean stdout/stderr split, and
  no third-party runtime dependencies. New functionality is added as *noun
  groups*, never bolted on. [Deep dive →](docs/features/agent-first-cli.md)
- **Agent-player harness & drivers** — Play a whole match through the public CLI
  surface with live models (one independent mind per seat, coordinating *only*
  through in-game messages) or bots. Driver kinds: `bot`, `command` (stateless),
  `resident` (a persistent session per seat), and `bot-file`. Residency is a
  recorded fairness axis; orchestrator mode runs a master mind over per-seat
  ground agents. Which model sits in a seat is config, not code.
  [Deep dive →](docs/features/harness-and-drivers.md)
- **Coded-strategy bots** — A lane of automations with committed, readable
  strategies that play the *public* surface only (no engine internals, no
  nondeterminism — both enforced by AST scan), with declared **bronze/silver/gold**
  difficulty tiers and recorded proof the ordering holds.
  [Deep dive →](docs/features/coded-strategy-bots.md)
- **Play presets** — One-command launch of every bundled mode
  (`solo`/`team`/`orchestrator`/`resident` vs. the house bot, plus a fully-offline
  bot-vs-bot) — no hand-authored `team register` / `match new` / `harness run`
  dance. [Deep dive →](docs/features/play-presets.md)

### The agent itself

- **Identity & mesh** — League of Agents is itself an AgentCulture mesh agent:
  `culture.yaml` declares its nick/backend/model (backend `colleague` →
  `AGENTS.colleague.md`), `whoami` reads identity without a YAML dependency,
  `doctor` checks the mesh invariants, and a vendored *cite-don't-import* skill
  kit lives under `.claude/skills/`.
  [Deep dive →](docs/features/identity-and-mesh.md)

## Quickstart

```bash
uv sync
uv run pytest -n auto                 # run the test suite
uv run league whoami                  # identity from culture.yaml
uv run league learn                   # self-teaching prompt (add --json)
uv run teken cli doctor . --strict    # the agent-first rubric gate CI runs
```

Play a full bot-vs-bot match end to end:

```bash
uv run league team register blue --agent b1:bot:greedy:scout \
    --agent b2:bot:greedy:harvester --agent b3:bot:greedy:defender --apply
uv run league team register red --agent r1:bot:greedy:scout \
    --agent r2:bot:greedy:harvester --agent r3:bot:greedy:defender --apply
uv run league match new --scenario skirmish-1 --team blue --team red \
    --seed 7 --id my-first-match --apply
uv run league match act my-first-match --team blue \
    --action b1:move:2,1 --plan "scout east" --apply
uv run league match act my-first-match --team red \
    --action r1:move:9,8 --apply        # last team in -> the turn resolves
uv run league match show my-first-match --json
uv run league match replay my-first-match > match.html   # open in a browser
uv run league match score my-first-match
```

Or let the harness drive both sides (see `league explain harness` for live
model drivers):

```bash
uv run league harness run --config docs/playtests/season-0/opener.config.json --apply
```

Or skip the hand-authored setup entirely: `league play` bundles every
documented mode as a preset (`league play list`), so each one launches with
a single command (`league play show <preset>` prints the resolved config
first if you want to check before applying):

```bash
uv run league play start solo-vs-bot --apply          # one agent, handicapped, vs the house bot
uv run league play start team-vs-bot --apply          # one mind per seat (stateless) vs the house bot
uv run league play start team-vs-team --apply         # bot-file vs bot-file, fully offline
uv run league play start orchestrator-vs-bot --apply  # a master mind + per-seat ground agents vs the house bot
uv run league play start resident-vs-bot --apply      # one long-lived session per seat vs the house bot
```

## CLI

| Verb | What it does |
|------|--------------|
| `whoami` / `learn` / `explain <path>` / `overview` / `doctor` | Agent-first introspection: identity, self-teaching, per-path docs, snapshot, invariants. |
| `arena list\|show` | The scenario catalog (read-only). |
| `team register\|list\|show` | Rosters: agent seats as `id:model:role` triples. |
| `match new\|act\|tick\|show\|list` | The play loop: stage orders, deterministic canonical-order resolution, current state (`--team`/`--fog` for one team's view). |
| `match score\|probe\|brief\|replay\|record\|tui\|rematch` | Read the log back: dual scores + MVP/LVP, span-of-control probe, markdown briefing, self-contained HTML replay, offline GIF/MP4 video, terminal view, fair rematches (same scenario+seed, new roster). |
| `standings` / `history` | Per-team and per-agent trends across all recorded matches. |
| `harness run` | Play a configured match with live drivers end to end. |
| `play list\|show\|start` | One-command launch of a bundled preset mode (solo/team/orchestrator/resident vs. the house bot). |

Every read verb supports `--json`; write verbs (`team register`, `match
new/act/tick/rematch`, `harness run`, `play start`) are **dry-run by
default** — `--apply` commits. Results go to stdout, errors/diagnostics to stderr (never mixed).
Exit codes: `0` success, `1` user error, `2` environment error, `3+` reserved.

## How the game grows

Development runs a recursive **spec → plan → implement → live-test** cycle —
no new spec opens without a recorded live match from the previous increment.
See [`docs/process/cycle.md`](docs/process/cycle.md); season-0 artifacts live
in `docs/specs/`, `docs/plans/`, and `docs/playtests/`.

## License

Apache 2.0 — see [`LICENSE`](LICENSE).
