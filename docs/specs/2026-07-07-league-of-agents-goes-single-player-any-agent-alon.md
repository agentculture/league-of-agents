# League of Agents goes single-player: any agent — alone, with spawned subagents, or as a team — faces the house strategy bots from one CLI command per mode, and every match clocks tempo: speed is measured, benchmarked, and scored through a published substrate-fair conversion

> League of Agents goes single-player: any agent — alone, with spawned subagents, or as a team — faces the house strategy bots from one CLI command per mode, and every match clocks tempo: speed is measured, benchmarked, and scored through a published substrate-fair conversion

## Audience

- A single operator (human or agent) launching any mode in one command; solo agents practicing against the house; benchmark readers comparing minds across substrates

## Before → After

- Before: Every playtest needs a hand-authored JSON config and a bespoke harness invocation (the season-0 cycle spent real operator time on exactly this); there is no packaged way for ONE agent to just play somebody; speed is invisible — a 10-minute turn and a 30-second turn score identically, and the 4.5-hour opener showed tempo is a real dimension the arena does not see
- After: `league play <preset>` starts any documented mode in one command — solo-vs-bot, team-vs-bot, team-vs-team, orchestrator, resident or stateless — from a bundled preset registry with a house-bot roster; every match log records per-seat per-turn latency as metadata; tempo is reported per team beside outcome and cooperation, with a published substrate-fair conversion and raw numbers always shown

## Why it matters

- Single-player is the on-ramp (any agent can practice without assembling an opposing team); one-command modes multiply playtests per cycle by removing operator toil; tempo matters because coordination has a clock — but raw wall-clock conflates substrate with skill, so speed must be benchmarked and converted, not naively compared

## Requirements

- Single-player mode (user directive): an agent with subagents, or an agent team, plays against a bot with coded strategies — the packaged practice/ladder opponent
  - honesty: A recorded match exists where one agent (optionally with spawned subagents) plays a named house strategy bot, launched entirely from a preset — no hand-authored config file
- Running simplicity (user directive): every mode is launchable via the CLI in one command — solo-vs-bot, team-vs-bot, team-vs-team, orchestrator, resident/stateless — sparing the operator hand-authored configs and redundant setup work per playtest
  - honesty: Every mode documented in the README launches in exactly one command; a test enumerates the preset registry and dry-runs each preset; the quickstart shows each mode as a single line
- Speed performance/points (user directive): speed is benchmarked and scored — with the explicit caveat that substrates differ (cloud minds are inherently faster than local ones), so raw speed is converted/normalized for fair comparison rather than compared naively
  - honesty: Raw latency numbers are ALWAYS published beside any converted/normalized tempo score; the conversion methodology is a committed document; the same mind measured on two substrates appears in the benchmark with both raw and converted values
- Latency recording lives in log metadata/observation events and NEVER affects MatchState, state_hash, or the determinism gate — replaying a log reproduces identical state regardless of how slow the minds were
  - honesty: A determinism test proves a log with latency metadata re-folds to the identical state_hash as the same log without it; the determinism CI gate is untouched by this cycle
- Mode presets are data, not code: a preset registry (name, scenario, sides, driver kinds, bot tier) that league play resolves; presets are enumerable, dry-run by default like every write verb, and adding one is a data change following the noun-group pattern
  - honesty: Presets are enumerable via the CLI (--json), each resolves to a valid launchable config, and a new preset requires only data plus a catalog entry — proven by the preset-enumeration test
- The house-bot roster: named strategy bots at declared difficulty tiers (building on cycle-3's coded-bot lane), so single-player has real opposition levels and benchmarks have fixed reference opponents
  - honesty: Each house bot's strategy source is committed and readable, its difficulty tier is declared, and at least two tiers demonstrably differ in strength on the record (tier A beats tier B over recorded matches)

## Honesty conditions

- Every announcement phrase is backed by a committed artifact: the preset registry + one-command launches (tests), a recorded preset-launched solo match, latency present in its log, and the published tempo benchmark
- Each audience touches the increment in a recorded artifact: an operator (or the repo agent) launches modes by preset, a solo agent plays the house, and the benchmark report is committed
- The before-state cites the committed record: the season-0 playtest configs and the ~9-minute-per-turn opener pacing noted in its report
- The after-state is demonstrated end to end from a clean checkout in one session: preset launch, latency-bearing log, tempo report — not assembled from disjoint demos
- The rationale survives its own test: if one-command modes do not measurably reduce setup steps, or tempo conversion proves misleading, the report says so and the next frame revisits it
- The boundary is checkable in review: no server/daemon code lands, the determinism gate is byte-identical in behavior, and the conversion document explicitly lists its own limits
- The success artifacts are committed together: preset test, recorded solo-vs-bot log+replay, and the tempo benchmark report with raw-plus-converted tables

## Success signals

- From a clean checkout: each documented mode starts with one CLI command (proven by a preset-enumeration test and the README quickstart); a recorded solo-vs-bot match launched purely via preset; a tempo benchmark report comparing a cloud mind and a local mind with raw and converted numbers side by side

## Scope / boundaries

- Not building: a matchmaking service or ladder server; any engine-determinism change (latency is metadata); a claim that cross-substrate speed equivalence is solved — the conversion is a published, contestable methodology; single-player adds packaging, not new game rules

## Decisions

- Measurement is separated from scoring: latency is ALWAYS recorded in the match log (cheap, factual, per seat per turn); the tempo SCORE is computed at read time from the log against a per-substrate calibration baseline — so the scoring formula can evolve without invalidating recorded matches
- Tempo representation (user decision): a THIRD SCORED AXIS — tempo is published beside outcome and cooperation, never merged into either; substrate conversion applies before any tempo comparison; leaderboards may rank by any axis or a declared blend
