"""Markdown catalog for ``league-of-agents explain <path>``.

Each entry is verbatim markdown. Keys are command-path tuples. The empty tuple
and ``("league-of-agents",)`` both resolve to the root entry.

Keep bodies self-contained: an agent reading one entry should get enough
context without chaining reads.
"""

from __future__ import annotations

_ROOT = """\
# league-of-agents

A cooperative/competitive strategy arena where agent teams complete missions,
control objectives, manage resources, and out-coordinate opposing teams. Matches
are deterministic and replayable, scored on **both mission outcome and
cooperation quality** — the core question being whether a group of agents can
become a coherent, strategic team under constraint. It is driven through an
agent-first CLI (cited from the teken `python-cli` reference) and is itself an
AgentCulture mesh agent (`culture.yaml`, backend `colleague`).

## Introspection

- `league whoami` — identity probe from `culture.yaml`.
- `league learn` — structured self-teaching prompt.
- `league explain <path>` — markdown docs for any noun/verb.
- `league overview` — descriptive snapshot of the agent.
- `league doctor` — check the agent-identity invariants.
- `league cli overview` — describe the CLI surface.

## The arena

- `league arena list|show` — the scenario catalog (read-only).
- `league team register|list|show` — the competitors' rosters (`id:model:role`).
- `league match new|act|tick|show|list` — the play loop: declare orders,
  deterministic canonical-order resolution, current state (`--team`/`--fog` for
  one team's view).
- `league match score|probe|brief` — read the log back: dual scores plus a
  per-unit MVP/LVP scorecard, the span-of-control probe, and the agents' markdown
  briefing (`--team` fogs it).
- `league match replay|record|tui` — watch it: self-contained HTML replay,
  offline GIF/MP4 video, terminal view.
- `league match rematch` — same scenario+seed, new roster.
- `league standings|history` — cross-match trends, per team and per agent.
- `league harness run` — play a configured match end to end with live drivers.
- `league play list|show|start` — one-command launch of a bundled game mode.
- `league cmatch new|show|act|tick|run` — the continuous (real-time) lane's own
  external-driver play loop: a mind is asked for ONE unit's action at a
  decision point, never a whole-team turn order. `match score`/`match replay`
  already read `cmatch`-produced logs unchanged (lane auto-detected).

Write verbs (`team register`, `match new/act/tick/rematch`, `harness run`,
`play start`, `cmatch new/act/tick/run`) are dry-run by default; add `--apply`
to commit. Every read verb takes `--json` — except the interactive `league
match tui`, which renders a terminal view only.

## Exit-code policy

- `0` success
- `1` user-input error
- `2` environment / setup error
- `3+` reserved

## See also

- `league explain match`
- `league explain harness`
- `league explain play`
"""

_WHOAMI = """\
# league-of-agents whoami

Reports the agent's identity from `culture.yaml`: nick (`suffix`), backend,
served model, and the package version. Read-only.

## Usage

    league whoami
    league whoami --json
"""

_LEARN = """\
# league-of-agents learn

Prints a structured self-teaching prompt covering purpose, command map,
exit-code policy, `--json` support, and the `explain` pointer.

## Usage

    league learn
    league learn --json
"""

_EXPLAIN = """\
# league-of-agents explain <path>

Prints markdown documentation for any noun/verb path. Unlike `--help` (terse,
positional), `explain` is global and addressable by path.

## Usage

    league explain league
    league explain whoami
    league explain --json <path>
"""

_OVERVIEW = """\
# league-of-agents overview

Read-only descriptive snapshot of the agent: identity (from `culture.yaml`), the
verb surface, and the sibling-pattern artifacts the template carries. Accepts an
ignored `target` so a stray path never hard-fails.

## Usage

    league overview
    league overview --json
"""

