"""The tick engine — pure, deterministic resolution of one turn.

``resolve_turn(state, scenario, orders)`` is a pure function: the same inputs
produce the same ``(new_state, events)`` on every run and platform (spec
c9/h2). Two properties make that hold:

* **Events first, state second.** The tick never edits state directly; it
  computes the turn's events and folds them with ``apply_event``. Every
  transition is therefore on the record by construction.
* **Canonical order, not submission order.** Declared actions are processed
  sorted by ``(team_id, unit_id)``; scarce allocations (a resource node with
  more gatherers than stock) drain in that same canonical order. Simultaneous
  moves all take effect together; nothing depends on who declared first.

v0 resolution rules (documented here, exercised in tests):

* A unit's turn is one action: ``move`` (Manhattan distance ≤ its role's
  ``move`` stat), ``gather`` (on a resource node: fill up to carry capacity),
  ``deliver`` (on the deliver-mission square: unload into team resources), or
  ``hold`` (stay put). Invalid orders become ``action_rejected`` events and do
  nothing — a stray call never silently advances the game.
* Messages and a per-team plan are free, observational, and on the record —
  coordination is played *through* the engine so cooperation can be scored.
* Control points: sole occupancy builds a streak (``hold``). A non-owner's
  streak ≥ ``capture_hold_turns`` flips ownership. A hold-mission completes
  once its point has been owned-and-occupied ``amount`` turns beyond capture.
  Both teams on the square = contested: the streak resets.
* A deliver-mission completes when the team's delivered resources reach its
  ``amount``. Ties (both teams cross in one turn) go to the larger total,
  then lexicographic team id — a documented v0 bias, deliberately rare.
* The match finishes when every mission is resolved or the turn limit is hit.
  Competitive winner: mission rewards + 2 points per owned control point +
  delivered resources; equal points is a ``draw``. Cooperative: the team wins
  iff every mission completed inside the limit.
"""

from __future__ import annotations

from typing import Any, Mapping

from league.engine.events import Event, fold_events
from league.engine.scenario import Scenario
from league.engine.state import MatchState

CP_POINTS = 2


def start_match(state: MatchState, *, seq_start: int = 0) -> tuple[MatchState, tuple[Event, ...]]:
    """Move a pending match to active (the opening event)."""
    if state.status != "pending":
        raise ValueError(f"cannot start a match in status {state.status!r}")
    events = (Event(turn=state.turn, seq=seq_start, kind="match_started", data={}),)
    return fold_events(state, events), events


def _manhattan(a: tuple[int, int], b: tuple[int, int]) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def outcome_points(state: MatchState) -> dict[str, int]:
    """The deterministic outcome tally the tick uses to pick a winner.

    Scoring (t7) recomputes richer breakdowns from the log; this function is
    the engine-side rule so ``winner`` is derivable from state alone.
    """
    points = {team.id: 0 for team in state.teams}
    for mission in state.missions:
        if mission.status == "completed" and mission.completed_by in points:
            points[mission.completed_by] += mission.reward
    for cp in state.control_points:
        if cp.owner in points:
            points[cp.owner] += CP_POINTS
    for team in state.teams:
        points[team.id] += team.resources
    return points


