"""Per-unit role-purpose scorecards — MVP/LVP from the log alone.

Plan task t1 (spec c10/h1, c3/h16, c6): team axes (outcome, cooperation v0/v1,
tempo t0, probe p0 — ``scoring.py``/``tempo.py``/``probe.py``) answer WHETHER a
team cohered; :func:`grade_units` answers WHO made it so. It is a NEW axis
beside those, never a drift inside them — this module never imports
``league.engine.scoring``/``tempo``/``probe`` (enforced by an AST test in
``tests/test_grades.py``, mirroring the two-lane boundary test's technique),
and it takes nothing but a :class:`~league.engine.events.MatchLog`: no store,
no filesystem, no scenario lookup. Same log in, same payload out — always.

**Role purposes.** Every role documented in ``docs/roles.md`` has a declared
job: the harvester runs the economy (gather + deliver), the defender captures
and holds objectives, the scout/explorer are the team's eyes (movement is the
only reconnaissance the grid log can observe today — vision/fog is parked for
a later cycle, ``docs/specs/...grades-every-seat...md`` requirement "Scout as
eyes"), and the planner coordinates through messages. :data:`ROLE_HOME_PURPOSE`
pins that mapping; a role name outside it (a future/custom role) simply has no
home purpose, so nothing it does is ever "on-role" — everything it does still
scores, just at the off-role rate (see below).

**The formula (deliberately pinned here, not in the spec — plan risk r1).**
Four purposes, each fed by the log events that are its plainest observable
proxy:

======  =============================  =================================
purpose fed by                         raw weight
======  =============================  =================================
economy resource_gathered/_delivered   the event's own ``amount``
control control_point_captured/_held   :data:`CAPTURE_POINTS`/`HOLD_POINTS`
recon   unit_moved                     :data:`MOVE_POINTS`
coord.  message_sent                   :data:`MESSAGE_POINTS`
======  =============================  =================================

Every contribution is attributed to the acting unit (``unit_id`` on the event
directly for movement/gather/deliver; ``message_sent``'s ``from`` is an
AGENT id per ``league/harness.py``, resolved to its unit via the initial
roster). ``control_point_captured``/``_held`` carry only a ``team_id`` — no
unit_id exists on these events — so credit goes to every unit of that team
standing on the control point's (fixed, never-moving) position at that
moment, tracked by folding ``unit_moved`` in log order alongside every other
event. This is a simplification of the engine's own occupancy rule (which
also gates on a scenario's ``can_capture`` flag, scenario config the log does
not carry) — a role such as explorer/planner that coincides on the same cell
as a capturing teammate is credited too. Documented here rather than hidden:
the alternative (importing ``league.engine.scenario`` to resolve
``RoleStats``) would make this module a function of the log AND the scenario
registry, which is a stronger and unwanted dependency for a "pure function of
the log" contract.

A contribution scores at :data:`ON_ROLE_MULTIPLIER` times its raw weight when
the acting unit's role's home purpose matches the purpose it fed, and at
:data:`OFF_ROLE_MULTIPLIER` otherwise. Both multipliers are positive integers
with ``OFF_ROLE_MULTIPLIER < ON_ROLE_MULTIPLIER`` — every raw weight used here
is a positive integer too (event amounts are always >= 1; the flat weights
are pinned positive constants) — so for the identical contribution, the
off-role score is always strictly greater than zero and strictly less than
the on-role score. That is the user's own framing, quoted in the spec: "a
scout not scouting should still get points, but less."

A unit's ``grade`` is the sum of its per-purpose contributions. **MVP is the
unit with the highest grade; LVP is the unit with the lowest.** Ties break
canonically, ascending by ``(team_id, unit_id)`` — the plan's own tie-break
order: among units tied for the best (resp. worst) grade, the unit with the
lexicographically-first ``team_id``, then the lexicographically-first
``unit_id``, is named. Concretely: ``mvp`` is the unit minimizing
``(-grade, team_id, unit_id)``; ``lvp`` is the unit minimizing
``(grade, team_id, unit_id)``.
"""

from __future__ import annotations

from typing import Any

from league.engine.events import MatchLog

# The four purposes every role-purpose breakdown reports, in a fixed order.
PURPOSES = ("economy", "control", "recon", "coordination")

# Each role's designated job (docs/roles.md). A role not listed here has no
# home purpose: nothing it does is ever "on-role", but everything it does
# still scores at the off-role rate.
ROLE_HOME_PURPOSE: dict[str, str] = {
    "harvester": "economy",  # implementer: hauls and delivers the payload
    "defender": "control",  # implementer: captures and holds objectives
    "scout": "recon",  # quick reconnaissance pass — the team's eyes
    "explorer": "recon",  # reconnaissance / code-reading: ranges far, sees far
    "planner": "coordination",  # architect / tech-lead: coordinates via plan+messages
}

# Flat per-event weights for purposes whose feeding events carry no natural
# magnitude of their own. Gather/deliver instead use the event's own
# ``amount`` — the resource unit already IS the natural, integer measure of
# that contribution, so no separate constant is needed for those two.
CAPTURE_POINTS = 3
HOLD_POINTS = 1
MOVE_POINTS = 1
MESSAGE_POINTS = 1

# On-role contributions count double; off-role contributions count at the
# base (raw) rate. Both are positive integers with OFF < ON, so for any
# positive raw weight w: 0 < w * OFF_ROLE_MULTIPLIER < w * ON_ROLE_MULTIPLIER.
ON_ROLE_MULTIPLIER = 2
OFF_ROLE_MULTIPLIER = 1


