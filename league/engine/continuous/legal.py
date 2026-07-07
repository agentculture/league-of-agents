"""The continuous action menu — legality as a query, with durations (plan C7-t5).

This is the continuous-lane sibling of the grid's ``league/engine/legal.py`` and
it plays the same role: it exposes, as a pure query, exactly the actions the
resolver (``resolve.py``) will accept, so a mind can see what it may do *before*
it spends a decision on it. The grid's coordination playtest burned a fifth of
its orders on moves and delivers the engine then rejected; the continuous lane
closes that gap the same way — but now every menu entry also carries the in-game
**duration** the action will cost, because time is the resolver here (spec c8).

The legal<->resolver agreement, continuous edition
--------------------------------------------------
There is a single source of truth for "is this action legal, and how long does
it take": :func:`plan_action`. :func:`legal_actions_continuous` builds the menu
by asking :func:`plan_action` about each candidate; the resolver's
``_start_action`` gates every order through the *same* :func:`plan_action`. So
the two can never drift — an action the menu offers always plans (and therefore
always *starts*), and an action the menu omits never plans (and therefore never
*resolves* into an effect). That is the pattern
``tests/test_continuous_legal.py`` proves in both directions.

What each kind requires (mirrors the grid's applicability rules, in continuous
positions and with role-given durations):

* ``move`` — always legal toward any target the unit is not already *arrived* at
  (:func:`~league.engine.continuous.space.arrived`); its duration is the exact
  number of game-time units to reach the target at the role's ``move_rate_mu``
  (:func:`move_duration`). The menu enumerates moves toward every *point of
  interest* (control points, resource nodes, mission locations) — a bounded,
  useful destination set — but the resolver accepts a move toward any position,
  so the menu is a subset of what is plannable for moves (moves never fail for
  legality). This asymmetry is deliberate and the only one: gather / take_post /
  deliver are fully enumerable, so the menu and the resolver agree exactly on
  them.
* ``gather`` — the role ``can_gather``, the unit is arrived at a resource node
  with ``remaining > 0``, and it is carrying below its role's ``carry``. Duration
  is the role's ``gather_duration``.
* ``take_post`` — the role ``can_take_post``, the unit is arrived at the control
  point, and the point is **not already owned by the unit's own team** (taking a
  post your team holds is illegal — there is nothing to take; contest case *d*).
  Taking an unowned or enemy-owned post is legal (an enemy post is a flip).
  Duration is the role's ``take_post_duration``.
* ``deliver`` — the unit is carrying more than zero and is arrived at a
  deliver-mission location; duration is the role's ``deliver_duration`` (a role
  that can never carry, ``carry == 0``, has ``deliver_duration == 0`` and so can
  never deliver). Mirrors the grid's economy: delivery banks the whole carry into
  the team's resources.

Everything is pure integer arithmetic over :class:`~league.engine.continuous.
space.Pos` (no ``float`` anywhere — the package-wide source scan enforces it) and
free of randomness/wall-clock, so a menu is a deterministic function of state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from league.engine.continuous.roles import CRoleStats, stats_for
from league.engine.continuous.space import Pos, arrived, dist_sq, isqrt
from league.engine.continuous.state import CMatchState, CUnit


def move_duration(dsq: int, speed: int) -> int:
    """The minimal integer game-time ``D`` for a mover at ``speed`` milliunits per
    time-unit to *arrive* at a target whose squared distance is ``dsq``.

    Arrival happens (``move_toward``'s exact clamp) exactly when ``speed*D`` reaches
    the true distance ``sqrt(dsq)``. Since ``m*m >= dsq`` for an integer ``m`` iff
    ``m >= ceil(sqrt(dsq))``, the smallest such ``D`` is ``ceil(ceil_root/speed)``
    — pure integer math, no ``float``. Returns ``0`` when already at the target.
    Raises ``ValueError`` on a non-positive ``speed``.
    """
    if speed <= 0:
        raise ValueError(f"speed must be positive, got {speed}")
    if dsq <= 0:
        return 0
    root = isqrt(dsq)  # floor(sqrt(dsq))
    if root * root < dsq:
        root += 1  # ceil(sqrt(dsq)): smallest r with r*r >= dsq
    return (root + speed - 1) // speed


@dataclass(frozen=True)
class Plan:
    """A validated, legal action ready to schedule: its ``kind``, in-game
    ``duration``, and resolved target (an entity ``target_id`` or a spatial
    ``target_pos``). Produced by :func:`plan_action`; consumed by the resolver's
    ``_start_action``. ``None`` from :func:`plan_action` means *illegal*.
    """

    kind: str
    duration: int
    target_id: str | None = None
    target_pos: Pos | None = None


def _find_unit(state: CMatchState, unit_id: str) -> CUnit:
    for unit in state.units:
        if unit.id == unit_id:
            return unit
    raise ValueError(f"unknown unit {unit_id!r}")


def _find_by_id(items: tuple, item_id: Any):
    if item_id is None:
        return None
    for item in items:
        if item.id == item_id:
            return item
    return None


def _plan_move(unit: CUnit, role: CRoleStats, action: dict) -> Plan | None:
    raw = action.get("target_pos")
    if raw is None:
        return None
    target = Pos.from_dict(raw)
    if arrived(unit.pos, target):
        return None  # already there — a zero-length move is not an action
    duration = move_duration(dist_sq(unit.pos, target), role.move_rate_mu)
    if duration <= 0:
        return None
    return Plan("move", duration, target_id=None, target_pos=target)


def _plan_gather(state: CMatchState, unit: CUnit, role: CRoleStats, action: dict) -> Plan | None:
    if not role.can_gather:
        return None
    node = _find_by_id(state.resource_nodes, action.get("target_id"))
    if node is None or not arrived(unit.pos, node.pos):
        return None
    if node.remaining <= 0 or unit.carrying >= role.carry:
        return None
    return Plan("gather", role.gather_duration, target_id=node.id)


def _plan_take(state: CMatchState, unit: CUnit, role: CRoleStats, action: dict) -> Plan | None:
    if not role.can_take_post:
        return None
    cp = _find_by_id(state.control_points, action.get("target_id"))
    if cp is None or not arrived(unit.pos, cp.pos):
        return None
    if cp.owner == unit.team_id:
        return None  # contest case (d): taking a post your team already holds is illegal
    return Plan("take_post", role.take_post_duration, target_id=cp.id)


def _deliver_mission(state: CMatchState, unit: CUnit):
    for mission in state.missions:
        if mission.kind == "deliver" and arrived(unit.pos, mission.pos):
            return mission
    return None


def _plan_deliver(state: CMatchState, unit: CUnit, role: CRoleStats, action: dict) -> Plan | None:
    if unit.carrying <= 0 or role.deliver_duration <= 0:
        return None
    if _deliver_mission(state, unit) is None:
        return None
    return Plan("deliver", role.deliver_duration, target_id=unit.team_id)


def plan_action(
    state: CMatchState,
    role_table: tuple[tuple[str, CRoleStats], ...],
    unit_id: str,
    action: dict,
) -> Plan | None:
    """The single legality+duration oracle shared by the menu and the resolver.

    Returns a :class:`Plan` (kind, duration, resolved target) when ``action`` is
    legal for ``unit_id`` in ``state``, or ``None`` when it is illegal — so the
    resolver's ``_start_action`` and :func:`legal_actions_continuous` can never
    disagree. Raises ``ValueError`` if ``unit_id`` names no unit (corruption is
    loud, as everywhere in the engine).
    """
    unit = _find_unit(state, unit_id)
    if not unit.alive:
        return None
    role = stats_for(role_table, unit.role)
    kind = action.get("kind")
    if kind == "move":
        return _plan_move(unit, role, action)
    if kind == "gather":
        return _plan_gather(state, unit, role, action)
    if kind == "take_post":
        return _plan_take(state, unit, role, action)
    if kind == "deliver":
        return _plan_deliver(state, unit, role, action)
    return None


def _points_of_interest(state: CMatchState) -> list[tuple[tuple[int, int], str]]:
    """Distinct board positions worth moving toward — control points, resource
    nodes and mission locations — each tagged with a reference id (first wins).
    Deterministic: fixed scan order, deduped by position."""
    seen: dict[tuple[int, int], str] = {}
    for cp in state.control_points:
        seen.setdefault((cp.pos.x, cp.pos.y), cp.id)
    for node in state.resource_nodes:
        seen.setdefault((node.pos.x, node.pos.y), node.id)
    for mission in state.missions:
        seen.setdefault((mission.pos.x, mission.pos.y), mission.id)
    return sorted(seen.items())


def _menu_sort_key(entry: dict) -> tuple[str, str, int, int]:
    pos = entry.get("target_pos")
    return (
        entry["kind"],
        entry.get("target_id", ""),
        pos["x"] if pos is not None else -1,
        pos["y"] if pos is not None else -1,
    )


def legal_actions_continuous(
    state: CMatchState,
    role_table: tuple[tuple[str, CRoleStats], ...],
    unit_id: str,
) -> dict[str, Any]:
    """The action menu for ``unit_id`` right now — every legal order with its
    in-game duration. Returns::

        {"unit_id", "clock", "role", "move_rate_mu", "can_gather",
         "can_take_post", "carrying", "carry_capacity",
         "actions": [ {"kind", "duration", ...}, ... ]}

    Each ``actions`` entry is directly returnable to the resolver as a decision
    (it carries ``kind`` plus ``target_id`` / ``target_pos``); the ``duration`` is
    informational — the resolver recomputes it from role data, never trusting the
    caller. The list is sorted canonically so the menu is byte-deterministic.

    Raises ``ValueError`` if ``unit_id`` names no unit (mirrors the grid).
    """
    unit = _find_unit(state, unit_id)
    role = stats_for(role_table, unit.role)
    actions: list[dict[str, Any]] = []

    for (x, y), ref in _points_of_interest(state):
        plan = plan_action(
            state, role_table, unit_id, {"kind": "move", "target_pos": {"x": x, "y": y}}
        )
        if plan is not None:
            actions.append(
                {
                    "kind": "move",
                    "target_pos": {"x": x, "y": y},
                    "target_ref": ref,
                    "duration": plan.duration,
                }
            )

    for node in state.resource_nodes:
        plan = plan_action(state, role_table, unit_id, {"kind": "gather", "target_id": node.id})
        if plan is not None:
            actions.append({"kind": "gather", "target_id": node.id, "duration": plan.duration})

    for cp in state.control_points:
        plan = plan_action(state, role_table, unit_id, {"kind": "take_post", "target_id": cp.id})
        if plan is not None:
            actions.append({"kind": "take_post", "target_id": cp.id, "duration": plan.duration})

    deliver_plan = plan_action(state, role_table, unit_id, {"kind": "deliver"})
    if deliver_plan is not None:
        mission = _deliver_mission(state, unit)
        actions.append(
            {
                "kind": "deliver",
                "target_id": unit.team_id,
                "mission_id": mission.id if mission is not None else None,
                "duration": deliver_plan.duration,
            }
        )

    actions.sort(key=_menu_sort_key)
    return {
        "unit_id": unit_id,
        "clock": state.clock,
        "role": unit.role,
        "move_rate_mu": role.move_rate_mu,
        "can_gather": role.can_gather,
        "can_take_post": role.can_take_post,
        "carrying": unit.carrying,
        "carry_capacity": role.carry,
        "actions": actions,
    }
