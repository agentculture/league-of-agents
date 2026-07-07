"""``rusher`` — reference coded strategy for the bot lane (plan task t2, spec
c3/h2): rush the nearest control point with every unit, then hold.

Committed, readable source, distinct from the harness's own in-process
greedy bot (``league.harness.make_bot_driver``, which also runs the
harvester economy and splits points by role): rusher ignores the economy
entirely and sends every living unit straight at whichever control point is
nearest to it.

This module is loaded by ``league.harness.make_bot_file_driver`` and called
with EXACTLY the dict ``league match show --json`` returns — see
``bots/README.md`` for the full contract. It never imports anything from
``league`` and never uses randomness or the wall clock: given the same
``show_json`` input, ``decide`` always returns the same output, and every
tie (equal-distance control points, equal-distance legal moves) is broken by
sorting on id/coordinates so two runs of the same seed rush identically.
"""

from __future__ import annotations

from typing import Any


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


def decide(show_json: dict[str, Any], team_id: str) -> dict[str, Any]:
    """Every live unit on `team_id` rushes its nearest control point, then
    holds. Reads ONLY `show_json` — the parsed dict `league match show
    --json` returns (`state`, `legal_actions`, ...) — never an engine object,
    never anything beyond the public CLI surface (spec c3/h2)."""
    state = show_json["state"]
    legal_actions = show_json.get("legal_actions", {})
    control_points = state.get("control_points", [])

    my_units = sorted(
        (u for u in state["units"] if u["team_id"] == team_id and u["alive"]),
        key=lambda u: u["id"],
    )

    actions: list[dict[str, Any]] = []
    for unit in my_units:
        pos = unit["pos"]
        if not control_points:
            actions.append({"unit_id": unit["id"], "action": "hold"})
            continue
        nearest = min(control_points, key=lambda c: (_manhattan(pos, c["pos"]), c["id"]))
        if pos == nearest["pos"]:
            actions.append({"unit_id": unit["id"], "action": "hold"})
            continue
        moves = legal_actions.get(unit["id"], {}).get("move", [])
        step = _step_toward(pos, nearest["pos"], moves)
        if step is None:
            actions.append({"unit_id": unit["id"], "action": "hold"})
        else:
            actions.append({"unit_id": unit["id"], "action": "move", "to": step})

    result: dict[str, Any] = {"actions": actions}
    if state.get("turn", 0) == 0:
        result["plan"] = "rusher: every unit rushes its nearest control point, then holds"
    return result
