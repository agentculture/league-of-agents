# Cycle 7 live playtest — the race, live: four resident minds on the continuous timeline

**Match:** `c-race-live` · scenario `c-skirmish-1` · seed 20260707 · competitive ·
finished at game_time **14** of 20 · **Blue Foundry 19 — Red Relay 0**

**Seats:** four live minds — two per team, every seat a resident `claude`
(sonnet) session fielded through `scripts/cseat_driver.py` (a `command` driver
with `residency: resident`; model choice is config, not code). No seat is a
bot; both teams are the same mind, so the outcome separates *play*, not model.

**Artifacts** (each named for the audience it serves, per the spec's honesty
conditions):

| Artifact | Audience | What it proves |
|---|---|---|
| `race-live.log.jsonl` | researchers | the race, checkable event-by-event |
| `race-live.replay.html` | researchers / humans | the race visible: `race-win` and `race-fail` moments, the contested post's dashed taker rings |
| `race-live.config.json` | agent teams / operators | how live seats are fielded (driver spec, roster, roles) |
| `race-live.outcome.json` | maintainers | the recorded outcome the compat sweep re-folds forever |
| the two-lane compat sweep (`tests/test_committed_logs_compat.py`) | maintainers | this log is now a permanent tripwire, same as every grid playtest |

## The race actually happened — cited to the exact events

The spec's success signal asks for "a recorded continuous-arena match where a
faster agent takes a post while a slower agent is mid-capture." The log records
precisely that, unscripted:

| game_time | event | fact |
|---|---|---|
| 0 | `action_started` | red-u2 (harvester, spawned ON `cp-crossing`) starts `take_post`, completion **10** |
| 0 | `action_started` | blue-u1 (defender) starts `move` toward the post, completion 2 |
| 2 | `action_started` | blue-u1 arrives and starts its own `take_post`, completion **8** — the post now has TWO concurrent takers (`CControlPoint.takers`), a full 6-time-unit overlap window |
| 8 | `post_taken` | `cp-crossing` → blue (blue-u1) |
| 8 | `action_failed` | red-u2, reason **"post taken by a faster agent"** — mid-take, 2 time-units short of its own completion |

Red started 2 time-units earlier and still lost: `take_post_duration` is role
data (defender 6, harvester 10), so the slower role's head start was arithmetic
the faster role could beat. That is the cycle's whole thesis in one exchange.

## The minds narrated the race before it resolved

Every quote below is a `message_sent` / `plan_declared` observation in the
committed log (thinking happened live; the log is the record):

- **blue-defender, t=0** — "Rushing cp-crossing to contest/hold it (red
  harvester already there…)"; plan: "u1 holds cp-crossing for ms-hold; u2 farms
  rn-home and delivers to ms-supply."
- **red-harvester, t=0** — "Holding cp-crossing now (already here, complete
  t=10, beats blue's earliest possible completion…)" — **a live timing
  miscalculation**: it priced the race in its *own* role's numbers. Blue's
  racer was a defender (take 6, arrive t=2, finish t=8), not another harvester
  (which would indeed have finished 2+10=12 > 10).
- **blue-defender, t=2** — "Taking cp-crossing now — my take_post completes at
  t=8, beating red-u2's t=10." The winning mind called the outcome six
  time-units before the engine resolved it, from the briefing's `menu`
  durations and the post's live `takers` list.
