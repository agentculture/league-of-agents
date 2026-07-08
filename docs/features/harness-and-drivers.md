# Agent-player harness & drivers

The harness ([`league/harness.py`](../../league/harness.py) for the grid lane,
[`league/charness.py`](../../league/charness.py) for continuous) plays a whole
match with live team drivers, acting **only through the public CLI surface** —
it reads `match show --json`, produces orders, and submits them with
`match act --orders-json --apply`. It never reaches into engine internals, which
is exactly what keeps a live agent honest: it sees no more than any external
process would.

```bash
league harness run --config playtest.json          # dry-run
league harness run --config playtest.json --apply   # play it
```

## One mind per seat

The defining design choice: each seat is an **independent mind that coordinates
only through in-game messages**. There is no shared scratchpad and no
out-of-band channel — if two seats are going to cooperate, they have to
communicate on the board. Which model sits in a seat is **configuration, not
code**: a colleague model, a Sonnet subagent, or an orchestrator is a config
change.

## Driver kinds

Set per team in the config JSON:

- **`bot`** — the deterministic in-process greedy baseline (no model), which runs
  the harvester economy and splits control points by role.
- **`command`** — any external agent as a subprocess: the prompt (rules + state
  JSON) goes in on stdin, orders JSON comes back on stdout. Defaults to
  `stateless` residency (a fresh subprocess every turn).
- **`resident`** — one persistent session per seat for the whole match (a
  long-lived mind, set with `"residency": "resident"`).
- **`bot-file`** — a committed [coded strategy](coded-strategy-bots.md) loaded by
  name, played through the same public surface.

## Residency is a recorded fairness axis

Every driver declares a residency, and `run_match` records each team's kind in
the match log header — so `match show --json`'s `driver_kinds` always answers
"how was this team's mind driven?" beside its score. Residency is a *fairness
axis*, never game state.

## Orchestrator mode

A team can be run as a **master mind commanding per-seat ground agents**. Two
declared levers ride in the log header (see [Fog of war](fog-of-war.md)):
`map_read` (does the master read the full board or the fogged view) and
`unit_comms` (may ground units talk to each other, or only through the master).
The harness reads these off each team's config to decide what the master's
briefing sees and which messages a seat relays.

## The seat contract

`charness` bakes a `SEAT_CONTRACT` / `SEAT_DELTA` for every driver kind at first
contact, so the transport scripts (`scripts/cseat_driver.py`) stay
transport-only — the contract, not the plumbing, defines what a seat is handed.

Config shape (grid):

```json
{"match": {"scenario": "...", "mode": "...", "seed": 7, "id": "..."},
 "teams": [{"id": "blue", "name": "...", "driver": {"type": "command", "argv": ["..."]},
            "agents": [{"id": "blue-1", "model": "...", "role": "scout"}]}],
 "max_rounds": 30, "fog": false}
```

## See also

- [Play presets](play-presets.md) — bundled configs that launch these modes in
  one command.
- [Coded-strategy bots](coded-strategy-bots.md) — the `bot-file` lane.
- [Agent-first CLI](agent-first-cli.md) — the public surface the harness rides.
