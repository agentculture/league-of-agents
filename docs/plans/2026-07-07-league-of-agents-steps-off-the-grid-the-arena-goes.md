# Build Plan — League of Agents steps off the grid: the arena goes continuous — decimal positions, role-given speed, and time itself as the resolver, where actions take duration, a faster agent acts again sooner, and a post can be snatched mid-capture by whoever finishes first

slug: `league-of-agents-steps-off-the-grid-the-arena-goes` · status: `exported` · from frame: `league-of-agents-steps-off-the-grid-the-arena-goes`

> League of Agents steps off the grid: the arena goes continuous — decimal positions, role-given speed, and time itself as the resolver, where actions take duration, a faster agent acts again sooner, and a post can be snatched mid-capture by whoever finishes first

## Tasks

### t1 — Fixed-point spatial core

- covers: c6, h6
- acceptance:
  - A continuous-space module (league/engine/continuous/) represents positions as integer-scaled fixed-point values with vectors, distance, movement-toward-at-speed, and arrival tolerance — the representation and scale pinned here (frame v2), documented in the module docstring
  - A test scans every continuous-state value for binary float types and fails on any; canonical JSON round-trips positions exactly; the same operations produce identical results across platforms (pure integer arithmetic)

### t2 — Deterministic initiative timeline

- covers: c8, h8
- acceptance:
  - A timeline scheduler orders the world by action completion times: actions carry in-game durations, the next decision point goes to the earliest completion, and a faster agent demonstrably gets more decision points per unit of game time (unit test with two speeds)
  - Simultaneous completions break ties by canonical order (time, team_id, unit_id); a test proves submission order can never change resolution; the event-queue-vs-micro-tick decision (frame v3) is pinned here with rationale in the docstring

### t3 — Continuous match state and event vocabulary

- depends on: t1
- covers: c6, c8
- acceptance:
  - Frozen dataclasses for the continuous lane's MatchState with a stable state hash; new event kinds (at minimum: action_started, action_completed, action_failed, decision_point) fold deterministically — replaying a log reproduces the identical final state and hash
  - No float, wall-clock, or randomness imports anywhere in the continuous package — the engine AST ban extended to it by test

### t4 — Role speed and action-duration data

- depends on: t3
- covers: c7
- acceptance:
  - Continuous role stats carry in-game speed (movement rate) and per-action durations (gather, take-post, deliver) as pure role DATA; the coding-reflective roles (explorer fast/planner slow) get continuous stats consistent with their grid capability contracts
  - Role data is scenario-declared and hash-covered — two scenarios can field different speed tables without code changes

### t5 — The continuous resolver with race semantics

- depends on: t2, t4
- covers: c9, h9, c8
- acceptance:
  - Taking a post and gathering take in-game duration; the scripted race test passes: a slower agent starts taking a post FIRST, a faster agent starts LATER and completes first — the post goes to the faster agent and the slower agent's attempt fails with a first-class action_failed event in the log
  - Interruption and contest rules are explicit engine rules with tests (what happens when a taker is displaced, when two attempts overlap, when a post changes owner mid-attempt); everything the legality surface offers resolves without rejection (the legal<->resolver agreement pattern, continuous edition)

### t6 — Continuous scenario + its own determinism gate

- depends on: t5
- covers: c10, h3
- acceptance:
  - A hand-authored continuous scenario ships with a canonical scripted match; its final-state hash is committed as a fixture and a CI gate test replays the script and compares — the continuous lane earns determinism the same way the grid did
  - The scenario registry serves both lanes without ambiguity (a continuous scenario is distinguishable by data, not by special-casing)

### t7 — Mind-facing contract: decision points, briefings, harness loop

- depends on: t5
- covers: c7, h7, c2
- acceptance:
  - The decision cadence (frame v1 — the hardest question) is pinned: minds receive a decision point when their unit becomes idle (action completed/failed/interrupted), the briefing exposes the game clock, the unit's action menu WITH durations, and the visible initiative outlook (who is due next), so time budgets are plannable
  - The substrate-independence test passes: the same continuous match log emerges whether a seat's driver answers in 1ms or 60s — game time comes only from role data and the timeline (h7); all driver kinds (bot, bot-file, command, per-seat, resident) get the continuous loop per the all-backends rule

### t8 — Two-lane honesty: compat + AST ban + boundary review

- depends on: t6
- covers: c10, h10, c11, h11
- acceptance:
  - In the PR that lands the continuous lane: the full committed-log compat sweep is green, the grid determinism hash is untouched, and the extended AST ban covers the continuous package (no wall-clock/random/float-producing imports)
  - Scoring for continuous matches is an explicit documented decision, not silent drift: cooperation v1 / tempo t0 / probe p0 remain grid-only; the continuous lane ships outcome scoring plus a documented adaptation decision (even if that decision is 'deferred to the next cycle')

### t9 — Continuous replay face: the race made visible

- depends on: t6
- covers: c12, c2
- acceptance:
  - A replay face for continuous logs renders the timeline and the board (fixed-point positions interpolated) well enough that the race — faster agent snatching the post mid-capture — is VISIBLE: the failed attempt and the successful take are both distinguishable moments; grid renderers stay untouched for grid logs (frame v4 pinned: minimal-but-real this cycle, full mesmerizing/video generalization is follow-up)
  - The face is byte-deterministic from the log and self-contained, matching the repo's replay conventions

### t10 — The recorded race match + cycle report

- depends on: t7, t8, t9
- covers: c12, h12, c1, h1, c3, h3, c4, h4, c5, h5, c2, h2
- acceptance:
  - A recorded continuous-arena match is committed (log + replay + report) in which the race actually happened — cited to the exact events; the report quotes issue #1 for the why, cites the before-state code (tick.py's uniform turn, streak capture, t0's wall-clock-only speed), and states which audience each artifact serves
  - Every announcement phrase maps to its committed artifact in the report's closing ledger — no thread ships silently

## Risks

- [unknown_nonblocking] Decision cadence for minds in continuous time (frame v1) — pinned by t7's mind-facing contract before any harness work (task t7)
- [unknown_nonblocking] Fixed-point representation, scale, and movement model (frame v2) — pinned by t1 (task t1)
- [unknown_nonblocking] Event queue vs micro-tick (frame v3) — pinned by t2 with rationale (task t2)
- [unknown_nonblocking] Replay/video/vision generalization to continuous space (frame v4) — t9 ships the minimal honest face; the mesmerizing/video/fog generalization is follow-up work for a later cycle (task t9)
