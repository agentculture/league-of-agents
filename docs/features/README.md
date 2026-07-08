# Features

Deep-dive pages for everything the arena offers. Each page is self-contained —
read one without chaining through the others. For the one-screen summary and
quickstart, see the [root README](../../README.md).

## The engine

- [Deterministic engine (grid lane)](deterministic-engine.md) — immutable state,
  an event log as the single source of truth, canonical-order resolution, and the
  CI determinism gate that keeps it all honest.
- [Continuous engine lane (real-time)](continuous-lane.md) — the event-timeline
  sibling engine: fixed-point positions, race semantics, and two-lane honesty.
- [Scenarios & roles](scenarios-and-roles.md) — the boards, and roles as
  engine-enforced capability contracts that force coordination by construction.

## Scoring & inspection

- [Scoring & grades](scoring-and-grades.md) — dual scoring (outcome +
  cooperation), the published tempo axis, the span-of-control probe, and per-unit
  MVP/LVP scorecards.
- [Fog of war & vision](fog-of-war.md) — per-role vision, the knowledge fold, fog
  mode, and orchestrator information levers.
- [Standings & history](standings-and-history.md) — cross-match trends, per team
  and per agent, straight from the record.

## Watching a match

- [Replay & faces](replay-and-faces.md) — the self-contained HTML replay (grid +
  continuous faces), the markdown briefing, a terminal view, offline GIF/MP4
  video, and generative audio.

## Playing the arena

- [Agent-first CLI](agent-first-cli.md) — the contract: dry-run by default,
  `--json` everywhere, a stable error/exit-code interface, and the noun-group
  pattern the arena grows by.
- [Agent-player harness & drivers](harness-and-drivers.md) — field live models
  (one independent mind per seat) or bots; stateless, resident, and orchestrator
  modes.
- [Coded-strategy bots](coded-strategy-bots.md) — the public-surface bot lane and
  its declared bronze/silver/gold difficulty tiers.
- [Play presets](play-presets.md) — one-command launch of every bundled mode.

## The agent itself

- [Identity & mesh](identity-and-mesh.md) — `culture.yaml`, the `colleague`
  backend, the `doctor` invariants, and the vendored skill kit.

## How the game is built

The arena grows on a recursive **spec → plan → implement → live-test** cycle: no
new increment opens without a recorded live match from the previous one. See
[`docs/process/cycle.md`](../process/cycle.md); season-0 artifacts live in
[`docs/specs/`](../specs/), [`docs/plans/`](../plans/), and
[`docs/playtests/`](../playtests/).
