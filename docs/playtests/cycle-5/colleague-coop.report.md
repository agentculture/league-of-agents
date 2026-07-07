# Playtest — colleague guild, cooperative mode (cycle-5 c6 live-test thread)

- **Match:** `m-colleague-coop` · skirmish-1 · **cooperative** (one team vs the
  environment's turn limit) · seed 20260710
- **Team:** *Colleague Guild* — three seats of the colleague agent
  (Qwen3.6-27B on the local lobes vLLM, fielded through its work-loop harness
  `scripts/colleague_driver.py` — field agents, not raw chat/completions),
  per-seat: each mind commands only its unit and coordinates ONLY through
  in-game messages.
- **Result:** **won at turn 16** of 30 — both missions completed, both
  reachable control points captured, 29 points
  (missions 18 · control 4 · resources 7).
- **Artifacts:** [`colleague-coop.log.jsonl`](colleague-coop.log.jsonl) ·
  [`colleague-coop.replay.html`](colleague-coop.replay.html) ·
  [`colleague-coop.score.json`](colleague-coop.score.json) ·
  [`colleague-coop.config.json`](colleague-coop.config.json)

## The headline: same mind, solo vs team

The same model played the same board solo hours earlier
([`bench-colleague`](../cycle-4/bench-colleague.log.jsonl), the tempo
benchmark's local row): it reached the turn-30 limit with **14 points and the
supply mission incomplete**. Three coordinated seats of the same mind
**finished everything by turn 16**:

| | Solo (competitive, 1 action/turn) | Guild of 3 (cooperative, per-seat) |
|---|---|---|
| Outcome | 14, ms-supply incomplete at t30 | **29, all missions done at t16** |
| ms-outpost / ms-supply | t12 / — | t10 / **t16** |
| Cooperation v1 | 69 | **99** |
| — message_utility | 0.68 (23/34) | **1.00 (52/52)** |
| — plan_fidelity | 0.93 (28/30) | **1.00 (16/16)** |
| — delegation_spread | 0.33 (solo floor) | **0.99** (three even lanes, one rejection taxed) |
| Median seat latency | 73,074 ms | 67,451 ms |

Every one of the guild's 52 messages carried a referent that later action
realized — position reports with coordinates, control-point ETAs, handoff
calls — and all 16 declared plans were followed through. One order was
rejected all match (turn 4, `guild-u1` overreached its move range) and the
team recovered the next turn; v1's rejection tax cost it the single point that
kept the score off 100.

**Two honesty caveats before reading this as "coordination wins":** the solo
run carried the deliberate one-action-per-turn handicap (that is the
coordination-necessity design — solo is *supposed* to be action-starved), and
cooperative mode has no opponent, so the guild's captures were uncontested
where the solo run's cp-center was contested by the house bot all match. The
clean claim is narrower and still the one issue #1 asks for: **the same mind
that could not finish the board alone finished it in half the turn budget as
a coordinated team, with the coordination visible and verifiable in the log**
— team coherence changed the outcome.

## Watching it (from the log alone)

Turns 1–6: the seats split lanes immediately — scout east, harvester to the
west resource node, defender screening center — narrating positions and ETAs
each turn (*"Turn 3: Moving to [6,3] to position near cp-center [6,5]. I'll be
there in 1 more turn to help secure it when guild-2 arrives"*). Scout captured
cp-east at t7; defender took cp-center at t8; **ms-outpost fell at t10**, and
the harvester's gather→deliver loop banked the sixth resource for
**ms-supply at t16**, ending the match at nearly half the turn limit.

## Methodology limitations (review findings, disclosed)

1. **Shared per-seat scratch workdir.** All three seats ran
   `colleague_driver.py --workdir .league/colleague-coop-seat` — one scratch
   git repo. Post-match inspection: the repo's tracked content never changed
   (single `init` commit, README only — no seat committed anything), but the
   colleague harness wrote 97 per-work-item trace/result files for all three
   seats into the same `.colleague/` directory, so a seat *could in principle*
   have read another's traces. Nothing in the decision traces suggests it
   happened, and the in-game message evidence (52/52 referent-realized)
   independently supports genuine in-game coordination — but the
   "messages-only" isolation claim is weakened to that extent and this match
   is not rerun to hide it. Fix-forward: per-seat workdirs (harness-level
   per-seat argv templating), queued with the cycle-5 closure work.
2. **Replay panel shows cooperation v0.** The embedded score breakdown in
   [`colleague-coop.replay.html`](colleague-coop.replay.html) is rendered by
   the replay's built-in scorer, which predates v1 selection — its
   cooperation signals are the v0 schema. The authoritative cooperation-v1
   numbers for this match are
   [`colleague-coop.score.json`](colleague-coop.score.json) (and the table
   above). A replay-side cooperation-version selector is part of the cycle-6
   replay overhaul.

## Cycle-5 thread status

This closes the *bot-independent* half of the c6 live-test thread for the
colleague substrate (solo + cooperative team, both through the real agent
harness, both reports reconstructible from committed logs). Still pending
from the c6 set: the resident-vs-stateless rematch, the fogged orchestrator
on skirmish-2, and the h9 retest — tracked for the cycle-5 closure PR.
