# Coded-strategy bots

The [`bots/`](../../bots/) directory is the **coded-strategy bot lane**:
automations with committed, readable strategies that play the arena through the
*public* CLI/JSON surface only — the same surface any external agent process
sees. A coded bot is honest opposition, not a hidden engine privilege: its
strategy is source you can read, and its matches are deterministic given the
seed. Full contract in [`bots/README.md`](../../bots/README.md).

## The strategy contract

A strategy is a single `bots/<name>.py` file exporting one function:

```python
def decide(show_json: dict, team_id: str) -> dict:
    ...
```

`show_json` is **exactly** the dict `league match show --json` returns (state,
`legal_actions`, staged teams, last-turn rejections, driver kinds); the return
value is the orders JSON `league match act --orders-json` accepts. A strategy
**may not** import `league.engine`/`league.store` (it sees only the parsed JSON),
and **may not** be nondeterministic — no `random`, `time`, `datetime`, `secrets`,
or `uuid`. Both bans are enforced structurally: the `bot-file` driver hands the
strategy only the JSON dict, and `tests/test_bots.py` AST-scans every file the
same way the engine's own import ban is enforced.

## Declared difficulty tiers

Every strategy declares a module-level `TIER` from one ordered vocabulary —
**bronze < silver < gold** — so "a higher tier beats a lower tier" has one
unambiguous meaning:

| Tier | Bot | Strategy in one line |
|------|-----|----------------------|
| bronze | `shambler.py` | Holds every turn, forever — always legal, never plays for anything. |
| silver | `rusher.py` | Every unit rushes its own nearest control point, then holds; no economy. |
| silver | `lampbearer.py` | Rusher's rush, played fog-fair against the fogged surface. |
| gold | `vanguard.py` | Runs the deliver/gather economy and splits control points by role. |

The ordering is proven, not asserted: recorded matches under
[`docs/playtests/house-tiers/`](../playtests/house-tiers/) show gold beating
silver and silver beating bronze over two seeds each, and `tests/test_bots.py`
re-runs those match-ups as a fast regression check.

## Wiring a bot into a match

```json
{"type": "bot-file", "strategy": "rusher"}
```

The fog-aware `lampbearer` opts into the fogged surface with a flag, so a fogged
bot-vs-agent match has an opponent that plays the same information game:

```json
{"type": "bot-file", "strategy": "lampbearer", "fogged": true}
```

A `bot-file` driver is recorded as residency `"bot"` — a coded strategy is a
fairness-axis peer of the greedy baseline, not an agent-residency question.

## See also

- [Harness & drivers](harness-and-drivers.md) — the `bot-file` driver and its
  in-process `bot` sibling.
- [Fog of war](fog-of-war.md) — the fogged surface `lampbearer` reads.
- [Play presets](play-presets.md) — `team-vs-team` pairs two strategies offline.
