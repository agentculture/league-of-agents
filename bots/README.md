# Coded-strategy bots

This directory is the **coded-strategy bot lane** (plan task t2, spec c3/h2):
automations with committed, readable strategies that play the arena through
the *public* CLI/JSON surface only — the same surface any external agent
process sees. A coded bot is honest opposition, not a hidden engine
privilege: its strategy is source you can read in this repo, and its
matches are deterministic given the seed.

## The contract

A strategy is a single `bots/<name>.py` file exporting one function:

```python
def decide(show_json: dict, team_id: str) -> dict:
    ...
```

- `show_json` is **exactly** the dict `league match show --json` returns:

  ```json
  {"state": {...}, "legal_actions": {...}, "staged_teams": [...],
   "last_turn_rejections": [...], "driver_kinds": {...}}
  ```

  `show_json["state"]` carries everything a public projection of a match
  carries — `units`, `control_points`, `missions`, `resource_nodes`, `teams`,
  `turn`, `grid_width`/`grid_height`, and so on (see `league match show
  --json` / `league/engine/state.py:MatchState.to_dict`). `legal_actions` is
  keyed by unit id and gives each living unit's legal `move` targets
  (already clamped to the grid and its role's move range — see
  `league/engine/legal.py`), plus `gather`/`deliver`/`hold` booleans.

- `team_id` names which team this strategy is playing this turn (a strategy
  module can be reused for either side of a match).

- The return value is the orders JSON accepted by `league match act
  --orders-json`:

  ```json
  {"plan": "<optional standing plan>",
   "messages": [{"from": "<agent-id>", "text": "..."}],
   "actions": [{"unit_id": "...", "action": "move|gather|deliver|hold",
                "to": [x, y]}]}
  ```

  `plan` and `messages` are optional; `actions` may be an empty list (every
  unit implicitly holds if it declares nothing).

## What a strategy may NOT do

- **No engine internals.** A strategy never receives (and must never import)
  anything from `league.engine` or `league.store` — it sees the same parsed
  JSON dict an external process would get over the CLI, nothing more. This
  is enforced structurally: the `bot-file` harness driver
  (`league.harness.make_bot_file_driver`) calls `match show --json` itself
  and hands the strategy only the resulting dict.
- **No nondeterminism.** No `random`, `time`, `datetime`, `secrets`, or
  `uuid` imports — matches must be reproducible given the seed, the same
  invariant the engine itself is held to (`league/engine/state.py`'s AST
  import ban). `tests/test_bots.py` enforces this over every file in this
  directory by AST scan, the same way the engine's own ban is enforced.
- **No hidden state beyond what's in `show_json`.** A strategy may keep
  module-level constants, but should treat every `decide` call as if it
  could be the first — the harness may re-load the module at any time.

## House-bot roster: declared difficulty tiers

(plan task t4, spec c12/h11) Every strategy in this directory declares a
module-level `TIER` constant from one small, ordered vocabulary —
**bronze < silver < gold** — so "a higher tier should beat a lower tier" has
one unambiguous meaning across the whole roster:

| Tier   | Bot                | Strategy, one line                                                                 |
| ------ | ------------------ | ----------------------------------------------------------------------------------- |
| bronze | `shambler.py`       | Holds every turn, forever — legal every time, never plays for anything.             |
| silver | `rusher.py`         | Every unit rushes its own nearest control point, then holds; no economy.            |
| silver | `lampbearer.py`     | Rusher's rush, played fog-fair: explores toward never-seen cells until a control point is known, then rushes it (see the fog-aware section below).                           |
| gold   | `vanguard.py`       | Harvester runs the deliver/gather economy off `legal_actions`; scout and defender claim *distinct* control points instead of duplicating coverage the way rusher's units do. |

Recorded proof that the ordering holds — gold beating silver, and silver
beating bronze, over two seeds each (matches are deterministic; the `seed`
carries no RNG, so re-running reproduces the same result) — lives under
[`docs/playtests/house-tiers/`](../docs/playtests/house-tiers/); see that
directory's [`house-tiers.report.md`](../docs/playtests/house-tiers/house-tiers.report.md)
for the final scores and what each match's log shows actually happened on
the board. `tests/test_bots.py` also re-runs the
same two match-ups directly (`test_vanguard_gold_beats_rusher_silver`,
`test_rusher_silver_beats_shambler_bronze`) as a fast, cheap regression
check that the ordering keeps holding as the bots evolve.

