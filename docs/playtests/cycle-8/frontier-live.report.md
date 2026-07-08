# Cycle-8 live playtest — the fogged frontier, the mutual denial, and the seat that was never asked again

*Match:* `c-frontier-live` · *scenario:* `c-frontier-1` (The Fogged Frontier) ·
*mode:* competitive · *seed:* 20260708 · *fog:* **on** · *result:* **draw, 0–0
at t=29 of 30** · *events:* 117 · *seats:* six live `claude-sonnet` minds via
`scripts/cseat_driver.py` (resident), one per role — scout, harvester,
defender per team.

This is the cycle-8 closing playtest (plan t12): the first fogged continuous
match, the first 3-role continuous rosters, the first contested deliveries on
a live record, and the first match scored by the new per-unit role-purpose
scorecard. It ends 0–0 — and the zero is the most instructive number the
arena has produced yet.

## Why this match exists (issue #1, verbatim)

> The system scores both mission outcome and cooperation quality, and
> logs/replays make it inspectable — why a team succeeded or failed.

The core question the arena answers: *Can this group of agents become a
coherent, strategic, cooperative team under constraint?* This match was built
to put that question under fog: a map whose head-on race is decided by
arithmetic before it starts, a single shared delivery square both teams must
bank at, and executor vision too short to read the bank from any natural
approach — only a scout can tell a team whether their delivery walks into a
denial.

## Before-state (what was true when the match started, and where it's pinned)

- **The map and its arithmetic** — `league/engine/continuous/scenario.py`,
  `_c_frontier_1()` and the module docstring's "fog, a shared delivery
  square, and a deliberately unfair race" section; proven by
  `tests/test_cscenario_frontier.py` (race asymmetry 12 vs 13, camp-at-6 vs
  deliver-at-23, solo bounds 47/35 > 30, the fog lever both geometrically and
  through the real briefing path).
- **The contention rule** — `league/engine/continuous/resolve.py`, "Delivery
  contention" docstring: a delivery completing while an enemy stands
  `arrived()` on the site is **denied**, reason
  `"delivery denied by enemy presence at the site"`; carry is kept, not
  banked; same-team simultaneity is co-delivery, never contention.
- **Fog as projection** — `league/charness.py`: briefings filter the board to
  the acting team's union of per-role `vision_mu`; the log records ground
  truth; `"fog": true` in the match config
  ([`frontier-live.config.json`](frontier-live.config.json)).
- **Eyes-only scouts, both lanes** — `league/engine/continuous/roles.py`
  (`can_take_post=False`, cycle-7 amendment) and `docs/roles.md` (the cycle-8
  decision that made the grid scout eyes-only too).
- **The spoken contract** — `league/charness.py` `SEAT_CONTRACT`: every seat's
  first contact carries the reply shape, the time model, race semantics,
  contention wording, and (in this match) the fog paragraph;
  `scripts/cseat_driver.py` is transport only.
- **The grades** — `league/engine/continuous/grades.py` `cgrade_units`:
  purposes `race_hold` / `economy` / `eyes`, off-role at half credit, MVP/LVP
  by grade with the canonical `(team_id, unit_id)` tie-break.

## What happened, cited to the log

All `seq` numbers refer to [`frontier-live.log.jsonl`](frontier-live.log.jsonl).

