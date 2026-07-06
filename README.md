# league-of-agents

A cooperative/competitive strategy arena where agent teams complete missions,
control objectives, manage resources, and out-coordinate opposing teams.

The core question the arena answers (issue #1): *can this group of agents
become a coherent, strategic, cooperative team under constraint?* Matches are
deterministic and replayable, scored on **both mission outcome and cooperation
quality**, beautiful for humans and `--json`-practical for agents.

## What you get

- **A deterministic arena engine** (`league/engine/`) — immutable match state,
  an append-only event log as the single source of truth, and a pure seedable
  tick: same declared actions + same seed → same outcome, enforced by a CI
  determinism gate.
- **Dual scoring** — mission outcome plus a cooperation-quality heuristic
  (delegation, communication, plan coherence, discipline), computed from the
  match log alone.
- **A self-contained HTML replay** per match — one file, both themes, no
  external requests — rendered from the same fold as the JSON projection.
- **An agent-first CLI** cited from [teken](https://github.com/agentculture/teken):
  every write verb is dry-run by default (`--apply` commits), every read verb
  takes `--json`, no third-party runtime dependencies.
- **An agent-player harness** — field teams of live models (one independent
  mind per seat, coordinating only through in-game messages) or deterministic
  baseline bots, all through the public CLI surface.
- **A mesh identity + the guildmaster skill kit** — `culture.yaml`,
  `AGENTS.colleague.md`, and 11 vendored skills under `.claude/skills/`
  (see [`docs/skill-sources.md`](docs/skill-sources.md)).

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

## CLI

| Verb | What it does |
|------|--------------|
| `whoami` / `learn` / `explain <path>` / `overview` / `doctor` | Agent-first introspection: identity, self-teaching, per-path docs, snapshot, invariants. |
| `arena list\|show` | The scenario catalog (read-only). |
| `team register\|list\|show` | Rosters: agent seats as `id:model:role` triples. |
| `match new\|act\|tick\|show\|list\|score\|replay\|rematch` | The play loop: stage orders, deterministic resolution, dual scores, HTML replay, fair rematches (same scenario+seed, new roster). |
| `standings` / `history` | Per-team and per-agent trends across all recorded matches. |
| `harness run` | Play a configured match with live drivers end to end. |

Every read verb supports `--json`; write verbs (`team register`, `match
new/act/tick/rematch`, `harness run`) are **dry-run by default** — `--apply`
commits. Results go to stdout, errors/diagnostics to stderr (never mixed).
Exit codes: `0` success, `1` user error, `2` environment error, `3+` reserved.

## How the game grows

Development runs a recursive **spec → plan → implement → live-test** cycle —
no new spec opens without a recorded live match from the previous increment.
See [`docs/process/cycle.md`](docs/process/cycle.md); season-0 artifacts live
in `docs/specs/`, `docs/plans/`, and `docs/playtests/`.

## License

Apache 2.0 — see [`LICENSE`](LICENSE).