- **red-defender, t=0** — correctly wrote off the economy ("rn-home arrival for
  me is t=20 (time limit, useless)") and red doubled down on the hold — then
  lost the hold race it had mispriced.

Blue's labor split (defender races, harvester runs the economy in parallel) is
exactly the coordination the scenario forces by construction: the committed
solo-path arithmetic is 36 > 20 for either role, and blue finished both
missions at t=14 — the same clock the canonical scripted match posts.

## Findings

1. **Race semantics create a new reasoning class, and live minds engage it.**
   Both teams reasoned about completion times, not moves. One got it right by
   reading the opponent's role data; one got it wrong by assuming symmetric
   speed. Nothing in the grid lane could have distinguished these two minds.
2. **Reading the opponent's role table is the new skill gap.** Red's
   miscalculation ("complete t=10 beats blue") is the continuous lane's
   version of not counting tempo in chess. A briefing surfaces `role` for
   every visible unit; the winning mind used it, the losing mind didn't.
3. **Substrate independence held under live load** (spec h7, demonstrated in
   anger): the four seats spent **252.9s of wall-clock thinking** across 9
   decision points (median 14.3s, max 90.7s on a first briefing) while the
   game clock ran 14 integer units and the log's event order came only from
   role durations and the timeline. `seat_latency` observations carry the
   wall-clock beside the game clock — raw always beside converted, as the
   tempo axis requires.
4. **The operator layer is where the contract lives — for now.** The
   continuous harness hands `command`/`resident` drivers the raw briefing
   JSON; `scripts/cseat_driver.py` supplies the mind-facing contract text on
   first contact and threads later decisions into the same `claude` session
   (`--session-id` / `--resume`), the same field-the-agent-not-the-API
   doctrine `scripts/colleague_driver.py` set in season 0. The grid harness
   bakes seat prompts in (`_SEAT_PROMPT`); lane parity is a cycle-8 seed
   under the all-backends rule.
5. **A losing seat keeps playing legally.** After the t=8 failure, red-u2
   immediately re-took the (now blue-owned) post — completion 18, mooted by
   blue finishing both missions at t=14. Post-loss behavior is on the record,
   not off it.

## Before-state, cited (why this cycle exists)

Issue #1 asks that "roles/specialization matter" and that "decisions [have]
visible consequences over multiple turns/phases" — quoted, not strengthened.
Before this cycle, the engine could not express a race at all:

- `league/engine/tick.py` resolves **uniform simultaneous turns** in canonical
  `(team_id, unit_id)` order — every unit acts exactly once per turn regardless
  of role; in-game speed does not exist.
- Capture is a **streak of whole turns** (`hold` on `ControlPoint`,
  `league/engine/state.py`; "sole occupancy builds a streak… both teams on the
  square = contested: the streak resets", `tick.py` module docstring) — a
  faster agent snatching a post mid-capture is impossible by construction.
- Speed existed only **out of game**: tempo t0 (`league/engine/tempo.py`)
  measures wall-clock read-time; in-game time was "perfectly uniform and
  strategically inert" (spec, before-state).

## Closing ledger — every announcement phrase, its committed artifact

| Announcement phrase | Committed artifact |
|---|---|
| "decimal positions" (exact, never floats) | `league/engine/continuous/space.py` (fixed-point milliunits, SCALE=1000); the float-ban and hash tests in `tests/test_continuous_state.py` |
| "role-given speed" | `league/engine/continuous/roles.py` `DEFAULT_CROLE_STATS` (defender take 6 vs harvester 10 decided this match) |
| "time itself as the resolver / actions take duration" | `league/engine/continuous/timeline.py` + `resolve.py`; every `action_started` in this log carries `start_time`/`completion_time` |
| "a faster agent acts again sooner" | this log's decision cadence: blue-u1 decided at t=0, 2, 8; red-u1 (slow start, far spawn) at t=0, 10 |
| "a post can be snatched mid-capture by whoever finishes first" | events cited above (t=8 `post_taken` + `action_failed` "post taken by a faster agent"), live, unscripted |
| "deterministic… its own scripted determinism gate" | `tests/test_determinism_gate_continuous.py` + `tests/fixtures/determinism_continuous.hash` |
| "the grid engine and every committed artifact keep working untouched" | the two-lane boundary tests (`tests/test_two_lane_honesty.py`), the untouched grid hash, and this PR's two-lane compat sweep — grid logs fold exactly as before |
| "the race visible in the replay" | `race-live.replay.html` (`race-win` / `race-fail` moments; dashed concurrent-taker rings during the t=2–8 overlap) |
| "briefings that give agent teams their time budgets" | the briefing contract (`league/charness.py` `build_briefing`: menu durations, absolute `completion_time`, initiative `outlook`) — the same JSON each of these four seats received |

Scoring note (the explicit two-lane decision, `docs/continuous-contract.md`):
this match is scored on **outcome only** (2 per held post + mission rewards →
19–0). Cooperation v1, tempo t0, and probe p0 remain grid-only this cycle;
their continuous adaptation is deliberately deferred, not silently drifted.