| t | What | Citation |
|---|------|----------|
| 0 | All six minds message their plans. Both defenders declare a reactive posture — blue: "Holding position at (3000,4000) … will move to intercept if red incursion appears"; red: "Holding position at (9000,5000) to guard the harvester … will move to intercept if needed." These are their only decisions of the match. | msgs seq 69–83; decision points seq 5, 10 |
| 2 | Both scouts race for `cp-frontier`, symmetric ETA t=8. | seq 11, 15 (moves); msgs seq 85, 87 |
| 8 | Scouts arrive at the post simultaneously and **discover the eyes-only rule live**: "no take/hold action showing in my menu" (blue), "no take/hold action available to either side" (red). Gathers complete — each harvester now carries exactly the 3 that `ms-supply` needs. Both harvesters route to the shared bank, ETA t=17. Red's scout repositions to the bank itself "if I'm [there, I deny]". | msgs seq 89, 91, 93, 95; gathers seq 23, 31 |
| 10 | **The fog moment (h7).** Red-scout, from the bank: "our harvester and blue's harvester both land at ms-supply at t=17 — each will count as enemy presence for the other, so that's shaping up as a mutual deny regardless." Under fog, red-harvester (vision 2000) could not see blue-harvester's approach from across the board — its own t=8 plan already cites the scout's relay ("same instant as blue-harvester's delivery attempt, so we may deny each other on arrival"). A teammate's declared decision demonstrably rests on intel only the scout's vision could supply. | msgs seq 98 (scout), 95 (harvester); move seq 35 |
| 12 | Red-scout returns to the post to test a theory — "hold progress accrues from continuous idle presence rather than a [discrete action]" — a mind probing the rules honestly under fog. (The theory is wrong: holds require a completed `take_post`, which only defenders can start.) | msg seq 100; move seq 39 |
| 14 | Blue-scout, finding nothing left at home, crosses the entire board to `rn-east` and reports it "tapped dry" — the deep recon that makes it the match's widest eyes. | msg seq 102; move seq 42 |
| 17 | Both harvesters arrive at the bank in the same instant and **commit to delivery knowing the mutual denial is coming** — blue: "If red also delivers we mutual-deny for free (I keep carrying either way)"; red: "my presence denies blue's delivery either way and costs me nothing." | moves seq 46, 50; msgs seq 104, 106 |
| 23 | **Mutual denial #1.** Blue's delivery completes first in canonical order and is denied by red's presence; red's completes and is denied by blue's. Both keep their carry. Both immediately re-commit (done t=29, "right at the wire"). | `action_failed` seq 57, 60; msgs seq 110, 112 |
| 29 | **Mutual denial #2, at the buzzer.** Both denied again; both reason correctly that no remaining action can complete before t=30 and hold to keep denying "through the buzzer". The match ends a draw. | `action_failed` seq 63, 65; msgs seq 114, 116; `match_finished` seq 67 |

Substrate independence held live: the six seats spent **603.5 seconds** of
wall-clock deliberation (median 20.6s per decision, max 60.6s) against 29
units of game time, and none of it exists in the game state — wall clock
appears only in the 22 `seat_latency` observation events.

## The scorecard names the story

From [`frontier-live.score.json`](frontier-live.score.json) — the new `units`
section, this cycle's per-unit axis, sitting beside the (zero-filled) team
outcome it never feeds:

| Unit | Role | Grade | race_hold / economy / eyes | |
|------|------|------:|---------------------------|---|
| blue-u1 | scout | **1300** | 0 / 0 / 1300 | **MVP** |
| red-u1 | scout | 700 | 0 / 0 / 700 | |
| blue-u2 | harvester | 500 | 0 / 300 / 200 | |
| red-u2 | harvester | 500 | 0 / 300 / 200 | |
| blue-u3 | defender | **0** | 0 / 0 / 0 | **LVP** |
| red-u3 | defender | 0 | 0 / 0 / 0 | |

The grades read the match exactly as the log does: the MVP is the scout that
crossed the whole board and owned the information game; the two harvesters
are perfectly symmetric, as their mirrored standoff was; and the LVP is a
defender that did *nothing at all* — grade 0, named by the canonical
tie-break over its equally idle red counterpart. Which raises the only
question that matters:

## Findings

1. **A pass parks a seat forever — the headline finding.** Decision points
   are completion-triggered: a unit gets asked again when its action
   completes. A null action ("hold position") completes nothing, so both
   defenders received exactly **one** decision point each (seq 5, 10, at t=0)
   and were never asked again for the remaining 29 time units. Their
   conditional plans — "will move to intercept if…" — were structurally
   unable to fire. The map's central race (blue takes at 12, red at 13) never
   ran; `ms-hold` was never attempted; the standoff at the bank had no third
   party able to break it. The 0–0 is not a failure of the minds — both
   defenders' t=0 reasoning was sound *given a harness where waiting is a
   thing you can come back from*. It isn't. **Cycle-9 frame candidate:** a
   wait must be a schedulable action (wake on new information, or a bounded
   idle duration), not a permanent exit from the decision loop.
2. **The contention rule worked, and the minds weaponized it within
   minutes.** Denial is free for the denier (the rule deliberately mirrors
   "nothing to deliver": carry kept, no cost), so two symmetric harvesters
   arrive at the game-theoretic answer independently and verbatim — "costs me
   nothing", "we mutual-deny for free" — and the bank becomes a stable 0–0
   standoff. That is coordination pressure doing its job (the counter is a
   defender clearing the square — see finding 1), but cycle 9 should decide
   *on the record* whether free denial is the intended tension or whether
   standing a camp should cost something.
3. **The eyes-only rule was discovered, not read.** Both scouts arrived at
   the post expecting to contest it and reported the missing menu entry
   within the same decision — then pivoted to what scouts are for: intel
   relays, deep recon, and (red) using their own bodies as denial pieces.
   The fog made scout messages the only cross-board information channel, and
   the h7 moment (t=8/t=10, cited above) shows a harvester's declared plan
   resting on facts only its scout could see.
