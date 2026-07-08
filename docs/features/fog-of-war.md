# Fog of war & vision

Every role has a `vision` radius, and **fog mode** turns that stat into a real
information constraint: an agent under fog sees only what its team has actually
witnessed or been told, never the full board. Crucially, fog is a **projection
computed in the harness/CLI, never a mutation of engine state** — the engine
still folds one true, complete match; fog only narrows what a given team is
*shown*.

## The knowledge fold

`league/engine/vision.py` computes what each unit can see; `league/engine/
knowledge.py` accumulates a team's fold of seen-and-told facts across turns. A
team's fogged view is its own roster in full, plus every other unit, control
point, resource node, and discovered mission it has actually seen or been told
about — and nothing else (no enemy scores, no unseen board).

```bash
league match show <id> --team blue --fog --json   # state replaced by blue's fold; adds a `knowledge` key
league match brief <id> --team blue               # the markdown briefing, fogged to blue
league match tui <id> --team blue --frame 3       # terminal view, fogged
```

The plain (no `--team`/`--fog`) responses are untouched — fog is purely
additive.

## Fog in a live match

A harness config with `"fog": true` narrows every `command`/`resident`
briefing to that team's vision-plus-knowledge fold. The harness calls
`match show --team <id> --fog --json` per team, per turn, and folds the result
into each seat's briefing.

**Documented asymmetry:** the in-harness greedy `bot` (and any `bot-file`
strategy that does not opt in) currently stays full-information under fog. A
*fair* fogged match keeps fog on for every driver or none — which is why the
fog-aware [`lampbearer` bot](coded-strategy-bots.md) exists, written against the
fogged surface so a fogged bot-vs-agent match has an opponent that plays the same
information game instead of cheating past the fog.

## Orchestrator information levers

Orchestrator mode declares two fairness axes that ride in the match log header
(never in engine state):

- **`--map-read <team>:full|fog`** — whether a team's master/commander reads the
  whole board (`full`, a declared information-asymmetry rule of the mode) or the
  same fogged view as everyone (`fog`, the default).
- **`--unit-comms <team>:on|off`** — whether that team's ground units may message
  each other directly, or are master-mediated only (`off`, orchestrator mode's
  default).

## See also

- [Scenarios & roles](scenarios-and-roles.md) — `vision` as a per-role stat.
- [Harness & drivers](harness-and-drivers.md) — orchestrator mode and residency.
- [Coded-strategy bots](coded-strategy-bots.md) — the fog-fair `lampbearer`.
