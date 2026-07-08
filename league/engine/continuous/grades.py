"""Per-unit scorecards for the continuous lane — the same grade contract the
grid lane earns in a sibling task this wave (plan task C8-t2, spec c10/h1/c6).

This is the continuous twin of ``league/engine/grades.py`` (plan task C8-t1,
built in a *different* worktree this wave — deliberately not visible from
here). The two modules are never allowed to import each other or reach across
lanes (two-lane honesty, spec c11/h11); ``tests/test_two_lane_honesty.py`` (this
task's other owned file) enforces the boundary by module-path string. What they
share is the CONTRACT, not code: :func:`cgrade_units` is a pure function of a
:class:`~league.engine.continuous.events.CMatchLog`, producing a per-unit grade
with a per-role-purpose breakdown and naming the match MVP and LVP.

The human review that asked for this (verbatim, ``docs/playtests/cycle-6/
human-review.md``): *"We need 'Best unit (MVP)' and 'Worst unit (LVP)' — grades
per unit per role (a unit should get more points for the designated purpose of
its role — a scout not scouting should still get points, but less if it's not a
scouting task, etc.)"* Team axes (outcome — see ``resolve.py``'s
``outcome_points``) are untouched by this module; grades are a NEW axis beside
outcome, never merged into it, and never feed a ranking/ELO surface (spec
boundary — no cross-match aggregation exists here or anywhere in this module).

Three role purposes, read from what the continuous engine actually records
today (``docs/roles.md``'s vocabulary)
-----------------------------------------------------------------------------
* **defender — race/hold**: winning a contested ``take_post`` race
  (``post_taken``) and then holding the post long enough to bank a ``hold``
  mission (``mission_completed`` with ``kind == "hold"``).
* **harvester — economy**: gathering (``resource_gathered``) and delivering
  (``resource_delivered``) resources, including banking a ``deliver`` mission
  (``mission_completed`` with ``kind == "deliver"``).
* **scout — eyes**: today, scored from ``unit_moved`` (mobility) — the closest
  event kind that exists in the log now, since the continuous lane is fogless
  this cycle (``docs/continuous-contract.md``). **THE SEAM**: fog mode lands in
  a parallel task (plan C8-t5) and will emit its own vision-derived event
  kind(s); when it does, extend ``_EYES_EVENT_KINDS`` below (and the branch in
  :func:`_accumulate` that reads it) — the rest of this module's shape does not
  need to change. Nothing here hard-codes "eyes == unit_moved forever."

Off-role discounting (spec c10, the human review's own words above)
-----------------------------------------------------------------------------
A role's *designated* purpose earns full credit; the identical contribution
made by a unit whose role does not own that purpose still earns credit —
strictly more than zero, strictly less than the on-role credit for the same
raw contribution (:func:`_credit`, ``OFF_ROLE_NUM``/``OFF_ROLE_DEN`` below).
Explorer and planner have no designated purpose graded this cycle (the spec
names exactly three role-purposes — defender, harvester, scout); every
contribution either of those two roles makes is scored at the off-role
discount against whichever purpose the event belongs to, never at zero and
never at full on-role credit.

Points are pinned in ``GRADE_UNIT``-scaled integers (fixed-point-friendly,
mirroring the continuous lane's own ``SCALE = 1000`` milliunit convention
without reusing it — a grade point is not a spatial unit): every raw
contribution this module ever computes is an exact multiple of
``GRADE_UNIT`` (mission rewards, gather/deliver amounts, and whole
board-units of movement are all integers >= 1 in a real log), so halving for
the off-role discount never truncates to zero.

Deterministic MVP/LVP tie-break (pinned, spec c10)
-----------------------------------------------------------------------------
Candidates are ordered by ``(grade, team_id, unit_id)`` — MVP takes the unit
first in that order sorted by *descending* grade (ties broken by the smallest
``team_id``, then the smallest ``unit_id``); LVP takes the unit first in that
order sorted by *ascending* grade (the same tie-break). This is the same
canonical ``(team_id, unit_id)`` ordering the resolver itself uses for
decision order (``resolve.py``'s ``_offer_decisions``), extended with grade as
the primary key. ``tests/test_cgrades.py::
test_mvp_and_lvp_tie_break_is_grade_then_team_id_then_unit_id`` pins it with a
constructed tie.
"""

from __future__ import annotations

from typing import Any

from league.engine.continuous.events import CMatchLog
from league.engine.continuous.space import SCALE, Pos, arrived, dist

# --------------------------------------------------------------------------
# Pinned point constants — every raw contribution is an exact multiple of
# GRADE_UNIT, so the off-role halving in _credit() never rounds to zero for a
# real (nonzero) contribution.
# --------------------------------------------------------------------------

