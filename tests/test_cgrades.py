"""Acceptance tests for the continuous per-unit scorecard engine (plan C8-t2).

Mirrors the acceptance criteria pinned in ``docs/plans/2026-07-07-league-of-
agents-grades-every-seat-role-purpose-sc.md``'s t2 entry:

1. ``cgrade_units(clog)`` mirrors the grid grade contract for continuous role
   purposes (defender race/hold, harvester economy, scout eyes), is a pure
   function of the log, and names MVP/LVP with the canonical tie-break.
2. Off-role contributions score strictly more than zero and strictly less
   than the identical contribution on-role (spec c10, human review verbatim).

This file is owned by task t2 (the continuous lane); ``tests/test_grades.py``
(the grid lane's mirror, task t1) is a different worktree's file this wave —
never touched here.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from league.engine.continuous.events import CEvent, CMatchLog
from league.engine.continuous.grades import (
    GRADE_UNIT,
    OFF_ROLE_DEN,
    OFF_ROLE_NUM,
    PURPOSES,
    cgrade_units,
)
from league.engine.continuous.space import from_units
from league.engine.continuous.state import (
    CAgentSlot,
    CControlPoint,
    CMatchState,
    CMission,
    CTeamState,
    CUnit,
)

RACE_LIVE_LOG = (
    Path(__file__).parent.parent / "docs" / "playtests" / "cycle-7" / "race-live.log.jsonl"
)


# --------------------------------------------------------------------------- #
# Builders (self-contained, mirroring tests/test_continuous_resolve.py's style
# — this repo's convention is per-file builders, not a shared conftest).
# --------------------------------------------------------------------------- #
def _slot(uid, role):
    return CAgentSlot(id=uid, model="colleague/qwen", role=role)


def _team(tid, name, roster):
    return CTeamState(id=tid, name=name, resources=0, agents=tuple(roster))


def _unit(uid, team, role, pos):
    return CUnit(id=uid, team_id=team, agent_id=uid, role=role, pos=pos)


def _state(*, teams, units, control_points=(), missions=()):
    return CMatchState(
        match_id="cm-grades",
        scenario_id="c-grades-test",
        seed=1,
        mode="competitive",
        clock=0,
        time_limit=1000,
        width=20000,
        height=20000,
        status="pending",
        winner=None,
        teams=tuple(teams),
        units=tuple(units),
        control_points=tuple(control_points),
        missions=tuple(missions),
        resource_nodes=(),
    )


def _log(initial, events):
    return CMatchLog(initial_state=initial, events=tuple(events))


def _e(game_time, seq, kind, **data):
    return CEvent(game_time=game_time, seq=seq, kind=kind, data=data)


# --------------------------------------------------------------------------- #
# 1. Pure function of the log + the real committed fixture
# --------------------------------------------------------------------------- #
def test_cgrade_units_is_a_pure_function_same_log_twice_identical_payload() -> None:
    payload = RACE_LIVE_LOG.read_text(encoding="utf-8")
    clog = CMatchLog.from_jsonl(payload)
    first = cgrade_units(clog)
    second = cgrade_units(CMatchLog.from_jsonl(payload))
    assert first == second


def test_cgrade_units_on_the_committed_race_live_log() -> None:
    """The committed cycle-7 fixture, hand-traced against the pinned formula:

    * blue-u1 (defender) wins the post race (``post_taken``, 300 on-role) and
      banks ``ms-hold`` (reward 8 -> 800 on-role) = 1100 race_hold, plus one
      1-board-unit move off-role in "eyes" (100 raw // 2 = 50) = grade 1150.
    * blue-u2 (harvester) gathers 3 (300 on-role) and delivers 3 (300 on-role)
      then banks ``ms-supply`` (reward 6 -> 600 on-role) = grade 1200 — the
      match MVP, all on-purpose.
    * red-u1 (defender) only completes one move (5 board-units, 500 raw,
      off-role in "eyes" // 2 = 250) before the match ends mid-take = grade 250.
    * red-u2 (harvester) loses the post race (``action_failed``, no credit)
      and never gathers/delivers/moves = grade 0 — the match LVP, exactly the
      unit whose own in-log messages show it committing to (and losing) a
      fight outside its economy purpose.

    This also proves the committed outcome axis stays untouched: this test
    reads the log only through ``cgrade_units``, never ``resolve.py``, and
    ``tests/test_committed_logs_compat.py`` / ``test_two_lane_honesty.py``
    already pin the outcome/hash fixtures byte-for-byte.
    """
    clog = CMatchLog.from_jsonl(RACE_LIVE_LOG.read_text(encoding="utf-8"))
    result = cgrade_units(clog)

    assert result["match_id"] == "c-race-live"
    by_unit = {u["unit_id"]: u for u in result["units"]}
    assert by_unit["blue-u1"]["grade"] == 1150
    assert by_unit["blue-u2"]["grade"] == 1200
    assert by_unit["red-u1"]["grade"] == 250
    assert by_unit["red-u2"]["grade"] == 0

    assert result["mvp"] == {"unit_id": "blue-u2", "team_id": "blue", "grade": 1200}
    assert result["lvp"] == {"unit_id": "red-u2", "team_id": "red", "grade": 0}

    # The committed outcome.json fixture pairs with this log by match_id;
    # grades are read independently and never touch it.
    outcome_path = RACE_LIVE_LOG.with_name("race-live.outcome.json")
    outcome = json.loads(outcome_path.read_text(encoding="utf-8"))
    assert outcome["match_id"] == result["match_id"]
    assert outcome["outcome_points"] == {"blue": 19, "red": 0}  # untouched, cross-checked


def test_every_unit_carries_all_three_purposes_in_canonical_order() -> None:
    clog = CMatchLog.from_jsonl(RACE_LIVE_LOG.read_text(encoding="utf-8"))
    result = cgrade_units(clog)
    for unit in result["units"]:
        assert tuple(unit["purposes"]) == PURPOSES


def test_units_are_listed_in_canonical_team_id_unit_id_order() -> None:
    clog = CMatchLog.from_jsonl(RACE_LIVE_LOG.read_text(encoding="utf-8"))
    result = cgrade_units(clog)
    ids = [(u["team_id"], u["unit_id"]) for u in result["units"]]
    assert ids == sorted(ids)


# --------------------------------------------------------------------------- #
# 2. Off-role discounting: strictly > 0, strictly < on-role, same contribution
# --------------------------------------------------------------------------- #
def test_off_role_scores_less_than_on_role_for_the_identical_contribution() -> None:
    """The worked case (human review, verbatim): "a scout not scouting should
    still get points, but less" — inverted here to the mobility purpose itself:
    a scout and a defender each make the IDENTICAL 1-board-unit move. The scout
    (on-role for "eyes") earns full credit; the defender (off-role for "eyes")
    earns strictly less, and strictly more than zero, for that same move.
    """
    scout_pos_a, scout_pos_b = from_units(0, 0), from_units(1, 0)
    defender_pos_a, defender_pos_b = from_units(5, 5), from_units(6, 5)

    initial = _state(
        teams=(
            _team(
                "blue", "Blue", (_slot("blue-scout", "scout"), _slot("blue-defender", "defender"))
            ),
        ),
        units=(
            _unit("u-scout", "blue", "scout", scout_pos_a),
            _unit("u-defender", "blue", "defender", defender_pos_a),
        ),
    )
    events = [
        _e(
            0,
            0,
            "unit_moved",
            unit_id="u-scout",
            **{"from": scout_pos_a.to_dict()},
            to=scout_pos_b.to_dict(),
        ),
        _e(
            0,
            1,
            "unit_moved",
            unit_id="u-defender",
            **{"from": defender_pos_a.to_dict()},
            to=defender_pos_b.to_dict(),
        ),
    ]
    result = cgrade_units(_log(initial, events))
    by_unit = {u["unit_id"]: u for u in result["units"]}

    scout_eyes = by_unit["u-scout"]["purposes"]["eyes"]
    defender_eyes = by_unit["u-defender"]["purposes"]["eyes"]

    assert scout_eyes["on_role"] is True
    assert defender_eyes["on_role"] is False
    assert scout_eyes["points"] == GRADE_UNIT  # 1 board-unit, full credit
    assert defender_eyes["points"] == (GRADE_UNIT * OFF_ROLE_NUM) // OFF_ROLE_DEN
    assert 0 < defender_eyes["points"] < scout_eyes["points"]


def test_off_role_gather_still_scores_less_than_on_role_gather() -> None:
    """The same discount principle over the economy purpose: a defender that
    gathers (off-role) scores less than a harvester's identical gather amount
    (on-role), and strictly more than zero."""
    initial = _state(
        teams=(
            _team(
                "blue",
                "Blue",
                (_slot("blue-harvester", "harvester"), _slot("blue-defender", "defender")),
            ),
        ),
        units=(
            _unit("u-harvester", "blue", "harvester", from_units(0, 0)),
            _unit("u-defender", "blue", "defender", from_units(1, 1)),
        ),
    )
    events = [
        _e(0, 0, "resource_gathered", unit_id="u-harvester", node_id="rn", amount=3),
        _e(0, 1, "resource_gathered", unit_id="u-defender", node_id="rn", amount=3),
    ]
    result = cgrade_units(_log(initial, events))
    by_unit = {u["unit_id"]: u for u in result["units"]}

    harvester_economy = by_unit["u-harvester"]["purposes"]["economy"]
    defender_economy = by_unit["u-defender"]["purposes"]["economy"]

    assert harvester_economy["points"] == 3 * GRADE_UNIT
    assert defender_economy["points"] == (3 * GRADE_UNIT * OFF_ROLE_NUM) // OFF_ROLE_DEN
    assert 0 < defender_economy["points"] < harvester_economy["points"]


# --------------------------------------------------------------------------- #
# Mission attribution: hold credit to the post holder, deliver credit to the
# last delivering unit — both computed from the log alone.
# --------------------------------------------------------------------------- #
def test_hold_mission_credit_is_attributed_to_the_unit_that_took_the_post() -> None:
    cp_pos = from_units(5, 5)
    initial = _state(
        teams=(_team("blue", "Blue", (_slot("blue-defender", "defender"),)),),
        units=(_unit("u-defender", "blue", "defender", cp_pos),),
        control_points=(CControlPoint(id="cp-1", pos=cp_pos),),
        missions=(CMission(id="ms-hold", kind="hold", pos=cp_pos, amount=5, reward=8),),
    )
    events = [
        _e(0, 0, "post_taken", cp_id="cp-1", team_id="blue", unit_id="u-defender"),
        _e(5, 1, "mission_completed", mission_id="ms-hold", team_id="blue"),
    ]
    result = cgrade_units(_log(initial, events))
    unit = result["units"][0]
    assert unit["unit_id"] == "u-defender"
    assert unit["purposes"]["race_hold"]["points"] == 300 + 8 * GRADE_UNIT
    assert unit["purposes"]["race_hold"]["on_role"] is True


def test_deliver_mission_credit_is_attributed_to_the_last_delivering_unit() -> None:
    home = from_units(0, 0)
    initial = _state(
        teams=(_team("blue", "Blue", (_slot("blue-harvester", "harvester"),)),),
        units=(_unit("u-harvester", "blue", "harvester", home),),
        missions=(CMission(id="ms-supply", kind="deliver", pos=home, amount=3, reward=6),),
    )
    events = [
        _e(0, 0, "resource_delivered", unit_id="u-harvester", team_id="blue", amount=3),
        _e(0, 1, "mission_completed", mission_id="ms-supply", team_id="blue"),
    ]
    result = cgrade_units(_log(initial, events))
    unit = result["units"][0]
    assert unit["purposes"]["economy"]["points"] == 3 * GRADE_UNIT + 6 * GRADE_UNIT
    assert unit["purposes"]["economy"]["on_role"] is True


def test_a_units_matching_hold_mission_never_credits_the_wrong_team() -> None:
    """Two teams contest the same control point; only the team that currently
    holds it (per the log's own ``post_taken`` history) may bank the hold
    mission's credit — a defensive-attribution test, not a live race (t3 owns
    contested-delivery rules; this only proves grading reads history, not
    guesses)."""
    cp_pos = from_units(5, 5)
    initial = _state(
        teams=(
            _team("blue", "Blue", (_slot("blue-defender", "defender"),)),
            _team("red", "Red", (_slot("red-defender", "defender"),)),
        ),
        units=(
            _unit("blue-u1", "blue", "defender", cp_pos),
            _unit("red-u1", "red", "defender", cp_pos),
        ),
        control_points=(CControlPoint(id="cp-1", pos=cp_pos),),
        missions=(CMission(id="ms-hold", kind="hold", pos=cp_pos, amount=5, reward=8),),
    )
    events = [
        _e(0, 0, "post_taken", cp_id="cp-1", team_id="blue", unit_id="blue-u1"),
        _e(2, 1, "post_taken", cp_id="cp-1", team_id="red", unit_id="red-u1"),
        _e(7, 2, "mission_completed", mission_id="ms-hold", team_id="red"),
    ]
    result = cgrade_units(_log(initial, events))
    by_unit = {u["unit_id"]: u for u in result["units"]}
    # blue-u1 only ever earns its own post_taken (300); red-u1 earns its own
    # post_taken (300) PLUS the hold mission credit (its team currently holds).
    assert by_unit["blue-u1"]["purposes"]["race_hold"]["points"] == 300
    assert by_unit["red-u1"]["purposes"]["race_hold"]["points"] == 300 + 8 * GRADE_UNIT


# --------------------------------------------------------------------------- #
# Deterministic MVP/LVP tie-break: (grade, team_id, unit_id)
# --------------------------------------------------------------------------- #
def test_mvp_and_lvp_tie_break_is_grade_then_team_id_then_unit_id() -> None:
    """Two units tie for the top grade, two tie for the bottom (zero). The
    pinned rule (module docstring) orders candidates by ``(grade, team_id,
    unit_id)`` — MVP takes the smallest ``team_id``/``unit_id`` among the top
    tie, LVP the smallest among the bottom tie."""
    cp_a, cp_b = from_units(1, 1), from_units(9, 9)
    initial = _state(
        teams=(
            _team(
                "blue",
                "Blue",
                (_slot("blue-defender", "defender"), _slot("blue-harvester", "harvester")),
            ),
            _team(
                "red",
                "Red",
                (_slot("red-defender", "defender"), _slot("red-harvester", "harvester")),
            ),
        ),
        units=(
            _unit("blue-u1", "blue", "defender", cp_a),
            _unit("blue-u2", "blue", "harvester", cp_a),
            _unit("red-u1", "red", "defender", cp_b),
            _unit("red-u2", "red", "harvester", cp_b),
        ),
        control_points=(CControlPoint(id="cp-a", pos=cp_a), CControlPoint(id="cp-b", pos=cp_b)),
    )
    events = [
        # blue-u1 and red-u1 tie at the top (300 each); blue-u2/red-u2 tie at
        # the bottom (0 each, no events at all).
        _e(0, 0, "post_taken", cp_id="cp-a", team_id="blue", unit_id="blue-u1"),
        _e(0, 1, "post_taken", cp_id="cp-b", team_id="red", unit_id="red-u1"),
    ]
    result = cgrade_units(_log(initial, events))
    by_unit = {u["unit_id"]: u["grade"] for u in result["units"]}
    assert by_unit["blue-u1"] == by_unit["red-u1"] == 300
    assert by_unit["blue-u2"] == by_unit["red-u2"] == 0

    assert result["mvp"] == {"unit_id": "blue-u1", "team_id": "blue", "grade": 300}
    assert result["lvp"] == {"unit_id": "blue-u2", "team_id": "blue", "grade": 0}


# --------------------------------------------------------------------------- #
# Corruption must be loud (mirrors events.py's own discipline)
# --------------------------------------------------------------------------- #
def test_event_referencing_an_unknown_unit_raises() -> None:
    initial = _state(
        teams=(_team("blue", "Blue", (_slot("blue-defender", "defender"),)),),
        units=(_unit("u-defender", "blue", "defender", from_units(0, 0)),),
    )
    events = [_e(0, 0, "resource_gathered", unit_id="ghost-unit", node_id="rn", amount=1)]
    with pytest.raises(ValueError, match="unknown unit"):
        cgrade_units(_log(initial, events))


def test_cgrade_units_rejects_a_match_with_no_units() -> None:
    initial = _state(teams=(), units=())
    with pytest.raises(ValueError, match="no units"):
        cgrade_units(_log(initial, []))
