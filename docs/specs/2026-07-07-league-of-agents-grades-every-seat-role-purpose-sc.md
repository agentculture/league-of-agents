# League of Agents grades every seat: role-purpose scorecards name each match's MVP and LVP, the scout becomes true eyes that lift the fog, deliveries can be contested and denied, and every mind — grid or continuous — receives the same spoken contract

> League of Agents grades every seat: role-purpose scorecards name each match's MVP and LVP, the scout becomes true eyes that lift the fog, deliveries can be contested and denied, and every mind — grid or continuous — receives the same spoken contract

## Audience

- The human reviewer judging replays (who asked for MVP/LVP because the guide made them judge one level deeper than it explained); researchers comparing role compositions and individual contribution across teams; the maintainers keeping per-unit scoring honest beside the untouched team axes

## Before → After

- Before: Scoring stops at the team: outcome, cooperation v0/v1, tempo t0 and probe p0 are all team-level, so the first human review had to eyeball that red's defender flopped — nothing in the score payload, replay, or guide names WHO carried or sank a match, or whether a unit did its ROLE's job
- Before: Roles are still blunt at the edges: the grid scout can capture posts (the eyes-only decision from the human review was applied to the continuous lane only and explicitly parked for grid); the continuous lane has per-role vision radii but its briefings are fogless full-information; and a delivery can never be contested — two units co-delivered into the same post in the reviewed match with no interaction, which the reviewer flagged as a possible lockdown-strategy hole
- Before: A grid mind receives a spoken seat prompt baked into the harness (_SEAT_PROMPT), but a continuous mind gets raw briefing JSON — the contract text lives in an operator script (scripts/cseat_driver.py), a lane-parity gap recorded as a finding in the cycle-7 live report
- After: Every committed match can answer WHO: a per-unit, role-purpose-weighted scorecard computed from the log alone names the match MVP and LVP with per-role breakdowns, and it surfaces in the score payload, the replay's side deck, and the assessor guide — the reviewer no longer judges one level deeper than the guide explains
- After: The scout is the eyes: the continuous lane gains a fog mode where a briefing shows only what your team's vision radii reveal (the scout's widest-among-executors vision finally does strategic work), the grid lane's eyes-only-scout default is decided and recorded rather than parked, and deliveries have explicit contention rules — a defended post can deny or delay a handover, making lockdown a legal strategy instead of an accident of no-rules
- After: Lane parity in the mind-facing contract: the continuous harness speaks the same kind of baked-in seat contract the grid harness always had, for all five driver kinds, so an external driver script no longer owns the rules of the game; and the committed cycle-6 artifacts are regenerated through the current replay/GIF pipeline as a deliberate, documented event

## Why it matters

- Issue #1 asks that the system "scores both mission outcome and cooperation quality" and that "logs/replays make it inspectable — why a team succeeded or failed": team axes answer WHETHER a team cohered, per-unit role-purpose grades answer WHO made it so — and issue #1's "roles/specialization matter" only bites if a role's constraints (eyes that cannot capture, deliveries that can be denied) are real rules with visible consequences

## Requirements

- MVP/LVP per-unit grades (user directive, human review): each unit earns a grade from the log alone, weighted by its role's designated purpose — on-purpose contributions score full, off-role contributions still score but at a discount ("a scout not scouting should still get points, but less") — and the payload names the match MVP and LVP; the existing team axes (outcome, cooperation v0/v1, tempo t0, probe p0) are bit-identical untouched: this is a NEW axis beside them, never a drift inside them
  - honesty: Team axes provably untouched: the committed season-0/cycle-4/5/6 score.json files re-score bit-identically after the MVP/LVP axis lands, and the grade is a pure function of the log (same log -> same grades, proven the determinism way); off-role work scores strictly more than zero and strictly less than the same work done on-role, proven by a worked test case
- Scout as eyes (user directive, human review): the continuous lane gets a fog mode — briefings show only what the acting team's per-role vision radii reveal, with the scout the widest executor — while ground truth stays full in the log for replay/scoring; and the grid lane's eyes-only-scout question is closed with a recorded decision this cycle, whichever way it goes
  - honesty: Fog is projection, never mutation: the continuous log still records ground truth (replay and scoring unchanged by fog); a fogged briefing contains exactly the entities within the team's union of vision radii, proven by a test with a hand-placed board; the grid decision is recorded in docs with its rationale even if the decision is 'grid keeps capturing scouts'
- Delivery contention (user directive, human review): explicit, deterministic engine rules in the continuous lane for contested handovers — at minimum, whether and how a defending presence at a delivery site denies or delays an enemy delivery, and what two same-team simultaneous deliveries do — as first-class tested rules with log events, not emergent accidents
  - honesty: Contention rules are deterministic and first-class: every contested-delivery outcome is an explicit log event with a reason, the canonical-order tie-break applies to simultaneous handovers, and the rules are exercised by scripted tests that construct each contested case (deny, delay, same-team co-delivery) rather than hoping a live match wanders into them
