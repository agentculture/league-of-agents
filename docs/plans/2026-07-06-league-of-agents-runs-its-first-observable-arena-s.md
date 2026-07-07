# Build Plan — League of Agents runs its first observable arena season: deterministic matches where AI agent teams coordinate on missions, scored on both outcome and cooperation quality, replayable and beautiful for humans, benchmarked per agent and over time — grown through a self-propagating spec-plan-implement cycle

slug: `league-of-agents-runs-its-first-observable-arena-s` · status: `exported` · from frame: `league-of-agents-runs-its-first-observable-arena-s`

> League of Agents runs its first observable arena season: deterministic matches where AI agent teams coordinate on missions, scored on both outcome and cooperation quality, replayable and beautiful for humans, benchmarked per agent and over time — grown through a self-propagating spec-plan-implement cycle.

## Tasks

### t1 — Engine state core: immutable match state model (grid, teams, units, control points, missions, resources) with injected-seed randomness only

- covers: c9
- acceptance:
  - Match state serializes to JSON and loads back byte-identical (round-trip test)
  - The engine package imports no wall-clock time and no global random; a test enforces the import ban

### t2 — Match event log: append-only record of every turn; folding events over initial state reproduces final state

- depends on: t1
- covers: c11
- acceptance:
  - Every state transition is expressible as an event; replaying the event log from the initial state reproduces the final state exactly (test)
  - The log is the single source of truth: scoring and replay consume only this artifact

### t3 — v0 grid scenario skirmish-1: control points, missions, resource economy, with cooperative and competitive variants from one definition

- depends on: t1
- covers: c16, c18, h11
- acceptance:
  - Scenario loads by id with at least 3 control points, 2 missions, and resource nodes, for two-team or team-vs-environment play
  - Scenario parameters force tradeoffs: turn limit and distances make it impossible for one unit to hold all control points and complete missions alone (asserted in tests)
  - Cooperative and competitive variants share the same definition and engine path (no forked scenario code)

### t4 — Deterministic tick engine: pure resolution function (state, declared actions, seed) to (new state, events)

- depends on: t1, t2, t3
- covers: c9, c18, h11
- acceptance:
  - Same inputs yield identical outputs across repeated runs (property test)
  - Simultaneous declared actions resolve by documented deterministic rules with no dependence on submission order

### t5 — CLI noun groups: league arena / team / match verbs honoring the agent-first contract

- depends on: t4
- covers: c17, h10, c12
- acceptance:
  - Every write verb defaults to dry-run and mutates only with --apply (tests per verb)
  - Every read verb supports --json; every new path has an explain catalog entry; noun groups with action verbs expose overview
  - uv run teken cli doctor . --strict stays green with all new verbs registered

### t6 — Determinism CI gate: recorded action log + seed replays to an identical end-state hash on every PR

- depends on: t4
- covers: h2
- acceptance:
  - A CI-run test replays a committed action log + seed and fails on any end-state hash mismatch

### t7 — Dual scoring from the match log: mission outcome score + cooperation-quality heuristic

- depends on: t2
- covers: c10, h3, c5
- acceptance:
  - Scoring computes both an outcome score and a cooperation score from a finished match log alone (test feeds a canned log; no live state, no external calls)
  - Each cooperation signal (communication/delegation events, plan-vs-action coherence, redundant-effort waste) is documented with its weight

### t8 — Self-contained HTML replay viewer rendered from the match log (league match replay --html)

- depends on: t2
- covers: c12, h5, c11, h4
- acceptance:
  - Emits a single self-contained HTML file (no external requests) that plays the match turn by turn with map, units, control points, scores, and per-team communication
  - HTML replay and --json projections render from the same log; a test asserts they agree on every turn's facts

### t9 — Tracking store + standings/history read verbs for per-agent and per-team trends

- depends on: t5, t7
- covers: c13, h6, c3
- acceptance:
  - Finished matches persist to a queryable per-repo store; league standings --json and league history --json compute per-agent and per-team trends (test with at least two stored matches)

### t10 — Fair rematch: identical scenario + seed with a different roster for apples-to-apples comparison

- depends on: t4, t5
- covers: c14, h7
- acceptance:
  - A rematch verb replays the identical scenario + seed with a swapped roster; a test proves two rosters differing only in model/composition face identical initial conditions and resolution rules

### t11 — Agent-player harness: colleague + Sonnet subagent teams drive full matches through the CLI

- depends on: t5
- covers: c2, h13
- acceptance:
  - A harness runs a full match where every team member is a live agent (colleague backend or Sonnet subagent) acting only through league match show --json and league match act --json --apply
  - The harness is model-agnostic: fielding an orchestrator (Fable/Opus) or Claude as a player is a roster-config change, not a code change

### t12 — Playtest 1 (season opener): full scored colleague + Sonnet match with recorded artifacts and a human replay review

- depends on: t6, t8, t9, t11
- covers: c1, h12, c3, h14, c7, h17, h18, h15, c5
- acceptance:
  - Match log, HTML replay, and both scores are recorded in-repo or reproducibly generated; determinism verified by re-running the recorded log + seed
  - A human reviews the replay and states why the winner won, from the replay alone; the playtest report checks off legibility, recorded-playtest, and one-match-demonstrates-all-three

### t13 — Playtest 2 (coordination necessity): a solo strong agent measurably loses to a coordinated weaker team

- depends on: t11
- covers: c16, h9
- acceptance:
  - A shipped scenario where a solo stronger-model agent plays against a coordinated team of weaker-model agents and measurably loses; result, replay, and analysis recorded in a playtest report

### t14 — Playtest 3 (orchestrator mode): Fable or Opus fields a spawned-subagent team in a real scored match

- depends on: t11
- covers: c15, h8
- acceptance:
  - An orchestrator agent registers a team, spawns its own subagents as roster members, and plays a scored match end to end; artifacts recorded like every playtest

### t15 — Document the operable development cycle in docs/process/cycle.md (frame to plan to PR to playtest to next frame)

- covers: c8, h1, c4, c6, h16
- acceptance:
  - The document names the concrete mechanism with real repo paths and verbs: devague frame in .devague/, plan via spec-to-plan, PR via cicd, playtest report location, and how findings seed the next frame
  - It restates the boundary: details parked in the season-0 frame stay parked until their own cycle picks them up
  - The documented cycle mandates a live test between specs: a recorded live match (playtest) from the current increment must exist before the next devague frame opens

### t16 — Propagate: seed the next spec cycle (new devague frame) from the season-0 playtest findings

- depends on: t12, t13, t14
- covers: c8, h1, c1, h12, c3, h14
- acceptance:
  - A new devague frame exists, derived from recorded playtest findings, and the playtest report links to it (specs beget specs, demonstrated not asserted)

## Risks

- [follow_up] The v0 cooperation heuristic may be a weak or noisy signal; refinement is already parked as its own follow-up cycle (task t7)
- [unknown_nonblocking] Playtest cost and latency of live agent teams (colleague availability, Sonnet spend) could throttle iteration speed (task t11)
- [unknown_nonblocking] The coordination-necessity scenario will likely need tuning iterations before a solo strong agent reliably loses (task t13)
- [follow_up] Orchestrator-mode fairness/budget rules are undefined (parked v3 in the frame); the demo playtest may surface constraints early (task t14)
