# DRAFT (parked) — League of Agents opens the fog

> **Status: parked for cycle 3.** This is a written-ahead spec draft, not a
> converged export. The devague frame is
> `league-of-agents-opens-the-fog-agentfront-gives-ev` — user directives are
> captured as confirmed claims; everything the assisting agent proposed is
> still `proposed`, and one deliberately **blocking** unknown (v4, the
> agentfront dependency policy) holds convergence until this cycle is picked
> up. Resume with `devague status` on that frame after cycle 2 (resident
> minds) records its live match — the cycle rule applies as always.

## Announcement (draft)

League of Agents opens the fog: AgentFront gives every audience its native
face — markdown for agents, TUI and HTML for humans, JSON for coded bots —
orchestrator mode becomes a real game mode where the master reads the map and
ground units see only their radius, and strategy-coded bots join the ladder.

## User directives (confirmed claims c2–c6)

1. **AgentFront faces (c2):** agents read markdown, humans read TUI/HTML,
   bots/automations read JSON — three audience-typed projections of the same
   match fold.
2. **Coded-strategy bots (c3):** the JSON face lets automations with
   committed, coded strategies play against agent teams — the arena tests
   agents against programmed strategy, not only against other minds.
3. **Orchestrator mode, for real (c4):** the orchestrator agent reads the
   map; its spawned subagents do the ground work.
4. **Line of sight (c5):** units see at most *x* tiles (fog of war); the
   master agent has to guide them.
5. **Optional sub-agent communication (c6):** a config option lets ground
   units message each other to help each other — a declared fairness axis.

## Discovery: AgentFront already exists

`agentfront` is the **renamed teken** (formerly afi-cli) — the exact tool
whose rubric (`teken cli doctor --strict`) already gates this repo's CI. It is
now an importable runtime: one `App` registry of docs + tools, from which the
CLI, MCP, and HTTP surfaces derive and therefore cannot drift. The natural
reading of this frame: the league's faces become audience-typed projections
registered once — the markdown face doubling as the seat briefing payload the
harness already assembles.

## Proposed shape (unconfirmed — c7–c16)

- **Before:** every seat sees the whole board (full observability is why solo
  beat the swarm and h9 failed in season 0); two faces exist (JSON, HTML
  replay); orchestrator mode is a harness demo; the only bot is the greedy
  baseline.
- **After:** per-role vision radii, engine-computed and deterministic (scouts
  see farther — issue #1 names visibility as a specialization axis); a unit's
  briefing contains **only** what it can see plus what teammates/master told
  it; the orchestrator's full-map view is a *declared* capability in config
  and log, never a hidden privilege; coded bots with committed source play
  through the same public JSON surface as everyone; replays show ground truth
  **and** a per-team knowledge overlay so a reviewer can verify a blind unit
  acted on relayed guidance.
- **Why it matters:** fog is the recorded #1 candidate fix for the failed h9
  coordination-necessity test. When a unit cannot see the objective,
  communication stops being flavor and becomes the mechanism of victory —
  cooperation quality becomes measurable as information flow that changed an
  outcome. Coded bots give agents a reproducible strategic opponent and the
  ladder a fixed reference point.
- **Success signals:** a recorded fogged orchestrator match where a ground
  unit completes an objective it never saw (guidance auditable in messages);
  a coded-strategy bot winning or losing on the record; the h9 retest
  published either way; projection-agreement tests proving all faces are one
  fold.

## Proposed honesty conditions (h1–h5, unconfirmed)

- **h1** — the three faces are provably one fold: projection-agreement tests
  (the HTML=JSON pattern) extend to markdown and TUI.
- **h2** — a coded bot is honest opposition: committed readable source,
  public JSON surface only, deterministic given the seed.
- **h3** — the orchestrator's map-reading is declared in config and log; its
  guidance flows only through logged in-game messages.
- **h4** — fog is enforced at the briefing boundary and tested: an
  out-of-vision fact reaches a unit ONLY via a logged message.
- **h5** — the comms option is recorded in config echo and log; comparisons
  across configs state it; orchestrator default is master-mediated only.

## Parked unknowns

- **v1** — exact vision radii per role + turn-limit retuning (the scenario
  arithmetic must re-prove coordination-necessity by construction).
- **v2** — whether messages cost anything under fog (free chatter inflated
  cooperation scores in season 0; fog may fix that without costs).
- **v3** — TUI approach (stdlib curses vs dev-only dependency; live-follow vs
  replay-step).
- **v4 (BLOCKING)** — agentfront runtime-dependency policy: the league
  runtime is dependency-free today; `import agentfront` changes the install
  story. Options: runtime import / dev-only projection tooling /
  cite-don't-import. Deliberately blocks convergence until decided.
- **v5** — orchestrator fairness budgets (spawn counts, model mixing): season
  0's v3 continues; this frame gives the mode its mechanics.

## Interactions with cycle 2 (resident minds)

Fog multiplies the value of residency: a resident unit accumulates a mental
map from what it has seen and been told — exactly the "contextual mindset"
cycle 2 builds. The rejection-feedback and legal-actions surfaces (cycle 2)
must become vision-aware here: legal moves are computable from own vision;
mission targets outside vision are knowable only by message.