- Harness contract parity (cycle-7 finding, all-backends rule): league/charness.py bakes the mind-facing seat contract into first contact for command and resident drivers (the continuous twin of the grid's _SEAT_PROMPT), scripts/cseat_driver.py thins to transport-only, and the contract text never leaks engine internals beyond what the briefing already exposes
  - honesty: Parity without leakage: the baked contract text tells a continuous mind exactly what scripts/cseat_driver.py told it in cycle 7 (reply shape, time model, race semantics, menu discipline) and nothing the briefing does not already expose; all five driver kinds get it per the all-backends rule; the cycle-7 live config re-run against the thinned driver still produces a legal, finishable match
- Committed-artifact refresh: the cycle-6 playtest replay/GIF artifacts are regenerated through the current pipeline as a deliberate, documented event in the PR (the committed memory-longhorizon.gif still shows the pre-restyle face), with logs and scores untouched — the compat sweep proves the facts did not move
  - honesty: Refresh is regeneration, not revision: only presentation artifacts (replay.html, gif) change bytes; every log.jsonl, score.json, probe.json and outcome.json is byte-identical before and after, enforced by the compat sweep staying green with no fixture edits in the refresh commit
- Audio (user directive, verbatim mood): the experience gains music that is "pleasant… complement the experience and make me feel content and relaxed, but also curious and intrigued" — in the HTML replay as a runtime-synthesized generative ambient score (WebAudio, seeded deterministically from the match, no audio files, the document stays self-contained and byte-identical), and in exported video as an offline-synthesized soundtrack (pure-stdlib WAV generation muxed by the existing optional ffmpeg path into MP4)
  - honesty: Audio respects every standing invariant: the HTML document's bytes are unchanged by the feature's runtime behavior (music is synthesized at play time, seeded from data already in the page), no external asset or network request appears, audio is OFF by default with a visible toggle (browser autoplay policy and reviewer choice), the same match always plays the same score, and the format truth is documented honestly — MP4 gains the soundtrack, GIF stays silent because the format has no audio
  - honesty: The mood brief is testable at review: the next human review explicitly rates whether the music lands "content and relaxed, but also curious and intrigued" — a recorded reviewer verdict, not a developer assertion; if it misses, the miss is a finding for the next cycle, not a silent pass

## Honesty conditions

- Every announcement phrase is backed by a committed artifact in the cycle PR: the scorecard axis with MVP/LVP in payload+replay+guide, the fogged continuous mode and the recorded grid decision, the delivery-contention rules with their scripted tests, the baked charness contract with the thinned driver, and the refreshed cycle-6 artifacts — closed out in a ledger the report maps phrase-by-phrase
- Each named audience touches the increment on the record: the reviewer gets the scorecard in payload/replay/guide and a recorded verdict slot in the next review, researchers get a report with per-unit breakdowns they can dissect, maintainers get the diff-provable untouched-axes tests
- The deficiency cites its sources: scoring.py/tempo.py/probe.py expose team-keyed payloads only (no per-unit surface), and the MVP/LVP ask is quoted verbatim from the recorded human review (docs/playtests/cycle-6/human-review.md), not paraphrased
- Each blunt edge cites code or log: grid scout capture via RoleStats defaults in league/engine/scenario.py, the fogless briefing via charness._board_projection's own full-information docstring, and the uncontested co-delivery moment in the committed cycle-6 match log the reviewer flagged
- The parity gap cites both sides: league/harness.py's baked _SEAT_PROMPT versus league/charness.py handing drivers raw briefing JSON with the contract living in scripts/cseat_driver.py — exactly as recorded in the cycle-7 live report's findings
- The reviewer test: the next human review can name the best and worst unit from the payload/replay/guide alone without watching the match twice — the guide explains what the grade weighs and shows the per-role breakdown beside the board
- Eyes do work on the record: a live fogged match shows a scout's vision materially changing a teammate's decision (the enemy/objective it revealed is cited in a message or plan), so 'the eyes' is demonstrated, not asserted
- One contract, one source of truth: after the parity change there is exactly one place the continuous seat contract lives (charness), the operator script contains zero rules prose, and docs/continuous-contract.md matches what minds actually receive
- The why quotes issue #1's own words — "scores both mission outcome and cooperation quality", "logs/replays make it inspectable", "roles/specialization matter" — quoted, not strengthened, and the report ties each new mechanic back to the phrase it serves
- Boundary checkable in review: no ranking/ELO surface exists anywhere in the payload or CLI; grades never feed team scores; the determinism gates and team-axis formulas are diff-provably untouched; no combat mechanics appear
- The success signal is verifiable by pointing at committed artifacts: the fogged live log with its contested-delivery events, the payload naming MVP/LVP, the replay/guide surfacing them, the refreshed cycle-6 artifacts, and the green sweep — all in one PR

## Success signals

- A recorded live continuous match under fog, with a contested-delivery moment on the record, whose score payload names MVP and LVP with role-purpose breakdowns — visible in the replay side deck and explained by the assessor guide — plus the refreshed cycle-6 artifacts and a green two-lane suite in the same PR

## Scope / boundaries

- Not a ranking system: no ELO, no cross-match leaderboards, no model-vs-model verdicts — MVP/LVP is per-match and role-relative; determinism stays non-negotiable (fog projections and grades are pure functions of the log); the team-axis formulas (cooperation v1, tempo t0, probe p0) are unchanged for both lanes; measured tempo calibration and combat/elimination mechanics stay out

## Decisions

- User decision (2026-07-08, verbatim, added while confirming the frame): "add audio that will make experience superb. Both for the reply (html) and the videos we export. I want a pleasent music that will complement the experience and make me feel content and relaxed, but also curious and intrigued." — captured as requirement c17 with h10/h11; user confirmed all three.

## Open / follow-up

- Measured tempo calibration (replacing illustrative per-substrate baselines with measured ones) — needs accumulated seat-latency data across many live matches; the illustrative-baseline caveat stays documented
- Same-mind-two-substrates and resident-vs-stateless benchmark rows, per-seat colleague workdirs, cycle-2/3 leftover live tests — live-run backlog, not engine work; pick up when a benchmarking cycle opens
- Continuous-lane video export and span-probe generalization (GIF face and probe p0 read grid logs only) — the minimal continuous replay face is the honest floor this cycle; generalize when the continuous lane earns its own visual cycle
