# League of Agents hardens the arena: the pending live matches land on the record, cooperation is scored for real, fog is fair for every player, and the release train learns its lessons

> League of Agents hardens the arena: the pending live matches land on the record, cooperation is scored for real, fog is fair for every player, and the release train learns its lessons

## Audience

- Operators and researchers comparing agent teams fairly, the maintainers running the recursive dev cycle, and (cross-repo) the devague upstream

## Before → After

- Before: Cycles 2/3 code is merged but unproven live; v0 cooperation rewarded cadence over content (losers out-cooperated winners in all three season-0 matches); bots are omniscient under fog (a documented asymmetry); the merge train minted duplicate 0.7.1 CHANGELOG entries and needed a restack merge per PR; parked blocking vagueness was resolved by hand-editing frame JSON
- After: Cycles 2/3 close their loop: resident-vs-stateless, fogged-orchestrator, and h9-retest matches are recorded and reported; cooperation v1 distinguishes real delegation from pseudo-coordination and prices discipline; a fog-aware bot lane makes fogged bot-vs-agent matches fair by construction; the stacked-train release workflow is documented with a single-bump rule; the devague resolve-verb gap is filed upstream

## Why it matters

- Issue #1 demands teams be compared fairly and scores be inspectable — a cooperation score that rewards chatter, an omniscient bot behind fog, and unrecorded live behavior all undermine the question the arena exists to answer

## Requirements

- The pending cycle-2/3 live tests run through the real agent harnesses (field agents, not raw APIs) and land as recorded reports: the resident-vs-stateless rematch on the same scenario+seed publishing rejections, latency, and token use both ways; a fogged orchestrator match on skirmish-2; the h9 coordination-necessity retest under fog; and a bot-vs-agent match. Execution stays gated on the user confirming the lobes substrate is settled
  - honesty: The seats run through their real agent harnesses (claude-cli sessions, colleague work loop) and every report reconstructs from the committed log alone
- Cooperation metric v1: rejected orders penalize delegation_spread, message content utility is scored rather than cadence alone, and one-mind pseudo-coordination is distinguished from real delegation; all season-0 logs are re-scored and published v0-vs-v1 side by side
  - honesty: v1 is not fitted to outcomes — cooperation stays a process axis; if losers still out-cooperate winners under v1, that stands as a finding, not a bug
  - honesty: Every v0-to-v1 divergence on the season-0 logs traces to a named, documented signal change
- A fog-aware bot lane: bots can consume the same fogged public surface agent teams get, with an explore-toward-unknown baseline policy, so a fogged bot-vs-agent match is fair by construction; the full-information bot remains for unfogged play and the standing asymmetry warning is retired or per-match declared
  - honesty: The fog-aware bot reads only the same fogged JSON surface an agent team gets — enforced by the same spy-test pattern that already guards the bot lane
- The stacked-train release workflow is documented in docs/process/: single version bump at the train front, the restack procedure, and CHANGELOG collision avoidance — recording this train's actual failure modes, not idealized advice
  - honesty: The doc records this train's real failure modes (duplicate 0.7.1 CHANGELOG entries, one restack merge per PR) as they actually happened
- Cross-repo: the devague gap (no CLI verb to resolve parked blocking vagueness) is filed as an issue on agentculture/devague with the hand-edit workaround as evidence; league adopts the verb when it ships and documents the workaround until then
  - honesty: The upstream issue links the hand-edit commit as evidence and proposes the verb's contract; league-side adoption is a follow-up, not a blocker

## Honesty conditions

- No thread of the announcement ships silently: each of the five hardening threads lands as a recorded artifact (report, score table, process doc, or filed upstream issue) — nothing is claimed done without its artifact
- The named audiences are real consumers: every shipped cycle-5 artifact (report, scoring change, doc, issue) states which audience it serves and how they'd use it.
- The after-state is claimed only when each of its five threads has a committed artifact on main — live-match reports, v1 scoring code plus the re-score, the fog-aware bot lane, the train doc, and the filed devague issue link.
- Every before-state deficiency cites existing evidence: the season-0 score JSONs for the cadence finding, bots/rusher.py reading full state, the duplicate-0.7.1 resolution in git history, and the hand-edited frame commit.
- The why traces to issue #1's own requirements (fair comparison, inspectable scoring) — quoted, not paraphrased into something stronger.
- tests/fixtures/determinism.hash is byte-identical before and after cycle 5 — the CI determinism gate proves the no-tick-changes boundary held, not a promise in prose.
- Each success signal is verifiable by pointing at a committed artifact (report, side-by-side score table, match log); none rests on unrecorded claims.

## Success signals

- A fogged bot-vs-agent match runs with no omniscience caveat in its report; v0 and v1 cooperation scores for every season-0 log are published side by side with each divergence explained by a named signal; the resident-vs-stateless comparison table is on the record

## Scope / boundaries

- No engine tick changes (the determinism hash stays untouched); cooperation v1 lives in scoring (log-derived) and fog-awareness in the bot/harness lane; no new game modes (cycle 4 owns single-player), no live UI, no benchmark methodology (still parked), and the SonarCloud token stays a user-side action

## Decisions

- Publish cadence stays per-merge: every merge to main touching pyproject/league/** auto-publishes to PyPI via Trusted Publishing. User decision 2026-07-07 (suggestion 5b resolved) — continuous releases match the recursive cycle; each version is a green-CI snapshot. No workflow change.
