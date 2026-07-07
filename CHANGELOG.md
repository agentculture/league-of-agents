# Changelog

All notable changes to this project will be documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/). This project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

<<<<<<< HEAD
## [0.11.1] - 2026-07-08

### Changed

- GIF turn/tween frames now mirror the HTML replay's play view: the board card raster — card surface with header row (title, team chips with live scores, turn readout) and HTML-parity mark geometry — replacing the PR #20 board-panel layout, per direct user comparison feedback

=======
<<<<<<< HEAD
## [0.11.0] - 2026-07-08

### Added

- Continuous engine lane (league/engine/continuous/): exact fixed-point milliunit positions (SCALE=1000, integer isqrt), event-timeline initiative with integer game time and the canonical (time, team_id, unit_id) tie-break, explicit race semantics (concurrent takers on a control point; the losing mid-take attempt fails first-class with "post taken by a faster agent"), role-given in-game speed (CRoleStats), a shared legality/duration oracle, the c-skirmish-1 scenario, and the lane's own scripted determinism gate with a committed hash
- Continuous mind-facing contract and harness (league/charness.py): decision points on unit-idle, briefings carrying menu durations, absolute completion times and the initiative outlook, all five driver kinds per the all-backends rule, seat_latency observations, and a substrate-independence proof (thinking time never advances game time)
- Continuous replay face (league/replay/chtml.py): the race made visible (race-win/race-fail moments, dashed concurrent-taker rings); league match replay detects the lane from the log itself — grid output pinned byte-identical
- Eyes-only scout in the continuous role table (human-review decision): can_take_post withdrawn, gather/carry/deliver/vision unchanged; c-skirmish-1 recast defender-vs-harvester and the continuous determinism hash deliberately regenerated with documented provenance
- Two-lane honesty enforced by tests: the AST-ban walk provably covers the continuous package, grid scoring axes (cooperation v1 / tempo t0 / probe p0) and the continuous lane cannot import each other, both determinism hash fixtures fenced byte-exact; continuous scoring is outcome-only this cycle by documented decision (docs/continuous-contract.md)
- First continuous live playtest (docs/playtests/cycle-7/race-live.*): four resident claude seats, the race live and unscripted at t=8, 19-0 at t=14; fielded via scripts/cseat_driver.py and scripts/run_cmatch.py
- Committed-logs compat sweep extended two-lane: lane detection from each log's own header, continuous logs fold through CMatchLog and pin outcomes via *.outcome.json, grid logs sweep unchanged, anti-vacuity floors on both lanes

### Changed

