# Build Plan — League of Agents becomes watchable and vast: replays turn mesmerizing with a built-in judge's guide, any match exports to a shareable video, seeded generation scales boards from skirmish to campaign, and coding-shaped roles — explorer, planner, and the subagent chains they command — measure whether a mind can truly run a team over the long haul

slug: `league-of-agents-becomes-watchable-and-vast-replay` · status: `exported` · from frame: `league-of-agents-becomes-watchable-and-vast-replay`

> League of Agents becomes watchable and vast: replays turn mesmerizing with a built-in judge's guide, any match exports to a shareable video, seeded generation scales boards from skirmish to campaign, and coding-shaped roles — explorer, planner, and the subagent chains they command — measure whether a mind can truly run a team over the long haul

## Tasks

### t1 — Seeded scenario generator

- covers: c8, h8
- acceptance:
  - generate(seed, params) returns a valid Scenario deterministically: a test proves same seed yields a byte-identical scenario and different seeds yield structurally different boards; no runtime randomness (the engine import ban holds — seeds drive a pure PRNG-free derivation or a hash-based one)
  - Every match on a generated scenario records the generator seed and params in its log header, so any match is re-creatable from the log alone
  - Generated boards are fair by construction (symmetric spawns/objectives per team), asserted by test; hand-authored scenarios and existing presets keep working unchanged

### t2 — Board scale and complexity knobs

- depends on: t1
- covers: c9, c12
- acceptance:
  - The generator (and match new/play surfaces) accept grid size, roster size, team count, turn limit, and objective-mix parameters well beyond the current 30-turn two-scenario ceiling
  - A generated large-board long-turn scenario runs a full bot-vs-bot match to completion in tests (fast, coded bots) proving the engine scales; every previously committed log still folds to its recorded final state

### t3 — Coding-reflective roles: explorer, planner, executor lattice

- covers: c11, h11, c12
- acceptance:
  - Explorer has extended vision/reach and CANNOT gather or capture — such orders are rejected by engine legality, proven by tests mirroring legal.py<->resolve_turn agreement both ways
  - Planner's coordination function is real: it can receive explorer intel and hand instructions to teammates through the existing message/plan channels, with role stats that make it strategically necessary; scenarios can roster the new roles alongside scout/harvester/defender (migration decision from parked v4 pinned here)
  - Each role documents its software-work analog (explorer=reconnaissance/code-reading, planner=architect/tech-lead, executors=implementers) next to its stats; determinism-hash regeneration, if any, is a deliberate documented event in the PR

### t4 — Replay visual overhaul: the mesmerizing pass

- covers: c6, h6
- acceptance:
  - The replay's visual system passes the design method's own checks: palette validated by script (CVD-safe, contrast), dark+light themes both designed (not auto-flipped), purposeful motion, no anti-pattern hits; stacked-unit fan-out and deep links keep working
  - The board, event feed, team panels, and score breakdown are legible at a glance and beautiful in both themes — reviewed against the design checklist in the PR, with screenshots committed

### t5 — Embedded assessor guide

- depends on: t4
- covers: c6, h6, c2
- acceptance:
  - The replay embeds a per-scenario assessor guide: phase-by-phase explanations of what to look at and how to judge coordination quality (delegation, message content, multi-turn consequences), derived from the scenario and the log — not generic boilerplate
  - A human evaluator can assess a match using ONLY the replay and its guide — validated by the recorded human review task (t10), which this task enables

### t6 — Video export from the match log

- depends on: t4
- covers: c7, h7
- acceptance:
  - One command renders a committed match log into a shareable video file, offline, from the log alone — no screen capture, no live session; the toolchain decision (parked v1: ffmpeg vs stdlib-only animated format) is pinned here with the runtime kept dependency-free
  - Reproducibility proven by test: the same log renders the same frame sequence (content-hash of frames or deterministic intermediate); the render command is recorded in each artifact's provenance

### t7 — Span-of-control probe: delegation measured from the log

- covers: c10, h10
- acceptance:
  - A probe mode/report measures from the committed log alone: how many subagents a mind actually fielded, orders realized per subagent, and how command quality degrades as N grows (the parked v2 formula pinned with unit tests on synthetic logs)
  - Only real spawned subagents count — the probe runs through the harness (field agents), and a test proves self-reported delegation without log evidence scores zero

### t8 — Long-horizon memory playtest on a generated board

- depends on: t1, t2
- covers: c9, h9, c13
- acceptance:
  - A recorded match on a seeded generated large board with an extended turn limit, played by a resident mind, is committed with log+replay+report
  - The report assesses memory concretely: whether the mind used early-match knowledge late (e.g. returning to a resource node or threat it saw many turns earlier), cited to specific turns in the log

### t9 — Span-of-control live comparison: two minds

- depends on: t7
- covers: c10, h10, c13, c2
- acceptance:
  - A committed report compares at least two minds (e.g. sonnet-orchestrator vs colleague-orchestrator) on the probe's span-of-control score, on the same seeded scenario, with every claim reconstructible from the logs

### t10 — The shared-video human review

- depends on: t5, t6, t8
- covers: c13, h13, h6, c2, h2, c5, h5
- acceptance:
  - A seeded large-board match is rendered to video and shared; the human evaluator (Ori) assesses the match using only the replay's embedded guide, and the review is recorded in docs/ (the cycle-3 h15 pattern), including whether the guide sufficed
  - The report quotes issue #1's own inspectability/fair-comparison language for the why (quoted, not strengthened)

### t11 — Compatibility sweep: every committed log still folds

- depends on: t1, t3
- covers: c12, h12, c4, h4
- acceptance:
  - A test sweeps every committed *.log.jsonl under docs/playtests/ and asserts each still folds to its recorded final state after this cycle's engine changes
  - The before-state deficiencies cited in reports point at the current code/record (the pre-overhaul replay, the two hand-coded scenarios, scenario.py's turn ceiling, the unmeasured orchestrator mode)

### t12 — Cycle-6 closure ledger

- depends on: t8, t9, t10, t11
- covers: c1, h1, c3, h3
- acceptance:
  - A committed ledger maps every announcement thread (mesmerizing replay+guide, video, seeded generation at scale, span-of-control, role lattice) to its artifact on main and names which audience each serves; no thread claimed done without one

## Risks

- [unknown_nonblocking] Video toolchain (parked frame v1): ffmpeg-on-PATH vs stdlib-only animated format — pinned in t6 (task t6)
- [unknown_nonblocking] Span-of-control formula (parked frame v2) — pinned in t7's unit tests (task t7)
- [unknown_nonblocking] Generator parameter space + fairness guarantees (parked frame v3) — pinned in t1 (task t1)
- [unknown_nonblocking] Role-set migration (parked frame v4: join vs replace scout/harvester/defender) — pinned in t3 (task t3)
