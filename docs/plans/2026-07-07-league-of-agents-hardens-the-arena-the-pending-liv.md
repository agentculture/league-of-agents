# Build Plan — League of Agents hardens the arena: the pending live matches land on the record, cooperation is scored for real, fog is fair for every player, and the release train learns its lessons

slug: `league-of-agents-hardens-the-arena-the-pending-liv` · status: `exported` · from frame: `league-of-agents-hardens-the-arena-the-pending-liv`

> League of Agents hardens the arena: the pending live matches land on the record, cooperation is scored for real, fog is fair for every player, and the release train learns its lessons

## Tasks

### t1 — Cooperation metric v1 (log-derived scoring only)

- covers: c7, h2, c11, h12
- acceptance:
  - Rejected orders penalize delegation_spread, message content utility is scored rather than cadence, and pseudo-coordination (chatter uncorrelated with action) is distinguished — each signal implemented with unit tests pinning its exact weight
  - v1 lives entirely in scoring/log-derived code; tests/fixtures/determinism.hash is byte-identical and no engine tick file changes

### t2 — Season-0 re-score: v0 vs v1 side-by-side report

- depends on: t1
- covers: h3, c4, h10, c5, h11
- acceptance:
  - All committed season-0 logs re-scored; a side-by-side v0/v1 table where every divergence is explained by a named signal change
  - If losers still out-cooperate winners under v1 the report publishes that as a finding — no fitting to outcomes; the report cites the season-0 score JSONs as before-state evidence and quotes issue #1 for the why

### t3 — Fog-aware bot lane

- covers: c8, h4
- acceptance:
  - A fog-aware strategy in bots/ consumes only the fogged public JSON surface with an explore-toward-unknown baseline; a spy test enforces it sees nothing an agent team would not (same AST/import-ban pattern as the engine)
  - The full-information bot remains available for unfogged play; the omniscience asymmetry warning is retired or declared per match

### t4 — Stacked-train release workflow doc

- covers: c9, h5
- acceptance:
  - A docs/process/ document covers single version bump at the train front, the restack procedure after each squash merge, and CHANGELOG collision avoidance — recording this train's real failure modes (duplicate 0.7.1 entries, one restack merge per PR)
  - The document records the confirmed publish-cadence decision (per-merge PyPI publishing stays)

### t5 — File the devague resolve-vagueness-verb gap upstream

- covers: c10, h6, c2
- acceptance:
  - An issue on agentculture/devague describes the missing CLI verb to resolve parked blocking vagueness, links the hand-edit commit as evidence, and proposes the verb contract
  - League-side adoption is recorded as a follow-up, not a blocker on cycle-5 convergence

### t6 — Live tests: cycle-2/3 closure matches through real agent harnesses

- depends on: t1, t3
- covers: c6, h1, c12, h13
- acceptance:
  - Resident-vs-stateless rematch on the same scenario and seed with rejections, latency and token counts published both ways; fogged orchestrator on skirmish-2; the h9 retest; and a bot-vs-agent match with no omniscience caveat — all seats through their real agent harnesses
  - Every report is reconstructible from its committed log alone; matches run only after the user confirms the lobes/vLLM substrate restart

### t7 — Cycle-5 closure ledger: every thread to its artifact

- depends on: t2, t3, t4, t5, t6
- covers: c1, h7, c3, h9, h8
- acceptance:
  - A committed ledger maps each of the five hardening threads to its artifact on main (reports, scoring change + re-score, bot lane, process doc, issue link) and states which audience each serves; no thread is claimed done without an artifact

## Risks

- [unknown_nonblocking] Exact v1 signal weights and the message-utility scoring formula — pinned by t1's tests, not decided in the plan (task t1)
- [unknown_nonblocking] t6 is schedule-gated on the user confirming the lobes/vLLM substrate restart — all other tasks can land before it (task t6)
