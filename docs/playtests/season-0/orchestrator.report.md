# Playtest 3 — orchestrator subagent mode (t14, spec c15/h8)

- **Match:** `m-season0-orchestrator` · skirmish-1 · competitive · seed 20260709
- **Teams:** *Fable Spawn* — the orchestrator (**Claude Fable 5**, the agent
  operating this repo) designed the roster, wrote the team doctrine and three
  per-seat doctrines in [`orchestrator.config.json`](orchestrator.config.json),
  and fielded the seats as spawned claude-sonnet-5 subagents — vs *Greedy
  Baseline* (the deterministic bot).
- **Result:** **16–16 draw** at turn 16 (all missions resolved)
- **Artifacts:** [`orchestrator.log.jsonl`](orchestrator.log.jsonl) ·
  [`orchestrator.replay.html`](orchestrator.replay.html) ·
  [`orchestrator.score.json`](orchestrator.score.json)

## Verdict on h8

**Demonstrated.** An orchestrator agent registered a team, spawned its own
subagents as roster members (per-seat, each commanding only its unit,
coordinating through in-game messages), and played a scored match end to end.
The mode is a config surface, not a code change — the orchestrator's strategic
input is the doctrine text in the config.

## What happened (from the log alone)

Doctrine execution was crisp: the scout rushed cp-east and captured it (t5),
completing **ms-outpost by t8** — the fastest mission completion recorded this
season. Every seat messaged position/ETA/streak facts each turn, zero rejected
orders, plan declared turn 1: **cooperation 100/100**, the season's first
perfect score, and this time backed by real delegation (three minds, three
lanes, no collisions).

The draw came down to a photo finish with a biased camera: both harvesters
delivered their sixth resource **on the same turn** (t16). The v0 dead-heat
rule (larger total, then lexicographic team id) awarded ms-supply to
`baseline` — `b` sorts before `f`. Had the tie broken the other way, the score
would have been 26–6 Fable. The engine documented this bias as "deliberately
rare"; it decided the second match of the season.

## Human review (h15)

The human reviewer (Ori) reconstructed the match from the replay alone and
caught two things the log knew but the board hid:

- **Turn 3:** the baseline scout "disappeared" — it shared (6,7) with the
  baseline defender, and the renderer drew units at cell centers in state
  order, so the last-drawn unit fully occluded the rest.
- **Turn 7:** both carrying harvesters ("H3", blue *and* red) vanished — four
  units stacked on (6,5), the shared delivery square, with only the top one
  visible.

Both were the same defect: co-located units occluded each other. **Fixed** —
stacked units now fan out inside the cell (nothing is ever occluded), mission
squares are labeled (`ms-supply: deliver 6`, then `ms-supply → <team>` in the
earning team's color on completion), and replays accept `#t7`-style deep links
so a reviewer can point at the exact frame. The committed replay was
regenerated from this same log; the log itself is untouched.

The reviewer also noted agents standing in place: the two defenders parked on
(6,5) from turn 5 to the end. That one is real doctrine — both sides screened
the delivery square — and mutual occupancy kept cp-center contested all match,
which is a visible multi-turn consequence, not a rendering error.

## Findings → next cycle

1. **Dead-heat mission resolution needs a fair rule** — split the reward,
   award both, or resolve from the match seed; alphabetical order is not a
   game mechanic. (Highest-priority engine fix from this playtest.)
2. **Perfect cooperation ≠ win** is healthy — outcome and cooperation are
   deliberately separate axes — but the orchestrator's doctrine underweighted
   the economy race: tempo on the *bigger* mission beats tempo on the faster
   one. Strategy insight, on the record, reusable.
3. The orchestrator mode's fairness constraints (spawn budgets, model mixing)
   remain parked (frame v3) — this demo used equal seat counts by
   construction.

The dead-heat fix seeded **cycle 2 — resident minds**
([PR #6](https://github.com/agentculture/league-of-agents/pull/6)); the
dual-award rule is a cycle-2 plan task (user decision c15), and orchestrator
mode becomes a real game mode with fog in cycle 3
([PR #7](https://github.com/agentculture/league-of-agents/pull/7)).
