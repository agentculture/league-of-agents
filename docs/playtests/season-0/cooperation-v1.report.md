# Cooperation v1 re-score — season-0 side by side (t2, spec c7/h2/h3/c4/h11)

- **Scope:** all three committed season-0 logs
  ([`opener.log.jsonl`](opener.log.jsonl),
  [`coordination.log.jsonl`](coordination.log.jsonl),
  [`orchestrator.log.jsonl`](orchestrator.log.jsonl)) re-scored under
  cooperation **v1** (`league/engine/scoring.py`, task t1,
  `tests/test_engine_scoring_v1.py`) and compared against the committed v0
  `*.score.json` before-state — no match was re-run; every number below comes
  from folding the committed log a second time.
- **Script:** [`rescore_v1.py`](rescore_v1.py) — see [Methods](#methods) for
  the exact reproduction command.
- **Raw numbers:** [`cooperation-v1.scores.json`](cooperation-v1.scores.json)
  (full `score_match` payload, both versions, all six team-scores).

## Per-match v0/v1 table

| Match | Team | Outcome | v0 cooperation | v1 cooperation | Δ |
| --- | --- | --- | --- | --- | --- |
| opener | blue (Sonnet Foundry, **winner**) | 23 | 100 | 98 | −2 |
| opener | red (Qwen Relay, loser) | 10 | 98 | 96 | −2 |
| coordination | solo (Solo Sonnet, **winner**) | 16 | 80 | 73 | −7 |
| coordination | swarm (Gemma Swarm, loser) | 12 | 89 | 75 | −14 |
| orchestrator | fable (Fable Spawn, draw) | 16 | 100 | 99 | −1 |
| orchestrator | baseline (Greedy Baseline, draw) | 16 | 85 | 55 | −30 |

Every score drops under v1 — expected, since v1 only ever *discounts* cadence
credit that content doesn't back up (message_utility and plan_fidelity are
both ≤ their v0 cadence counterparts by construction; delegation_spread can
only lose ground to the rejection penalty; discipline is unchanged). No team
gained a point. The size of the drop is what is informative, and it is wildly
uneven — from −1 (fable) to −30 (baseline) — which is itself evidence that v1
is measuring something v0 could not see.

## Signal-level divergences (h3 — every gap traces to a named signal)

v0 has four signals: `delegation_spread`, `communication`, `plan_coherence`,
`discipline`. v1 keeps `delegation_spread` and `discipline` (with a rejection
penalty folded into the former) and replaces the two cadence signals with
content-checked ones: `communication` → `message_utility`, `plan_coherence` →
`plan_fidelity`. Component numbers below are the exact `components` block
each team's v1 payload carries (honesty h3 — the payload is designed to make
this traceable without re-deriving anything).

### Opener

| Signal | Team | v0 | v1 | What changed |
| --- | --- | --- | --- | --- |
| delegation_spread | blue | 1.0 | 1.0 | unchanged — zero rejections all match (`rejection_rate=0.0`), no penalty to apply |
| delegation_spread | red | 0.9444 | 0.9444 | unchanged, same reason |
| communication → message_utility | blue | 1.0 (cadence, saturated) | 0.9444 (85/90 messages useful) | 5 of 90 messages named nothing a subsequent action realized |
| communication → message_utility | red | 1.0 (cadence, saturated) | 0.9412 (80/85 messages useful) | 5 of 85 messages likewise uncorrelated |
| plan_coherence → plan_fidelity | blue | 1.0 | 1.0 (27/27 plans useful) | every declared plan was realized within `PLAN_WINDOW` |
| plan_coherence → plan_fidelity | red | 1.0 | 0.9655 (28/29 plans useful) | one red plan never got realized |
| discipline | both | 1.0 | 1.0 | unchanged — zero rejections |

Both teams communicated with unusually high referential density (unit
positions, coordinates, named control points) — this is the match where v0's
cadence credit and v1's content credit land closest together, and the
blue-over-red 2-point gap survives unchanged. Nothing here contradicts v0's
ranking; v1 just prices the same match on a stricter scale.

### Coordination

