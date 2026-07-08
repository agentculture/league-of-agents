# Scoring & grades

A match is graded on **more than who won**. Every axis below is computed from the
match log alone (never from live engine state), so scores can never disagree with
the record. All of them surface through `league match score` and
`league match probe`, in both text and `--json`.

```bash
league match score <id> --json          # outcome + cooperation + tempo + units
league match score <id> --substrate blue=cloud   # substrate-fair tempo
league match probe <id> --json          # span-of-control
```

## Dual scoring: outcome + cooperation

- **Mission outcome** — did the team achieve the objective the scenario set.
- **Cooperation quality (v1)** — a heuristic over delegation, communication,
  plan coherence, and discipline, read from the `plan_declared` /
  `message_sent` / action events in the log. This is the axis that answers the
  arena's real question: *was this a coordinated team, or lucky individuals?*

## Tempo axis (published, with its limits)

Tempo is per-team speed, converted against a **per-substrate calibration
baseline** with raw latency always shown beside the converted number. Because
comparing a cloud model to a local one is only fair with a stated baseline, the
calibration table, the `t0` conversion formula, and its own published limits are
documented in [`docs/tempo-methodology.md`](../tempo-methodology.md) — read that
before trusting a converted number across two declared substrates.

## Span-of-control probe

`match probe` measures how well a team's mind actually *commanded* its seats,
from the log alone:

- **span** — how many subagents a team really fielded (a real recorded per-seat
  call, or a real declared action tied to that seat's own voice; merely *naming*
  a subagent in a message counts for nothing).
- **realization_rate** — per seat, how well its declared orders landed
  (`1 - rejected/declared`).
- **guidance_linkage** — whether a commanding message actually steered behaviour
  (a message counts only if a later team action realizes something it named).

`seat_latency` evidence, when present, is authoritative over message content, and
a per-turn `degradation_curve` shows whether a mind "commands 3 seats well, 1
badly" — all visible from a single match.

## Per-unit role-purpose scorecards (MVP / LVP)

`score` also carries a **`units`** section: a per-unit, role-purpose-weighted
scorecard (`league.engine.grades.grade_units` for grid,
`league.engine.continuous.grades.cgrade_units` for continuous, chosen by the same
lane detection `replay` uses). Every seat is graded per purpose (grid:
economy / control / recon / coordination; continuous: race_hold / economy / eyes),
on-purpose work scores full credit and off-purpose work still scores — just at a
discount ("a scout not scouting should still get points, but less"). The match
**MVP** and **LVP** are named with a canonical tie-break.

This is a *new axis beside* outcome/cooperation/tempo — grading a match never
changes its team-axis numbers, and there is deliberately **no ranking, ELO, or
cross-match aggregation** anywhere in the CLI: MVP/LVP is named per match only.

## See also

- [Standings & history](standings-and-history.md) — cross-match trends (the one
  place aggregation lives, and only over recorded results).
- [Deterministic engine](deterministic-engine.md) — why log-only scoring is
  trustworthy.
