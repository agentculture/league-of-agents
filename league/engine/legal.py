"""Legal-actions surface — a pure helper reporting each unit's legal orders.

``resolve_turn`` (``tick.py``) already knows exactly which orders are legal —
it rejects everything else with an ``action_rejected`` event and a reason.
But that legality only becomes visible *after* a seat spends an order on it.
The season-0 coordination playtest (``docs/playtests/season-0/
coordination.report.md``) burned 19 of 53 orders on exactly that: 10
beyond-move-range moves and 6 off-square delivers, because nothing told the
deciding agent what was legal *before* it declared.

``legal_actions`` closes that gap by exposing the same legality as a query:
given a state and the scenario it came from, what can this one unit legally
do right now? It mirrors ``resolve_turn``'s applicability rules for
``move``/``gather``/``deliver`` (``hold`` is always legal — standing still
never fails) without engine mutation or randomness, so callers — the CLI
projection, a briefing, a future orchestrator — can check legality before
spending an order on it.
"""

from __future__ import annotations

from typing import Any

from league.engine.scenario import Scenario
from league.engine.state import MatchState


def legal_actions(state: MatchState, scenario: Scenario, unit_id: str) -> dict[str, Any]:
    """The legal orders available to ``unit_id`` in ``state``, right now.

    Returns::

        {"move": [[x, y], ...], "gather": bool, "deliver": bool, "hold": True}

    * ``move`` — every on-grid cell within the unit's role's ``move`` stat
      (Manhattan distance), excluding the unit's current cell, sorted
      ascending by ``(x, y)`` so the result is byte-for-byte deterministic.
    * ``gather`` — ``True`` iff the unit stands on a resource node with
      ``remaining > 0`` and it is carrying below its role's ``carry`` stat.
    * ``deliver`` — ``True`` iff the unit stands on an **open** deliver
      mission's square while carrying more than zero.
    * ``hold`` — always ``True``.

    Raises ``ValueError`` if ``unit_id`` names no unit in ``state``.
    """
    unit = next((u for u in state.units if u.id == unit_id), None)
    if unit is None:
        raise ValueError(f"unknown unit {unit_id!r}")

    stats = scenario.stats_for(unit.role)
    ux, uy = unit.pos

    moves: list[list[int]] = []
    for dx in range(-stats.move, stats.move + 1):
        remaining = stats.move - abs(dx)
        for dy in range(-remaining, remaining + 1):
            if dx == 0 and dy == 0:
                continue
            x, y = ux + dx, uy + dy
            if 0 <= x < state.grid_width and 0 <= y < state.grid_height:
                moves.append([x, y])
    moves.sort()

    node = next((n for n in state.resource_nodes if n.pos == unit.pos), None)
    gather = node is not None and node.remaining > 0 and unit.carrying < stats.carry

    mission = next((m for m in state.missions if m.kind == "deliver" and m.pos == unit.pos), None)
    deliver = mission is not None and mission.status == "open" and unit.carrying > 0

    return {"move": moves, "gather": bool(gather), "deliver": bool(deliver), "hold": True}