| Signal | Team | v0 | v1 | What changed |
| --- | --- | --- | --- | --- |
| delegation_spread | solo | 0.3333 | 0.3333 | unchanged — `rejection_rate=0.0`, no penalty (one mind, one acting unit, by design) |
| delegation_spread | swarm | 0.9815 (base_spread) | 0.8022 | `penalty = REJECTION_PENALTY(0.5) × rejection_rate(0.3585) = 0.1792`; `0.9815 − 0.1792 = 0.8022` |
| communication → message_utility | solo | 1.0 (cadence) | 0.8214 (23/28 useful) | 5 of 28 messages uncorrelated with a later action |
| communication → message_utility | swarm | 1.0 (cadence) | 0.717 (38/53 useful) | 15 of 53 messages uncorrelated |
| plan_coherence → plan_fidelity | solo | 1.0 | 0.8889 (16/18 useful) | 2 of 18 plan declarations never realized |
| plan_coherence → plan_fidelity | swarm | 1.0 | 0.8889 (16/18 useful) | same realized-plan count as solo |
| discipline | solo | 1.0 | 1.0 | unchanged, zero rejections |
| discipline | swarm | 0.6415 | 0.6415 | unchanged — same `1 − rejection_rate` formula in both versions |

This is the match where v1 does the most work: swarm's 53 declared orders
include 19 rejections (`rejection_rate = 19/53 = 0.3585`), which v0 only
taxed once (via `discipline`, weight 0.30). v1 taxes it **twice** — once on
`discipline` (unchanged) and again as a direct penalty on `delegation_spread`
(new in v1) — while *also* discounting swarm's message cadence down to its
actual 71.7% content-utility. Three of v1's four signals move against swarm;
only solo's already-low `delegation_spread` (one mind piloting one unit)
holds flat. Net: solo −7, swarm −14 — see [the h2 finding](#the-h2-finding)
below for what that does to the ranking.

### Orchestrator

| Signal | Team | v0 | v1 | What changed |
| --- | --- | --- | --- | --- |
| delegation_spread | fable | 1.0 | 1.0 | unchanged — zero rejections |
| delegation_spread | baseline | 1.0 | 1.0 | unchanged — zero rejections |
| communication → message_utility | fable | 1.0 (cadence) | 0.9592 (47/49 useful) | 2 of 49 messages uncorrelated |
| communication → message_utility | baseline | 0.25 (cadence, 2 message-turns / 16) | **0.0 (0/2 useful)** | both messages ("`delivered 3`") name no cp/rn/ms id, cell, or unit — zero referents to check, so neither can be realized |
| plan_coherence → plan_fidelity | fable | 1.0 | 1.0 (6/6 useful) | every declared plan realized |
| plan_coherence → plan_fidelity | baseline | 1.0 | **0.0 (0/1 useful)** | baseline's one plan ("*greedy split: harvester runs node-to-target relay; scout takes the far point, defender the near one*") names no cp/rn/ms id, cell, or unit either — same zero-referent failure |
| discipline | both | 1.0 | 1.0 | unchanged, zero rejections |

Fable drops 1 point on content noise. Baseline drops **30** — the largest
single divergence in the entire re-score — because both of its two
non-`delegation`/`discipline` signals collapse from full v0 cadence credit to
zero v1 content credit. See [the pseudo-coordination
story](#the-pseudo-coordination-story-orchestrators-baseline-team) below.

## The h2 finding

Plan risk and spec honesty h2 require this stated plainly, not tuned away:
**does the coordination match's loser still out-cooperate the winner under
v1?** Computed, not asserted:

- v0: swarm (loser, outcome 12) scores **89**; solo (winner, outcome 16)
  scores **80** — swarm ahead by 9.
- v1: swarm (loser) scores **75**; solo (winner) scores **73** — swarm
  **still ahead, by 2**.

**Yes — under v1, the coordination match's loser still out-cooperates the
winner.** The gap shrank by 78% (9 points → 2 points) because v1 taxes
swarm's 36% rejection rate twice (discipline *and* delegation_spread) and
discounts both teams' cadence down to their actual content-utility — but it
does not flip the ranking, and per honesty h2 this stands as the finding, not
a defect to fix by retuning weights. Real per-mind delegation (three
independently-acting Gemma seats, each doing something even when a third of
their orders bounced) is still, on this signal set, worth more than one
disciplined mind doing everything itself. `coordination.report.md`'s own
verdict on h9 ("solo wins on outcome despite the swarm's coordination")
holds; v1 sharpens *how much* cooperation credit that costs the swarm without
overturning it.

For completeness, the same check on the other two matches, reported for what
it actually shows rather than assumed: **opener's** v0 ranking already had
the winner (blue, 100) ahead of the loser (red, 98) — narrowly, but ahead —
and v1 preserves that ordering (98 vs 96). Only the coordination match
exhibits the loser-out-cooperates-winner pattern in this season-0 set;
**orchestrator** is a draw (no winner/loser to compare against). The build
plan's before-state note describes v0 as having rewarded cadence over
content across "all three season-0 matches" — that qualitative critique
(cadence inflates scores regardless of outcome) holds on the numbers for all
three, but the specific *loser-outranks-winner* pattern this task was asked
to verify is, on the committed logs, a coordination-match-specific finding,
not a three-for-three one. Reporting the distinction is the honest version
of h2: no fitting to outcomes in either direction.

## The pseudo-coordination story (orchestrator's baseline team)

`baseline` ("Greedy Baseline", `bot:greedy` — a scripted, non-agentic
strategy, not a language model) is the clearest pseudo-coordination case in
season-0. Under v0 it scored **85/100** — the second-highest cooperation
score of the entire season, trailing only the two perfect 100s — earned
almost entirely from `delegation_spread` (1.0, weight 0.30) and
`plan_coherence` (1.0, weight 0.20: one plan declared turn 1, credited for
covering every later acting turn) plus a modest `communication` credit (0.25,
weight 0.20) for messaging on 2 of 16 turns. That is real cadence: baseline
did act with all three units, and it did emit a plan and two messages on
schedule.

What v0 could not see is that none of that content named anything. The plan
text — "*greedy split: harvester runs node-to-target relay; scout takes the
far point, defender the near one*" — and both messages — "*delivered 3*",
verbatim, twice — contain no control-point id, resource-node id, mission id,
grid cell, or unit reference the v1 referent-extractor recognizes
(`_extract_referents` in `league/engine/scoring.py` matches `cp-*`, `rn-*`,
`ms-*`, `(x, y)` cells, and unit refs only). `_utterance_useful` is `any()`
over an empty referent set, which is `False` by definition — so
`message_utility` and `plan_fidelity` both come out **exactly 0.0**, not a
partial credit. Baseline's v1 score is **55** — built entirely from
`delegation_spread` (1.0) and `discipline` (1.0), the two signals that were
already content-free by design and require nothing more than "acted, and
never had an order bounce."

This is precisely the case cooperation v1 was built to catch (spec c7,
plan task t1's docstring): "one-mind pseudo-coordination is distinguished
from real delegation." Baseline is not one mind pretending to be a team —
it is a scripted bot whose scheduled chatter *looked* like the coordination
signals v0 rewards (cadence, plan presence) while carrying zero of the
substance those signals were meant to proxy for. Fable, the real
multi-agent team in the same match, communicated positions, ETAs, and named
control points throughout and lost only 1 point (100 → 99) to the same
stricter test. The 29-point gap between fable's and baseline's *drop* (−1 vs
−30) is the cleanest single number in this report for "v1 tells content
apart from cadence."

## Why cooperation scoring must be fair and inspectable

Quoted, not paraphrased, from [issue #1](https://github.com/agentculture/league-of-agents/issues/1)
(fetched via `gh issue view 1 --repo agentculture/league-of-agents`), the
requirements document this whole scoring lane answers to:

> The system can score both mission outcome and cooperation quality.

And:

> Logs or replays make it possible to inspect why a team succeeded or
> failed.

And:

> Different agent teams, models, or role compositions can be compared
> fairly.

v0 satisfied the letter of the first two — it did score cooperation, from
the log, and did expose a `signals` breakdown — but the season-0 reports
(`opener.report.md`, `coordination.report.md`) already flagged the third:
a metric that inflates on cadence regardless of content cannot compare teams
fairly, because a team that never says anything true still banks the same
score as a team that does. This report's own numbers are the evidence for
why that matters in practice: baseline's scripted, referent-free chatter
scored within 15 points of a perfect 100 under v0; under v1, held to the
same "logs make it possible to inspect why" standard the issue demands, it
scores 55 — a number that now actually reflects what the log shows baseline
did and did not communicate.

## Methods

Reproducible from the committed logs alone (honesty h1):

```bash
cd /home/spark/git/worktrees/agent-c5-t2
uv run python docs/playtests/season-0/rescore_v1.py
```

The script ([`rescore_v1.py`](rescore_v1.py)) loads each of
`opener.log.jsonl`, `coordination.log.jsonl`, and `orchestrator.log.jsonl`
with `league.engine.events.MatchLog.from_jsonl`, folds each into both
`league.engine.scoring.score_match(log, version="v0")` and
`score_match(log, version="v1")`, cross-checks the v0 recomputation against
the committed `*.score.json` (the same regression
`tests/test_engine_scoring_v1.py::test_v0_reproduces_committed_season0_scores`
pins — it matched byte-for-byte on this run, so v0 has not drifted), prints
the comparison table above, and writes the full six-team, two-version
payload to [`cooperation-v1.scores.json`](cooperation-v1.scores.json). No
match was re-run; no engine, tick, or existing season-0 artifact was
touched — this task's diff is additions under `docs/playtests/season-0/`
only.