#: The grade lane's own point scale (deliberately distinct from the spatial
#: ``SCALE`` in ``space.py`` — a grade point is not a milliunit).
GRADE_UNIT = 100

#: Winning a control-point race (one ``post_taken`` event) — a flat award,
#: independent of the mission reward riding on that post (the mission's own
#: ``reward`` is awarded separately, on completion, below).
POST_TAKEN_POINTS = 3 * GRADE_UNIT

#: Mobility credit per whole board-unit traveled by one ``unit_moved`` event
#: (``dist(from, to) // SCALE`` board-units — see ``space.py``'s ``SCALE``).
MOVE_POINTS_PER_BOARD_UNIT = GRADE_UNIT

#: Off-role credit is ``raw * OFF_ROLE_NUM // OFF_ROLE_DEN`` — strictly more
#: than zero and strictly less than the on-role (full ``raw``) credit for the
#: same contribution, for every raw value this module ever computes (all are
#: multiples of ``GRADE_UNIT``, so halving never truncates to zero).
OFF_ROLE_NUM = 1
OFF_ROLE_DEN = 2

#: The three role purposes this cycle grades (spec c10) — order is the
#: canonical breakdown order in every unit's payload.
PURPOSES = ("race_hold", "economy", "eyes")

#: Which purpose each role is graded ON for (full credit). Explorer and
#: planner have no entry: the spec names exactly three role-purposes this
#: cycle, so every contribution either role makes is off-role by construction
#: — never a KeyError, ``dict.get`` below simply returns ``None`` for them.
_ON_ROLE_PURPOSE: dict[str, str] = {
    "defender": "race_hold",
    "harvester": "economy",
    "scout": "eyes",
}

#: THE SEAM (see module docstring): the event kind(s) that earn "eyes" credit
#: today. Fog mode (plan C8-t5) will add its own vision-derived event kind(s)
#: here once it lands — this tuple is the one place that extension touches.
_EYES_EVENT_KINDS = ("unit_moved",)


def _credit(raw: int, on_role: bool) -> int:
    """Full credit on-role; halved (never zero, never full) off-role.

    Only ever called with a strictly positive ``raw`` (every call site below
    guards ``raw > 0`` before awarding) — see the module docstring for why
    that keeps the off-role half always >= 1.
    """
    if on_role:
        return raw
    return (raw * OFF_ROLE_NUM) // OFF_ROLE_DEN


def _mission_cp_id(mission_pos: Pos, control_points: tuple) -> str | None:
    """The control point a ``hold`` mission's position names, if any.

    A ``CMission`` carries only its own ``pos`` (never a ``cp_id`` — mirrors
    the resolver's own ``_open_hold_amounts``, which performs the identical
    match via ``arrived``). Returns ``None`` if no control point sits at the
    mission's position (defensive: a malformed/hand-built log should not
    crash grading, it should simply attribute no credit for that mission).
    """
    for cp in control_points:
        if arrived(mission_pos, cp.pos):
            return cp.id
    return None


def _award(
    points: dict[str, dict[str, int]],
    roles: dict[str, str],
    unit_id: str,
    purpose: str,
    raw: int,
) -> None:
    """Credit ``unit_id`` for one contribution to ``purpose``, applying the
    on-/off-role multiplier from its role. Raises if ``unit_id`` is not one of
    the match's units — a log crediting an unknown unit is corrupt, and
    corruption must be loud (mirrors ``events.py``'s own discipline)."""
    if unit_id not in points:
        raise ValueError(f"cgrade_units: event references unknown unit {unit_id!r}")
    role = roles[unit_id]
    on_role = _ON_ROLE_PURPOSE.get(role) == purpose
    points[unit_id][purpose] += _credit(raw, on_role)


