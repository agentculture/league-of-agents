# Playtest index

Every subdirectory here is a committed, historical playtest: a match that
actually happened, kept as a permanent record rather than a disposable
scratch run. Each carries a `*.log.jsonl` (always — the event log is the
single source of truth per `league/engine/events.py`) and usually a
`*.score.json` (the `score_match` output for that log), plus most carry a
`*.replay.html` and a `*.report.md` drawing conclusions from the two. A few
directories also keep the generator script that produced their matches, so
the set is reproducible, not just readable.

| Directory | What it recorded | Thread it serves |
| --- | --- | --- |
| [`season-0/`](season-0/) | The three season-0 launch matches — opener (solo vs solo), coordination (solo vs swarm under a turn-limit squeeze), and orchestrator mode (a spawning master vs a greedy baseline) — plus a v0/v1 cooperation re-score of all three logs, side by side. | Season-0's closing playtests (`opener`/`coordination`/`orchestrator` reports) and the cycle-5 cooperation-v1 re-score (`cooperation-v1.report.md`). |
| [`cycle-4/`](cycle-4/) | A preset-launched solo-vs-house-bot match, a three-mind tempo benchmark (Sonnet, Haiku, and a local Qwen agent on the same board), and a clean-checkout end-to-end demo. | Cycle-4 — "goes single-player": presets, house-bot tiers, and the tempo axis. |
| [`cycle-5/`](cycle-5/) | The colleague guild's cooperative-mode match: three local-model seats coordinating through in-game messages only, no solo handicap. | Cycle-5's orchestrator/harness live-test thread. |
| [`house-tiers/`](house-tiers/) | Four bot-vs-bot matches (two seeds each) proving the house roster's tier ordering — bronze < silver < gold — via `bots/shambler.py` / `bots/rusher.py` / `bots/vanguard.py`. | Cycle-4's house-bot ladder, kept reproducible via [`generate_matches.py`](house-tiers/generate_matches.py). |

Every log in every directory above — 11 as of cycle-6 t11, and growing — is
swept by `tests/test_committed_logs_compat.py` on every test run: it folds
each committed log to its final state and, wherever a `*.score.json` pairs
with it, checks the outcome totals haven't drifted. That sweep is the guard
against this whole directory going silently stale as the engine changes —
see its module docstring for what "additive" means and what to do if it ever
goes red.
