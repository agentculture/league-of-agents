# Build Plan — League of Agents grades every seat: role-purpose scorecards name each match's MVP and LVP, the scout becomes true eyes that lift the fog, deliveries can be contested and denied, and every mind — grid or continuous — receives the same spoken contract

slug: `league-of-agents-grades-every-seat-role-purpose-sc` · status: `exported` · from frame: `league-of-agents-grades-every-seat-role-purpose-sc`

> League of Agents grades every seat: role-purpose scorecards name each match's MVP and LVP, the scout becomes true eyes that lift the fog, deliveries can be contested and denied, and every mind — grid or continuous — receives the same spoken contract

## Tasks

### t1 — Grid per-unit scorecard engine: role-purpose-weighted grades from the log alone (new league/engine/grades.py)

- covers: c10, h1, c3, h16, c6
- acceptance:
  - grade_units(log) is a pure function of the log: per-unit grade with a per-role-purpose breakdown, MVP and LVP named with deterministic tie-break; same log twice -> identical payload
  - off-role contribution scores strictly more than zero and strictly less than the identical contribution made on-role, proven by a worked two-unit test case
  - every committed grid score.json re-scores bit-identically after this lands (team axes untouched), and grades.py imports no scoring/tempo/probe module (AST-checked)

### t2 — Continuous per-unit scorecard engine: the same grade contract for continuous logs (new league/engine/continuous/grades.py)

- covers: c10, h1, c6
- acceptance:
  - cgrade_units(clog) mirrors the grid grade contract for continuous role purposes (defender race/hold, harvester economy, scout eyes once fog lands), pure function of the log, MVP/LVP with the canonical tie-break
  - the two-lane boundary holds: no import in either direction between grades modules and the other lane (extends tests/test_two_lane_honesty.py), and the committed c-race-live outcome.json is untouched

### t3 — Delivery contention rules in the continuous resolver: deny, delay, and same-team co-delivery as explicit deterministic rules

- covers: c12, h3, c4, h17, c7
- acceptance:
  - each contested case is a scripted test constructing it directly: an enemy presence at the delivery site denies-or-delays per the documented rule, same-team simultaneous deliveries resolve by canonical order, and every outcome lands as an explicit log event with a reason
  - rules are additive for uncontested play: the committed continuous determinism hash is unchanged (c-skirmish-1 has no contested delivery), asserted in the PR; if a rule change ever forces regeneration it is a documented event, not silent

### t4 — Generative ambient score in the HTML replay: WebAudio synthesis, seeded from the match, off by default

- covers: c17, h10, c9, h12
- acceptance:
  - the document stays byte-deterministic and self-contained: no audio file, no external request; the score is synthesized at play time from a seed derived from data already in the page, so the same match always plays the same music
  - audio is OFF by default with a visible accessible toggle in the transport; enabling never changes the document; the mood brief (content/relaxed yet curious/intrigued) is written into the guide as what the reviewer should rate

### t5 — Continuous fog mode: briefings filtered by the team's union of vision radii — projection, never mutation

- covers: c11, h2, c7, c4
- acceptance:
  - with fog enabled in the match config, a briefing's board shows exactly the entities within the acting team's union of per-role vision radii (hand-placed-board test proves inclusion AND exclusion at the radius boundary); the log still records ground truth and replay/scoring are unchanged by fog
  - the scout's widest-among-executors vision is the fog lever: a test shows an entity visible to the scout-bearing team and invisible to the same team without its scout

### t6 — Score CLI surface: league match score gains the per-unit scorecard and names MVP/LVP, both lanes

- depends on: t1, t2
- covers: c6, c10, c15, h13
- acceptance:
  - `league match score <id> --json` carries a units section (grade, per-purpose breakdown, mvp/lvp flags) beside the untouched team axes for grid logs, and the continuous score path exposes the same shape; text mode renders a readable scorecard; explain catalog updated (test_every_catalog_path_resolves green)
  - no ranking surface exists: grades never feed team scores and no cross-match aggregation verb appears (boundary test)

