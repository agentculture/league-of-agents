# League of Agents seats become resident minds: every agent keeps one continuous context for the whole match — cultureagent anchors Claude and Colleague seats alike — orders are legal by construction, and no mission is ever decided by the alphabet

> League of Agents seats become resident minds: every agent keeps one continuous context for the whole match — cultureagent anchors Claude and Colleague seats alike — orders are legal by construction, and no mission is ever decided by the alphabet

## Audience

- Agent teams (Claude, colleague, and any cultureagent-anchored mind), the human reviewer reading replays, and the orchestrator fielding spawned seats

## Before → After

- Before: Every seat turn is a fresh stateless invocation: full re-briefing each turn (no prompt-cache reuse), no contextual mindset, seats repeat their own mistakes because rejections never reach the next prompt, and the swarm burned 19/53 orders on geometry the engine already knew was illegal; ms-supply's dead-heat was awarded by lexicographic team id
- After: Each seat is a resident mind for the whole match: one persistent context per agent (turn N gets a delta briefing, not a re-teach), anchored via culture's cultureagent for Claude and Colleague seats alike; the interface makes order legality checkable before declaring and feeds every rejection reason back; simultaneous mission completion resolves fairly; the event log remains the only inter-agent channel and the replay stays the legible source of truth

## Why it matters

- Continuity is cache-efficiency (persistent context = prefix-cache hits per turn on both Anthropic and vLLM sides) and game psychology (a mind that lives in the match plays in a contextual mindset instead of waking amnesiac 30 times); it also makes the h9 coordination retest meaningful — a swarm that stops wasting a third of its orders can actually test whether coordination beats solo strength

## Requirements

- Seats have cross-turn continuity: one persistent context per agent across the whole match (user directive: efficiency per agent, caching-wise, and a contextual mindset as part of the game)
  - honesty: Persistence is verifiable, not vibes: the resident driver holds ONE session per seat for the entire match, turn N>1 sends a delta briefing (new events + current state), never the full re-teach, and a harness test proves the same session served every turn
  - honesty: The efficiency claim is measured, not asserted: the playtest report compares resident vs stateless on the same scenario+seed — per-turn input tokens (or latency) and total cost — and prints the numbers even if they disappoint
- Culture's cultureagent anchors the resident seats — Claude and Colleague minds run through the same anchor (user directive)
  - honesty: Anchoring is real on both minds: a recorded match fields at least one Claude seat AND one Colleague seat through cultureagent sessions (not raw API, not claude -p), and the match log's roster labels state that routing truthfully
- Illegal moves must not be silently possible: per-unit legal actions are readable before declaring, and a rejected order's reason text reaches that agent's next briefing (user directive from the h15 review)
  - honesty: Legality is readable before declaring: match show --json exposes per-unit legal actions (move targets in range, gather/deliver/hold applicability) and the seat briefing cites them
  - honesty: Mistakes reach the mind that made them: when a seat's order is rejected, that seat's next briefing contains the engine's reason text — provable from the recorded harness transcript, and the engine's validation/events stay unchanged (determinism intact)
- Dead-heat mission resolution is fair: simultaneous completion of the same mission never resolves by team-id sort order — the rule must be deterministic yet id-neutral (split, dual-award, or seed-derived)
  - honesty: Id-neutrality is regression-tested: a test reproduces the orchestrator t16 double-delivery and proves the outcome is invariant under swapping team ids; the determinism hash is regenerated once, deliberately, in the PR that changes the rule
- Continuity is a declared fairness axis: a team's seat persistence (resident vs stateless) is recorded in the match config and log so cross-team comparisons stay honest, and a resident seat still coordinates with teammates ONLY through in-game messages
  - honesty: Residency is auditable: the match log records each team's driver kind (resident vs stateless), and the only inter-seat channel in a resident match remains in-game messages — the replay shows everything any seat was told by a teammate

## Honesty conditions

- Every phrase of the announcement is backed by a committed artifact before the next frame opens: resident context (harness transcript), cultureagent anchor (truthful roster routing), legal-by-construction (legal-actions surface + fed-back reasons), no-alphabet (id-neutral rule + its regression test)
- Each named audience actually touches the increment: agent teams play resident in a recorded match, the human reviewer reads its replay (the h15 pattern), and orchestrator mode still runs unchanged (the t14 config replays green)
- The before-state cites the committed season-0 record (stateless drivers, 19/53 rejections, the lexicographic ms-supply award) — not an after-the-fact reconstruction
- The after-state is demonstrated end to end in ONE recorded match — resident seats, delta briefings, legality surface, fed-back rejections, fair dead-heat — not assembled from disjoint demos
- The efficiency/mindset rationale survives its own test: if the resident-vs-stateless comparison shows no measurable gain, the report says so plainly and the rationale is revisited in the next frame rather than quietly dropped
- The boundary is checkable in review: no code path persists seat context past match end, no channel exists between seats besides in-game messages, and the increment patches nothing inside cultureagent itself (consumes its existing surface only)
- The comparison is honest: resident match and stateless baseline share scenario+seed (the t10 rematch rule), both logs+replays are committed, and the report publishes the numbers whichever way they point

## Success signals

- A recorded live match with resident seats on both teams, plus its stateless-baseline rematch on the same scenario+seed, and a report comparing rejection rates, per-turn latency/token cost, and dual scores — reviewed by a human from the replay alone

## Scope / boundaries

- Not building: persistent memory ACROSS matches (a seat's residency ends when the match ends), out-of-game side channels between seats, or a new agent framework — cultureagent is used as it exists

## Non-goals

- No engine changes for continuity: the engine stays a pure deterministic fold over the event log — residency lives entirely in the harness layer; parked items stay parked (cooperation-metric formula v1, benchmark methodology v2, orchestrator fairness v3, map pipeline v4, live spectator UI v5)

## Decisions

- The harness gains a resident driver type: per seat, one long-lived cultureagent session; the harness sends turn-delta briefings as messages into that session and parses the same one-JSON-action reply contract; bot/command drivers remain for baselines and rematches
- Dead-heat rule (user decision): DUAL AWARD — when two teams complete the same mission on the same turn, both earn the full mission reward; id-neutral, deterministic, honors both photo-finishers (the recorded orchestrator match becomes 26-16 under this rule)

## Open / follow-up

- Whether resident seats interact with orchestrator-mode fairness (spawn budgets, model mixing) stays parked with frame v3 — this cycle fields resident seats in per-seat mode only