_DOCTOR = """\
# league-of-agents doctor

Checks the agent-identity invariants `steward doctor` verifies:
prompt-file-present and backend-consistency (`colleague` → `AGENTS.colleague.md`), plus a
skills-present check. Exits 1 when unhealthy.

## Usage

    league doctor
    league doctor --json
"""

_CLI = """\
# league-of-agents cli

Noun group for CLI-surface introspection. `cli overview` describes the CLI
itself (distinct from the global `overview`, which describes the agent).

## Usage

    league cli overview
    league cli overview --json
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
    league match score <id> --json         # outcome + cooperation + tempo + units
    league match score <id> --substrate blue=cloud  # substrate-fair tempo
    league match probe <id> --json         # span-of-control: subagents, realization, guidance
    league match brief <id> [--team blue]  # markdown briefing (the agents' face)
    league match replay <id> > match.html  # self-contained human replay
    league match record <id> --out match.gif             # shareable video, offline
    league match record <id> --out m.gif --scale 32 --fps 3 --json
    league match record <id> --out m.mp4 --format mp4    # + seeded ambient soundtrack

`record --format mp4` (ffmpeg on PATH required) muxes the match's ambient
score — the same seeded piece the HTML replay plays, synthesized offline from
the log alone, byte-deterministic. The GIF stays silent because GIF has no
audio channel: format truth, not a missing feature.
    league match tui <id> --frame N [--team blue] [--no-color]  # terminal view

`score`'s tempo axis — the per-substrate calibration table, the t0 conversion
formula, and its own published limits — is documented in
`docs/tempo-methodology.md`; read it before trusting a converted number
across two declared substrates.

`score` also carries a `units` section (plan task t6, spec c6/c10/c15): a
per-unit, role-purpose-weighted scorecard computed from the log alone
(`league.engine.grades.grade_units` for grid, `league.engine.continuous.
grades.cgrade_units` for continuous — the same lane detection `replay` uses),
naming the match MVP and LVP. It is a NEW axis beside outcome/cooperation/
tempo, never merged into any of them — grading a match never changes its
team-axis numbers, and no ranking/ELO/cross-match aggregation verb exists
anywhere in this CLI: MVP/LVP is named per match only. Shape (identical for
both lanes; only the purpose names differ — grid: economy/control/recon/
coordination, continuous: race_hold/economy/eyes):

    "units": {
      "match_id": "...", "purposes": ["economy", "control", "recon", "coordination"],
      "units": {
        "<unit_id>": {"team_id", "role", "home_purpose", "grade", "breakdown": {
          "<purpose>": <points>, ...}, "mvp": bool, "lvp": bool}, ...
      },
      "mvp": {"unit_id", "team_id", "grade"} | null,
      "lvp": {"unit_id", "team_id", "grade"} | null
    }

On-purpose contributions score full credit, off-purpose contributions still
score — just at a discount ("a scout not scouting should still get points, but
less" — the human review that asked for this, quoted verbatim). Text mode
renders a ranked scorecard (best grade first) with `[MVP]`/`[LVP]` tags and
each unit's per-purpose breakdown.

`brief` is the markdown face for agents, served from the agentfront faces
registry (`league/faces/`): `--json` returns the SAME facts the markdown
renders — one declaration, two projections, proven fact-for-fact by the
face-agreement tests. `--team <id>` fogs the brief to that team's knowledge
fold (seen/told facts only — never the full board, never scores).

Orders can also be one JSON object: `--orders-json '{"plan": ..., "messages":
[...], "actions": [...]}'`.

`show --json` also includes `legal_actions`: for every living unit, its move
targets in range plus gather/deliver/hold applicability — computed straight
from state + scenario (deterministic, sorted, no engine mutation). Check it
before declaring an order; the season-0 coordination playtest burned 19 of 53
orders on exactly the misses this closes (10 beyond-move-range moves, 6
off-square delivers).

`--driver <team-id>:<bot|stateless|resident>` (repeatable) records how a
team's minds were invoked — a declared fairness axis (spec c10/h7), not game
state. It lives in the match log header and `match show --json`'s
`driver_kinds`, never in engine state; omit it and the team's kind is simply
unrecorded. `--driver <team-id>:bot-file:<strategy-name>` (issue #30) is a
distinct, accepted kind: it records the FULL string (kind + strategy, e.g.
`bot-file:rusher`) verbatim in the header — the same `bot-file:<name>`
convention a team's agent `model` field already uses in harness configs —
more specific than `league.harness.driver_kind()`'s own "bot" residency
label, which only says HOW a team was invoked, not which strategy.

`--max-actions <team-id>:<positive-int>` (repeatable, issue #29) declares the
mode/handicap profile: a cap on how many unit actions a team may stage in one
`match act` call (e.g. the solo preset's one-action-per-turn handicap). It
lives in the match log header and `match show --json`'s `max_actions`, a team
absent from the map is uncapped. `match act` enforces it where orders are
staged — never silently truncating an over-cap submission, always a
structured `CliError` — and, whenever an `--apply`'d attempt actually trips
it, appends a durable `orders_capped` event straight to the log (bypassing
the tick, the same way `seat_latency` does) so the refusal is verifiable from
the record, not just the CLI's own exit code. `league.harness.run_match`
threads a preset's/config's own declared `max_actions` into this flag, so a
solo preset's cap is enforced whether the harness or a raw `match act` call
stages the orders — the harness's own client-side truncation
(`actions[:1] if solo else actions`) becomes redundant under this, never
conflicting with it.

`--map-read <team-id>:<full|fog>` and `--unit-comms <team-id>:<on|off>`
(both repeatable) record orchestrator mode's two declared fairness axes
(plan t6, spec c4/c6/h3/h5): `map_read` is the team's master/commander
map-read capability under fog — `full` means the master reads the whole
board (a DECLARED information-asymmetry rule of the mode, never a hidden
privilege), `fog` (the implicit default when omitted) means the same fogged
view as everyone; `unit_comms` is whether that team's ground units may
message each other directly (`on`) or are master-mediated only (`off`,
orchestrator mode's own default). Both live in the match log header and
`match show --json`'s `map_read`/`unit_comms`, never in engine state; the
harness (`league/harness.py`) reads them off each team's config to decide
what the master's briefing sees and which messages a seat's briefing relays.

`show --json` also includes `last_turn_rejections`: every genuine
`action_rejected` event from the turn just resolved (`{team_id, unit_id,
reason}`), so a caller can see *why* an order failed without scraping the
whole log. The harness folds this into each agent's next briefing (spec
c8/h5) — a seat that never learns the reason otherwise repeats the mistake
for the whole match. A `passive` `action_rejected` (issue #31) — a
capture-incapable unit merely standing on a contested/owned control point,
fired from occupancy every turn regardless of whether the unit's own
declared order succeeded — is excluded from this list: it was never a
mistake to explain back.

`show` and `probe` are grid-lane-only today (issue #28 item f): against a
continuous-lane log they exit non-zero with a clean, structured `CliError`
naming the limitation, using the same header lane-sniff `score`/`replay`
already route on, rather than an opaque `KeyError: 'turn'`. Full
continuous-lane support for these two verbs is tracked separately.

`probe` (`league.engine.probe`, plan task t7) measures span of control from the
log alone: how many subagents a team's mind actually fielded (`span` — a real,
harness-recorded, per-seat call or a real declared action tied to that seat's
OWN voice; a message merely NAMING a subagent counts for nothing), how well
each subagent's orders landed (`realization_rate` — per seat, `1 -
rejected/declared`, counting only genuine declared-order rejections; a
`passive` capture-ineligibility rejection, issue #31, never penalizes it), and
whether guidance messages actually steered behavior (`guidance_linkage` —
reusing cooperation v1's referent-matching idea: a commanding message counts
only if a subsequent team action realizes something it named). `seat_latency`
evidence, when the team has any, is authoritative over message content (a
single whole-team driver call narrating several named
personas is still span 0/1, never one seat per persona); absent it (pre
seat_latency logs), the probe falls back to a stricter dual-evidence check —
own-voice message AND a real declared action on that seat's own unit. The
payload mirrors `score`'s style: `{score, signals, components, version}` per
team, plus a per-turn `degradation_curve` bucketed by how many seats acted
concurrently, so "commands 3 well, 1 badly" is visible from one match alone.

`record` (`league.replay.video`, plan task t6, spec c7/h7) renders the log
into a shareable video file, entirely offline — no screen capture, no live
session, no network. The default `--format gif` is a pure-stdlib animated
GIF89a writer (palette-indexed raster frames + a hand-rolled LZW encoder);
it always works, nothing to install, and the runtime stays dependency-free.
`--format mp4` pipes the same raw frames through `ffmpeg` if it's on PATH;
absent it, the flag fails with a remediated error naming the GIF fallback
rather than silently downgrading. Frame count is `turns + (turns - 1) * tween
+ 2`: an opening title card (match id, scenario, teams with color swatches +
rosters), one frame per turn actually played, `--tween N` linearly
interpolated frames between each pair of turns (default 4; 0 disables) so
movement flows instead of teleporting, and a closing card (final score by
axis). `--theme light|dark` (default light) selects the same validated palette
as the HTML replay — light Anthropic cream, dark Culture black-green — and
changes only the GIF's color table. Reproducible by construction: the same log
at the same `--theme`/`--scale`/`--fps`/`--tween` renders byte-identical
output, and the exact command is embedded as a GIF Comment Extension (or MP4
`comment` metadata) — provenance travels with the artifact, not in a separate
sidecar. `--scale` is pixels per grid cell (bounds enforced); `--fps` is
turn-frame rate (the title/closing cards hold several times longer
automatically, for readability).

`--team <id>` scopes `legal_actions`/`last_turn_rejections` to that team.
Add `--fog` (requires `--team`) for that team's fog-of-war projection (plan
t5, spec c5/h4): `state` is replaced by that team's own roster in full plus
every other unit / control point / resource node / discovered mission it has
actually seen or been told about (`league.engine.knowledge`), and a new
`knowledge` key carries the raw fold. The plain (no `--team`/`--fog`)
response is untouched — this is additive. The harness calls this per team,
per turn, for `command`/`resident` drivers when the match config sets
`"fog": true`; bot drivers stay on the full, un-fogged state (documented,
temporary asymmetry — see `league/harness.py`).
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

_CMATCH = """\
# league cmatch