def grade_units(log: MatchLog) -> dict[str, Any]:
    """Per-unit, role-purpose-weighted grades — a pure function of ``log``.

    Returns::

        {
            "match_id": str,
            "purposes": [<the four purpose names, in PURPOSES order>],
            "units": {
                unit_id: {
                    "team_id": str,
                    "role": str,
                    "home_purpose": str | None,
                    "grade": int,               # sum of the breakdown below
                    "breakdown": {purpose: int, ...},  # every PURPOSES key
                },
                ...
            },
            "mvp": {"unit_id": str, "team_id": str, "grade": int} | None,
            "lvp": {"unit_id": str, "team_id": str, "grade": int} | None,
        }

    ``mvp``/``lvp`` are ``None`` only when the log's initial roster is empty
    (no units to grade). See the module docstring for the exact formula and
    tie-break.
    """
    team_of: dict[str, str] = {}
    role_of: dict[str, str] = {}
    alive: dict[str, bool] = {}
    position: dict[str, tuple[int, int]] = {}
    agent_unit: dict[str, str] = {}

    for unit in log.initial_state.units:
        team_of[unit.id] = unit.team_id
        role_of[unit.id] = unit.role
        alive[unit.id] = unit.alive
        position[unit.id] = unit.pos
        # First unit wins if an agent_id were ever (incorrectly) shared —
        # deterministic either way since initial_state.units is a fixed tuple.
        agent_unit.setdefault(unit.agent_id, unit.id)

    cp_pos: dict[str, tuple[int, int]] = {cp.id: cp.pos for cp in log.initial_state.control_points}

    breakdowns: dict[str, dict[str, int]] = {
        unit_id: {purpose: 0 for purpose in PURPOSES} for unit_id in team_of
    }

    def credit(unit_id: str | None, purpose: str, raw: int) -> None:
        if not unit_id or raw <= 0 or unit_id not in breakdowns:
            return
        on_role = ROLE_HOME_PURPOSE.get(role_of[unit_id]) == purpose
        multiplier = ON_ROLE_MULTIPLIER if on_role else OFF_ROLE_MULTIPLIER
        breakdowns[unit_id][purpose] += raw * multiplier

    def occupants(cp_id: str, team_id: str) -> tuple[str, ...]:
        """Living units of ``team_id`` currently standing on ``cp_id``.

        Position is tracked by folding ``unit_moved`` in log order; control
        point positions are fixed (never folded by any event), so a single
        lookup at load time suffices for them.
        """
        pos = cp_pos.get(cp_id)
        if pos is None:
            return ()
        return tuple(
            uid
            for uid, uteam in team_of.items()
            if uteam == team_id and alive.get(uid, True) and position.get(uid) == pos
        )

    for event in log.events:
        data = event.data
        kind = event.kind
        if kind == "unit_moved":
            unit_id = data["unit_id"]
            position[unit_id] = (data["to"][0], data["to"][1])
            credit(unit_id, "recon", MOVE_POINTS)
        elif kind == "resource_gathered":
            credit(data["unit_id"], "economy", int(data["amount"]))
        elif kind == "resource_delivered":
            credit(data["unit_id"], "economy", int(data["amount"]))
        elif kind == "control_point_captured":
            for unit_id in occupants(data["cp_id"], data["team_id"]):
                credit(unit_id, "control", CAPTURE_POINTS)
        elif kind == "control_point_held":
            # Mirrors apply_event's own gate (events.py): an empty team_id or
            # turns == 0 is the contested/abandoned reset form, not a hold.
            if data.get("team_id") and data.get("turns", 0) > 0:
                for unit_id in occupants(data["cp_id"], data["team_id"]):
                    credit(unit_id, "control", HOLD_POINTS)
        elif kind == "message_sent":
            unit_id = agent_unit.get(str(data.get("from", "")))
            credit(unit_id, "coordination", MESSAGE_POINTS)
        elif kind == "unit_defeated":
            alive[data["unit_id"]] = False

    units_payload: dict[str, dict[str, Any]] = {}
    for unit_id in sorted(breakdowns):
        breakdown = breakdowns[unit_id]
        units_payload[unit_id] = {
            "team_id": team_of[unit_id],
            "role": role_of[unit_id],
            "home_purpose": ROLE_HOME_PURPOSE.get(role_of[unit_id]),
            "grade": sum(breakdown.values()),
            "breakdown": dict(breakdown),
        }

    mvp = _named(units_payload, _best(units_payload, worst=False))
    lvp = _named(units_payload, _best(units_payload, worst=True))

    return {
        "match_id": log.initial_state.match_id,
        "purposes": list(PURPOSES),
        "units": units_payload,
        "mvp": mvp,
        "lvp": lvp,
    }


def _best(units_payload: dict[str, dict[str, Any]], *, worst: bool) -> str | None:
    """The canonical MVP (``worst=False``) or LVP (``worst=True``) unit id.

    Tie-break: ascending ``(team_id, unit_id)`` among units tied on grade —
    see the module docstring's worked-out ``(-grade|grade, team_id, unit_id)``
    key.
    """
    if not units_payload:
        return None
    sign = 1 if worst else -1
    return min(
        units_payload,
        key=lambda uid: (
            sign * units_payload[uid]["grade"],
            units_payload[uid]["team_id"],
            uid,
        ),
    )


def _named(units_payload: dict[str, dict[str, Any]], unit_id: str | None) -> dict[str, Any] | None:
    if unit_id is None:
        return None
    entry = units_payload[unit_id]
    return {"unit_id": unit_id, "team_id": entry["team_id"], "grade": entry["grade"]}
