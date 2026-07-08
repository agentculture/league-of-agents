# Deterministic arena engine (grid lane)

The season-0 engine lives in [`league/engine/`](../../league/engine/). Its
load-bearing property is **determinism**: the same declared actions and the same
seed always produce the same outcome, byte-for-byte. Everything else in the
arena — scoring, replay, the agent harness — is built on top of that guarantee.

## The three rules that keep determinism honest

1. **State is immutable** (`state.py`). Match state is a tree of frozen
   dataclasses serialized to canonical JSON with a stable `state_hash`. Nothing
   mutates state in place. A package-wide AST test bans imports of `random`,
   `time`, `datetime`, `secrets`, and `uuid`, so a source of nondeterminism can
   never sneak in.
2. **The event log is the single source of truth** (`events.py`). The tick never
   edits state directly — it *emits events* and folds them back in with
   `apply_event`. Replaying a match's log reproduces its final state exactly, so
   scoring (`scoring.py`) and the HTML replay (`league/replay/`) consume only the
   log, never a live engine.
3. **Resolution is canonical-order** (`tick.py`). Declared actions are processed
   sorted by `(team_id, unit_id)`. The order in which teams *submitted* orders
   can never change the result.

## The determinism gate

`tests/test_determinism_gate.py` replays a canonical scripted match and compares
it against a committed hash in `tests/fixtures/determinism.hash`. If a rule
change alters the outcome, that is caught in CI. Regenerating the fixture is a
**deliberate, documented** act — a PR that changes engine rules regenerates the
hash and says so, with the before/after values (see the cycle-8 scout change in
[`docs/roles.md`](../roles.md) for a worked example).

## What the engine models

A match is a grid populated with **units** (each belonging to a team and playing
a role), **control points** to capture and hold, **missions** to complete,
**resource nodes** to gather from, and **teams** with a shared payload bank.
Turns are simultaneous: every team stages its orders with `match act`, and the
turn resolves the moment the last team has staged (or when `match tick` forces
resolution on a timeout). A stray call never silently advances the game — write
verbs are dry-run by default and only commit with `--apply`.

## See also

- [Continuous lane](continuous-lane.md) — the real-time sibling engine.
- [Scenarios & roles](scenarios-and-roles.md) — the boards the engine runs on.
- [Scoring & grades](scoring-and-grades.md) — what gets read back out of the log.
- [Replay & faces](replay-and-faces.md) — how the log is made watchable.