### t7 — Harness contract parity: charness bakes the seat contract; scripts/cseat_driver.py thins to transport-only

- depends on: t5
- covers: c13, h4, c5, h18, c8, h8
- acceptance:
  - first contact for command and resident drivers carries the baked contract (reply shape, time model, race semantics, menu discipline — the cycle-7 driver text, including fog wording once t5 lands); later decision points are deltas; all five driver kinds covered per the all-backends rule (test parametrizes kinds)
  - scripts/cseat_driver.py contains zero rules prose (transport only) and docs/continuous-contract.md matches what minds actually receive; the contract text exposes nothing the briefing does not already expose (leakage test mirrors the grid harness's own)

### t8 — Replay surfaces the scorecard: MVP/LVP and per-unit grades in the side deck and assessor guide, both replay faces

- depends on: t1, t2, t4
- covers: c6, h6, c2, h15
- acceptance:
  - the grid replay's tabbed deck gains a Scorecard tab (units ranked by grade, MVP/LVP chips, per-purpose breakdown) and the guide explains exactly what the grade weighs; the continuous face lists the same facts in its minimal idiom
  - the reviewer test is honored: payload, replay and guide alone name best/worst unit and why — asserted structurally (the guide text names the weights; the deck renders every unit's breakdown)

### t9 — MP4 soundtrack: pure-stdlib WAV synthesis muxed by the existing ffmpeg path; GIF stays silent by documented format truth

- depends on: t4, t6
- covers: c17, h10, h11
- acceptance:
  - league/replay/audio.py synthesizes a deterministic ambient WAV from the same match seed the HTML score uses (same log -> byte-identical WAV, unit-tested); league match record --format mp4 muxes it via the existing optional-ffmpeg path; --format gif output is byte-unchanged and the docs state why GIF has no audio
  - the mood target is recorded verbatim in docs/replay-design.md with the reviewer-verdict obligation (h11) — the next human review rates it on the record

### t10 — Grid eyes-only-scout decision: closed and recorded, whichever way it goes

- covers: c11, h2, c4
- acceptance:
  - a decision section in docs/roles.md records the grid call with rationale (user decides at the split-plan gate): either grid scout loses can_capture — with the grid determinism hash regenerated as a documented deliberate event — or grid deliberately keeps capturing scouts with the reasoning written down; tests match whichever is decided

### t11 — Cycle-6 artifact refresh: presentation bytes regenerated through the current pipeline, facts untouched

- depends on: t8, t9
- covers: c14, h5, c8
- acceptance:
  - every cycle-6 replay.html and gif is regenerated with the shipped 0.11.1+ pipeline (new scorecard tab included); every log.jsonl, score.json, probe.json, outcome.json is byte-identical before and after (asserted in the PR by diff and by the untouched compat sweep fixtures)

### t12 — The graded, fogged live match: contested delivery on the record, MVP/LVP named, cycle report with closing ledger

- depends on: t3, t6, t7, t8, t9, t10, t11
- covers: c16, h14, c1, h9, c9, h12, c2, h15, h6, h7, h11
- acceptance:
  - a recorded live continuous match under fog is committed (config, log, outcome, replay, report) in which a contested-delivery moment actually happened — cited to exact events — and a scout's vision materially changed a teammate's decision on the record (h7)
  - the score payload names MVP and LVP with per-purpose breakdowns, surfaced in the replay deck and explained by the guide; the report quotes issue #1 verbatim, cites every before-state source, states which audience each artifact serves, and closes the ledger phrase-by-phrase; the audio mood verdict slot is queued for the next human review

## Risks

- [unknown_nonblocking] Exact MVP/LVP formula shape (event-kind -> role-purpose weights) — pinned by t1/t2's tests at implementation, not guessed here
- [unknown_nonblocking] Grid eyes-only decision may regenerate the grid determinism hash — allowed only as the documented deliberate event t10 describes, decided by the user at the split-plan gate
- [unknown_nonblocking] Live fogged match must produce a contested delivery organically; if live minds never contest, t12 re-runs with a scenario whose geometry forces the contest (scripted fallback stays out of the live claim)
