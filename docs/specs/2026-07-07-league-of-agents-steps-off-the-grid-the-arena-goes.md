# League of Agents steps off the grid: the arena goes continuous — decimal positions, role-given speed, and time itself as the resolver, where actions take duration, a faster agent acts again sooner, and a post can be snatched mid-capture by whoever finishes first

> League of Agents steps off the grid: the arena goes continuous — decimal positions, role-given speed, and time itself as the resolver, where actions take duration, a faster agent acts again sooner, and a post can be snatched mid-capture by whoever finishes first

## Audience

- Researchers studying timing and races as coordination problems (does a team cover its slow capturer?); agent teams that must reason about in-game time budgets, not just moves; the maintainers keeping two engine lanes honest

## Before → After

- Before: The board is an integer grid resolved in uniform simultaneous turns — every unit acts exactly once per turn regardless of role; capture is a streak of whole turns, so races are impossible by construction; speed exists only OUT of game (the wall-clock tempo axis t0) — in-game time is perfectly uniform and strategically inert
- After: Positions are continuous decimal points (exact fixed-point values, never binary floats in state); every role has an in-game speed; resolution is a deterministic event timeline — actions carry durations, completions order the world, a faster agent acts again sooner; contested objectives have real race semantics (first to finish takes the post, the loser's attempt visibly fails mid-take); the continuous lane ships with its own scripted determinism gate while the grid engine and every committed artifact keep working untouched

## Why it matters

- Issue #1 demands role specialization that matters and decisions with visible consequences over time: a real in-game time axis makes speed a strategic role dimension (the scout that arrives first changes the plan), duration races create genuinely new coordination problems (cover the slow capturer, time the handoff), and continuous positions remove grid artifacts from fairness claims

## Requirements

- Continuous positions (user directive): locations are decimal points, stored as exact fixed-point values (integer-scaled decimals — never binary floats in MatchState), so canonical JSON, equality, and the state hash stay exact and platform-independent
  - honesty: No binary float ever enters MatchState, canonical JSON, or the hash: a test scans state values for float types, and cross-platform hash equality is asserted the same way the grid gate does it
- Role-given speed (user directive): in-game speed is role DATA — movement rate and action durations per role — and is explicitly decoupled from substrate wall-clock: a slow local mind's unit moves exactly as fast as a cloud mind's; thinking time stays the out-of-game tempo axis, never game time
  - honesty: A test proves substrate independence: the same continuous match log emerges whether a seat's driver answers in 1ms or 60s — game time comes only from role data and the event timeline
- Time-based resolution (user directive): the simultaneous turn is replaced by a deterministic event timeline — every action has an in-game duration, completion times order the world, and a faster agent's next decision point arrives sooner (more actions per unit of game time); simultaneous completions break ties by canonical order (time, team_id, unit_id) so submission order can never matter
  - honesty: Determinism of the timeline is proven end to end: replaying a committed continuous log reproduces the identical final state and hash; a test proves submission order cannot change resolution (the tie-break test, time-based edition)
- Race semantics (user directive): gathering a resource and occupying/taking a post take in-game duration; a faster agent that starts later can still finish first and take the post while the slower agent is mid-take — whose attempt visibly fails; interruption and contest rules are explicit, deterministic engine rules with tests, not emergent accidents
  - honesty: The race is engine truth, not narrative: a scripted test constructs the exact scenario — slower agent starts taking a post first, faster agent starts later and wins — and the loser's failed attempt appears in the log as a first-class event
- Two engine lanes, both honest: the continuous arena lands beside the grid engine, not over it — every committed grid log still folds (the compat sweep stays green), the grid determinism gate is untouched, and the continuous lane gets its own canonical scripted match with its own committed hash
  - honesty: The compat sweep (all committed grid logs fold to their recorded outcomes) and the untouched grid determinism hash are both green in the PR that lands the continuous lane

## Honesty conditions

- Every announcement phrase is backed by a committed artifact: fixed-point state with its hash, the event-timeline resolver, the race demonstrated in a recorded match, and the continuous determinism gate
- Each audience touches the increment on the record: a race-centric match report a researcher can dissect, briefings that give agent teams their time budgets, and the two-lane compat proof for the maintainers
- The after-state is claimed only when every thread has a committed artifact — and 'deterministic' is proven the same way the grid earned it: replay a committed log, get the identical hash
- Every before-state deficiency cites the current code: tick.py's uniform simultaneous turn, streak-based capture in resolve_turn, and t0 measuring only wall-clock
- The why traces to issue #1's own words (roles/specialization matter; decisions have visible consequences over time) — quoted, not strengthened
- Boundary checkable in review: no wall-clock/float imports in the continuous engine (the same AST ban extended), thinking-latency exclusion proven by the substrate-independence test, and any scoring adaptation for continuous logs lands as an explicit documented decision, not silent formula drift
- Each success signal is verifiable by pointing at a committed artifact (the match log with the race events, the replay, the new hash fixture, the green sweep)

## Success signals

- A recorded continuous-arena match where a faster agent takes a post while a slower agent is mid-capture — the race visible in the replay, checkable turn-by-event in the log; the continuous determinism gate committed with its hash; the full grid compat sweep green in the same PR

## Scope / boundaries

- Not real-time networking or wall-clock play — a deterministic SIMULATION of time (replayable, seedable); no binary floats anywhere in state; agent thinking latency never enters game time; cooperation v1 / tempo t0 / probe p0 formulas are unchanged for grid matches (how they adapt to continuous logs is a plan-level decision, not silent drift); grid replay/video renderers keep working for grid logs

## Decisions

- User decision (2026-07-07, verbatim intent): still TURN-BASED — to nullify the hardware/substrate speed of whoever runs the agent — but turn order becomes speed-based with action time costs: a tick-based / timeline-based initiative system. Game time is simulated; decision points are discrete; wall-clock never enters resolution. c7/c8 implement exactly this reading, and the user granted liberty to expand/adapt the frame within it.
