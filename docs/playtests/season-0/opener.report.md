# Playtest 1 — season opener (t12, spec h17/h18)

- **Match:** `m-season0-opener` · skirmish-1 · competitive · seed 20260707
- **Teams:** *Sonnet Foundry* (3 independent claude-sonnet-5 per-seat minds via
  `claude -p`) vs *Qwen Relay* (3 independent Qwen3.6-27B per-seat minds)
- **Driver caveat (recorded before the match ended):** the Qwen seats were
  driven **raw over the vLLM endpoint** (`scripts/openai_driver.py`) — the
  `colleague/qwen3.6-27b` roster label overstates the routing. Per the
  season-0 review directive, local models are fielded as agents from here on;
  the fair rematch config
  ([`opener-colleague.config.json`](opener-colleague.config.json)) re-runs
  this exact scenario+seed with honestly-labeled routing.
- **Result:** **Sonnet Foundry (blue) wins 23–10** at the turn-30 limit
- **Artifacts:** [`opener.log.jsonl`](opener.log.jsonl) ·
  [`opener.replay.html`](opener.replay.html) ·
  [`opener.score.json`](opener.score.json) ·
  [`opener.config.json`](opener.config.json)

## Verdicts on the spec's honesty conditions

- **h17 (deterministic record): holds.** Re-folding the committed log
  reproduces the final `state_hash` exactly.
- **h18 (dual scoring from the log alone): holds.** Outcome 23–10; cooperation
  **blue 100, red 98** — both computed from the log, nothing else.

## What happened (from the log alone)

Both sides played clean — **zero rejected orders in 30 turns, from either
team** (598 events, 175 in-game messages). The 27B Qwen seats, even raw,
made none of the geometry mistakes that cost the 12B Gemma swarm 19 orders in
playtest 2 — rejection rate tracks model capability, which is exactly why the
next cycle feeds rejections back and surfaces legal moves.

Blue won on **tempo at the objectives**: cp-center captured turn 6, the
ms-supply race won at turn 16 (the same deliver-6 race that dead-heated in
playtest 3), cp-west added turn 23. Final: 10 (mission) + 4 (two control
points) + 9 (resources) = 23.

Red out-gathered blue all match (10 resources delivered vs 9, 49 moves vs 32)
but converted none of it into objectives: **no control point in 30 turns**.
The telling detail sits in the final frame: red's defender ends *standing on*
cp-east — permanently contested by blue's scout on the same square, so its
hold streak never started. Ten points of economy, zero points of territory.
ms-outpost expired uncompleted for both sides.

## Cooperation scores — same lesson, third time

Red's 98/100 while losing 23–10 repeats the playtest-2 finding: the v0
heuristic prices message cadence and delegation spread, not whether the
communicated plan *worked*. Three matches in, the pattern is consistent —
the cooperation-metric refinement (parked v1) has its evidence.

## Findings → next cycle

1. **Tempo decides matches the scoring can't see** — blue's win was earlier
   captures and an earlier mission at nearly equal economy. The cycle-4 spec
   (tempo as a third axis, substrate-converted) is now grounded in all three
   season-0 matches.
2. **Contested-square stalemates are legible but unpriced**: red's defender
   spent the endgame nullifying cp-east for both sides — a real tactical
   choice the replay shows and no score reflects.
3. **Pacing**: ~9–10 minutes per turn (~4.7 h total including one
   driver-crash restart) with six stateless seats re-briefed from scratch
   every turn. The cycle-2 resident driver exists to attack exactly this;
   its playtest must publish the comparison (spec h2).

## The cycle continues

Findings from all three playtests seeded the next frames, per
[`docs/process/cycle.md`](../../process/cycle.md): **cycle 2 — resident
minds** (continuity, legal-by-construction orders, dual-award dead-heats;
[PR #6](https://github.com/agentculture/league-of-agents/pull/6)), **cycle 3
— fog + faces**
([PR #7](https://github.com/agentculture/league-of-agents/pull/7)), and
**cycle 4 — single-player + tempo**
([PR #8](https://github.com/agentculture/league-of-agents/pull/8)) — each
converged with user confirmation before implementation.
