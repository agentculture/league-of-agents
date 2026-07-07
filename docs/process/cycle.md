# The development cycle — specs beget specs

League of Agents grows through a **recursive spec → plan → implement →
live-test cycle** (spec requirement c8/h1). This document names the concrete,
operable mechanism — real repo paths and verbs, not aspiration. Season 0's
artifacts are the worked example.

## The loop

```text
   ┌────────────────────────────────────────────────────────────┐
   │  1. SPEC        /think (devague)      .devague/frames/     │
   │  2. PLAN        /spec-to-plan         .devague/plans/      │
   │  3. IMPLEMENT   waves via PRs         league/, tests/      │
   │  4. LIVE TEST   playtests             docs/playtests/      │
   └──── findings seed the next frame ── back to 1 ─────────────┘
```

1. **Spec** — every increment starts as a devague frame:
   `bash .claude/skills/think/scripts/think.sh new "<announcement>"`. Claims are
   captured, pressure-tested with honesty conditions, and **the user confirms
   every proposal** (LLM proposals never self-confirm). Once `converge` passes,
   `export` writes `docs/specs/<date>-<slug>.md`; the frame state in
   `.devague/frames/` is committed as the evidence trail.
2. **Plan** — `devague plan new --frame <slug>` (via
   `.claude/skills/spec-to-plan/scripts/spec-to-plan.sh`) derives coverage
   targets from the confirmed claims. Tasks carry TDD acceptance criteria and an
   honest dependency graph; `devague plan waves` emits the file-disjoint
   execution waves. Converged plans export to `docs/plans/`.
3. **Implement** — waves land as PRs (branch → version bump → `cicd` skill →
   review → merge), each task gated by its acceptance criteria as tests.
4. **Live test** — the increment is exercised by **real agent players**
   (colleague backend, Sonnet subagents, or an orchestrator fielding spawned
   subagents). Playtest reports — match log, replay, both scores, and what the
   match taught us — live under `docs/playtests/`.

## The live-test-between-specs rule

**No new frame opens without a recorded live match from the previous
increment.** A spec cycle earns its successor only by contact with reality: the
playtest report for increment *N* is a prerequisite artifact for the frame of
increment *N+1*, and the new frame links back to the report that seeded it.
This is what makes "specs beget specs" honest — findings, not vibes, propagate.

## What stays parked stays parked

The season-0 frame deliberately parked several unknowns (cooperation-metric
formula, benchmark methodology, orchestrator-mode fairness rules, map/content
pipeline, live spectator UI — see the frame's open/follow-up section). A parked
item is picked up by **its own future cycle**, with its own frame and plan. No
implementation PR resolves a parked unknown as a side effect; if work needs an
answer, the unknown graduates to a frame first. This keeps issue #1's
deliberately-omitted details (engine design, map format, protocol, agent API,
UI) decided by evidence, in order, on purpose.

## Season 0 (the worked example)

- Spec: `docs/specs/2026-07-06-league-of-agents-runs-its-first-observable-arena-s.md`
- Plan: `docs/plans/2026-07-06-league-of-agents-runs-its-first-observable-arena-s.md`
  — 16 tasks, 7 waves, ending in three playtests (season opener,
  coordination-necessity, orchestrator subagent mode) and t16: *propagate the
  next frame from the findings*.
- Baseline before this cycle: the agent-first CLI scaffold
  (`whoami`/`learn`/`explain`/`doctor`) with zero arena domain — the state
  issue #2 provisioned and issue #1 constrained.
