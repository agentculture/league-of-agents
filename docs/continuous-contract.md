# The continuous mind-facing contract

This is the pinned answer to the frame's hardest parked question (cycle-7 `v1`):
**when does a mind get asked for orders in a timeline-based world, and how are
its time budgets exposed?** It is the contract every continuous driver kind
answers, implemented in [`league/charness.py`](../league/charness.py) around the
resolver in [`league/engine/continuous/resolve.py`](../league/engine/continuous/resolve.py).

Read it beside the grid contract: the grid drives uniform simultaneous turns —
each turn a driver receives the whole board and returns a whole-team order dict.
The continuous lane replaces the turn with an event **timeline**, and the
contract changes at its root.

## Decision cadence — when a mind is asked

A mind is asked for exactly **one** action at a **decision point**: the instant
its unit becomes idle. A unit becomes idle when

- the match starts (every unit gets an opening decision point, in canonical
  `(team_id, unit_id)` order), or
- its in-progress action **completes** (`action_completed`), or
- its action **fails** (`action_failed` — e.g. a post was taken by a faster
  agent mid-take), or
- its action is **interrupted** (`fail_action`, the cancel/replace primitive).

Because a faster role's actions carry shorter durations, a faster unit reaches
its next decision point sooner — "more decisions per unit of game time" is not a
special rule, it is the arithmetic of the timeline queue. The resolver owns the
loop; it emits a `decision_point` observation event and then calls the harness's
`decide(unit_id, state, menu)` callback. There is exactly one driver call per
`decision_point`.

The fundamental contract change from the grid: a driver produces **one action
for one unit**, never a whole-team order dict.

## The briefing — what a mind receives

At each decision point the harness builds a **briefing**: the JSON a mind sees.
`league.charness.build_briefing` pins its shape.

```json
{
  "game_time": 7,
  "you": {
    "unit_id": "blue-def", "agent_id": "blue-def", "team_id": "blue",
    "role": "defender", "pos": {"x": 3000, "y": 3000}, "carrying": 0,
    "action": null
  },
  "menu": [
    {"kind": "take_post", "target": "cp", "target_id": "cp",
     "duration": 6, "completion_time": 13},
    {"kind": "move", "target": "n1", "target_ref": "n1",
     "target_pos": {"x": 9000, "y": 9000}, "duration": 8, "completion_time": 15}
  ],
  "outlook": [
    {"unit_id": "red-def", "team_id": "red", "completion_time": 15}
  ],
  "board": { "clock": 7, "units": [ ... ], "control_points": [ ... ], "...": "..." },
  "messages": [
    {"from": "blue-harv", "text": "covering your take", "game_time": 6}
  ],
  "clock_budget_note": "Game time is 7 (integer game-time units ...)"
}
```

Field by field:

- **`game_time`** — the integer game clock at this decision point (`state.clock`).
  It is *game* time, never wall-clock; a driver's thinking time never advances
  it.
- **`you`** — the unit being asked. `action` is always `null` here (a decision
  point is, by definition, a unit going idle). `pos` and `carrying` are its
  current spatial/economy state; `agent_id`/`team_id` are added beyond the pinned
  minimum so a mind and a per-seat transport can identify themselves.
