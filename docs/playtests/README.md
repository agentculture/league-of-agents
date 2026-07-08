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
| [`cycle-6/`](cycle-6/) | The long-horizon memory match (a resident mind on a seeded 21×17 fogged board, 60 turns), the two span-of-control probe runs (Sonnet and colleague orchestrators), their comparison report, and the first recorded human review with its findings ledger. | Cycle-6 — "watchable and vast": seeded generation, the span probe, and the human-evaluation loop. |
| [`cycle-7/`](cycle-7/) | The first continuous-lane live match: four resident claude seats racing for `cp-crossing` on the event timeline — the race (`post_taken` at t=8 over a mid-take rival, `action_failed` "post taken by a faster agent") happened live and unscripted. | Cycle-7 — "steps off the grid": race semantics, role-given speed, and the mind-facing time-budget contract, all demonstrated in anger. |
| [`cycle-8/`](cycle-8/) | The first fogged continuous match: six sonnet seats on full 3-role rosters (`c-frontier-1`), four `action_failed` delivery denials in a mutual standoff both teams entered knowingly, a 0–0 draw, and the per-unit scorecard naming a scout MVP and a never-re-asked defender LVP — the "a pass parks a seat forever" finding that seeds cycle 9. | Cycle-8 — "grades every seat": fog, contention, MVP/LVP, and the baked seat contract, all live in one record. |
| [`house-tiers/`](house-tiers/) | Four bot-vs-bot matches (two seeds each) proving the house roster's tier ordering — bronze < silver < gold — via `bots/shambler.py` / `bots/rusher.py` / `bots/vanguard.py`. | Cycle-4's house-bot ladder, kept reproducible via [`generate_matches.py`](house-tiers/generate_matches.py). |

Every log in every directory above — 16 as of cycle-8 t12 (14 grid, 2
continuous), and growing — is swept by `tests/test_committed_logs_compat.py`
on every test run: it detects each log's engine lane from its own header,
folds it to its final state with that lane's fold, and checks the committed
outcome hasn't drifted (`*.score.json` for grid logs, `*.outcome.json` for
continuous ones). That sweep is the guard against this whole directory going
silently stale as the engine changes — see its module docstring for what
"additive" means and what to do if it ever goes red.
