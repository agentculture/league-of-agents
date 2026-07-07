# Playtest — long-horizon memory on a generated board (cycle-6 t8, spec c9/h9)

- **Match:** `m-memory-longhorizon` · **generated scenario**
  `gen-777-w21y17t60c2r2m2k2` (21×17 board, 60-turn limit, 2 control-point
  pairs, 2 node pairs, 2 hold-mission pairs — seeded, re-creatable from this id
  alone) · competitive · seed 20260714
- **Teams:** *Memory Keepers* — three **resident** claude-sonnet-5 seats (one
  long-lived session per seat for the whole match; the session IS the memory
  under test), **fogged** map reads — vs *House Vanguard (gold)*, the strongest
  coded strategy, full information.
- **Result:** **keeper wins 56–16 at turn 26** of 60 — every mission on the
  board resolved (4 holds + the deliver), all four control points captured at
  least once.
- **Artifacts:** [`log`](memory-longhorizon.log.jsonl) ·
  [`replay`](memory-longhorizon.replay.html) (with the embedded assessor
  guide) · [`video`](memory-longhorizon.gif) ·
  [`score`](memory-longhorizon.score.json) ·
  [`probe`](memory-longhorizon.probe.json) ·
  [`config`](memory-longhorizon.config.json)

## Verdict on c9/h9

**Demonstrated — with the honest distinction the claim needs.** Mission
positions are briefing-disclosed under fog, so *knowing where* an objective
sits is not memory. What the log actually proves:

1. **Symmetry inference at turn 1, executed at turn 23.** The scout's first
   message reads: *"Board is mirror-symmetric so cp-1a and cp-2b are our
   closest control points, cp-1b/cp-2a are theirs."* The mind read the
   generator's fairness geometry off the board itself and planned the far
   side's objectives before ever seeing them. `cp-2a` then stayed **out of all
   keeper units' sight from turn 0 through turn 20** (verified: no keeper unit
   within Manhattan distance 3 until turn 21) — and the team routed to it at
   t21, captured it at t23, and completed `ms-hold-2a` at t26. A 22-turn gap
   between inference and execution, bridged only by session memory.
2. **Plan persistence across ~78 decision points.** The turn-1 three-message
   plan (scout → cp-1a; harvester → rn-1a gather/deliver loop; defender →
   cp-2b) played out in exactly the declared order across 26 turns:
   captures at t5 (cp-1a) → t10 (cp-2b) → t15 (cp-1b) → t23 (cp-2a), missions
   at t8 → t13 → t18 → t19 (deliver) → t26. Zero rejected orders in 78
   declared actions — no drift, no re-planning churn.
3. **Sight-discovered knowledge reused later:** `rn-2b` first enters the
   team's messages at t13 (discovery by movement) and is still being referenced
   and acted around through t21.

## The scores — three firsts

| Axis | keeper | Note |
|------|--------|------|
| Outcome | 56–16, won t26/60 | Beat the *gold* house bot under fog |
| Cooperation v1 | **100** | First perfect score under the harder metric: 49/49 messages useful, 3/3 plans realized, spread 1.0, 78/78 orders clean |
| Span (p0) | **100** (3/3, latency evidence) | |
| Tempo (t0) | raw median **9,980 ms**/turn | See below |

**The residency finding:** the same model, stateless, ran a 64,740 ms median
turn in the [cycle-4 benchmark](../cycle-4/tempo-benchmark.report.md). The
resident sessions here ran **9,980 ms median — 6.5× faster** — because each
seat keeps its context and never re-reads the world from scratch. Residency is
not just a memory mechanism; on this evidence it is the single largest tempo
lever measured so far. (Raw numbers beside everything, per h4; substrate
declared cloud; concurrent background load on this machine was light but
nonzero.)

## Scale note (spec c9)

This is the first recorded match on a **generated** board beyond the old
ceilings (21×17 vs 12×10, 60-turn limit vs 30) — mid-scale by the new knobs'
range (41×41/200 available), chosen so a live-mind match stays affordable.
The engine-side extremes are covered by the merged large-board bot tests; the
next live rung is a 31×25/100-turn resident match.

## Findings → next

1. Residency's 6.5× tempo advantage should be a headline row in the next
   benchmark — same mind, same board, resident vs stateless (also closes the
   cycle-2 rematch thread).
2. The symmetry inference suggests generated boards *teach* their own
   geometry; the assessor guide could point human reviewers at exactly this
   (a "did the team exploit symmetry?" checklist line).
3. Vanguard (gold) under fog never adapted to losing its economy race —
   fog-aware tiers above gold (lampbearer-style knowledge use with vanguard's
   economy) are the natural ladder extension.