- Grid-replay byte-identity pin in tests re-anchored to the restyled grid face (PR #18); docs/playtests/README.md gains its missing cycle-6 row plus the cycle-7 row
=======
>>>>>>> origin/main
## [0.10.3] - 2026-07-08

### Changed

- GIF/video face recomposed to the mesmerizing design system: centered title lockup, board-hero turn frames with hairline grid + unit rings + score footer, big-numeral closing card, typographic hierarchy via scaled glyphs — both themes, same indices
>>>>>>> origin/main

## [0.10.2] - 2026-07-07

### Added

- Replay + video restyle from the first human review: Anthropic-cream light and Culture black-green dark themes (validator-passing, worst adjacent CVD dE 86.7 light / 85.7 dark), team identity moves to clay vs violet, chrome-green accent
- 100% smooth playback: linear gapless waypoint flow while playing (eased snap only when paused), GIF gains deterministic tween frames (--tween, default 4) and a --theme light|dark flag
- Tabbed side deck: Guide/Events/Teams/Score beside the sticky board hero — the assessor guide no longer scrolls away from the board

## [0.10.1] - 2026-07-07

### Added

- Cycle-6 closure: the long-horizon memory playtest (resident sonnet 56-16 over gold on a generated 21x17/60-turn board; first perfect cooperation v1; residency measured as a 6.5x tempo lever), the two-mind span-of-control comparison (sonnet 100 vs colleague 98 on the same fogged board; commanding costs ~3x obeying on the colleague substrate), the first human review through the new stack (7 findings recorded verbatim, 3 already commissioned), and the closure ledger mapping every announcement thread to its artifact

## [0.10.0] - 2026-07-07

### Added

- Seeded scenario generator: `gen-<seed>-...` ids fully encode seed+params (any match re-creatable from its log header), 180-degree rotational fairness proven by property tests, boards to 41x41 / 200 turns / 8 objective pairs / executor_scale rosters up to 14 units
- Coding-reflective roles: explorer (extended vision/reach, gather+capture rejected by engine legality) and planner (coordination-only) in the new recon-1 scenario, each documenting its software-work analog (docs/roles.md); scout/harvester/defender byte-identical
- The mesmerizing replay: validated palette (CVD-safe both themes), deliberately designed dark+light with toggle, purposeful motion behind prefers-reduced-motion, zero anti-pattern hits (docs/replay-design.md), byte-deterministic
- Embedded assessor guide: per-scenario, phase-by-phase judging guidance derived from THIS match's log — key moments as #tN scrub links, cooperation-v1 numbers explained, real-vs-pseudo delegation taught
- Video export: league match record renders any committed log to a shareable GIF offline via a pure-stdlib GIF89a writer (tests ship their own decoder); optional --format mp4 via ffmpeg on PATH; provenance embedded in the file
- Span-of-control probe (p0): league match probe measures span, per-seat realization, guidance linkage and a degradation curve from log evidence alone — claimed delegation without evidence scores zero
- Committed-log compatibility sweep: every docs/playtests log must fold to its recorded outcome (the additive-engine-changes tripwire) + docs/playtests/README.md index

### Changed

- instantiate() no longer collapses duplicate-role agents (real bug found by the executor_scale work)
- league/replay exports palette constants shared by the HTML and GIF renderers

## [0.9.3] - 2026-07-07

### Added

- Cycle-7 spec (devague /think): the continuous arena — decimal fixed-point positions, role-given in-game speed decoupled from substrate wall-clock, tick/timeline-based initiative (user decision c13: still turn-based, hardware nullified; turn ORDER is speed-based with action time costs), race semantics with first-class failed attempts, two engine lanes with the grid untouched — 12 user-confirmed claims, 12 honesty conditions, 4 parked unknowns pinned to plan tasks
- Cycle-7 build plan (devague /spec-to-plan): 10 user-confirmed tasks over 7 waves — spatial core, initiative timeline, continuous state/events, role durations, the race resolver, its own determinism gate, the mind-facing decision-point contract, two-lane honesty, the minimal race-visible replay face, the recorded race match

## [0.9.2] - 2026-07-07

### Added

- Live playtest: colleague guild in cooperative mode — three per-seat colleague-agent seats (local Qwen via lobes) finish the whole board by turn 16 with cooperation v1 = 99 (52/52 useful messages), where the same mind solo hit the turn-30 limit at 14 points; caveats (solo handicap, no opponent in cooperative mode) stated in the report

## [0.9.1] - 2026-07-07

### Added

- Cycle-6 spec (devague /think): the watchable, vast arena — mesmerizing replay + embedded assessor guide, video export from logs, seeded scenario generation at any scale, board size/complexity for long-horizon + memory assessment, subagent span-of-control probe, coding-reflective roles (explorer/planner/executor) — 13 user-confirmed claims, 13 honesty conditions, 4 parked unknowns
- Cycle-6 build plan (devague /spec-to-plan): 12 user-confirmed tasks over 5 waves, risks pinned to tasks

## [0.9.0] - 2026-07-07

### Added

- league play noun group + bundled preset registry: five one-command modes (solo-vs-bot, team-vs-bot, team-vs-team, orchestrator-vs-bot, resident-vs-bot), dry-run by default
- seat_latency observation events: every driver call measured harness-side; fold no-op, determinism hash untouched
- Tempo, the third scored axis (t0): read-time scoring against declared per-substrate baselines, raw always beside converted; methodology + limits in docs/tempo-methodology.md
- House-bot tier roster: shambler (bronze), rusher (silver), vanguard (gold) + recorded tier-ordering matches under docs/playtests/house-tiers/
- Fog-aware bot lane: lampbearer (silver) reads only the fogged JSON surface, spy-test enforced; bot-file driver gains an opt-in fogged flag
- Cooperation metric v1: rejection-taxed delegation_spread, message content utility over cadence, plan fidelity, pseudo-coordination priced; v0 kept bit-identical, season-0 re-scored side by side in docs/playtests/season-0/cooperation-v1.report.md
- Stacked-train release workflow doc (docs/process/release-train.md) recording the 0.5.0-0.8.0 train's real failure modes and the per-merge publish decision
- Cycle-4 playtests: preset-launched solo sonnet vs the named silver house bot (26-2, all three axes recorded) and the clean-checkout end-to-end demo with the boundary review checklist
- Cross-repo: devague resolve-verb gap filed upstream (agentculture/devague#60) with hand-edit evidence

### Changed

- solo-vs-bot preset faces the named silver strategy (bots/rusher.py) instead of the in-harness greedy baseline

## [0.8.1] - 2026-07-07

### Added

- Cycle-5 spec (devague /think): arena hardening — the five adopted improvement threads (pending cycle-2/3 live tests, cooperation scoring v1, fog-aware bot lane, stacked-train workflow doc, cross-repo devague resolve-verb gap) as user-confirmed requirements, publish-cadence decision (keep per-merge), honesty h1-h13
- Build plan for cycle 4 (devague /spec-to-plan): 9 user-confirmed tasks over 4 waves — latency metadata, preset registry, league play noun group, house-bot tiers, tempo axis with substrate conversion, methodology doc, recorded playtests and benchmark
- Build plan for cycle 5 (devague /spec-to-plan): 7 user-confirmed tasks over 3 waves — cooperation v1, season-0 re-score, fog-aware bots, release-train doc, upstream devague issue, live closure matches (lobes-gated), closure ledger

## [0.8.0] - 2026-07-07

### Added

- Cycle 2 (resident minds): legal-actions surface in match show --json; rejection reasons + legal actions in every next-turn briefing; resident driver (one session per seat, delta briefings, per-seat audit transcripts; claude-cli + colleague-direct transports); residency recorded as a declared fairness axis (--driver, log header); cultureagent session spike note
- Cycle 3 (fog + faces): per-role vision engine (scout sees farther); per-team knowledge fold (seen vs told, derived from the log); skirmish-2 Fogbound Crossing with coordination-necessity re-proven by arithmetic; fog-aware briefings (out-of-vision facts arrive only via logged messages); coded-strategy bot lane (bots/, public-JSON-only, rusher reference); TUI face (match tui, truth/knowledge toggle); agentfront runtime adoption + markdown face (match brief, face-agreement tests); orchestrator declared map-read capability + unit-comms fairness flag

### Changed

- Dead-heats are dual award (user decision c15): simultaneous mission completion pays both teams in full; the lexicographic tiebreak is deleted and outcomes are team-id-swap invariant by test (determinism fixture regenerated once, deliberately)
- First runtime dependency: agentfront>=0.20 (user decision c17) — faces layer only; an AST test keeps the engine stdlib-pure
- PR #9/#10 review hardening folded in during the merge-train restack: `_as_list` coercion on every driver-JSON list field (including the orchestrator master path), circle fan-out for 5+ stacked units, driver-script top-level error guards, deliver legality mirrors resolve_turn, TUI requires stdin+stdout ttys

## [0.7.3] - 2026-07-07

### Added

- Cycle-4 spec (devague, converged): single-player mode vs house strategy bots, one-command mode presets (league play), and tempo as a third scored axis with substrate-fair conversion (user decisions: third axis; measurement separated from scoring)

## [0.7.2] - 2026-07-07

### Added

- Cycle-3 spec + plan (devague): AgentFront audience-typed faces (markdown/TUI+HTML/JSON), fog of war with per-role line of sight, orchestrator as a real game mode, coded-strategy bots as opponents — frame converged on user confirmations, with the agentfront dependency unknown resolved by user decision c17 (runtime import); the earlier parked draft of this frame is superseded by the converged spec + 10-task/6-wave plan

## [0.7.1] - 2026-07-07

### Added

- Cycle-2 spec + plan (devague): seats become resident minds — one persistent session per seat with delta briefings; legal-by-construction orders (legal-actions surface + rejection feedback); dual-award dead-heat rule (user decision); residency as a declared fairness axis; resident-vs-stateless comparison as the success signal

## [0.7.0] - 2026-07-07

### Added

- Season-0 playtest wave complete: opener (Sonnet 23-10 Qwen, h17/h18 verified), coordination-necessity (h9 not demonstrated, recorded), orchestrator subagent mode (h8 demonstrated, dead-heat finding); resilient live-driver harness (per-seat minds, solo handicap, retry-and-idle); colleague_driver.py fields colleague as an agent; replay legibility fixes from human review (stacked-unit fan-out, mission labels, #tN deep links)

### Fixed

- replay: co-located units no longer occlude each other; mission squares labeled with completion credit; playtests branch rebased to include the PR #5 XSS/traversal fixes

## [0.6.0] - 2026-07-07

### Added

- Deterministic arena engine: immutable match state, event-log single source of truth, skirmish-1 scenario (coop + competitive from one definition), pure seedable tick with canonical-order resolution
- Dual scoring from the log alone: mission outcome + cooperation quality (4 documented weighted signals) with legibility guarantees
- Self-contained HTML match replay (validated blue/red palette, light+dark themes) rendered from the same fold as --json
- CLI noun groups: league arena|team|match (+ rematch), standings/history trend verbs, harness noun — all write verbs dry-run by default with --apply
- Determinism CI gate: canonical scripted match replayed against a committed end-state hash on every PR
- Agent-player harness: bot + command drivers playing full matches through the public CLI surface only
- docs/process/cycle.md: the operable spec→plan→implement→live-test cycle with the live-test-between-specs rule

## [0.5.0] - 2026-07-07

### Added

- Arena season 0 spec (devague /think): deterministic matches, dual scoring (outcome + cooperation), replayable + beautiful observability, benchmarking/tracking, subagent-creation as a game mode, recursive spec→plan→implement cycle (docs/specs/)
- Arena season 0 build plan (devague /spec-to-plan): 16 user-confirmed tasks in 7 file-disjoint waves covering all 36 spec targets, incl. three playtests and the live-test-between-specs cycle rule (docs/plans/)

## [0.4.1] - 2026-07-07

### Changed

- **Re-initialized `CLAUDE.md` from the seed placeholder into a full runtime
  prompt** (`/init`). It records the two-truths framing — an agent-first CLI
  scaffold today vs. the strategic team arena it is meant to become per
  [issue #1](https://github.com/agentculture/league-of-agents/issues/1) — the
  CLI dispatch / structured-error / `explain`-catalog architecture, the
  "add a noun group" build recipe, and the mesh-identity + cite-don't-import
  conventions. Also documents the distribution-name (`league-of-agents`) vs
  console-command (`league`) split.

### Fixed

- README quickstart invoked `uv run league-of-agents <verb>`, which does not
  resolve: `league-of-agents` is the distribution name (install/publish), not
  the console script. Corrected to `uv run league <verb>`.
- `explain` catalog: added a `league` key (aliased to the root entry) so
  `league explain league` resolves. The agent-first rubric gate
  (`teken cli doctor . --strict`) derives the CLI's self-name from
  `[project.scripts]` (= `league`) and its `explain_self` check was failing
  because the catalog was keyed only on the display name `league-of-agents`.

## [0.4.0] - 2026-06-23

### Added

- **Vendored the `remember` + `recall` memory skills from eidetic-cli**
  (cite-don't-import) — the write/read halves of eidetic's shared
  `~/.eidetic/memory` surface, so this agent (Claude and its colleague backend)
  can persist facts across sessions and recall them later, sharing one store.
  `remember` drives `eidetic remember` (idempotent upsert of one JSON record or
  an NDJSON batch on stdin, dedup by id + content hash); `recall` drives
  `eidetic recall` with four search modes — exact / approximate / keyword /
  hybrid — each hit carrying text, full provenance metadata, a relevance score,
  and a freshness signal. The `.sh` wrappers are byte-verbatim from eidetic-cli
  (their first-party origin); each `SKILL.md` is localized only in the
  illustrative `--scope <nick>` examples (Provenance keeps "First-party to
  eidetic-cli"). Both default to this agent's PRIVATE scope, reading the suffix
  from `culture.yaml`. Runtime dep: the `eidetic` CLI on PATH (else a local
  eidetic-cli checkout with `uv`). Propagated by rollout-cli's `eidetic-memory`
  recipe.

## [0.3.4] - 2026-06-20

### Fixed

- Identity docs and self-description strings still claimed `backend: claude`
  (prompt file `CLAUDE.md`), but this template was promoted to a colleague
  resident in #14/#15: `culture.yaml` declares `backend: colleague` (Qwen) with
  `AGENTS.colleague.md` as the resident prompt. Corrected the stale claim in
  `CLAUDE.md` (Identity section), `README.md`, `docs/skill-sources.md`, and the
  two CLI description strings (`overview` artifacts and `explain doctor`). The
  `doctor` backend→prompt-file mapping and the tests were already on
  `colleague`; this aligns the prose and self-description with them.

## [0.3.3] - 2026-06-20

### Fixed

- pyproject.toml: correct the `license` field and PyPI classifier from MIT to
  Apache-2.0 to match the `LICENSE` file. The README License section was already
  corrected in 0.3.2, but the package metadata was missed; the built wheel now
  reports `License-Expression: Apache-2.0`.

## [0.3.2] - 2026-06-18

### Added

- ask-colleague skill: `monitor`/`guide`/`stop` pilot verbs plus a `--watch`
  flag to dispatch, watch the live feed of, send mid-flight guidance to, and
  cooperatively stop a running colleague flight (re-vendored from colleague).

### Changed

- README: correct the License section from MIT to Apache 2.0 to match the
  `LICENSE` file.

## [0.3.1] - 2026-06-13

### Changed

- CLAUDE.md: add a convention to reach for the `ask-colleague` skill reflexively
  for explore/review/write/grade — read-only `review`/`explore` are always safe;
  side-effecting `write` needs the user's go-ahead.

## [0.3.0] - 2026-06-13

### Added

- AGENTS.colleague.md resident prompt file (backend colleague <-> AGENTS.colleague.md)

### Changed

- Promote agent identity to a colleague resident: culture.yaml backend
  claude -> colleague with a pinned model. The `doctor` backend-consistency
  map gains `colleague` -> AGENTS.colleague.md.

## [0.2.1] - 2026-06-12

### Changed

- **Re-vendored the `ask-colleague` skill from colleague (now 1.7.0, up from the
  0.39.2 sync)** — the wrapper had drifted multiple releases behind origin. Picks
  up the `clean` verb (reap stale/corrupt `colleague/*` branches + orphaned
  `.colleague/` artifacts a crashed run left behind), the `--json` flag on every
  verb (result JSON on stdout, diagnostics/digest on stderr), the
  `_colleague_via_uv` local-dev resolution that honors `--repo`, and the
  tri-state (0/1/2) exit-code contract. `scripts/ask-colleague.sh` + `prompts/`
  are byte-identical to the origin; `SKILL.md` diverges only in the one
  consumer-identifying Provenance clause (`league-of-agents vendors from
  guildmaster`). `docs/skill-sources.md` sync row updated to
  `2026-06-12 (colleague 1.7.0, direct)`. Refs: colleague#183, #186.

## [0.2.0] - 2026-06-06

### Added

- **`ask-colleague` skill** (`.claude/skills/ask-colleague/`) — the first-party front door to the `colleague` CLI (the renamed `convertible`). On top of `explore` / `review` / `write` it adds a `feedback` verb (grade a finished work item — the ROI loop), and `write` now **previews by default** in a throwaway worktree (no side effects) unless `--apply` / `--pr` is given. Reach for it reflexively — `review` for a diverse second opinion on a committed diff before opening a PR, `explore` for a fresh read of an unfamiliar area.

### Changed

- **Replaced the `outsource` skill with `ask-colleague`.** `outsource` was renamed to `ask-colleague` upstream ([colleague#148](https://github.com/agentculture/colleague/pull/148)). Because guildmaster has not re-broadcast the rename yet (its kit still ships the old `outsource`), `ask-colleague` is vendored **directly from the sibling `colleague` checkout** rather than from guildmaster — a tracked local divergence recorded in `docs/skill-sources.md`, parallel to the `agex` → `devex` one. Vendored verbatim except one consumer-identifying clause in the Provenance paragraph.
- **Ledger + CLAUDE.md + `.gitignore`:** point `docs/skill-sources.md` and the CLAUDE.md Skills section at `colleague` / `ask-colleague`, swap the *optional* runtime prerequisite `convertible` → `colleague` (env prefix `CONVERTIBLE_*` → `COLLEAGUE_*`, with the legacy names kept as a deprecated fallback), and gitignore the `.colleague/` run-artifact dir the skill writes (plus the stale `.agex/`).

## [0.1.4] - 2026-05-31

### Added

- **Vendor the `outsource` skill** (`.claude/skills/outsource/`) from
  guildmaster's canonical copy (origin
  [`agentculture/convertible`](https://github.com/agentculture/convertible),
  re-broadcast via guildmaster — guildmaster
  [#51](https://github.com/agentculture/guildmaster/pull/51)). Every agent
  cloned from this template now inherits the ability to hand a scoped task to a
  *different* engine/mind: `explore` (read-only investigation), `review` (a
  diverse second opinion on the committed diff), and `write` (delegate a small
  implementation). `explore`/`review` run isolated in a throwaway `git worktree`;
  `write` refuses a dirty tree. Fulfils
  [#8](https://github.com/agentculture/league-of-agents/issues/8).
- **Ledger + CLAUDE.md:** record `outsource` in `docs/skill-sources.md`
  (origin = convertible, re-broadcast via guildmaster; vendored verbatim — it
  already carries `type: command`) and document its *optional* runtime
  dependency on the `convertible` CLI (the skill exits with an install hint if
  absent, so a clone that never uses it is unaffected).

### Changed

### Fixed

## [0.1.3] - 2026-05-31

### Changed

- Expanded the clone-and-rename instructions in `CLAUDE.md`: added `README.md` to
  the rename targets and a portable `git grep` discovery command so a cloner can
  find every occurrence of the template name (hard-coded in ~100 places across the
  package, including the CLI command files and `_ISSUES_URL` in
  `league/cli/__init__.py`) rather than renaming by hand.
- Synced `README.md`'s "Make it your own" checklist with `CLAUDE.md`: it now lists
  `README.md` itself as a rename target and points to `CLAUDE.md`'s discovery
  command as the authoritative procedure, so the two onboarding checklists no
  longer drift.

## [0.1.2] - 2026-05-30

### Changed

- Renamed the PR-lifecycle CLI references `agex` / `agex-cli` to `devex` (same
  tool, new name) across `CLAUDE.md`, `docs/skill-sources.md`, `.gitignore`, and
  the vendored `cicd`, `assign-to-workforce`, and `communicate` skills — the
  `cicd` scripts now invoke `devex pr`.
- Logged the vendored-skill in-place patch as a local divergence in
  `docs/skill-sources.md`; the matching canonical rename is tracked upstream for
  guildmaster in
  [agentculture/guildmaster#48](https://github.com/agentculture/guildmaster/issues/48)
  so a future re-sync reconciles cleanly.
- Aligned the documented `devex` version floor to `>=0.21` across the vendored
  `cicd` `SKILL.md` and `workflow.sh` install hint (were `>=0.1`), matching
  `docs/skill-sources.md` and the `await`-era feature set; flagged upstream on
  guildmaster#48.

### Fixed

- SonarCloud now reports code coverage — added `relative_files = true` to
  `[tool.coverage.run]` so `coverage.xml` emits repo-relative paths that map to
  `sonar.sources=league` (absolute / `.venv` paths were dropped
  as unmappable). Mirrors the sibling `convertible` setup.

## [0.1.1] - 2026-05-26

### Changed

- **CI gates on the SonarCloud quality gate**
  ([issue #3](https://github.com/agentculture/league-of-agents/issues/3)) —
  added `sonar.qualitygate.wait=true` to `sonar-project.properties` so a failing
  gate fails the `test` job when `SONAR_TOKEN` is set. Token-less repos and fork
  PRs remain green (the scan step is guarded by `if: env.SONAR_TOKEN != ''`).

## [0.1.0] - 2026-05-26

### Added

- **Onboarded into the AgentCulture mesh** ([issue #1](https://github.com/agentculture/league-of-agents/issues/1)).
- **Agent-first CLI** cited from teken's (`afi-cli`) `python-cli` reference
  (`teken cli cite`) — verbs `whoami`, `learn`, `explain`, `overview`, `doctor`,
  and the `cli` noun group. Runtime is self-contained (`dependencies = []`);
  `teken>=0.8` is a dev dependency only. Passes the seven-bundle agent-first
  rubric (`teken cli doctor . --strict`). `doctor` checks the agent-identity
  invariants (prompt-file-present, backend-consistency, skills-present).
- **Mesh identity**: `culture.yaml` (`suffix: league-of-agents`,
  `backend: claude`) and the matching `CLAUDE.md` prompt file.
- **Canonical guildmaster skill kit** (11 skills) vendored under
  `.claude/skills/` (cite-don't-import): `agent-config`, `assign-to-workforce`,
  `cicd`, `communicate`, `doc-test-alignment`, `pypi-maintainer`, `run-tests`,
  `sonarclaude`, `spec-to-plan`, `think`, `version-bump`. Every `SKILL.md`
  carries `type: command` (load-bearing for the culture/claude backend);
  `cicd` / `communicate` consumer-identifying prose adapted, all script bodies
  verbatim. Provenance in `docs/skill-sources.md`. Three skills (`think`,
  `spec-to-plan`, `assign-to-workforce`) originate in `devague`, re-broadcast
  via guildmaster.
- **Build + deploy baseline**: `pyproject.toml` (hatchling), `tests/` (pytest,
  xdist, coverage), `.github/workflows/{tests,publish}.yml` (CI rubric/lint gate,
  PyPI Trusted Publishing), `.flake8`, `.markdownlint-cli2.yaml`,
  `sonar-project.properties`, and `.claude/skills.local.yaml.example`.

### Changed

### Fixed
