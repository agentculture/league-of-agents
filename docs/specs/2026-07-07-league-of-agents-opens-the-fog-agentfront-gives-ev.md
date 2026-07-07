# League of Agents opens the fog: AgentFront gives every audience its native face — markdown for agents, TUI and HTML for humans, JSON for coded bots — orchestrator mode becomes a real game mode where the master reads the map and ground units see only their radius, and strategy-coded bots join the ladder

> League of Agents opens the fog: AgentFront gives every audience its native face — markdown for agents, TUI and HTML for humans, JSON for coded bots — orchestrator mode becomes a real game mode where the master reads the map and ground units see only their radius, and strategy-coded bots join the ladder

## Audience

- Agent teams (resident or stateless), human spectators (TUI + HTML replay), coded-strategy bot authors, and the orchestrator master guiding blind ground units

## Before → After

- Before: Every seat sees the whole board (full observability let one solo mind beat a coordinated swarm — h9 not demonstrated in season 0); the arena has two faces (JSON + HTML replay) but no markdown face for agents and no TUI for humans; orchestrator mode is a harness config demo, not a game mode with its own information asymmetry; the only bots are the greedy baseline
- After: One match fold projects three audience-typed faces via agentfront (the renamed teken already gating this repo): markdown briefings for agents, TUI/HTML for humans, JSON for bots; units carry per-role vision radii and briefings contain ONLY what that unit can see plus what teammates told it; the orchestrator reads the full map as a declared capability and guides blind units through auditable messages; coded-strategy bots with committed source play on the ladder

## Why it matters

- Fog of war is the recorded #1 candidate fix for the failed h9 coordination-necessity test: when a unit cannot see the objective, communication stops being flavor and becomes the mechanism of victory — cooperation quality becomes measurable as information flow that changed an outcome; coded bots give agents a reproducible strategic opponent and the benchmark ladder a fixed reference point

## Requirements

- AgentFront faces (user directive): agents read markdown, humans read TUI/HTML, bots/automations read JSON — three audience-typed projections of the same match fold
  - honesty: The three faces are provably one fold: projection-agreement tests (the HTML=JSON pattern from season 0) extend to the markdown and TUI faces — same log in, same facts out, byte-derivable
- Coded-strategy bots as first-class opponents (user directive): the JSON face lets automations with committed, coded strategies play against agent teams — the arena tests agents against programmed strategy, not only other minds
  - honesty: A coded bot is honest opposition: its strategy is committed, readable source; it consumes only the public JSON surface (no engine internals); its matches are deterministic given the seed and replayable
- Orchestrator mode becomes a real game mode (user directive): the orchestrator agent reads the map; its spawned subagents do the ground work
  - honesty: The orchestrator's map-reading is a DECLARED capability recorded in the match config and log — an information-asymmetry rule of the mode, never a hidden privilege; its guidance to units flows only through logged in-game messages
- Line of sight (user directive): units see at most x tiles (fog of war); the master agent has to guide them
  - honesty: Fog is enforced at the briefing boundary and tested: a unit's briefing contains nothing beyond its vision radius plus explicit teammate/master messages; a test proves an out-of-vision fact reaches a unit ONLY via a logged message
- Optional sub-agent communication (user directive): a config option lets ground units message each other to help each other — off by default in orchestrator mode, a declared fairness axis either way
  - honesty: The comms option is a recorded fairness axis: unit-to-unit messaging on/off is in the match config echo and the log; comparisons across configs state it; default in orchestrator mode is master-mediated only
- Visibility is deterministic, per-role, and engine-computed: vision radius is a role stat (scouts see farther — issue #1 names visibility as a specialization axis), computed purely from state with no RNG, and the determinism gate still holds
  - honesty: Vision is a pure function of state and role: the AST import ban still passes, the determinism gate hash is regenerated once deliberately, and identical logs re-fold to identical per-team knowledge
- Fog stays legible: the replay shows ground truth AND a per-team knowledge overlay; the log records what each seat was shown, so a reviewer can verify a blind unit acted on relayed guidance, not hidden knowledge
  - honesty: A reviewer can audit fog from the replay alone: ground truth and per-team knowledge are both visible, and the log records what each seat was shown each turn
- The h9 retest: the season-0 coordination-necessity match shape reruns under fog (solo strong mind vs coordinated weaker swarm) and the result is published either way
  - honesty: The h9 retest reuses the season-0 shape (solo strong mind vs coordinated weaker swarm, same scenario family) so the comparison is apples-to-apples, and the result is published even if h9 fails again

## Honesty conditions

- Every announcement phrase maps to a committed artifact before the next frame: faces (projection-agreement tests), fog (briefing-boundary test), orchestrator mode (recorded fogged match), coded bots (committed strategy source on the ladder)
- Each audience actually touches the increment: an agent team plays fogged, a human reviews via TUI/HTML, a coded bot plays through JSON, an orchestrator guides blind units — all in recorded artifacts
- The before-state cites the committed season-0 record (full observability, h9 not demonstrated, greedy-only bots) — not reconstructed after the fact
- The after-state is demonstrated in ONE recorded fogged match with all elements active — per-role vision, briefing boundary, declared orchestrator capability, knowledge overlay — not assembled from disjoint demos
- The rationale survives its own test: the h9 retest and the cooperation-as-information-flow claim are published with numbers either way
- The chosen dependency policy is enacted exactly and called out in the PR: if runtime import, CI proves the faces derive from one registry and cannot drift; if cite/dev-only, the same agreement tests hold without the import
- The boundary is checkable: the TUI renders from the same fold (agreement test), bots reach nothing but the public CLI/JSON surface, and no pathfinding/strategy aid ships inside the engine
- Success artifacts are all committed: the fogged-match log showing a unit completing an objective never in its vision (guiding messages logged), the bot's source + its match record, the h9 retest report, and the face-agreement test suite

## Success signals

- A recorded fogged orchestrator match where a ground unit completes an objective it never saw (guidance auditable in messages); a coded-strategy bot with committed source winning or losing on the record against an agent team; the h9 retest result published; all three faces proven projections of one fold by agreement tests

## Scope / boundaries

- Not building: a graphics engine (the TUI is a face over the same fold), a live networked spectator server (v5 stays parked), pathfinding aids for units, or bot strategies smuggled as hidden engine privileges — bots play through the same public JSON surface as everyone

## Decisions

- Adopt agentfront (formerly teken) as the runtime for the faces — one registry, three surfaces that cannot drift; NOTE: this changes the runtime dependency policy (dependencies = [] today; agentfront CLI/HTTP surfaces are stdlib-pure but it is still an import) — resolve deliberately at spec confirmation
- agentfront dependency policy (user decision, resolves parked v4): RUNTIME IMPORT — league adds agentfront to [project.dependencies]; the three faces derive from its one-registry runtime so they provably cannot drift; the install-story change is called out in the implementing PR
