"""``lampbearer`` — the fog-aware coded strategy for the bot lane (plan task
t3, spec c8/h4): explore toward unseen ground when no objective is known
yet, then rush the nearest known control point once fog has revealed one —
the same simple rush ``bots/rusher.py`` runs, just starting from a
fog-of-war-shaped view of the world instead of the omniscient one.

Unlike ``rusher.py`` (and the harness's own in-process bot,
``league.harness.make_bot_driver``, both of which stay full-information even
under fog — a documented, temporary asymmetry, see ``league/harness.py``'s
module docstring), this module is meant to be played with
``{"type": "bot-file", "strategy": "lampbearer", "fogged": true}`` —
``league.harness.make_bot_file_driver``'s opt-in flag — so it is handed
EXACTLY the dict ``league match show --team <id> --fog --json`` returns:
the SAME fog-of-war projection an agent team's own briefing is built from
(``league/cli/_commands/match.py:_fogged_state``,
``league/engine/knowledge.py``). Concretely, that means:

* ``show_json["state"]["control_points"]`` / ``["resource_nodes"]`` /
  ``["missions"]`` are the team's KNOWN subset only — often empty at
  kickoff — never the full board;
* ``show_json["state"]["cells_seen"]`` is the union of every grid cell the
  team's units have ever stood within vision of (accumulated across the
  whole match, not just this turn) — a cell outside that set is
  unexplored;
* ``show_json["state"]["units"]`` still lists the team's OWN roster in full
  (a team always knows its own units), plus any other team's units the fog
  fold has seen or been told about — this strategy never looks at them.

Policy, in priority order, per living unit on ``team_id``:

1. If the team's knowledge names at least one control point, rush the
   nearest one (Manhattan distance, ties broken by control-point id — the
   exact tie-break ``rusher.py`` uses) and hold once standing on it.
2. Otherwise explore: head for the nearest grid cell the team has NEVER
   seen (Manhattan distance from the unit's own position, ties broken by
   ``(x, y)`` so the choice never depends on set/dict iteration order),
   pulling the team's vision toward new ground. Once every cell is known
   (no unexplored cell remains) and still no control point has turned up,
   hold — there is nothing left to chase or explore.

Like ``rusher.py``, this is deliberately simple: no economy play
(``resource_nodes``/delivery are out of scope, the same scope rusher
draws), no defense — a fixed, readable reference for fog-fair play, not a
tuned strategy. It reads ONLY ``show_json`` — no ``league.*`` import, no
``random``/``time``/``datetime``/``secrets``/``uuid`` (the same
determinism bar ``tests/test_bots.py`` enforces over every file in this
directory by AST scan) — and never assumes a full-board key it has not been
handed: every fogged field it touches defaults to empty/absent rather than
raising, because "nothing known yet" is the normal starting condition under
fog, not an error case.
"""

from __future__ import annotations

from typing import Any

# Same rush strategy as rusher.py, played from the fogged view — the roster
# tier measures the strategy's strength, not its information diet.
TIER = "silver"


def _manhattan(a: list[int], b: list[int]) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def _step_toward(
    pos: list[int], target: list[int], legal_moves: list[list[int]]
) -> list[int] | None:
    """The legal move cell nearest `target` — `legal_moves` is already sorted
    ascending by (x, y) (``league.engine.legal.legal_actions``), and `min`
    breaks ties on that same order, so the choice never depends on how the
    caller's dict/set happened to iterate."""
    if not legal_moves:
        return None
    return min(legal_moves, key=lambda cell: (_manhattan(cell, target), cell))


def _nearest_unseen_cell(
    pos: list[int], seen: set[tuple[int, int]], grid_width: int, grid_height: int
) -> list[int] | None:
    """The never-seen grid cell nearest `pos` (Manhattan distance, ties
    broken by (x, y) ascending) — the explore-toward-unknown target. `None`
    when the grid is degenerate (no dimensions given) or every cell is
    already in `seen` (nothing left to explore)."""
    if grid_width <= 0 or grid_height <= 0:
        return None
    best: list[int] | None = None
    best_key: tuple[int, int, int] | None = None
    for x in range(grid_width):
        for y in range(grid_height):
            if (x, y) in seen:
                continue
            key = (_manhattan(pos, [x, y]), x, y)
            if best_key is None or key < best_key:
                best_key = key
                best = [x, y]
    return best


def decide(show_json: dict[str, Any], team_id: str) -> dict[str, Any]:
    """Every live unit on `team_id` rushes its nearest KNOWN control point,
    or — if none is known yet — heads for the nearest cell the team has
    never seen. Reads ONLY `show_json` — the parsed dict `league match show
    --team <id> --fog --json` returns (`state`, `legal_actions`, ...) —
    never an engine object, never anything beyond the fogged public CLI
    surface (spec c8/h4)."""
    state = show_json["state"]
    legal_actions = show_json.get("legal_actions", {})
    control_points = state.get("control_points", [])
    cells_seen = {(cell[0], cell[1]) for cell in state.get("cells_seen", [])}
    grid_width = state.get("grid_width", 0)
    grid_height = state.get("grid_height", 0)

    my_units = sorted(
        (u for u in state["units"] if u["team_id"] == team_id and u["alive"]),
        key=lambda u: u["id"],
    )

    actions: list[dict[str, Any]] = []
    for unit in my_units:
        pos = unit["pos"]
        if control_points:
            nearest = min(control_points, key=lambda c: (_manhattan(pos, c["pos"]), c["id"]))
            target = nearest["pos"]
        else:
            target = _nearest_unseen_cell(pos, cells_seen, grid_width, grid_height)

        if target is None or pos == target:
            actions.append({"unit_id": unit["id"], "action": "hold"})
            continue

        moves = legal_actions.get(unit["id"], {}).get("move", [])
        step = _step_toward(pos, target, moves)
        if step is None:
            actions.append({"unit_id": unit["id"], "action": "hold"})
        else:
            actions.append({"unit_id": unit["id"], "action": "move", "to": step})

    result: dict[str, Any] = {"actions": actions}
    if state.get("turn", 0) == 0:
        result["plan"] = (
            "lampbearer: chase known control points; otherwise explore toward unseen ground"
        )
    return result