def resolve_turn(
    state: MatchState,
    scenario: Scenario,
    orders: Mapping[str, Mapping[str, Any]],
    *,
    seq_start: int = 0,
) -> tuple[MatchState, tuple[Event, ...]]:
    """Resolve one turn. ``orders`` maps team id → declared orders::

        {"plan": str | None,
         "messages": [{"from": agent_id, "text": str}, ...],
         "actions": [{"unit_id": str, "action": "move|gather|deliver|hold", ...}]}

    Returns the new state and the events that produced it.
    """
    if state.status != "active":
        raise ValueError(f"cannot resolve a turn in status {state.status!r}")

    turn = state.turn + 1
    seq = seq_start
    events: list[Event] = []

    def emit(kind: str, data: dict[str, Any]) -> None:
        nonlocal seq
        events.append(Event(turn=turn, seq=seq, kind=kind, data=data))
        seq += 1

    team_ids = {team.id for team in state.teams}
    units = {unit.id: unit for unit in state.units}

    # 1. The social record, in canonical team order.
    for team_id in sorted(orders):
        if team_id not in team_ids:
            continue
        team_orders = orders[team_id]
        plan = team_orders.get("plan")
        if plan:
            emit("plan_declared", {"team_id": team_id, "text": str(plan)})
        for message in team_orders.get("messages", ()):
            emit(
                "message_sent",
                {"team_id": team_id, "from": message["from"], "text": str(message["text"])},
            )

    # 2. Declared unit actions, canonical (team_id, unit_id) order.
    declared: list[tuple[str, dict[str, Any]]] = []
    for team_id in sorted(orders):
        if team_id not in team_ids:
            continue
        for action in sorted(
            orders[team_id].get("actions", ()), key=lambda a: str(a.get("unit_id"))
        ):
            declared.append((team_id, dict(action)))
            emit(
                "action_declared",
                {"team_id": team_id, "unit_id": action.get("unit_id"), **_action_facts(action)},
            )

    def reject(team_id: str, action: Mapping[str, Any], reason: str) -> None:
        emit(
            "action_rejected",
            {"team_id": team_id, "unit_id": action.get("unit_id"), "reason": reason},
        )

    # 3. Validate + stage. One action per unit per turn.
    seen_units: set[str] = set()
    moves: list[tuple[str, tuple[int, int]]] = []  # (unit_id, to)
    gathers: list[str] = []
    delivers: list[str] = []
    for team_id, action in declared:
        # Trim pure-formatting noise (LLM drivers emit " hold" etc.); wrong
        # verbs and ids still reject loudly below.
        unit = units.get(str(action.get("unit_id") or "").strip())
        verb = str(action.get("action") or "").strip()
        if unit is None or unit.team_id != team_id:
            reject(team_id, action, "no such unit on this team")
            continue
        if not unit.alive:
            reject(team_id, action, "unit is not alive")
            continue
        if unit.id in seen_units:
            reject(team_id, action, "unit already acted this turn")
            continue
        seen_units.add(unit.id)
        if verb == "hold":
            continue
        if verb == "move":
            to = action.get("to")
            if not (isinstance(to, (list, tuple)) and len(to) == 2):
                reject(team_id, action, "move needs a to=[x,y] target")
                continue
            to = (int(to[0]), int(to[1]))
            if not (0 <= to[0] < state.grid_width and 0 <= to[1] < state.grid_height):
                reject(team_id, action, "target is off the grid")
                continue
            if _manhattan(unit.pos, to) > scenario.stats_for(unit.role).move:
                reject(team_id, action, "target beyond this role's move range")
                continue
            moves.append((unit.id, to))
            continue
        if verb == "gather":
            node = next((n for n in state.resource_nodes if n.pos == unit.pos), None)
            if node is None:
                reject(team_id, action, "not standing on a resource node")
                continue
            if unit.carrying >= scenario.stats_for(unit.role).carry:
                reject(team_id, action, "already carrying to capacity")
                continue
            gathers.append(unit.id)
            continue
        if verb == "deliver":
            target = next((m for m in state.missions if m.kind == "deliver"), None)
            if target is None or unit.pos != target.pos:
                reject(team_id, action, "not standing on the delivery square")
                continue
            if unit.carrying <= 0:
                reject(team_id, action, "nothing to deliver")
                continue
            delivers.append(unit.id)
            continue
        reject(team_id, action, f"unknown action {verb!r}")

    # 4. Moves land simultaneously.
    for unit_id, to in moves:
        emit("unit_moved", {"unit_id": unit_id, "to": [to[0], to[1]]})
    positions = {u.id: u.pos for u in state.units}
    positions.update({unit_id: to for unit_id, to in moves})

    # 5. Gathers drain nodes in canonical order (scarcity bites the latecomer).
    node_stock = {n.id: n.remaining for n in state.resource_nodes}
    for unit_id in gathers:
        unit = units[unit_id]
        node = next(n for n in state.resource_nodes if n.pos == unit.pos)
        want = scenario.stats_for(unit.role).carry - unit.carrying
        take = min(want, node_stock[node.id])
        if take <= 0:
            reject(unit.team_id, {"unit_id": unit_id, "action": "gather"}, "node is exhausted")
            continue
        node_stock[node.id] -= take
        emit("resource_gathered", {"unit_id": unit_id, "node_id": node.id, "amount": take})

    # 6. Deliveries.
    for unit_id in delivers:
        unit = units[unit_id]
        emit(
            "resource_delivered",
            {"unit_id": unit_id, "team_id": unit.team_id, "amount": unit.carrying},
        )

    # Fold what happened so far; occupancy and totals below read the mid-state.
    mid = fold_events(state, tuple(events))

    # 7. Control points: streaks, contests, captures.
    for cp in mid.control_points:
        occupants = {
            u.team_id for u in mid.units if u.alive and positions.get(u.id, u.pos) == cp.pos
        }
        if len(occupants) != 1:
            if cp.hold:
                emit("control_point_held", {"cp_id": cp.id, "team_id": "", "turns": 0})
            continue
        team_id = next(iter(occupants))
        streak = dict(cp.hold).get(team_id, 0) + 1
        emit("control_point_held", {"cp_id": cp.id, "team_id": team_id, "turns": streak})
        if cp.owner != team_id and streak >= scenario.capture_hold_turns:
            emit("control_point_captured", {"cp_id": cp.id, "team_id": team_id})
            emit("control_point_held", {"cp_id": cp.id, "team_id": team_id, "turns": streak})

    mid = fold_events(state, tuple(events))

    # 8. Missions.
    for mission in mid.missions:
        if mission.status != "open":
            continue
        if mission.kind == "deliver":
            totals = {team.id: team.resources for team in mid.teams}
            reached = sorted(
                (t for t, total in totals.items() if total >= mission.amount),
                key=lambda t: (-totals[t], t),
            )
            if reached:
                emit("mission_completed", {"mission_id": mission.id, "team_id": reached[0]})
        elif mission.kind == "hold":
            cp = next((c for c in mid.control_points if c.pos == mission.pos), None)
            if cp is None or cp.owner is None or not cp.hold:
                continue
            team_id, streak = cp.hold[0]
            if team_id == cp.owner and streak >= scenario.capture_hold_turns + mission.amount:
                emit("mission_completed", {"mission_id": mission.id, "team_id": team_id})

    # 9. Advance the clock; close out if done.
    emit("turn_advanced", {"turn": turn})
    mid = fold_events(state, tuple(events))
    all_resolved = all(m.status != "open" for m in mid.missions)
    if all_resolved or turn >= mid.turn_limit:
        winner = _pick_winner(mid, all_resolved)
        emit("match_finished", {"winner": winner})
    emit("turn_resolved", {"turn": turn})

    return fold_events(state, tuple(events)), tuple(events)


def _pick_winner(state: MatchState, all_resolved: bool) -> str | None:
    if state.mode == "cooperative":
        return state.teams[0].id if all_resolved else None
    points = outcome_points(state)
    best = max(points.values())
    leaders = sorted(t for t, p in points.items() if p == best)
    return leaders[0] if len(leaders) == 1 else "draw"


def _action_facts(action: Mapping[str, Any]) -> dict[str, Any]:
    facts = {"action": action.get("action")}
    if "to" in action:
        facts["to"] = list(action["to"])
    return facts