The continuous lane's external-driver play loop (issue #28) — the sibling of
`league match` for `league/engine/continuous/`. Where the grid asks a driver
for a whole-team turn order, the continuous lane asks for exactly ONE unit's
action at a decision point (the instant that unit goes idle) — see
`docs/continuous-contract.md` for the full mind-facing contract. Matches live
at the SAME `.league/matches/<id>/log.jsonl` path the grid uses (continuous
headers carry `clock`/`width`, not `turn`/`grid_width` — `match score`/`match
replay` already lane-sniff this automatically, unchanged by this noun group).

Write verbs (`new`, `act`, `tick`, `run`) are **dry-run by default; `--apply`
commits** — the same safe-by-default contract every other write verb in this
repo follows. State is always a pure fold of the log: killing an external
harness between any two `cmatch` calls and re-running from the same working
directory continues correctly, no in-memory state required.

## Usage

    league cmatch new --scenario c-skirmish-1 --team blue --team red \\
        --driver blue:bot --driver red:bot --apply --json
    league cmatch new --config match.json --apply         # or inline JSON
    league cmatch new --scenario c-skirmish-1 --team blue --team red \\
        --fog --apply                           # fog every briefing (recorded in
                                                 # the log header; a --config's own
                                                 # "fog": true does the same)

    league cmatch show <id> --json             # every currently-due unit's briefing
    league cmatch show <id> --unit blue-u1 --json  # scope to one due unit

    league cmatch act <id> --unit blue-u1 \\
        --action-json '{"kind": "move", "target_pos": {"x": 5000, "y": 4000}}' \\
        --message 'moving to the crossing — cover me' \\
        --plan 'defender races the post, harvester runs the economy' \\
        --apply --json
    league cmatch act <id> --unit blue-u1 --apply   # omit --action-json (or pass
                                                     # 'null') to park that unit

    league cmatch tick <id> --apply --json          # auto-resolve bot-driven due
                                                     # units, advance the timeline
    league cmatch tick <id> --timeout-park --apply  # + park anything left over

    league cmatch run --config match.json --apply --json   # the packaged one-shot
                                                             # (was scripts/run_cmatch.py)

