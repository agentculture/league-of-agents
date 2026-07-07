# Build Plan — League of Agents goes single-player: any agent — alone, with spawned subagents, or as a team — faces the house strategy bots from one CLI command per mode, and every match clocks tempo: speed is measured, benchmarked, and scored through a published substrate-fair conversion

slug: `league-of-agents-goes-single-player-any-agent-alon` · status: `exported` · from frame: `league-of-agents-goes-single-player-any-agent-alon`

> League of Agents goes single-player: any agent — alone, with spawned subagents, or as a team — faces the house strategy bots from one CLI command per mode, and every match clocks tempo: speed is measured, benchmarked, and scored through a published substrate-fair conversion

## Tasks

### t1 — Latency metadata in the match log (harness-side, never state)

- covers: c10, h9
- acceptance:
  - Harness records per-seat per-turn wall-clock latency as log metadata; MatchState, state_hash and apply_event folding are unchanged by its presence
  - A determinism test folds the same log with and without latency metadata to the identical state_hash; tests/fixtures/determinism.hash is untouched

### t2 — Preset registry: modes as data, not code

- covers: c11, h10
- acceptance:
  - A bundled registry maps preset name to scenario, sides, driver kinds and bot tier; presets enumerate via the CLI with --json
  - A preset-enumeration test dry-runs every registered preset and asserts each resolves to a valid launchable config
  - Adding a preset requires only a data entry plus an explain-catalog entry

### t3 — `league play <preset>`: one-command launch noun group

- depends on: t2
- covers: c3, h3, c7
- acceptance:
  - Every documented mode (solo-vs-bot, team-vs-bot, team-vs-team, orchestrator, resident/stateless) launches with exactly one CLI command
  - The play group exposes overview, every path has an explain catalog entry, and test_every_catalog_path_resolves passes
  - README quickstart shows each mode as a single line

### t4 — House-bot roster: named strategies at declared difficulty tiers

- covers: c12, h11
- acceptance:
  - At least three named strategy bots in bots/ with declared tiers, committed readable source, playing through the public CLI surface only
  - Recorded matches on the record show a higher tier beating a lower tier

### t5 — Tempo axis: read-time scoring with substrate conversion

- depends on: t1
- covers: c4, h4
- acceptance:
  - Tempo score is computed at read time from log latency metadata against a per-substrate calibration baseline; recorded logs are never invalidated by formula changes
  - Every surface that prints a converted tempo score prints raw latency beside it; tempo is a third axis beside outcome and cooperation, never merged into either

### t6 — Tempo conversion methodology document

- depends on: t5
- covers: c4, h4, h12
- acceptance:
  - A committed docs/ methodology document explains the calibration and conversion, explicitly lists its own limits, and is linked from the score surface and README

### t7 — Recorded preset-launched solo-vs-bot playtest

- depends on: t3, t4
- covers: c2, h2, c5, h5, c6, h6
- acceptance:
  - A committed report + log + replay where one agent (optionally with spawned subagents) plays a named house bot, launched purely from a preset with no hand-authored config
  - The report cites the before-state record (season-0 hand-authored configs, the ~9-minute-per-turn opener pacing) and states which audience each artifact serves

### t8 — Tempo benchmark report: cloud mind vs local mind

- depends on: t1, t5, t6
- covers: c8, h8, c14
- acceptance:
  - A committed benchmark report compares a cloud mind and a local mind with raw and converted numbers side by side (same mind on two substrates where feasible)
  - The report tests the rationale: if the conversion misleads or one-command modes did not reduce setup steps, it says so for the next frame

### t9 — Clean-checkout end-to-end demo + boundary review

- depends on: t3, t5
- covers: c1, h1, h7, c13, h12, c14, h13
- acceptance:
  - From a clean checkout in one session: preset launch, latency-bearing log, tempo report — recorded as a committed transcript/report, not assembled from disjoint demos
  - A review checklist confirms no server/daemon code landed, the determinism gate is byte-identical in behavior, and the success artifacts (preset test, solo match log+replay, benchmark report) are committed together
