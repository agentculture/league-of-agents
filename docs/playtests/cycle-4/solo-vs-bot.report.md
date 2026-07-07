# Playtest — preset-launched solo vs the house (cycle-4 t7, spec c2/h2)

- **Match:** `m-preset-solo-vs-bot` · skirmish-1 · competitive · seed 20260710
- **Launch:** `uv run league play start solo-vs-bot --apply` — one command, no
  hand-authored config. Everything below (teams, drivers, seed, match id) came
  from the bundled preset registry (`league/presets.py`).
- **Teams:** *Solo Agent* — one **claude-sonnet-5** mind (the `claude` CLI in
  print mode, a fresh session every turn) commanding all three units under the
  solo handicap (one action per turn) — vs *House Rusher (silver)*, the named
  coded strategy `bots/rusher.py` from the house ladder, playing through the
  public CLI surface.
- **Result:** **solo wins 26–2** at turn 25 (`ms-supply` completed).
- **Artifacts:** [`solo-vs-bot.log.jsonl`](solo-vs-bot.log.jsonl) ·
  [`solo-vs-bot.replay.html`](solo-vs-bot.replay.html) ·
  [`solo-vs-bot.score.json`](solo-vs-bot.score.json)

## Verdict on c2/h2

**Demonstrated.** A recorded match exists where one agent played a named house
strategy bot, launched entirely from a preset. The launch surface did all the
setup work: `play start` resolved the preset, registered both teams, created
the match, and ran it — zero rejected orders across 25 turns, 50 `seat_latency`
events recorded (25 per side), and the log replays to the committed final
state.

## What happened (from the log alone)

The solo mind played the economy; the rusher can't. House captured `cp-center`
by turn 4 (its whole roster rushes control points), but solo took `cp-east` at
turn 7, completed **ms-outpost at turn 10**, and spent the rest of the match
running the gather→deliver loop with its harvester while its other units held —
completing **ms-supply on turn 25** for the 18-point mission haul (26–2 final).
The one-action-per-turn handicap showed up as patience, not paralysis: the mind
messaged its own future seats every turn (37 messages, e.g. *"Scout standing by
at (0,0). Will hold position this turn so the harvester's move isn't
discarded…"*) — self-coordination across stateless sessions through the in-game
message channel, exactly the mechanism the arena scores.

## The three axes, on one match

| Axis | solo (cloud) | house (bot) |
|------|--------------|-------------|
| Outcome | **26** (missions 18 · control 2 · resources 6) | 2 (control 2) |
| Cooperation v1 | 77 | 55 |
| Tempo (t0) | **31** — raw median **64,740 ms**, p95 124,293 ms | 125 — raw median **8 ms**, p95 9 ms |

- Tempo is scored against declared substrates (`--substrate solo=cloud
  --substrate house=bot`); raw latency is printed beside every converted score
  (spec h4). The mind ran ~3.2× slower than the illustrative cloud baseline
  (median 64.7 s/turn, range 18.9–127.6 s) — real data for the calibration
  discussion in [`docs/tempo-methodology.md`](../../tempo-methodology.md).
- Cooperation v1 prices the house's referent-free plan chatter the same way it
  priced the season-0 orchestrator baseline
  ([`cooperation-v1.report.md`](../season-0/cooperation-v1.report.md)).

## Before → after (spec c6/h6)

Season 0 needed a hand-authored JSON config per playtest plus a bespoke harness
invocation, and the opener paced at ~9 minutes per turn under operator
supervision (see
[`the season-0 opener report`](../season-0/opener.report.md)). This match was
one CLI command, unattended, ~35 minutes end to end at ~65 s per solo turn —
the packaging change cycle 4 promised (spec c3).

## Who each artifact serves (spec h5)

- **Operators** — the one-command launch line above is the whole runbook.
- **Solo agents practicing** — the preset is the on-ramp: any agent that can
  run one command gets a scored ladder match against a named tier.
- **Benchmark readers** — the score JSON carries raw + converted tempo per
  team; this log is the first latency-bearing recorded match.

## Findings → next

1. Rusher (silver) is beatable by economy play even under the solo handicap —
   the gold tier (`vanguard`) runs the economy itself and is the right next
   ladder rung for minds that clear silver.
2. Solo latency variance is wide (18.9–127.6 s per turn); median-driven t0
   scoring absorbed it, confirming the formula choice, but per-turn latency in
   the replay UI would make the slow turns inspectable (parked; UI stays out of
   scope per spec c13).
