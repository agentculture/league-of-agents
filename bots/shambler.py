"""``shambler`` — bronze-tier reference strategy for the bot lane (plan task
t4, spec c12/h11): the roster's floor. Every live unit on the team holds,
every turn, forever.

Committed on purpose as the WEAK end of the roster's tier ordering
(bronze < silver < gold — see ``bots/README.md``): ``hold`` is always legal
(``bots/README.md``'s contract — every action here is one the harness would
accept from any strategy), so a shambler team never once breaks the rules.
It simply never plays for anything — no control point, no mission, no
resource node ever enters its decision — so it scores zero missions, zero
control points, and zero delivered resources against any tier that actually
contests the board (``bots/rusher.py``, ``bots/vanguard.py``). That is the
bronze tier's whole point: "legal-but-poor decisions," not illegal ones.

Same determinism bar as every strategy in this lane (no random/time/
datetime/secrets/uuid, no ``league.*`` import — ``tests/test_bots.py``'s AST
scan enforces this over every file in ``bots/``): there is nothing here that
could vary between two runs of the same seed in the first place.
"""

from __future__ import annotations

from typing import Any

TIER = "bronze"


def decide(show_json: dict[str, Any], team_id: str) -> dict[str, Any]:
    """Every live unit on `team_id` holds. Reads ONLY `show_json` — the
    parsed dict `league match show --json` returns (`state`, `legal_actions`,
    ...) — never an engine object, never anything beyond the public CLI
    surface (spec c3/h2)."""
    state = show_json["state"]

    my_units = sorted(
        (u for u in state["units"] if u["team_id"] == team_id and u["alive"]),
        key=lambda u: u["id"],
    )

    actions = [{"unit_id": unit["id"], "action": "hold"} for unit in my_units]

    result: dict[str, Any] = {"actions": actions}
    if state.get("turn", 0) == 0:
        result["plan"] = "shambler: holds every turn, never seeks an objective"
    return result
