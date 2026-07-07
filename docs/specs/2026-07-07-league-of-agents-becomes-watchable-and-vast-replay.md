# League of Agents becomes watchable and vast: replays turn mesmerizing with a built-in judge's guide, any match exports to a shareable video, seeded generation scales boards from skirmish to campaign, and coding-shaped roles — explorer, planner, and the subagent chains they command — measure whether a mind can truly run a team over the long haul

> League of Agents becomes watchable and vast: replays turn mesmerizing with a built-in judge's guide, any match exports to a shareable video, seeded generation scales boards from skirmish to campaign, and coding-shaped roles — explorer, planner, and the subagent chains they command — measure whether a mind can truly run a team over the long haul

## Audience

- The human evaluator judging matches visually (with the replay teaching them what to look for) and sharing recordings; researchers comparing minds on long-horizon, many-agent, memory-bound capability; agent developers testing whether their mind can command subagents

## Before → After

- Before: The replay is functional but utilitarian — no guidance for a human on HOW to assess what they see; no video export (sharing means sending an HTML file); exactly two hand-coded scenarios (skirmish-1/2) with small boards and a 30-turn ceiling — nothing can assess long-running tasks, many agents, or memory; orchestrator mode allows subagents but nothing measures span of control; roles are stat-lines (scout/harvester/defender) with no tie to the shape of real coding work
- After: Replays are mesmerizing — a designed visual system (validated palette, dark+light, motion with intent) with an embedded assessor guide per scenario; one command renders any match log to a shareable video; scenarios generate from seeds (random when you want novelty, byte-repeatable when you want a rematch) at any board size/complexity; a span-of-control probe measures how many subagents a mind can actually command and how well; roles form a coding-reflective capability lattice — explorer (wide vision/reach, no gather/capture) feeds planner (aggregates intel, coordinates, hands instructions to agents/subagents) feeds executors

## Why it matters

- Issue #1 demands the arena make WHY a team succeeded inspectable and teams comparable — a human can only judge what the replay teaches them to see, a shareable video recruits more human judges, and long-horizon + memory + span-of-control are exactly the questions that decide whether agent teams can do real (coding) work

## Requirements

- Replay visual overhaul (user directive: mesmerizing, beautiful, elegant): a designed system — validated color, dark+light themes, purposeful motion, legible at a glance — plus an embedded ASSESSOR GUIDE: per-scenario explanations and guidance telling a human evaluator what to look at, phase by phase, to judge coordination quality
  - honesty: Beauty is not self-declared: the replay passes the design method's own checks (validated palette, both themes, no anti-pattern hits) AND a real human review conducted with the embedded guide is recorded in docs/ — the guide is judged by whether the human could assess the match with it
- Recording generation (user directive): one command renders a committed match log into a shareable video file — offline, from the log alone, reproducible; sharing a match no longer means sending an HTML file
  - honesty: The video renders offline from the committed log alone — same log, same video content; no screen capture, no live session; the artifact's generation command is recorded in the report
- Seeded scenario system (user directive): scenarios generate from an explicit seed — randomize for novelty, repeat byte-identically for rematches and fair comparisons; hand-authored scenarios (skirmish-1/2) and named presets keep working unchanged
  - honesty: A test proves same seed → byte-identical scenario and different seeds → structurally different boards; every generated match log records its scenario seed so any match is re-creatable from the log header alone
- Board scale and complexity knobs (user directive): larger grids, more units and teams, longer turn limits, richer objective mixes — sized to assess long-running tasks, many agents, and MEMORY (does a mind retain and use early-match knowledge late?)
  - honesty: A recorded long-horizon match on a generated large board actually exists, and its report assesses memory concretely (whether a mind used early-match knowledge late) rather than asserting scale in the abstract
- Subagent span-of-control probe (user directive): measure whether a mind can spawn and command subagents, how many it can control, and how well — a scored, recorded report comparing minds on delegation capability, built on orchestrator mode
  - honesty: The probe measures real spawned subagents through the harness (field agents, not simulated fan-out) and every span-of-control claim reconstructs from the committed log's delegation evidence, not from the mind's self-report
- Coding-reflective roles (user directive): roles become capability contracts mirroring real coding work — EXPLORER: extended vision and reach, fewer tools, cannot gather resources or capture posts (reconnaissance/code-reading); PLANNER: listens to explorer intel, coordinates, hands instructions to other agents/subagents (architect/tech-lead); executor roles carry the do-work tools (builder/implementer) — each role documents its software-work analog and the engine ENFORCES the capability differences
  - honesty: Role capabilities are enforced by engine legality — an explorer's gather/capture order is REJECTED, not discouraged by prompt — proven by tests; each role's coding-work analog is documented next to its stats

## Honesty conditions

- Every announcement phrase is backed by a committed artifact: the redesigned replay, a rendered video file's provenance, a seed-repeat test, a large-board long-horizon match report, the span-of-control report, and the role-lattice match
- Each audience touches the increment on the record: a human review conducted through the new guide, a shared video artifact, and a span-of-control comparison a developer could act on
- The after-state is claimed only when each thread has a committed artifact — no thread ships silently
- Every before-state deficiency cites the current code or record: the existing replay html, the two hand-coded scenarios, the 30-turn ceiling in scenario.py, the unmeasured orchestrator mode, the role stat tables
- The why traces to issue #1's own words (inspectability, fair comparison) — quoted, not strengthened
- Every previously committed match log still folds to its recorded final state after this cycle's engine changes; if the determinism-gate hash regenerates, the PR says so and why in its own words
- Each success signal is verifiable by pointing at a committed artifact (video file or its checksum+provenance, the human review doc, the probe report, the match log)

## Success signals

- A shared video of a seeded large-board match exists; a human evaluator assesses a match using only the replay's embedded guide and their review is recorded (the cycle-3 h15 pattern); a span-of-control report compares at least two minds on real spawned subagents; an explorer+planner match where scouting demonstrably becomes strategy — visible in the replay, checkable in the log

## Scope / boundaries

- Determinism is non-negotiable: scenario generation is seed-derived (no runtime randomness — the engine import ban stands), video rendering is offline post-processing (no live UI service, no streaming); engine changes (roles, board scale) are ADDITIVE — every committed match log still folds to its recorded state, and any regeneration of the determinism-gate hash is a deliberate, documented PR event, never a side effect; cooperation v1 and tempo t0 formulas are untouched this cycle
