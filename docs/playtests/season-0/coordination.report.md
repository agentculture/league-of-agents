# Playtest 2 — coordination necessity (t13, spec c16/h9)

- **Match:** `m-season0-coordination` · skirmish-1 · competitive · seed 20260708
- **Teams:** *Solo Sonnet* (claude-sonnet-5 commander, **enforced one action per
  turn**) vs *Gemma Swarm* (3 independent gemma-4-12b seats, coordinating only
  through in-game messages)
- **Driver caveat (post-review):** the swarm seats were driven **raw over the
  vLLM endpoint** (`scripts/openai_driver.py`), not through the colleague
  agent — the `colleague/gemma-4-12b` label in the config overstates the
  routing. Per the season-0 review directive, local models are fielded as the
  colleague *agent* (`scripts/colleague_driver.py`, its work-item harness
  loop) from here on: the harness is part of the agent, the same way Sonnet
  seats play through `claude -p` rather than the raw API.
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

## Human review (h15)

The human reviewer (Ori) read the replay as *"blue only takes resources to the
enemy base"* — and the board earned that misreading: the ms-supply delivery
square **is** cp-center (6,5), the swarm owned that control point from turn 6,
so blue's harvester kept dropping resources onto a red-tinted circle with no
label saying what the square was or who got credit. (Scoring was correct —
deliveries always credit the delivering team — but a replay that needs the
scoring code to be believed fails h15.) **Fixed:** mission squares are labeled
with kind and amount, and on completion the label becomes
`ms-supply → solo` in the earning team's color; stacked units fan out instead
of occluding; `#t7`-style deep links let a reviewer cite the exact frame.

The review also produced a **user directive for the next cycle**: illegal
moves shouldn't be possible in the first place, and when an order is refused
the agent must get textual guidance on why. Today the engine logs a
`reason` on every `action_rejected` event, but the harness never feeds it back
— a seat that misjudged move range never learns why its unit stood still,
which is exactly how the swarm burned 19 orders.

## Findings → next cycle

1. **Coordination pressure is too weak.** Candidates: per-role fog of war
   (issue #1 names visibility as a specialization axis), simultaneous
   multi-point objectives, message costs/latency, shorter turn limits.
2. **Cooperation heuristic needs its refinement cycle** (parked v1): weight
   rejected actions inside delegation_spread; score message *content* utility,
   not cadence; distinguish one-mind pseudo-coordination from real delegation.
3. **Illegal orders must become impossible-by-construction** *(upgraded to a
   user requirement by the h15 review)*: surface per-unit legal actions in
   `match show --json` (issue #2 explicitly wanted "legal moves" readable),
   and feed each seat its own previous-turn rejections *with the engine's
   reason text* so weaker models stop repeating the same geometry mistakes
   and the game measures strategy, not arithmetic.
