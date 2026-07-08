# Continuous engine lane (real-time)

Alongside the turn-based grid engine, the arena carries a second, real-time
engine in [`league/engine/continuous/`](../../league/engine/continuous/). Where
the grid resolves simultaneous turns, the continuous lane resolves an
**event timeline**: units act when they become idle, actions take real in-game
duration, and initiative is decided by who finishes first.

## What makes it deterministic without floats

- **Fixed-point positions.** Coordinates are integer milliunits (`SCALE = 1000`)
  with an integer `isqrt` for distances — no floating-point drift, so positions
  are reproducible across machines.
- **Event-timeline initiative.** Game time is an integer clock; concurrent
  events break ties by the canonical `(time, team_id, unit_id)` ordering.
- **Explicit race semantics.** When two units reach for the same control point,
  the faster one wins and the loser's mid-take attempt fails **first-class** with
  the reason `"post taken by a faster agent"` — a race is a modeled outcome, not
  an accident of ordering.
- **Role-given speed.** `CRoleStats` gives each role its own in-game movement and
  action speed, and a shared legality/duration oracle answers "what can this unit
  do, and how long does it take?" for both the engine and the mind-facing menu.

## Two-lane honesty

The two engines are kept provably independent (spec c11/h11):

- The AST import ban that guards the grid engine provably covers the continuous
  package too.
- The grid scoring axes and the continuous lane **cannot import each other** — a
  test enforces the wall.
- Each lane has its own scripted determinism gate with its own committed hash,
  fenced byte-exact.
- Lane detection reads from each log's own header, so `match score` and
  `match replay` pick the right engine automatically.

Continuous scoring is **outcome-only** for now, a documented decision recorded in
[`docs/continuous-contract.md`](../continuous-contract.md).

## The mind-facing contract (`charness.py`)

Live agents drive the continuous lane through
[`league/charness.py`](../../league/charness.py): decision points fire on
unit-idle, briefings carry the menu of actions *with their durations*, absolute
completion times, and an initiative outlook. A key invariant is
**substrate-independence** — an agent's thinking time never advances game time,
so a slow model and a fast model face the same clock.

## See also

- [Deterministic engine](deterministic-engine.md) — the turn-based grid lane.
- [Replay & faces](replay-and-faces.md) — the continuous replay face
  (`chtml.py`) makes the race visible.
- [Harness & drivers](harness-and-drivers.md) — how live minds are fielded.
