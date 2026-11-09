"""Early end: how much of the score can still change, and is the lead decisive?

A match may end before its turn limit when the leader's lead is large
RELATIVE to the most the gap could still close by (``max_swing``). The bound
is generous to the trailing team on purpose, so ``lead > max_swing`` really
means "cannot be overcome":

* the trailing team is credited with EVERY objective it could still reach in
  time, all at once (as if its units could be everywhere): each open hold
  mission, each control point it does not own, the Crown, the deliver
  mission, and every resource still on the board or in its own units' (or,
  with a thief, the enemy's) cargo;
* the leader is assumed to gain nothing more and to lose every control point
  the trailing team could still capture in time.

"In time" uses exact travel: there is no blocking on the board, so a unit
needs ``ceil(distance / move)`` turns to arrive, and an occupancy streak
counts from its arrival turn. Pure and deterministic, like the tick.
"""

from __future__ import annotations

import math
from typing import Any

from league.engine.scenario import Scenario
from league.engine.state import MatchState

CP_POINTS = 2


def _eta(state: MatchState, scenario: Scenario, team_id: str, pos, *, capture: bool) -> int | None:
    """Fewest turns until one of the team's units (capture-capable when
    ``capture``) stands on ``pos``; ``None`` if it has no such unit."""
    best: int | None = None
    for unit in state.units:
        if unit.team_id != team_id or not unit.alive:
            continue
        stats = scenario.stats_for(unit.role)
        if capture and not stats.can_capture:
            continue
        dist = abs(unit.pos[0] - pos[0]) + abs(unit.pos[1] - pos[1])
        turns = math.ceil(dist / stats.move) if dist else 0
        best = turns if best is None else min(best, turns)
    return best


def _streak_turns(state, scenario, team_id, pos, need: int, current: int, remaining: int) -> bool:
    """Can ``team_id`` build a sole-occupancy streak of ``need`` on ``pos``
    within ``remaining`` turns? ``current`` is its streak there now."""
    eta = _eta(state, scenario, team_id, pos, capture=True)
    if eta is None:
        return False
    turns = need - current if eta == 0 else eta + need - 1
    return turns <= remaining


def max_swing(state: MatchState, scenario: Scenario, leader: str, trailer: str) -> int:
    """Most points the gap between ``leader`` and ``trailer`` could still close
    by before the turn limit (gain for the trailer + loss for the leader)."""
    remaining = state.turn_limit - state.turn
    if remaining <= 0:
        return 0
    cap = scenario.capture_hold_turns
    gain = 0
    loss = 0
    for cp in state.control_points:
        if cp.owner == trailer:
            continue
        current = dict(cp.hold).get(trailer, 0)
        if _streak_turns(state, scenario, trailer, cp.pos, cap, current, remaining):
            gain += CP_POINTS
            if cp.owner == leader:
                loss += CP_POINTS
    trailer_team = next(t for t in state.teams if t.id == trailer)
    stock = sum(n.remaining for n in state.resource_nodes)
    steals = any(scenario.stats_for(u.role).can_steal for u in state.units if u.team_id == trailer)
    cargo = sum(u.carrying for u in state.units if u.alive and (u.team_id == trailer or steals))
    available = stock + cargo
    gain += available
    for mission in state.missions:
        if mission.status != "open":
            continue
        if mission.kind == "hold":
            cp = next((c for c in state.control_points if c.pos == mission.pos), None)
            if cp is None:
                continue
            current = dict(cp.hold).get(trailer, 0)
            if _streak_turns(
                state, scenario, trailer, cp.pos, cap + mission.amount, current, remaining
            ):
                gain += mission.reward
        elif mission.kind == "deliver" and mission.serves(trailer):
            if trailer_team.resources + available >= mission.amount:
                gain += mission.reward
    crown = state.crown
    if crown is not None and crown.taken_by is None:
        current = dict(crown.hold).get(trailer, 0)
        if _streak_turns(state, scenario, trailer, crown.pos, crown.hold_turns, current, remaining):
            gain += crown.value
    return gain + loss


def standing(
    state: MatchState, scenario: Scenario, points: dict[str, int]
) -> dict[str, Any] | None:
    """The leader's lead over the closest challenger and that challenger's
    ``max_swing``; ``None`` on a tie for the lead (no leader)."""
    ranked = sorted(points.items(), key=lambda kv: (-kv[1], kv[0]))
    if len(ranked) < 2 or ranked[0][1] == ranked[1][1]:
        return None
    leader = ranked[0][0]
    worst: dict[str, Any] | None = None
    for trailer, pts in ranked[1:]:
        lead = points[leader] - pts
        swing = max_swing(state, scenario, leader, trailer)
        # The challenger closest to overturning the lead decides.
        if worst is None or lead - swing < worst["lead"] - worst["max_swing"]:
            worst = {"leader": leader, "trailer": trailer, "lead": lead, "max_swing": swing}
    return worst