`new`/`show`/`act`/`tick` accept either `--scenario`/`--team`/`--driver` flags
(referencing rosters already registered with `league team register` — lane-
agnostic, the same registry the grid lane uses) or a single `--config` (a
file path OR inline JSON, mirroring `league harness run`'s config shape:
`{"match": {"scenario", "mode", "seed", "id"}, "teams": [{"id", "name",
"driver", "agents"}], "fog": false}`). Fog (`--fog`, or the config's own
`"fog": true`) is recorded in the match log's header at `new` time, and every
later `show`/`tick` briefing is then fogged per the acting due unit's OWN
team — the identical union-of-vision projection `run_cmatch` hands its
drivers (`league.charness.build_briefing`; ground truth stays in the log,
scoring/replay unaffected).

`show` is the externally queryable "what is due right now": every unit that
is alive, idle, and has not yet been asked this idle window, in canonical
`(team_id, unit_id)` order, each with its FULL briefing (`game_time`, `you`,
`menu` with per-action `duration`/`completion_time`, `outlook`, `board`,
`messages` — the exact shape `league.charness.build_briefing` pins, see
`docs/continuous-contract.md`).

`act --unit <id> --action-json '<menu entry|null>'` submits ONE unit's
decision. Multiple units can be due at once (e.g. every unit at match start);
they must be answered in the order `show`'s `due` list reports them — the
canonical order the resolver itself would ask them in — or `act` refuses with
a clean error naming which unit is next. This is what makes stepwise,
externally-driven play produce a log BYTE-IDENTICAL to an equivalent single
`league.charness.run_cmatch` call given the same decisions (the parity proof,
`tests/test_continuous_resolve.py`/`tests/test_cli_cmatch.py`) — answering out
of order is refused rather than silently reordered.

