"""Markdown catalog for ``league-of-agents explain <path>``.

Each entry is verbatim markdown. Keys are command-path tuples. The empty tuple
and ``("league-of-agents",)`` both resolve to the root entry.

Keep bodies self-contained: an agent reading one entry should get enough
context without chaining reads.
"""

from __future__ import annotations

_ROOT = """\
# league-of-agents

A clonable template for AgentCulture mesh agents. It carries an agent-first CLI
(cited from the teken `python-cli` reference), a mesh identity (`culture.yaml` +
`CLAUDE.md`), the canonical guildmaster skill kit under `.claude/skills/`, and a
buildable/deployable package baseline. Clone it, rename the package, edit
`culture.yaml`, and you have a new agent.

## Verbs

- `league-of-agents whoami` — identity probe from `culture.yaml`.
- `league-of-agents learn` — structured self-teaching prompt.
- `league-of-agents explain <path>` — markdown docs for any noun/verb.
- `league-of-agents overview` — descriptive snapshot of the agent.
- `league-of-agents doctor` — check the agent-identity invariants.
- `league-of-agents cli overview` — describe the CLI surface.

## Arena (season 0)

- `league arena list|show` — the scenario catalog (read-only).
- `league team register|list|show` — the competitors' rosters.
- `league match new|act|tick|show|list|score|replay` — the play loop:
  declare orders, deterministic resolution, dual scoring, HTML replay.

Write verbs (`team register`, `match new/act/tick`) are dry-run by default;
add `--apply` to commit. Every read verb takes `--json`.

## Exit-code policy

- `0` success
- `1` user-input error
- `2` environment / setup error
- `3+` reserved

## See also

- `league-of-agents explain whoami`
- `league-of-agents explain doctor`
"""

_WHOAMI = """\
# league-of-agents whoami

Reports the agent's identity from `culture.yaml`: nick (`suffix`), backend,
served model, and the package version. Read-only.

## Usage

    league-of-agents whoami
    league-of-agents whoami --json
"""

_LEARN = """\
# league-of-agents learn

Prints a structured self-teaching prompt covering purpose, command map,
exit-code policy, `--json` support, and the `explain` pointer.

## Usage

    league-of-agents learn
    league-of-agents learn --json
"""

_EXPLAIN = """\
# league-of-agents explain <path>

Prints markdown documentation for any noun/verb path. Unlike `--help` (terse,
positional), `explain` is global and addressable by path.

## Usage

    league-of-agents explain league-of-agents
    league-of-agents explain whoami
    league-of-agents explain --json <path>
"""

_OVERVIEW = """\
# league-of-agents overview

Read-only descriptive snapshot of the agent: identity (from `culture.yaml`), the
verb surface, and the sibling-pattern artifacts the template carries. Accepts an
ignored `target` so a stray path never hard-fails.

## Usage

    league-of-agents overview
    league-of-agents overview --json
"""

_DOCTOR = """\
# league-of-agents doctor

Checks the agent-identity invariants `steward doctor` verifies:
prompt-file-present and backend-consistency (`colleague` → `AGENTS.colleague.md`), plus a
skills-present check. Exits 1 when unhealthy.

## Usage

    league-of-agents doctor
    league-of-agents doctor --json
"""

_CLI = """\
# league-of-agents cli

Noun group for CLI-surface introspection. `cli overview` describes the CLI
itself (distinct from the global `overview`, which describes the agent).

## Usage

    league-of-agents cli overview
    league-of-agents cli overview --json
"""


_ARENA = """\
# league arena

The scenario catalog — the maps, objectives, and economies matches run on.
Read-only: `list` names the scenarios, `show` prints one in full (grid, roles
and their move/carry stats, control points, missions, resource nodes).

Scenarios deliberately force coordination tradeoffs: role stats are lopsided
and the turn limit sits below the best solo run, so teams that don't divide
labour lose (see `docs/specs/` for the season-0 spec).

## Usage

    league arena list [--json]
    league arena show skirmish-1 [--json]
"""

_TEAM = """\
# league team

The competitors. A team is a named roster of agent seats — each seat an
`id:model:role` triple, so different models and role compositions can be
fielded and compared fairly. Rosters persist under `.league/teams/`.

`register` is a write verb: **dry-run by default, `--apply` writes.**

## Usage

    league team register blue --name "Blue Foundry" \\
        --agent blue-1:claude-sonnet-5:scout \\
        --agent blue-2:colleague/qwen:harvester \\
        --agent blue-3:colleague/qwen:defender --apply
    league team list [--json]
    league team show blue [--json]
"""