- **`menu`** — the action menu **with durations**, straight from
  [`legal_actions_continuous`](../league/engine/continuous/legal.py). Every entry
  carries its in-game `duration` **and** the absolute `completion_time`
  (`game_time + duration`) it would land at, so a time budget is plannable before
  a decision is spent. Each entry keeps its raw `target_id` / `target_pos`, so a
  driver returns a menu entry **directly** — the resolver recomputes the duration
  and effect from role data and never trusts the caller. `target` is a friendly
  label (the entity id, or a move's point-of-interest ref).
- **`outlook`** — the visible **initiative outlook**: which units are due to
  complete their current action next, soonest first, in canonical
  `(completion_time, team_id, unit_id)` order. This is a pure projection of the
  board (every unit currently mid-action) and is provably the same set the
  resolver's `Timeline.pending()` holds for real units — the synthetic
  hold-ownership-window markers the timeline also carries are resolver-internal
  scheduling, not decision points, so they never appear in a mind's outlook. This
  is how a team reasons about races: *"the enemy defender finishes its take at
  t=15; my defender can finish first at t=13."* (Scout never enters this kind
  of reasoning at all — it is forbidden from `take_post` in the continuous
  lane, a human-reviewed amendment, cycle 7 pre-publish: "scouts should not be
  able to take posts — only be the 'eyes'". Its menu simply never offers
  `take_post`; see [`docs/roles.md`](roles.md) for the cycle-8 decision that
  brought the grid lane's scout to the same eyes-only rule.)
- **`board`** — a projection of the whole state: teams, units, control points
  (with their concurrent `takers`), missions, and resource nodes. Fogless by
  default; with `config["fog"]` on (plan C8-t5), `units`/`control_points`/
  `resource_nodes`/`missions` are narrowed to the acting team's union of
  per-role vision radii (a team's own units are always kept) — filtering is
  purely a `league/charness.py` briefing-layer projection, never an engine
  change, so ground truth in the log and scoring are unaffected. See
  `build_briefing`'s "continuous fog" docstring section for the exact rule
  and `tests/test_fog.py` for the boundary/scout-lever proofs.
- **`messages`** — the running social record: messages other seats have attached
  to their orders so far, each `{from, text, game_time}`. A mind may attach a
  message to its own order reply; the harness records it as a `message_sent`
  OBSERVATION event and surfaces it in later briefings. Plans work the same way
  (`plan_declared`). The `from` is always forced to the seat's own agent id —
  never trusted from the reply.
- **`clock_budget_note`** — a short human-readable note restating how to read the
  clock, durations, and the outlook as a time budget.

## The order a mind returns

A driver returns one JSON object:

```json
{"action": {"kind": "take_post", "target_id": "cp"},
 "message": "taking the post — cover me",
 "plan": "hold center, harvester runs the economy"}
```

- **`action`** — one chosen menu entry (or a bare `{"kind", "target_id"|"target_pos"}`),
  or `null` to **park** the unit (skip this decision point). An action the
  legality oracle refuses safely parks the seat rather than crashing the match —
  the continuous analog of the grid's reject-and-idle.
- **`message`** / **`messages`** — optional; a string, `{"text": ...}`, or a
  list of either. Coordination is free and is the social record cooperation
  scoring reads.
- **`plan`** — optional standing plan (recorded once per seat).

## Delivery contention

A `deliver` is not unconditional: it can be **denied**. At the instant a
delivery would complete, the resolver checks whether an **enemy** unit is
standing at the delivery site (the same site the delivering unit already had
to reach to be offered `deliver` at all — see the menu's `target`). If one is,
the delivery fails instead of banking:

```json
{"kind": "action_failed", "data": {"unit_id": "blue-harv",
 "reason": "delivery denied by enemy presence at the site"}}
```

Nothing is banked — the carried resources stay on the unit, exactly as if
nothing had been delivered — and the unit goes idle with a fresh decision
point, the same as any other failed or interrupted action (see "Decision
cadence" above). A mind reading this reason knows the site is contested and
can choose its own response: try the delivery again once the defender moves
off, deliver somewhere else if another deliver site exists, or bring a
teammate to clear the site first. This is the "lockdown" strategy issue #1's
role-specialization ask implies but the engine never enforced before this
cycle: a defended delivery square is now a real tradeoff, not an accident of
no-rules.

**Deny, not delay.** The rule denies rather than delaying-and-retrying at a
later instant, so the outcome is always immediate and legible in the log — no
"pending, contested" state a mind would have to track across decision points.

**Same-team deliveries never contest each other.** Only an *enemy* presence
denies a delivery — two teammates completing a delivery at the exact same
instant both succeed (each earns its own `resource_delivered` /
`action_completed` pair); when an instant is shared, canonical `(time,
team_id, unit_id)` order — the same tie-break the outlook is built from —
decides only which of the two events is written first, never whether either
one happens.

## Substrate independence (honesty `h7`)

The load-bearing property: **the same continuous match log emerges whether a
seat's driver answers in 1 millisecond or 60 seconds.** Game time comes only
from role data and the timeline — never the wall clock.

It holds by construction:

- The resolver lives under the engine-wide AST import ban
  (`tests/test_engine_state.py`), so it *cannot* import `time`/`random`/… — game
  time can only come from role durations and the event timeline.
- Wall-clock is read **only** in `league/charness.py` (`_monotonic`), and only to
  fill `seat_latency` observations — the out-of-game tempo axis. It is never fed
  back to the resolver.
- The harness records `seat_latency` / `message_sent` / `plan_declared` as
  OBSERVATION events (fold no-ops), appended after the resolver's transition
  stream. Stripping them leaves the transitions — and the final `cstate_hash` —
  byte-for-byte unchanged.

`tests/test_continuous_harness.py::test_same_log_emerges_whether_the_driver_is_fast_or_slow`
proves it: the same match run under a fast fake clock and a slow fake clock
produces identical transition events and the identical final hash, while the
`seat_latency` observations legitimately differ.

## Driver kinds (the all-backends rule)

Every driver kind gets the continuous loop; a model choice is config, not code.

| kind        | how a mind answers                                                        |
| ----------- | ------------------------------------------------------------------------- |
| `bot`       | in-harness greedy continuous policy, reads only the briefing              |
| `bot-file`  | `bots/<name>.py`'s `decide_continuous(briefing, team_id)`, briefing-only  |
| `command`   | subprocess: briefing JSON on stdin, one JSON order on stdout              |
| `command` + `per_seat` | each seat carries its own `argv`/`prompt`                      |
| `resident`  | one long-lived session per seat for the whole match                       |

The `bot-file` lane mirrors the grid's exactly (a committed, readable strategy
that never imports `league` and sees only JSON), but its entry point is
`decide_continuous(briefing, team_id)` — a distinct name from the grid's
`decide(show_json, team_id)`, so a strategy file can never be called with the
wrong contract shape. The reference strategy is
[`bots/crusher.py`](../bots/crusher.py).

## Config and the initial-state seam

`run_cmatch(config)` mirrors the grid harness's config shape (`match` + per-team
`driver` specs), resolving via the continuous lane. The initial
`CMatchState` is taken through a clean seam so this task does not depend on the
continuous scenario module (built in parallel, `t6`):

1. an explicit `initial_state=` (a `CMatchState` or a builder callable), or
2. `config["state_builder"]` (a callable), or
3. an inline `config["match"]["state"]` (a `CMatchState.to_dict()` dict), or
4. a scenario **name** — resolved through
   `league.engine.continuous.scenario.get_cscenario` once it exists.

The `t6` registry wiring is a one-liner at `_try_get_cscenario`; until it lands,
a scenario name without a registry raises a clear `CHarnessError` pointing at the
inline seam.

## Scoring: the two-lane decision

Two engine lanes, both honest (spec c10): the continuous lane does not get a
silently-adapted copy of the grid's scoring formulas — it gets an explicit,
documented decision (spec c11/h11), pinned here rather than left to drift.

**What continuous matches score this cycle: OUTCOME ONLY.** A continuous
match's competitive tally is the grid's own outcome rule, ported —
[`league/engine/continuous/resolve.py`](../league/engine/continuous/resolve.py)'s
`outcome_points`/`CP_POINTS` compute mission rewards (dual awards paid in
full) + 2 points per owned control point + delivered resources, the same
shape [`league/engine/tick.py`](../league/engine/tick.py)'s `outcome_points`
computes for the grid. It is a deliberate, independent port, not a shared
import: the continuous package never imports `league.engine.tick`, and the
grid engine never imports `league.engine.continuous` — each lane earns its
own outcome tally from its own state.

**What stays grid-only: cooperation v1, tempo t0, span probe p0.** None of
the three read-time scoring axes —
[`league/engine/scoring.py`](../league/engine/scoring.py)'s cooperation v1,
[`league/engine/tempo.py`](../league/engine/tempo.py)'s tempo t0, or
[`league/engine/probe.py`](../league/engine/probe.py)'s span probe p0 — run
over continuous logs this cycle. This is enforced, not just documented:
`tests/test_two_lane_honesty.py` AST-checks that none of the three modules
imports `league.engine.continuous`, and that nothing under
`league/engine/continuous/` imports any of the three back.

**Why adaptation is non-trivial, named per axis** (this is the honest part —
each formula leans on a grid assumption continuous time does not hold):

- **Cooperation v1's `message_utility`** correlates a message with a
  subsequent team action inside a window,
  `_referent_realized(index, team_id, turn, window, referent)` computing
  `lo, hi = turn, turn + window` over `CORRELATION_WINDOW = 2` — a window
  measured in discrete, shared *turns* that every unit advances in lockstep.
  Continuous decision points are per-unit and asynchronous by construction
  (a fast role legitimately reaches several decision points while a slow
  role reaches one, per this document's own decision-cadence section) — there
  is no shared "turn" to window over, and it is not obvious what "2" should
  mean once the unit is game-time rather than turn count, especially when
  action durations vary by role and by menu entry.
- **Tempo t0's per-substrate calibration** is documented as "a representative
  *per-turn* latency in milliseconds"
  (`league/engine/tempo.py`'s `DEFAULT_CALIBRATION` comment) and its whole
  point is separating substrate speed from skill by comparing one
  `seat_latency` sample per synchronized grid turn. In continuous play,
  decision *frequency* is itself a role-driven variable — the faster role
  gets more decision points per unit of game time, not as a special rule but
  as this contract's own arithmetic (see "Decision cadence" above) — so a
  straight median-per-decision comparison would conflate "fast substrate"
  with "fast role", the exact confound tempo t0 exists to avoid for the grid.
- **Span probe p0's `guidance_linkage`/`degradation_curve`** reuses
  cooperation v1's referent-matching machinery directly
  (`league/engine/probe.py` imports `CORRELATION_WINDOW`,
  `_build_action_index`, `_utterance_useful` from `league.engine.scoring`)
  and additionally buckets turns by how many seats declared an action
  "CONCURRENTLY that turn" to build its degradation curve. Both legs depend
  on the same shared, turn-indexed notion cooperation v1 does, plus a
  concurrency test ("acted in the same turn") that has no continuous
  analogue until a real definition of "the same moment" exists for
  asynchronous per-unit decision points.

**The pinned decision:** adaptation of cooperation v1 / tempo t0 / span probe
p0 to continuous time is **deferred to a later cycle**. This cycle ships
continuous outcome scoring only; the three read-time axes keep scoring grid
matches exactly as before, untouched and unextended. When a later cycle picks
this up, the honest starting question for each axis is named above — not "why
did the number look different," but "what does a turn-shaped assumption mean
once turns are gone."
