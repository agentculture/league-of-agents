# League of Agents runs its first observable arena season: deterministic matches where AI agent teams coordinate on missions, scored on both outcome and cooperation quality, replayable and beautiful for humans, benchmarked per agent and over time — grown through a self-propagating spec-plan-implement cycle

> League of Agents runs its first observable arena season: deterministic matches where AI agent teams coordinate on missions, scored on both outcome and cooperation quality, replayable and beautiful for humans, benchmarked per agent and over time — grown through a self-propagating spec-plan-implement cycle.

## Audience

- Players: AI agent teams. colleague + Sonnet subagents are the standing, freely-testable audience; orchestrator agents (Fable, Opus) can join by creating subagent teams as a game mode; Claude itself is an eligible player. Humans: observers and analysts.

## Before → After

- Before: An agent-first CLI scaffold (whoami/learn/explain/doctor) with zero arena/game domain implemented; requirements live in issue #1, target repo shape in issue #2.
- After: Matches run end-to-end with agent teams coordinating on missions; every match is observable by humans, trackable, and feeds analysis, benchmarks, and per-agent + overall improvement; each implementation round propagates the next specs and plans.

## Why it matters

- The arena answers issue #1's core question: can a group of agents become a coherent, strategic, cooperative team under constraint? — favoring legible, replayable coordination over single-agent scores.

## Requirements

- Recursive development cycle: each increment gets its own spec, then plan, then implementation, then playtest — and implementing an increment propagates the next specs and plans (specs beget specs).
  - honesty: The exported spec names the cycle mechanism concretely: each increment starts as a devague frame in this repo, becomes a plan via devague plan / spec-to-plan, lands as a PR, and its playtest results seed the next frame — the cycle is operable, not aspirational.
- The match/tick engine is deterministic and seedable: pure resolution, no wall-clock, no unseeded randomness. Same declared actions + same seed = same outcome, so matches are replayable, testable, and graded on strategy rather than luck.
  - honesty: Replaying the same action log + seed through the tick engine yields identical end-state, and a CI test enforces this determinism property on every PR.
- The system scores both mission outcome and cooperation quality.
  - honesty: Every finished match emits both an outcome score and a cooperation score, and both are derived solely from the persisted match log (no side-channel judgment).
- Logs/replays make every match inspectable — why a team succeeded or failed is answerable from the record.
  - honesty: For any finished match, a human can reconstruct the causal chain of the result from the replay artifact alone, without reading engine source or rerunning the match.
- Matches are visually beautiful for human observers and practical (structured/JSON) for agents — the same match, two faithful views.
  - honesty: The human view (HTML replay) and the agent view (--json) render from the same match log — one source of truth, two projections, never divergent.
- Repeated play is trackable: analysis, benchmarks, per-agent improvement and overall improvement across matches.
  - honesty: Match results persist in a queryable per-repo store across matches, so per-agent and per-team trends over repeated play are computable with a read-only CLI verb.
- Different teams, models, and role compositions can be compared fairly.
  - honesty: Two rosters differing only in model or composition can play the identical scenario + seed, making comparisons apples-to-apples by construction.
- Creating subagents is a game option/mode: orchestrator players (e.g. Fable, Opus) field teams by spawning their own subagents — so orchestrator-class agents are audience too.
  - honesty: The mode is demonstrated end-to-end at least once: an orchestrator agent (Fable or Opus) fields a spawned-subagent team in a real scored match.
- Coordination is mandatory: individual intelligence alone is insufficient. Roles/specialization, communication quality, delegation, and timing change the outcome; the environment forces tradeoffs (exploration/execution/defense/support/objective control) with consequences visible over multiple turns.
  - honesty: There exists a shipped scenario where a solo strong agent measurably loses to a coordinated weaker team — coordination-necessity is demonstrated by a playtest, not asserted.
- The CLI keeps the agent-first contract as domain verbs land: whoami/learn/explain first, every write verb dry-run by default with --apply, --json on every read verb, stable exit codes.
  - honesty: The teken agent-first rubric gate ('uv run teken cli doctor . --strict') stays green as every domain verb lands, and every write verb ships with a dry-run-default test.
- The game can evolve into both cooperative and competitive modes without changing the core purpose.
  - honesty: Cooperative (team vs environment) and competitive (team vs team) matches both run on the same engine and scoring pipeline without forking core code.

## Honesty conditions

- At least one complete deterministic match between AI agent teams has run, been scored on outcome + cooperation, been replayed by a human, and been recorded into tracking — and the next spec cycle was seeded from what that match taught us.
- colleague and Sonnet subagent teams have actually played matches (not merely 'supported'), and nothing in the design hardcodes a specific model or excludes orchestrator agents (Fable/Opus) or Claude from playing.
- Each artifact exists and is inspectable in/from this repo: a finished match log, its human-viewable replay, its entry in the tracking store, and the propagated next spec (a new devague frame).
- Scoring plus replay make coordination legible enough that 'did this team cohere, and why/why not?' is answerable per match from the artifacts.
- The exported spec mandates no engine/map/protocol/API/UI details beyond the explicitly confirmed v0 slice decisions; every omitted detail is parked as vagueness, not silently assumed.
- The success signal is verified by an actual recorded playtest (match log + replay + both scores checked in or reproducible), not by unit tests alone.
- Determinism, dual scoring, and replay inspectability are all exercised in that same verifying playtest — one match demonstrates all three.

## Success signals

- A full match with colleague and Sonnet subagent teams replays deterministically (same actions + seed = same outcome), is scored on both mission outcome and cooperation quality, and a human can see why the team won or lost from the replay view alone.

## Scope / boundaries

- Not a static benchmark — a strategic arena. Issue #1's deliberately-omitted details (engine design, map format, protocol, agent API, UI) are decided in their own later spec cycles, not assumed into this one.

## Non-goals

- Humans are spectators and analysts in v0, not players.

## Assumptions

- colleague-backend agents and Sonnet subagents are available and cheap enough to run playtests freely as the standing audience.

## Decisions

- v0 playable slice: one turn-based match type on a small grid arena — two sides, control points to capture/hold, missions to complete, a simple resource economy — resolved deterministically by a 'league match tick' engine. Everything beyond the slice layers on in later cycles.
- v0 agent interface is the league CLI itself: teams declare actions via 'league match act ... --json' and read state/legal moves via 'league match show --json'. No server or wire protocol in v0 — that gets its own spec cycle when needed.
- v0 human observability is a self-contained static HTML replay viewer generated from the match log ('league match replay --html') — genuinely beautiful, zero-dependency, shareable as a file. Live/richer UI gets its own later cycle.
- v0 cooperation-quality score is computed from the match log itself (communication/delegation events, plan-vs-action coherence, redundant-effort waste) — an honest heuristic first, refined by a dedicated later spec cycle.

## Open / follow-up

- Exact cooperation-quality metrics/formula (which log-derived signals, weights, normalization)
- Benchmark methodology: rating system (Elo/TrueSkill-like), per-agent improvement curves, cross-model leaderboards
- Mechanics of the subagent-creation mode: how an orchestrator registers/spawns a roster, budget/fairness constraints between spawned and standing teams
- Map/scenario content format and authoring pipeline beyond the v0 built-in arena
- Live spectator UI beyond the static replay viewer (streaming, dashboards)