## Reference strategy: `rusher.py`

`rusher.py` is deliberately simple: every live unit on the team heads for
whichever control point is nearest to it (Manhattan distance, ties broken by
control-point id so the choice never depends on dict/set iteration order),
moving as far as its `legal_actions` entry allows toward that point each
turn, and holding once it arrives. No economy play, no defense — a fixed,
readable reference opponent, distinct from the harness's own in-process
greedy bot (`league.harness.make_bot_driver`, which also runs the harvester
economy and splits control points by role). It anchors the roster's middle
(`silver`) tier — `shambler.py` (`bronze`) and `vanguard.py` (`gold`) are
built as a deliberately weaker and a deliberately stronger strategy around
it, per the roster table above.

## Fog-aware strategy: `lampbearer.py`

`lampbearer.py` is the fog-aware counterpart to `rusher.py` (plan task t3,
spec c8/h4): it is written against the **fogged** public surface —
`league match show --team <id> --fog --json` — never the full board. Every
living unit heads for the nearest control point the team's knowledge fold
has already seen or been told about (rusher's own rush, applied to what fog
allows); once no control point is known yet, it falls back to an
explore-toward-unknown baseline, heading each unit toward the nearest grid
cell the team has never seen (`state["cells_seen"]`), so a fogged
bot-vs-agent match gets an opponent that plays the same information game
instead of cheating past the fog.

Wire it up with the `bot-file` driver's opt-in `"fogged"` flag —
`league.harness.make_bot_file_driver` then calls `match show --team <id>
--fog` instead of the plain view. Without the flag, a `bot-file` strategy
still gets the full board (today's default, unchanged for `rusher.py` or
any strategy that doesn't declare itself fog-aware):

```json
{"type": "bot-file", "strategy": "lampbearer", "fogged": true}
```

A match that pairs a `"fogged": true` bot-file team against a fogged agent
team needs no omniscience caveat in its report — the standing asymmetry
warning (`league/harness.py`'s module docstring) applies only when a
bot-file team's spec omits `"fogged"` (or when the in-harness `bot` driver,
`league.harness.make_bot_driver`, is used at all — that policy stays
full-information regardless, unchanged by this task).

## Wiring a bot into a match

Point a team's driver at a strategy by name — zero harness code changes
needed to add a new one, just drop a new `bots/<name>.py`:

```json
{"type": "bot-file", "strategy": "rusher"}
```

```python
from league.harness import build_driver

driver = build_driver({"type": "bot-file", "strategy": "rusher"}, scenario)
```

The match log records a `bot-file` driver the same way it records the
in-harness greedy bot: as residency `"bot"` (see `league.harness.driver_kind`)
— a coded strategy is a fairness-axis peer of the greedy baseline, not an
agent-residency question.

## Adding a new strategy

1. Add `bots/<name>.py` with a `decide(show_json, team_id)` function, stdlib
   only, no `league.*` imports, no randomness/wall-clock.
2. Use a name that is filesystem-safe (letters, digits, `.`, `_`, `-`,
   starting with a letter or digit — the same rule `league.store.validate_id`
   applies to every other id in this repo) — the loader validates it before
   ever touching the filesystem.
3. Declare a module-level `TIER` constant — one of `"bronze"`, `"silver"`,
   `"gold"` (the roster's ordered vocabulary above) — and add a row to the
   roster table describing the idea in one line.
4. Wire it up with `{"type": "bot-file", "strategy": "<name>"}` in a harness
   match config.
5. Add tests under `tests/test_bots.py` (or your own) proving it is
   deterministic and stays inside the public surface — follow the existing
   tests for `rusher.py`/`shambler.py`/`vanguard.py` as a template. If your
   new bot claims a place in the tier ordering, record a match proving it
   (see `docs/playtests/house-tiers/generate_matches.py` for the pattern) and
   update its report.