_MATCH = """\
# league match

The play loop. Matches live under `.league/matches/<id>/log.jsonl` — the
event log is the single source of truth: state, scores, and the HTML replay
are all derived from it.

Turns are simultaneous: each team stages orders with `act`; the turn resolves
deterministically once every team has staged (or when `tick` forces it).
Write verbs (`new`, `act`, `tick`) are **dry-run by default; `--apply`
commits** — a stray call never silently advances the game.

## Usage

    league match new --scenario skirmish-1 --team blue --team red --seed 7 \\
        --driver blue:bot --driver red:stateless --apply
    league match show <id> --json          # full state + staged teams + driver_kinds
    league match act <id> --team blue --plan "..." \\
        --action blue-u1:move:3,1 --action blue-u2:gather \\
        --message blue-1:"east is open" --apply
    league match tick <id> --apply         # force-resolve (timeouts)
    league match score <id> --json         # outcome + cooperation
    league match replay <id> > match.html  # self-contained human replay

Orders can also be one JSON object: `--orders-json '{"plan": ..., "messages":
[...], "actions": [...]}'`.

`--driver <team-id>:<bot|stateless|resident>` (repeatable) records how a
team's minds were invoked — a declared fairness axis (spec c10/h7), not game
state. It lives in the match log header and `match show --json`'s
`driver_kinds`, never in engine state; omit it and the team's kind is simply
unrecorded.
"""


_STANDINGS = """\
# league standings / league history

Read-only trend verbs, computed straight from the match logs (the queryable
store), so they can never disagree with the record.

- `league standings [--json]` — per-team W/L/D, outcome totals, cooperation
  averages and trend; per-agent records (matches, wins, cooperation average,
  orders declared/rejected). This is where per-agent improvement shows up.
- `league history [--json]` — finished matches in id order with both scores
  per team.
"""

_HARNESS = """\
# league harness

Runs a whole match with live team drivers, acting **only** through the public
CLI surface (`match show --json` → orders → `match act --orders-json --apply`).

Driver types (per team, in the config JSON):

- `{"type": "bot"}` — the deterministic greedy baseline (no model).
- `{"type": "command", "argv": ["claude", "-p", "--model", "claude-sonnet-5"],
   "timeout": 300}` — any external agent as a subprocess: prompt (rules +
  state JSON) on stdin, orders JSON on stdout. A colleague model, a Sonnet
  subagent, or an orchestrator is a config change, not a code change.

Every driver also declares a residency (spec c10/h7): `bot` is always `"bot"`;
`command` defaults to `"stateless"` (fresh subprocess per turn) unless the
spec adds `"residency": "resident"` (one persistent session per seat, a later
task). `run_match` records each team's kind in the match log header, so
`match show --json`'s `driver_kinds` always answers "how was this team's mind
driven?" alongside the score.

## Usage

    league harness run --config playtest.json          # dry-run
    league harness run --config playtest.json --apply  # play it

Config shape: {"match": {"scenario", "mode", "seed", "id"},
"teams": [{"id", "name", "driver", "agents": [{"id", "model", "role"}]}],
"max_rounds": N}.
"""


ENTRIES: dict[tuple[str, ...], str] = {
    (): _ROOT,
    # Both the console command (`league`) and the distribution/display name
    # (`league-of-agents`) resolve to the root entry, so `explain <self>` works
    # whichever name a caller reaches for. The rubric gate derives <self> from
    # `[project.scripts]` (= `league`) and checks `explain league` specifically.
    ("league",): _ROOT,
    ("league-of-agents",): _ROOT,
    ("whoami",): _WHOAMI,
    ("learn",): _LEARN,
    ("explain",): _EXPLAIN,
    ("overview",): _OVERVIEW,
    ("doctor",): _DOCTOR,
    ("cli",): _CLI,
    ("cli", "overview"): _CLI,
    ("arena",): _ARENA,
    ("arena", "overview"): _ARENA,
    ("arena", "list"): _ARENA,
    ("arena", "show"): _ARENA,
    ("team",): _TEAM,
    ("team", "overview"): _TEAM,
    ("team", "register"): _TEAM,
    ("team", "list"): _TEAM,
    ("team", "show"): _TEAM,
    ("match",): _MATCH,
    ("match", "overview"): _MATCH,
    ("match", "new"): _MATCH,
    ("match", "list"): _MATCH,
    ("match", "show"): _MATCH,
    ("match", "act"): _MATCH,
    ("match", "tick"): _MATCH,
    ("match", "score"): _MATCH,
    ("match", "replay"): _MATCH,
    ("match", "rematch"): _MATCH,
    ("standings",): _STANDINGS,
    ("history",): _STANDINGS,
    ("harness",): _HARNESS,
    ("harness", "overview"): _HARNESS,
    ("harness", "run"): _HARNESS,
}