def cgrade_units(clog: CMatchLog) -> dict[str, Any]:
    """Per-unit, role-purpose-weighted grades for a continuous match log.

    Pure function of ``clog`` alone (same log in, same payload out — no
    engine state is folded, no wall clock, no randomness): walks
    ``clog.events`` once, in log order, tallying each role-purpose
    contribution against the unit that earned it, and returns::

        {
          "match_id": str,
          "units": [
            {"unit_id", "team_id", "role", "grade",
             "purposes": {"race_hold": {"points", "on_role"},
                          "economy": {...}, "eyes": {...}}},
            ...  # canonical (team_id, unit_id) order
          ],
          "mvp": {"unit_id", "team_id", "grade"},
          "lvp": {"unit_id", "team_id", "grade"},
        }

    See the module docstring for the three role purposes, the off-role
    discount, and the pinned MVP/LVP tie-break. Never reads or writes team-axis
    scoring (``resolve.py``'s ``outcome_points``) — this is a separate axis,
    computed independently, alongside it.
    """
    initial = clog.initial_state
    roles = {u.id: u.role for u in initial.units}
    teams = {u.id: u.team_id for u in initial.units}
    if not roles:
        raise ValueError("cgrade_units: match has no units to grade")

    points: dict[str, dict[str, int]] = {uid: {p: 0 for p in PURPOSES} for uid in roles}

    # Mission bookkeeping: a ``mission_completed`` event carries only
    # ``mission_id``/``team_id`` (never its own kind, position, or reward), so
    # resolve those once, up front, from the initial state's mission roster.
    mission_reward: dict[str, int] = {}
    mission_purpose: dict[str, str] = {}
    hold_mission_cp: dict[str, str | None] = {}
    for mission in initial.missions:
        mission_reward[mission.id] = mission.reward
        if mission.kind == "hold":
            mission_purpose[mission.id] = "race_hold"
            hold_mission_cp[mission.id] = _mission_cp_id(mission.pos, initial.control_points)
        elif mission.kind == "deliver":
            mission_purpose[mission.id] = "economy"

    # Running trackers, updated chronologically as the log is walked, so a
    # mission's completion can be attributed to the specific unit that earned
    # it (the resolver itself never records that attribution directly).
    cp_holder: dict[str, str] = {}  # cp_id -> unit_id currently holding it
    last_delivered_by_team: dict[str, str] = {}  # team_id -> unit_id of its last delivery

    for event in clog.events:
        kind, data = event.kind, event.data

        if kind == "post_taken":
            unit_id = data["unit_id"]
            cp_holder[data["cp_id"]] = unit_id
            _award(points, roles, unit_id, "race_hold", POST_TAKEN_POINTS)

        elif kind == "resource_gathered":
            raw = data["amount"] * GRADE_UNIT
            if raw > 0:
                _award(points, roles, data["unit_id"], "economy", raw)

        elif kind == "resource_delivered":
            raw = data["amount"] * GRADE_UNIT
            if raw > 0:
                _award(points, roles, data["unit_id"], "economy", raw)
                last_delivered_by_team[data["team_id"]] = data["unit_id"]

        elif kind in _EYES_EVENT_KINDS:  # today: unit_moved (see the seam above)
            unit_id = data["unit_id"]
            distance = dist(Pos.from_dict(data["from"]), Pos.from_dict(data["to"]))
            board_units = distance // SCALE
            raw = board_units * MOVE_POINTS_PER_BOARD_UNIT
            if raw > 0:
                _award(points, roles, unit_id, "eyes", raw)

        elif kind == "mission_completed":
            mission_id = data["mission_id"]
            team_id = data["team_id"]
            purpose = mission_purpose.get(mission_id)
            reward = mission_reward.get(mission_id, 0)
            raw = reward * GRADE_UNIT
            if purpose == "race_hold" and raw > 0:
                cp_id = hold_mission_cp.get(mission_id)
                holder = cp_holder.get(cp_id) if cp_id is not None else None
                if holder is not None and teams.get(holder) == team_id:
                    _award(points, roles, holder, "race_hold", raw)
            elif purpose == "economy" and raw > 0:
                deliverer = last_delivered_by_team.get(team_id)
                if deliverer is not None:
                    _award(points, roles, deliverer, "economy", raw)

    units_out: list[dict[str, Any]] = []
    for unit_id in sorted(roles, key=lambda uid: (teams[uid], uid)):
        role = roles[unit_id]
        purposes_out: dict[str, dict[str, Any]] = {}
        grade = 0
        for purpose in PURPOSES:
            earned = points[unit_id][purpose]
            grade += earned
            purposes_out[purpose] = {
                "points": earned,
                "on_role": _ON_ROLE_PURPOSE.get(role) == purpose,
            }
        units_out.append(
            {
                "unit_id": unit_id,
                "team_id": teams[unit_id],
                "role": role,
                "grade": grade,
                "purposes": purposes_out,
            }
        )

    # Pinned tie-break (see module docstring): order by (grade, team_id,
    # unit_id), descending grade for MVP / ascending for LVP, take the first.
    mvp = sorted(units_out, key=lambda u: (-u["grade"], u["team_id"], u["unit_id"]))[0]
    lvp = sorted(units_out, key=lambda u: (u["grade"], u["team_id"], u["unit_id"]))[0]

    return {
        "match_id": initial.match_id,
        "units": units_out,
        "mvp": {"unit_id": mvp["unit_id"], "team_id": mvp["team_id"], "grade": mvp["grade"]},
        "lvp": {"unit_id": lvp["unit_id"], "team_id": lvp["team_id"], "grade": lvp["grade"]},
    }
