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
    "unit_id": "blue-scout", "agent_id": "blue-scout", "team_id": "blue",
    "role": "scout", "pos": {"x": 3000, "y": 3000}, "carrying": 0,
    "action": null
  },
  "menu": [
    {"kind": "take_post", "target": "cp", "target_id": "cp",
     "duration": 5, "completion_time": 12},
    {"kind": "move", "target": "n1", "target_ref": "n1",
     "target_pos": {"x": 9000, "y": 9000}, "duration": 8, "completion_time": 15}
  ],
  "outlook": [
    {"unit_id": "red-def", "team_id": "red", "completion_time": 13}
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
  t=13; my scout can finish first at t=12."*
- **`board`** — a full-information (fogless) projection of the whole state:
  teams, units, control points (with their concurrent `takers`), missions, and
  resource nodes. Continuous fog is a later cycle's concern; this contract is
  fogless by construction.
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
