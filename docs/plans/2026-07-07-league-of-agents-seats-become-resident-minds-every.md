# Build Plan — League of Agents seats become resident minds: every agent keeps one continuous context for the whole match — cultureagent anchors Claude and Colleague seats alike — orders are legal by construction, and no mission is ever decided by the alphabet

slug: `league-of-agents-seats-become-resident-minds-every` · status: `exported` · from frame: `league-of-agents-seats-become-resident-minds-every`

> League of Agents seats become resident minds: every agent keeps one continuous context for the whole match — cultureagent anchors Claude and Colleague seats alike — orders are legal by construction, and no mission is ever decided by the alphabet

## Tasks

### t1 — Engine+CLI: legal-actions surface — a pure helper computes each unit's legal actions (move targets in range, gather/deliver/hold applicability) and 'match show --json' exposes it per unit; explain catalog updated

- covers: c8, h4
- acceptance:
  - match show --json contains legal_actions for every living unit, derived from state+scenario only (deterministic, AST-clean)
  - A test asserts a rejected-yesterday order (beyond-range move) is absent from legal_actions

### t2 — Harness: rejection feedback — every seat/commander briefing includes that agent's own prior-turn rejections with the engine's reason text (stateless AND resident paths)

- depends on: t1
- covers: c8, h5
- acceptance:
  - A harness test stages an illegal order and asserts the same seat's next prompt contains the rejection reason verbatim
  - Briefings cite the legal_actions surface so legality is checkable before declaring

### t3 — Spike cultureagent's resident-session surface: one persistent session per seat for BOTH a claude-backed and a colleague-backed mind; send two sequential messages into the same session and prove the second reply remembers the first; record the working invocation + chosen transport in a committed spike note (unparks v1)

- covers: c7
- acceptance:
  - A committed spike note shows one session per backend answering a turn-2 question that requires remembering turn 1
  - The note names the transport the resident driver will use, with the actual commands/config that worked

### t4 — Engine: dual-award dead-heat rule — simultaneous completion of one mission awards BOTH teams the full reward (user decision c15); regenerate the determinism fixture deliberately in the same PR

- covers: c9, h6
- acceptance:
  - A regression test reproduces the orchestrator t16 double-delivery shape and both teams score the mission
  - A team-id-swap invariance test proves outcomes are identical under renamed team ids
  - tests/fixtures/determinism.hash regenerated once, called out in the PR body

### t5 — Harness: resident driver type — one long-lived cultureagent session per seat for the whole match; turn 1 sends the full briefing, turn N>1 sends only the delta (new events, current state, teammate messages); same one-JSON-action reply contract; per-seat session transcript recorded for audit

- depends on: t3, t2
- covers: c6, h1
- acceptance:
  - A harness test proves the same session id serves every turn of a match and turn N>1 input contains no rules re-teach
  - bot/command drivers still work unchanged (rematch baselines stay possible)

### t6 — Store+log: residency is a declared fairness axis — each team's driver kind (resident vs stateless) is recorded in the match config echo and the match log, readable via match show/standings

- covers: c10, h7
- acceptance:
  - The match log header records driver kind per team; match show --json surfaces it
  - A test asserts a resident-vs-stateless match is labeled as such in both projections

### t7 — Playtest: the resident match — a recorded live match where at least one Claude seat AND one Colleague seat play as cultureagent-anchored resident minds, with delta briefings, legal-actions surface, and rejection feedback all active; log + replay + score committed

- depends on: t2, t4, t5, t6
- covers: c4, h11, c7, h3
- acceptance:
  - The committed log shows resident routing in the roster labels and residency recorded per team
  - The t14 orchestrator config still plays green (audience regression)

### t8 — Playtest: the stateless baseline rematch — same scenario+seed (t10 rule) with fresh-invocation drivers, then the comparison report: rejection rates, per-turn input tokens/latency, dual scores; numbers published whichever way they point

- depends on: t7
- covers: c14, h14, h2, c5, h12
- acceptance:
  - Both logs+replays committed; the report tables resident vs stateless on the same seed
  - If resident shows no measurable gain the report says so plainly (the rationale survives its own test)

### t9 — Human review of the resident replay (the h15 pattern): the reviewer reconstructs WHY from the replay alone; findings recorded in the report and fed to the next frame

- depends on: t7
- covers: c2, h9
- acceptance:
  - The report contains a human-review section with the reviewer's reconstruction and any legibility findings

### t10 — Docs + propagation: before-state cites the committed season-0 reports; a boundary audit confirms no cross-match persistence, no side channels, no cultureagent patches; announcement-to-artifact traceability table; seed the next frame from findings (the cycle continues)

- depends on: t8, t9
- covers: c1, h8, c3, h10, c13, h13
- acceptance:
  - The spec's announcement phrases each map to a committed artifact in a traceability table
  - Boundary audit checklist committed with the review
  - Next-frame candidates recorded from the resident playtest findings

## Risks

- [unknown_nonblocking] cultureagent may not expose a clean headless per-seat session surface; the spike may force fallback wiring (e.g. SDK sessions without the mesh) — the frame's one-session-per-seat requirement still binds (task t3)
- [unknown_nonblocking] Resident colleague seats share one vLLM server — parallel sessions may contend for GPU; turn timeouts need tuning against real latencies (task t7)
- [unknown_nonblocking] Prompt-cache economics differ per provider (Anthropic TTL vs vLLM prefix cache); the measured gain may be asymmetric across teams — report per-team, don't average it away (task t8)
