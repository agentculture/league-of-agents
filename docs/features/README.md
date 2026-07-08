# Features — deep dives

The canonical overview lives in the [root README](../../README.md) — it carries
the full feature list with a paragraph each, and it's what ships on PyPI. This
directory holds the **per-feature deep-dive pages** the README links to; each is
self-contained (read one without chaining through the others).

## Index

- [Deterministic engine (grid lane)](deterministic-engine.md)
- [Continuous engine lane (real-time)](continuous-lane.md)
- [Scenarios & roles](scenarios-and-roles.md)
- [Scoring & grades](scoring-and-grades.md)
- [Fog of war & vision](fog-of-war.md)
- [Standings & history](standings-and-history.md)
- [Replay & faces](replay-and-faces.md)
- [Agent-first CLI](agent-first-cli.md)
- [Agent-player harness & drivers](harness-and-drivers.md)
- [Coded-strategy bots](coded-strategy-bots.md)
- [Play presets](play-presets.md)
- [Identity & mesh](identity-and-mesh.md)

## How the game is built

The arena grows on a recursive **spec → plan → implement → live-test** cycle: no
new increment opens without a recorded live match from the previous one. See
[`docs/process/cycle.md`](../process/cycle.md); season-0 artifacts live in
[`docs/specs/`](../specs/), [`docs/plans/`](../plans/), and
[`docs/playtests/`](../playtests/).
