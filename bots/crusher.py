"""``crusher`` — reference coded strategy for the CONTINUOUS bot lane (plan
C7-t7): rush the nearest control point and take it the instant you arrive.

The continuous-lane sibling of ``bots/rusher.py``, and it keeps the same
discipline — committed, readable source that plays through the *public* surface
only. ``decide_continuous`` receives EXACTLY the briefing JSON
``league.charness`` builds for a mind at a decision point (``game_time``,
``you``, ``menu`` with per-action durations and completion times, ``outlook``,
``board``) and returns ONE action for THIS decision point.

That single-action return IS the fundamental continuous contract change: a mind
is asked per idle unit as game time advances, not once per turn for a whole
team. Where ``bots/rusher.py`` returns a whole-team ``{"actions": [...]}`` dict
for the grid's simultaneous turn, the continuous entry point is
``decide_continuous(briefing, team_id)`` returning ``{"action": <menu entry |
None>, "message"?: str}`` — the exact shape ``league.charness`` expects back
from every driver kind. The distinct function name is deliberate: a grid
``decide`` and a continuous ``decide_continuous`` can never be called with the
wrong contract.

Like ``rusher``, this file never imports anything from ``league`` and never uses
randomness or the wall clock: given the same briefing, ``decide_continuous``
always returns the same action, and every tie (equal completion times) is broken
by sorting on the target label, so two runs of the same match rush identically.
"""

from __future__ import annotations

from typing import Any


def _by_soonest(menu: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    """Menu entries of one kind in a deterministic order: soonest completion
    first, ties broken on the target label so the choice never depends on how
    the caller happened to order the menu."""
    return sorted(
        (m for m in menu if m.get("kind") == kind),
        key=lambda m: (m["completion_time"], str(m.get("target"))),
    )


def decide_continuous(briefing: dict[str, Any], team_id: str) -> dict[str, Any]:
    """Take the post the moment it is on offer; otherwise rush the nearest
    control point (then any nearest point of interest). Reads ONLY ``briefing``
    — never an engine object, never anything beyond the public mind-facing
    contract."""
    menu = briefing.get("menu", [])

    takes = _by_soonest(menu, "take_post")
    if takes:
        return {"action": takes[0], "message": f"taking {takes[0].get('target')}"}

    control_point_ids = {cp["id"] for cp in briefing.get("board", {}).get("control_points", [])}
    moves = _by_soonest(menu, "move")
    toward_posts = [m for m in moves if m.get("target") in control_point_ids]
    if toward_posts:
        return {"action": toward_posts[0]}
    if moves:
        return {"action": moves[0]}
    return {"action": None}