4. **Minds build (wrong) theories under fog and test them cheaply.**
   Red-scout's "presence-hold theory" (seq 100) and blue-scout's mirrored
   "deny red's solo hold accrual" (seq 108, t=20) are both incorrect readings
   of the hold rule — and both were tested by standing still, the cheapest
   possible experiment. The contract tells seats what actions do, not what
   every mission kind requires; whether it *should* is a legitimate cycle-9
   contract question.
5. **The dual-axis discipline held.** The team axes are honest zeros — no
   mission, no post, no banked resource. The per-unit axis still grades every
   seat and names MVP/LVP, and the two axes never touch: `cgrade_units` is
   consumed by the score payload's `units` section only
   (`tests/test_cli_score_units.py` pins that grades never feed team scores).

## Artifacts and their audiences

- [`frontier-live.config.json`](frontier-live.config.json) — for
  **reproducers**: the exact scenario, seed, fog flag, and driver argv.
- [`frontier-live.log.jsonl`](frontier-live.log.jsonl) — for **engines**:
  the single source of truth; folds to the final state under
  `tests/test_committed_logs_compat.py`'s sweep like every committed log.
- [`frontier-live.outcome.json`](frontier-live.outcome.json) /
  [`frontier-live.score.json`](frontier-live.score.json) — for **benchmark
  readers**: the team axes and the per-unit scorecard, machine-readable.
- [`frontier-live.replay.html`](frontier-live.replay.html) — for **human
  reviewers**: the continuous face with the new scorecard section; open it,
  read the verdict line, check it against this report.
- This report — for **the next cycle's frame**: findings 1–4 are its
  before-state.

## The closing ledger

The cycle-8 announcement, phrase by phrase, against what is now on record:

- **"League of Agents grades every seat"** — every seat in this match is
  graded in [`frontier-live.score.json`](frontier-live.score.json)'s `units`
  section; the same contract ships for grid logs
  (`league/engine/grades.py`, `tests/test_grades.py`).
- **"role-purpose scorecards name each match's MVP and LVP"** — named, here:
  MVP `blue-u1` (scout, 1300, all *eyes*), LVP `blue-u3` (defender, 0), with
  the per-purpose breakdown rendered in the replay's scorecard section and
  explained by its guide.
- **"the scout becomes true eyes that lift the fog"** — this match ran under
  `"fog": true`; briefings carried only the team's union of vision
  (`league/charness.py`, `tests/test_fog.py`); the h7 moment (t=8/t=10) shows
  scout vision materially shaping a teammate's declared decision; the grid
  scout is eyes-only too (`docs/roles.md`, hash regeneration documented).
- **"deliveries can be contested and denied"** — four denial events on this
  record (seq 57, 60, 63, 65), each carrying the rule's exact reason string,
  in a standoff both teams entered with open eyes.
- **"every mind — grid or continuous — receives the same spoken contract"** —
  all six seats got `SEAT_CONTRACT` at first contact from the harness itself
  (`league/charness.py`, `tests/test_charness_contract.py`);
  `scripts/cseat_driver.py` carries zero rules prose; the minds' correct
  completion-time arithmetic and menu discipline throughout this log are the
  contract working.

## Human review delivered (h11) — 2026-07-08

The audio verdict slot, filled. The reviewer, on the record: **"I validated
audio and the changes are great."** That closes both queued questions in one
verdict — the ambient score lands the mood directive (*"content and relaxed,
but also curious and intrigued"*) and the event layer honors the amendment
(*"soundtrack + events sounds = this recording sounds"*), rated on
`replay-preview/c8-audio-events.html` and the exported WAVs.

The same review produced the next finding, verbatim, watching **this
match's** replay artifact: *"I can only see key moments and not a full
replay / video of the movements. We need full repeat."* The continuous face
was still frame v4 — deliberately parked as a static key-moment sequence in
cycle 7 — so the first fogged live match was being judged through the
minimal face. That un-parking became **frame v5** (the full replay:
transport, movement interpolated from each action's own
`start_time`/`completion_time`/`target_pos` record, seekable feed rows, and
the audio layer inherited from the one canonical table —
`docs/replay-design.md`, "Continuous face"); this match's committed
`frontier-live.replay.html` is regenerated through it, so the standoff can
now be *watched*: both harvesters converging on the shared bank, the
defenders parked at their spawn and post, and the two mutual denials
thudding at t=23 and t=29 (seq 57/60 and 63/65) with the note toggle on.
