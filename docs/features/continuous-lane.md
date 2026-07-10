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

## Driving it externally: `league cmatch` (issue #28)

`league.charness.run_cmatch` is an in-process, one-shot library call — it owns
the whole match and drives every seat synchronously in one Python process. The
`cmatch` noun group (`league/cli/_commands/cmatch.py`) is the external-driver
CLI parity for that: `cmatch new`/`show`/`act`/`tick` let a subprocess-only
harness — no `import league` required — create a continuous match, ask "what
is due right now" (every idle unit's full briefing), submit ONE unit's
decision at a time, and let bot-driven due units auto-resolve, exactly the way
`league match new/show/act/tick` already does for the grid lane. `cmatch run`
is the packaged one-shot (what `scripts/run_cmatch.py` used to be the only way
to reach; it is now a thin, deprecated wrapper). State is always a pure fold
of the log, so suspending an external harness between any two `cmatch` calls
and resuming from the same working directory continues correctly.

The load-bearing engine primitive underneath is
[`league.engine.continuous.resolve.advance_external`](../../league/engine/continuous/resolve.py):
it REPLAYS a match's own already-recorded decisions through the exact same
resolver `resolve_match` uses, then hands the first genuinely new decision
point to the caller — which is what makes stepwise, one-decision-per-CLI-call
driving produce a log byte-identical to an equivalent single `run_cmatch` call
given the same decisions in the same (canonical) order. See
[`league explain cmatch`](../../league/explain/catalog.py) for the full verb
reference and `tests/test_continuous_resolve.py`/`tests/test_cli_cmatch.py`
for the parity proofs. Scope this cycle: fog (`config["fog"]`) is supported by
`cmatch run` (a straight pass-through to `run_cmatch`) but not yet by the
stepwise `new`/`show`/`act`/`tick` loop.

## See also

- [Deterministic engine](deterministic-engine.md) — the turn-based grid lane.
- [Replay & faces](replay-and-faces.md) — the continuous replay face
  (`chtml.py`) makes the race visible.
- [Harness & drivers](harness-and-drivers.md) — how live minds are fielded.
