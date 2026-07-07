# Playtest 2 — coordination necessity (t13, spec c16/h9)

- **Match:** `m-season0-coordination` · skirmish-1 · competitive · seed 20260708
- **Teams:** *Solo Sonnet* (claude-sonnet-5 commander, **enforced one action per
  turn**) vs *Gemma Swarm* (3 independent colleague/gemma-4-12b seats,
  coordinating only through in-game messages)
- **Result:** **solo wins 16–12** at turn 18 (all missions resolved)
- **Artifacts:** [`coordination.log.jsonl`](coordination.log.jsonl) ·
  [`coordination.replay.html`](coordination.replay.html) ·
  [`coordination.score.json`](coordination.score.json) ·
  [`coordination.config.json`](coordination.config.json)

## What happened (from the log alone)

The solo mind read the handicap correctly on turn 1 — *"only one of us can act
per turn, so I'm yielding this turn to the harvester's relay"* — and spent all
18 of its actions on one unit: the harvester ran the west-node relay and
completed **ms-supply** (10 pts) on turn 18, plus 6 delivered resources.
Its scout and defender never acted (0 orders each).

The swarm played the territory game: captured cp-center (t6) and cp-east
(t12), completed **ms-outpost** (t15) — 8 + 4 control points. But it burned
**19 of 53 orders on rejections** (10 beyond-move-range, 6 delivering off the
delivery square): the 12B seats repeatedly misjudged Manhattan distances and
the delivery rule, and the match ended before territory could out-earn the
relay: 16–12.

## Cooperation scores — and what they expose

Swarm scored **89**, solo **80** — the *loser out-cooperated the winner*. The
signals are working as documented (delegation spread and message cadence
measure process, not outcome), but this match exposes v0 heuristic limits:

- `delegation_spread` rewards three units *acting*, even when a third of those
  actions are illegal;
- `discipline` (0.30 weight) didn't penalize the swarm's 36% rejection rate
  enough to flip the comparison;
- the solo team's "coordination" was internal to one mind — cheap plan/message
  declarations kept its score at 80 despite zero actual delegation.

## Verdict on h9

**Not demonstrated.** The honesty condition — *a solo strong agent measurably
loses to a coordinated weaker team* — did not hold on skirmish-1 v0: full
observability plus no action-bandwidth pressure on the map let one competent
mind with one action per turn beat three coordinated-but-weaker minds. This
was pre-registered as plan risk r3 ("the scenario will likely need tuning").

## Findings → next cycle

1. **Coordination pressure is too weak.** Candidates: per-role fog of war
   (issue #1 names visibility as a specialization axis), simultaneous
   multi-point objectives, message costs/latency, shorter turn limits.
2. **Cooperation heuristic needs its refinement cycle** (parked v1): weight
   rejected actions inside delegation_spread; score message *content* utility,
   not cadence; distinguish one-mind pseudo-coordination from real delegation.
3. **Rejection rate is a capability signature** — surface legal moves in
   `match show --json` (issue #2 explicitly wanted "legal moves" readable) so
   weaker models waste less and the game measures strategy, not geometry
   arithmetic.