`act --message <text>` (repeatable) and `act --plan <text>` attach the driver
reply's social record (`{"action", "message"?, "plan"?}` per
`docs/continuous-contract.md`) to the decision: recorded as
`message_sent`/`plan_declared` OBSERVATION events riding the decision's own
`decision_point`/`action_started` pair — the same interleave convention (and
the same bytes) `run_cmatch` writes. The sender is always the acting unit's
own agent (never a flag — spoof-proof, like the harness); a plan is recorded
once per agent, first declaration wins. Later briefings — `show`'s and the
ones `tick` hands bot/bot-file drivers — surface the running message record
exactly as an in-harness seat would have seen it.

`tick` is the verb an external harness calls when it has **nothing to
submit**: it resolves every currently-due unit belonging to a team whose
driver label (recorded at `new`/`--config` time) is `bot` or
`bot-file:<name>` — deterministic, in-process, no live session to persist
across CLI calls — and, with `--timeout-park`, parks any OTHER due unit
instead of leaving it pending. A `stateless`/`resident` (live-mind) team's due
units are neither resolved nor parked by default: they stay due for an
external `cmatch act` call, exactly mirroring `match tick`'s own grid-lane
behavior (it force-resolves with whatever is staged; it never invokes a live
mind itself either). Every bot-driven briefing `tick` builds carries the
running message record (rebuilt from the log's own `message_sent` events plus
this call's) and the match's fog projection — so a strategy that reads
`briefing["messages"]` or a fogged board behaves identically whether
`run_cmatch` or `cmatch tick` drives it — and any message/plan a bot's reply
attaches is recorded exactly as `act --message`/`--plan` records one.

`run` is the packaged one-shot — bot-vs-bot, live minds, or a mix, all in one
call, exactly what `league.charness.run_cmatch` already did as a library call
(`scripts/run_cmatch.py` used to be the only way to reach it from a shell; it
is now a thin, deprecated wrapper around this verb). The stepwise loop and
`run` support the same config surface — fog included — and produce
byte-identical logs for the same decisions in the same order (minus `run`'s
wall-clock `seat_latency` instrumentation, which a stepwise decision has no
analog for).

`match score`/`match replay` keep working on `cmatch`-produced logs
completely unchanged (they already lane-sniff the header shape, PR #33) —
there is no separate `cmatch score`/`cmatch replay` verb.
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
"max_rounds": N, "fog": false}.

`"fog": true` (plan t5, spec c5/h4) narrows every `command`/`resident`
briefing to that team's own vision plus its accumulated knowledge
(`match show --team <id> --fog --json`) — never the full board. Bot drivers
(`bot`/`bot-file`) stay full-information under fog for now, a documented,
temporary asymmetry (see `league/harness.py`); a fair fogged match keeps fog
on for every driver or none.
"""


_PLAY = """\
# league play

One-command launch of a bundled preset game mode (`league/presets.py`, plan
task t2). Every documented mode — `solo-vs-bot`, `team-vs-bot`,
`team-vs-team`, `orchestrator-vs-bot`, `resident-vs-bot` — runs end to end
from a single `league play start <preset> --apply` call: no hand-authored
`team register` / `match new` / `harness run` dance required.

`start` is a write verb: **dry-run by default, `--apply` actually plays the
match** (the same safe-by-default contract `match new`/`team
register`/`harness run` follow). `--seed`/`--id` override the preset's own
declared defaults — handy for running the same mode more than once without a
match-id collision — without ever editing the bundled registry.

## Usage

    league play list [--json]                    # every bundled preset
    league play show team-vs-team [--json]        # the resolved harness config
    league play start team-vs-team --apply        # bot-file vs bot-file, offline
    league play start solo-vs-bot --seed 99 --id my-solo-run --apply

`solo-vs-bot`, `team-vs-bot`, `orchestrator-vs-bot` and `resident-vs-bot`
drive a live agent process (`command`/`resident` drivers) — `--apply` on
those spawns whatever `argv` the preset declares (see `play show <preset>`).
`team-vs-team` is the one mode that never spawns anything: two committed
`bots/rusher.py` strategies play each other, fully deterministic given the
seed.
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
    ("match", "probe"): _MATCH,
    ("match", "brief"): _MATCH,
    ("match", "replay"): _MATCH,
    ("match", "record"): _MATCH,
    ("match", "tui"): _MATCH,
    ("match", "rematch"): _MATCH,
    ("standings",): _STANDINGS,
    ("history",): _STANDINGS,
    ("cmatch",): _CMATCH,
    ("cmatch", "overview"): _CMATCH,
    ("cmatch", "new"): _CMATCH,
    ("cmatch", "show"): _CMATCH,
    ("cmatch", "act"): _CMATCH,
    ("cmatch", "tick"): _CMATCH,
    ("cmatch", "run"): _CMATCH,
    ("harness",): _HARNESS,
    ("harness", "overview"): _HARNESS,
    ("harness", "run"): _HARNESS,
    ("play",): _PLAY,
    ("play", "overview"): _PLAY,
    ("play", "list"): _PLAY,
    ("play", "show"): _PLAY,
    ("play", "start"): _PLAY,
}
