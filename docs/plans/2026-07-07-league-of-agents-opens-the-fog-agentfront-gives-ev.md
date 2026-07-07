# Build Plan — League of Agents opens the fog: AgentFront gives every audience its native face — markdown for agents, TUI and HTML for humans, JSON for coded bots — orchestrator mode becomes a real game mode where the master reads the map and ground units see only their radius, and strategy-coded bots join the ladder

slug: `league-of-agents-opens-the-fog-agentfront-gives-ev` · status: `exported` · from frame: `league-of-agents-opens-the-fog-agentfront-gives-ev`

> League of Agents opens the fog: AgentFront gives every audience its native face — markdown for agents, TUI and HTML for humans, JSON for coded bots — orchestrator mode becomes a real game mode where the master reads the map and ground units see only their radius, and strategy-coded bots join the ladder

## Tasks

### t1 — Engine: per-role vision — vision radius as a role stat in the scenario schema, and a pure visibility function (league/engine/vision.py) computing what a unit/team sees from state alone; determinism hash regenerated deliberately

- covers: c12, h12
- acceptance:
  - vision is a pure function of (state, scenario): no RNG, AST import ban passes, identical logs yield identical visibility
  - scout sees strictly farther than harvester/defender in skirmish scenarios (specialization axis)

### t2 — Coded-strategy bot lane: bots/ holds committed strategy sources that consume ONLY the public CLI/JSON surface; one reference strategy bot beyond greedy registers as a driver

- covers: c3, h2
- acceptance:
  - the reference bot's strategy is readable committed source and its matches are deterministic given the seed
  - a test proves the bot driver touches no league internals (public surface only)

### t3 — Engine: per-team knowledge fold — what each team has seen and been told, derived purely from the event log (the substrate for fogged briefings, the replay overlay, and the TUI)

- depends on: t1
- covers: c13
- acceptance:
  - knowledge is a fold over events: re-folding a log reproduces per-team knowledge exactly
  - an out-of-vision fact enters a team's knowledge ONLY via a logged message or own sighting

### t4 — Scenario: skirmish-2 (fogged) — vision radii per role + turn-limit arithmetic re-proving coordination-necessity by construction under fog (unparks v1)

- depends on: t1
- covers: c5
- acceptance:
  - a test proves by arithmetic that the best solo run cannot complete both missions inside the limit under fog

### t5 — Harness: fog-aware briefings — a seat's briefing contains only its unit's vision + team knowledge + teammate/master messages; never the full board

- depends on: t3
- covers: c5, h4
- acceptance:
  - a test stages an out-of-vision objective and proves it reaches the seat's briefing ONLY after a logged message names it

### t6 — Harness: orchestrator mode for real — the master's full-map read is a declared capability in config echo + match log; unit-to-unit comms an explicit config flag (default off in orchestrator mode; a recorded fairness axis)

- depends on: t5
- covers: c4, c6, h3, h5
- acceptance:
  - the log records map_read=full for the master and the comms flag per team; match show --json surfaces both
  - with comms off, a unit's briefing contains master messages only; with comms on, teammate messages too — both tested

### t7 — TUI face for humans: replay-stepping terminal view over the same fold (board, fog overlay, feed) — the human's third face beside HTML

- depends on: t3
- covers: c2, c13, c15, h13
- acceptance:
  - the TUI renders from build_replay_data (or the knowledge fold) — an agreement test pins it to the same facts as JSON
  - ground truth vs per-team knowledge toggle works in the TUI and the HTML replay overlay

### t10 — agentfront runtime adoption + the markdown face: dependencies gains agentfront (user decision c17, honesty h11); match/briefing state renders as markdown for agents from one registry; face-agreement tests prove markdown/JSON/HTML are one fold

- depends on: t3
- covers: c2, h1
- acceptance:
  - pyproject dependencies includes agentfront and the PR body calls out the install-story change
  - a face-agreement test renders the same log to markdown and JSON and asserts fact-for-fact equality

### t8 — Playtests: the fogged orchestrator match (master guides blind units), a coded-bot-vs-agent-team match, and the h9 retest (season-0 solo-vs-swarm shape under fog); logs, replays, scores, reports committed

- depends on: t2, t4, t6, t7, t10
- covers: c9, c14, c16, c7, c10, h9, h14, h16, h7, h10
- acceptance:
  - the fogged match log shows a unit completing an objective never inside its own vision, with the guiding messages logged
  - the h9 retest result is published either way
  - the coded bot's match record is committed beside its strategy source

### t9 — Docs + propagation: before-state citations from the season-0 record, announcement-to-artifact traceability, boundary audit (TUI same-fold, bots public-surface-only, no engine strategy aids), human review of the fogged replay, next-frame seeding

- depends on: t8
- covers: c1, c8, c15, h6, h8, h15
- acceptance:
  - traceability table maps every announcement phrase to a committed artifact
  - human-review section records the reviewer's reconstruction from the replay/TUI alone

## Risks

- [unknown_nonblocking] Fog may make weak models helpless rather than cooperative — the h9 retest could fail in a new direction (units ignore guidance); scenario tuning (v1) may need iteration (task t8)
- [unknown_nonblocking] agentfront App registry integration with the existing argparse CLI is untested territory — the faces may adopt the registry while the CLI surface migrates incrementally (task t10)
