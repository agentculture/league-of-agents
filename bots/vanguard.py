"""``vanguard`` — gold-tier strategy for the bot lane (plan task t4, spec
c12/h11): the roster's strongest coded opponent, built to improve on
``rusher.py`` on the two axes that decided every season-0 playtest
(``docs/playtests/season-0/*.report.md``) — the delivery-mission economy,
which rusher ignores entirely, and control-point coverage, where rusher lets
its units independently converge on the same "nearest" point instead of
splitting the board.

Two ideas, both readable from ``show_json`` alone (spec c3/h2), never a
scenario/role-stat constant:

* **Run the economy.** A harvester's own ``legal_actions`` entry already
  says everything it needs, without ever reading a role's carry capacity
  directly: deliver when ``legal["deliver"]`` is true (standing on the
  delivery square with cargo), gather when ``legal["gather"]`` is true
  (standing on a node with room left to carry), otherwise head for whichever
  matters next — the delivery square if it is already carrying something,
  else the nearest resource node with stock left.
* **Split the control points, don't duplicate them.** Scouts and defenders
  claim DISTINCT control points this turn (nearest-available-first, in unit
  id order, preferring a point the team doesn't already own) instead of
  every unit separately picking its own nearest point the way rusher's units
  do — two units racing the same point is coverage rusher leaves on the
  table.

Same determinism bar as every strategy here (no random/time/datetime/
secrets/uuid, no ``league.*`` import — ``tests/test_bots.py``'s AST scan
enforces it): every tie-break sorts on id/coordinates, never on dict/set
iteration order.
"""

from __future__ import annotations

from typing import Any

TIER = "gold"


def _manhattan(a: list[int], b: list[int]) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def _step_toward(
    pos: list[int], target: list[int], legal_moves: list[list[int]]
) -> list[int] | None:
    """The legal move cell nearest `target` — mirrors ``rusher._step_toward``:
    `legal_moves` is already sorted ascending by (x, y) (``league.engine.
    legal.legal_actions``), and `min` breaks ties on that same order, so the
    choice never depends on how the caller's dict/set happened to iterate."""
    if not legal_moves:
        return None
    return min(legal_moves, key=lambda cell: (_manhattan(cell, target), cell))


def _harvester_order(
    unit: dict[str, Any], legal: dict[str, Any], deliver_pos: list[int] | None, nodes: list[dict]
) -> dict[str, Any]:
    unit_id = unit["id"]
    if legal.get("deliver"):
        return {"unit_id": unit_id, "action": "deliver"}
    if legal.get("gather"):
        return {"unit_id": unit_id, "action": "gather"}

    pos = unit["pos"]
    if unit["carrying"] > 0 and deliver_pos is not None:
        target = deliver_pos
    elif nodes:
        nearest = min(nodes, key=lambda n: (_manhattan(pos, n["pos"]), n["id"]))
        target = list(nearest["pos"])
    elif deliver_pos is not None:
        target = deliver_pos
    else:
        return {"unit_id": unit_id, "action": "hold"}

    if pos == target:
        return {"unit_id": unit_id, "action": "hold"}
    step = _step_toward(pos, target, legal.get("move", []))
    if step is None:
        return {"unit_id": unit_id, "action": "hold"}
    return {"unit_id": unit_id, "action": "move", "to": step}


def decide(show_json: dict[str, Any], team_id: str) -> dict[str, Any]:
    """Harvesters run the delivery economy; scouts and defenders split
    distinct control points instead of duplicating coverage. Reads ONLY
    `show_json` — the parsed dict `league match show --json` returns
    (`state`, `legal_actions`, ...) — never an engine object, never anything
    beyond the public CLI surface (spec c3/h2)."""
    state = show_json["state"]
    legal_actions = show_json.get("legal_actions", {})
    control_points = state.get("control_points", [])
    missions = state.get("missions", [])
    resource_nodes = [n for n in state.get("resource_nodes", []) if n.get("remaining", 0) > 0]
    deliver_mission = next((m for m in missions if m.get("kind") == "deliver"), None)
    deliver_pos = list(deliver_mission["pos"]) if deliver_mission is not None else None

    my_units = sorted(
        (u for u in state["units"] if u["team_id"] == team_id and u["alive"]),
        key=lambda u: u["id"],
    )

    actions: list[dict[str, Any]] = []
    claimed: set[str] = set()
    for unit in my_units:
        legal = legal_actions.get(unit["id"], {})

        if unit["role"] == "harvester":
            actions.append(_harvester_order(unit, legal, deliver_pos, resource_nodes))
            continue

        pos = unit["pos"]
        available = [c for c in control_points if c["id"] not in claimed]
        wanted = [c for c in available if c.get("owner") != team_id] or available
        if not wanted:
            actions.append({"unit_id": unit["id"], "action": "hold"})
            continue
        target_cp = min(wanted, key=lambda c: (_manhattan(pos, c["pos"]), c["id"]))
        claimed.add(target_cp["id"])
        if pos == list(target_cp["pos"]):
            actions.append({"unit_id": unit["id"], "action": "hold"})
            continue
        step = _step_toward(pos, list(target_cp["pos"]), legal.get("move", []))
        if step is None:
            actions.append({"unit_id": unit["id"], "action": "hold"})
        else:
            actions.append({"unit_id": unit["id"], "action": "move", "to": step})

    result: dict[str, Any] = {"actions": actions}
    if state.get("turn", 0) == 0:
        result["plan"] = (
            "vanguard: harvester runs the delivery relay; scout and defender "
            "split distinct control points instead of duplicating coverage"
        )
    return result
