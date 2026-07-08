# Scenarios & roles

A **scenario** is the board a match runs on — its grid, objectives, economy, and
roster of roles. Scenarios are read-only and browsable through the `arena` noun
group; the season-0 catalog ships `recon-1`, `skirmish-1`, and `skirmish-2`,
plus a seeded generator (`league/engine/genscenario.py`) that produces fresh
boards.

```bash
league arena list                 # name the scenarios
league arena show skirmish-1      # grid, roles + stats, control points, missions, nodes
league arena show skirmish-1 --json
```

## Coordination is forced by construction

The arena's core question is whether a group of agents can become a *coherent
team under constraint*, so scenarios are built to make solo play lose. Role
stats are deliberately lopsided and the turn limit sits **below the best
possible solo run** — a fact proven by arithmetic in the tests, not asserted.
A team that refuses to divide labour cannot finish in time. This is the design
lever that turns "smart individual agents" into "did they actually cooperate?"

## Roles are enforced capability contracts

A role is not a label an agent chooses to honour — it is a capability contract
the **engine enforces**. Two levers are quantitative (`move`, `carry`,
`vision`) and two are hard booleans (`can_gather`, `can_capture`). If a role
cannot do something, the tick rejects the order and `legal_actions` never offers
it — the enforcement lives in engine data and legality, never in prompt
convention.

| Role | Software-work analog | move | carry | vision | can_gather | can_capture |
|------|----------------------|------|-------|--------|------------|-------------|
| explorer | reconnaissance / code-reading | high | 0 | high | no | no |
| planner | architect / tech-lead | 1 | 0 | baseline | no | no |
| scout | quick reconnaissance pass | fast | light | wide | yes | **no** (cycle 8) |
| harvester | implementer (executor) | slow | high | baseline | yes | yes |
| defender | implementer (executor) | slow | light | baseline | yes | yes |

The exact numbers are per-scenario (`arena show <id> --json` reports them); the
table is the shape, not one fixed board. As of cycle 8 the **scout is
eyes-only** in both engine lanes — it gathers, carries, and delivers but no
longer holds ground, so its value is measured by what it reveals, not by a
capture it happened to stand near. The full rationale, the mechanism in each
lane, and the deliberate determinism-hash regeneration are documented in
[`docs/roles.md`](../roles.md).

## See also

- [Deterministic engine](deterministic-engine.md) — how a scenario is played.
- [Fog of war](fog-of-war.md) — vision is a per-role stat that fog turns into a
  real information constraint.
- [Scoring & grades](scoring-and-grades.md) — per-role purpose grading.
