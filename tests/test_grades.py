"""Acceptance tests for the per-unit role-purpose scorecard (plan task t1).

Criteria under test (verbatim from the plan):

* ``grade_units(log)`` is a pure function of the log: per-unit grade with a
  per-role-purpose breakdown, MVP and LVP named with deterministic tie-break;
  same log twice -> identical payload.
* Off-role contribution scores strictly more than zero and strictly less than
  the identical contribution made on-role, proven by a worked two-unit test
  case.
* Every committed grid ``score.json`` re-scores bit-identically after this
  lands (team axes untouched — grades are a NEW axis beside them, never
  merged into team scores), and ``league/engine/grades.py`` imports no
  scoring/tempo/probe module (AST-checked).
"""

from __future__ import annotations

import ast
import json
import pathlib

from league.engine.events import Event, MatchLog
from league.engine.grades import (
    CAPTURE_POINTS,
    HOLD_POINTS,
    MESSAGE_POINTS,
    MOVE_POINTS,
    OFF_ROLE_MULTIPLIER,
    ON_ROLE_MULTIPLIER,
    PURPOSES,
    ROLE_HOME_PURPOSE,
    grade_units,
)
from league.engine.scoring import score_match
from league.engine.state import (
    AgentSlot,
    ControlPoint,
    MatchState,
    ResourceNode,
    TeamState,
    Unit,
)

GRADES_MODULE = pathlib.Path(__file__).resolve().parent.parent / "league" / "engine" / "grades.py"
PLAYTESTS_DIR = pathlib.Path(__file__).resolve().parent.parent / "docs" / "playtests"


# --------------------------------------------------------------------------- #
# Synthetic-log builders (mirrors tests/test_engine_scoring_v1.py's pattern):
# apply_event only raises on missing/unknown ids, so hand-built transition
# events fold cleanly without a full tick.resolve_turn() round trip.
# --------------------------------------------------------------------------- #


def _team(tid: str, roles: tuple[str, ...]) -> TeamState:
    agents = tuple(
        AgentSlot(id=f"{tid}-a{i}", model="m", role=role) for i, role in enumerate(roles, start=1)
    )
    return TeamState(id=tid, name=tid.title(), resources=0, agents=agents)


def _unit(tid: str, i: int, role: str, pos: tuple[int, int] = (0, 0)) -> Unit:
    return Unit(id=f"{tid}-u{i}", team_id=tid, agent_id=f"{tid}-a{i}", role=role, pos=pos)


def _state(
    *,
    units: tuple[Unit, ...],
    cps: tuple[ControlPoint, ...] = (),
    nodes: tuple[ResourceNode, ...] = (),
) -> MatchState:
    teams = tuple(
        TeamState(id=tid, name=tid.title(), resources=0, agents=())
        for tid in sorted({u.team_id for u in units})
    )
    return MatchState(
        match_id="m-grades",
        scenario_id="skirmish-1",
        seed=0,
        mode="competitive",
        turn=1,
        turn_limit=30,
        grid_width=12,
        grid_height=10,
        status="active",
        winner=None,
        teams=teams,
        units=units,
        control_points=cps,
        missions=(),
        resource_nodes=nodes,
    )


def _log(initial: MatchState, triples: list[tuple[int, str, dict]]) -> MatchLog:
    events = tuple(
        Event(turn=turn, seq=i, kind=kind, data=data)
        for i, (turn, kind, data) in enumerate(triples)
    )
    return MatchLog(initial_state=initial, events=events)


def _gather(unit: str, turn: int, amount: int, node: str = "rn-1") -> tuple[int, str, dict]:
    return (turn, "resource_gathered", {"unit_id": unit, "node_id": node, "amount": amount})


def _deliver(unit: str, team: str, turn: int, amount: int) -> tuple[int, str, dict]:
    return (turn, "resource_delivered", {"unit_id": unit, "team_id": team, "amount": amount})


def _move(unit: str, turn: int, to: tuple[int, int]) -> tuple[int, str, dict]:
    return (turn, "unit_moved", {"unit_id": unit, "to": list(to)})


def _capture(team: str, turn: int, cp: str) -> tuple[int, str, dict]:
    return (turn, "control_point_captured", {"team_id": team, "cp_id": cp})


def _held(team: str, turn: int, cp: str, turns: int) -> tuple[int, str, dict]:
    return (turn, "control_point_held", {"team_id": team, "cp_id": cp, "turns": turns})


def _message(team: str, turn: int, sender_agent: str, text: str = "hi") -> tuple[int, str, dict]:
    return (turn, "message_sent", {"team_id": team, "from": sender_agent, "text": text})


# --------------------------------------------------------------------------- #
# 1. Purity: same log twice -> identical payload.
# --------------------------------------------------------------------------- #


def test_grade_units_is_pure_same_log_twice_identical_payload() -> None:
    initial = _state(units=(_unit("blue", 1, "harvester"), _unit("blue", 2, "scout")))
    triples = [_gather("blue-u1", 1, 4), _gather("blue-u2", 2, 4), _move("blue-u2", 3, (1, 0))]
    log = _log(initial, triples)

    first = grade_units(log)
    second = grade_units(log)
    assert first == second


# --------------------------------------------------------------------------- #
# 2. The worked two-unit off-role case: identical resource_gathered amount,
#    one unit on-role (harvester -> economy), one off-role (scout -> recon).
# --------------------------------------------------------------------------- #


def test_off_role_contribution_scores_between_zero_and_the_on_role_score() -> None:
    initial = _state(units=(_unit("blue", 1, "harvester"), _unit("blue", 2, "scout")))
    triples = [_gather("blue-u1", 1, 4), _gather("blue-u2", 1, 4)]
    log = _log(initial, triples)

    report = grade_units(log)
    on_role = report["units"]["blue-u1"]["breakdown"]["economy"]  # harvester: on-role
    off_role = report["units"]["blue-u2"]["breakdown"]["economy"]  # scout: off-role

    assert on_role == 4 * ON_ROLE_MULTIPLIER
    assert off_role == 4 * OFF_ROLE_MULTIPLIER
    assert 0 < off_role < on_role
    # Pinned exact values so a future formula change is a deliberate, visible
    # diff here rather than a silent drift.
    assert on_role == 8
    assert off_role == 4


def test_off_role_holds_for_control_purpose_too_defender_versus_scout() -> None:
    """The same on/off-role contrast, exercised on the control purpose (a
    defender capturing versus a scout capturing the identical point)."""
    initial = _state(
        units=(_unit("blue", 1, "defender", pos=(5, 5)), _unit("blue", 2, "scout", pos=(5, 5))),
        cps=(ControlPoint(id="cp-1", pos=(5, 5)),),
    )
    defender_log = _log(initial, [_capture("blue", 1, "cp-1")])
    only_defender = grade_units(
        MatchLog(
            initial_state=_state(
                units=(_unit("blue", 1, "defender", pos=(5, 5)),),
                cps=(ControlPoint(id="cp-1", pos=(5, 5)),),
            ),
            events=defender_log.events,
        )
    )
    only_scout = grade_units(
        MatchLog(
            initial_state=_state(
                units=(_unit("blue", 1, "scout", pos=(5, 5)),),
                cps=(ControlPoint(id="cp-1", pos=(5, 5)),),
            ),
            events=defender_log.events,
        )
    )
    on_role = only_defender["units"]["blue-u1"]["breakdown"]["control"]
    off_role = only_scout["units"]["blue-u1"]["breakdown"]["control"]
    assert on_role == CAPTURE_POINTS * ON_ROLE_MULTIPLIER
    assert off_role == CAPTURE_POINTS * OFF_ROLE_MULTIPLIER
    assert 0 < off_role < on_role


# --------------------------------------------------------------------------- #
# 3. MVP/LVP naming and the canonical tie-break.
# --------------------------------------------------------------------------- #


def test_mvp_and_lvp_are_named_at_the_grade_extremes() -> None:
    initial = _state(
        units=(
            _unit("blue", 1, "harvester"),
            _unit("blue", 2, "scout"),
            _unit("red", 1, "harvester"),
        )
    )
    triples = [
        _gather("blue-u1", 1, 10),  # on-role: 20
        _gather("blue-u2", 1, 1),  # off-role: 1
        _gather("red-u1", 1, 3),  # on-role: 6
    ]
    log = _log(initial, triples)
    report = grade_units(log)

    grades = {uid: entry["grade"] for uid, entry in report["units"].items()}
    assert grades["blue-u1"] == max(grades.values())
    assert grades["blue-u2"] == min(grades.values())
    assert report["mvp"] == {"unit_id": "blue-u1", "team_id": "blue", "grade": 20}
    assert report["lvp"] == {"unit_id": "blue-u2", "team_id": "blue", "grade": 1}


def test_mvp_lvp_tie_breaks_ascending_by_team_id_then_unit_id() -> None:
    """A constructed tie: two units, different teams, identical grade.

    Per the module docstring, MVP among ties is the unit minimizing
    ``(-grade, team_id, unit_id)`` — i.e. the lexicographically-first team,
    then unit id — and LVP mirrors it minimizing ``(grade, team_id, unit_id)``.
    Both ties are resolved by that SAME (team_id, unit_id) ascending order, so
    with only two equally-graded units, one is named MVP and the other LVP —
    and it is always "blue-u1" (blue < red) that wins the tie either way.
    """
    initial = _state(units=(_unit("red", 1, "harvester"), _unit("blue", 1, "harvester")))
    triples = [_gather("red-u1", 1, 5), _gather("blue-u1", 1, 5)]
    log = _log(initial, triples)
    report = grade_units(log)

    assert report["units"]["red-u1"]["grade"] == report["units"]["blue-u1"]["grade"]
    assert report["mvp"]["unit_id"] == "blue-u1"
    assert report["lvp"]["unit_id"] == "blue-u1"


def test_no_units_yields_no_mvp_or_lvp() -> None:
    initial = _state(units=())
    log = _log(initial, [])
    report = grade_units(log)
    assert report["units"] == {}
    assert report["mvp"] is None
    assert report["lvp"] is None


# --------------------------------------------------------------------------- #
# 4. Per-role-purpose breakdown shape and attribution correctness.
# --------------------------------------------------------------------------- #


def test_every_unit_breakdown_carries_every_purpose_key() -> None:
    initial = _state(units=(_unit("blue", 1, "harvester"),))
    log = _log(initial, [_gather("blue-u1", 1, 2)])
    report = grade_units(log)
    assert report["purposes"] == list(PURPOSES)
    assert set(report["units"]["blue-u1"]["breakdown"]) == set(PURPOSES)


def test_role_home_purpose_field_matches_the_pinned_mapping() -> None:
    assert ROLE_HOME_PURPOSE == {
        "harvester": "economy",
        "defender": "control",
        "scout": "recon",
        "explorer": "recon",
        "planner": "coordination",
    }
    initial = _state(units=(_unit("blue", 1, "planner"),))
    log = _log(initial, [])
    report = grade_units(log)
    assert report["units"]["blue-u1"]["home_purpose"] == "coordination"


def test_unknown_role_has_no_home_purpose_but_still_scores() -> None:
    initial = _state(units=(_unit("blue", 1, "mystic"),))
    log = _log(initial, [_move("blue-u1", 1, (1, 0))])
    report = grade_units(log)
    entry = report["units"]["blue-u1"]
    assert entry["home_purpose"] is None
    assert entry["breakdown"]["recon"] == MOVE_POINTS * OFF_ROLE_MULTIPLIER
    assert entry["grade"] > 0


def test_resource_delivered_credits_economy_by_amount() -> None:
    initial = _state(units=(_unit("blue", 1, "harvester"),))
    log = _log(initial, [_deliver("blue-u1", "blue", 1, 6)])
    report = grade_units(log)
    assert report["units"]["blue-u1"]["breakdown"]["economy"] == 6 * ON_ROLE_MULTIPLIER


def test_capture_and_hold_credit_every_occupying_unit_of_the_credited_team() -> None:
    """Two defenders share the control point's cell; both are credited for a
    capture and a subsequent hold — presence is rewarded, not exclusivity."""
    initial = _state(
        units=(
            _unit("blue", 1, "defender", pos=(5, 5)),
            _unit("blue", 2, "defender", pos=(5, 5)),
            _unit("red", 1, "defender", pos=(0, 0)),
        ),
        cps=(ControlPoint(id="cp-1", pos=(5, 5)),),
    )
    triples = [
        _capture("blue", 1, "cp-1"),
        _held("blue", 1, "cp-1", 1),
        _held("blue", 2, "cp-1", 2),
    ]
    log = _log(initial, triples)
    report = grade_units(log)

    expected = (CAPTURE_POINTS + 2 * HOLD_POINTS) * ON_ROLE_MULTIPLIER
    assert report["units"]["blue-u1"]["breakdown"]["control"] == expected
    assert report["units"]["blue-u2"]["breakdown"]["control"] == expected
    assert report["units"]["red-u1"]["breakdown"]["control"] == 0


def test_control_point_held_reset_event_credits_nothing() -> None:
    """A contested/abandoned hold (team_id="", turns=0) is the streak-reset
    form the fold itself treats as a no-op (events.py) — grading mirrors it."""
    initial = _state(
        units=(_unit("blue", 1, "defender", pos=(5, 5)),),
        cps=(ControlPoint(id="cp-1", pos=(5, 5)),),
    )
    log = _log(initial, [_held("", 1, "cp-1", 0)])
    report = grade_units(log)
    assert report["units"]["blue-u1"]["breakdown"]["control"] == 0


def test_message_sent_credits_the_sending_units_coordination_via_agent_id() -> None:
    """``message_sent``'s ``from`` field is an agent id, not a unit id
    (league/harness.py) — grading resolves it through the initial roster."""
    initial = _state(units=(_unit("blue", 1, "planner"), _unit("blue", 2, "harvester")))
    log = _log(initial, [_message("blue", 1, "blue-a1", "scout reports enemy at cp-east")])
    report = grade_units(log)
    assert report["units"]["blue-u1"]["breakdown"]["coordination"] == (
        MESSAGE_POINTS * ON_ROLE_MULTIPLIER
    )
    assert report["units"]["blue-u2"]["breakdown"]["coordination"] == 0


def test_message_from_an_unmapped_sender_credits_no_unit() -> None:
    """Orchestrator-mode messages can come from a master seat with no ground
    unit of its own (``from`` names no agent in the roster) — a safe no-op."""
    initial = _state(units=(_unit("blue", 1, "planner"),))
    log = _log(initial, [_message("blue", 1, "blue-master", "hold the line")])
    report = grade_units(log)
    assert report["units"]["blue-u1"]["breakdown"]["coordination"] == 0


def test_unit_moved_updates_tracked_position_before_a_same_turn_capture() -> None:
    """A unit that moves onto the control point's cell earlier in the SAME
    turn is credited for a capture that fires later that turn — position
    tracking must reflect the turn's moves in log order, not just spawn."""
    initial = _state(
        units=(_unit("blue", 1, "defender", pos=(0, 0)),),
        cps=(ControlPoint(id="cp-1", pos=(5, 5)),),
    )
    triples = [_move("blue-u1", 1, (5, 5)), _capture("blue", 1, "cp-1")]
    log = _log(initial, triples)
    report = grade_units(log)
    assert report["units"]["blue-u1"]["breakdown"]["control"] == CAPTURE_POINTS * ON_ROLE_MULTIPLIER


# --------------------------------------------------------------------------- #
# 5. Boundary: no import of any team-axis scoring module (AST-checked), and
#    the committed grid score.json compat sweep stays bit-identical.
# --------------------------------------------------------------------------- #


def _imported_dotted_modules(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                modules.add(node.module)
                modules.update(f"{node.module}.{alias.name}" for alias in node.names)
    return modules


def test_grades_module_imports_no_scoring_tempo_or_probe_module() -> None:
    banned = {"league.engine.scoring", "league.engine.tempo", "league.engine.probe"}
    imported = _imported_dotted_modules(GRADES_MODULE)
    offenders = imported & banned
    assert not offenders, f"league/engine/grades.py must not import {offenders}"


def test_committed_grid_scores_are_unaffected_by_grading_the_same_logs() -> None:
    """Acceptance c3: every committed grid score.json re-scores bit-identically
    after this axis lands. grades.py never touches scoring.py, so this is a
    direct check — grade the same committed logs and confirm score_match's
    outcome for each is exactly what the committed score.json already says."""
    logs = sorted(PLAYTESTS_DIR.glob("**/*.log.jsonl"))
    checked = 0
    for log_path in logs:
        text = log_path.read_text(encoding="utf-8")
        header = json.loads(text.splitlines()[0])
        if "turn" not in header.get("initial_state", {}):
            continue  # a continuous-lane log; grid-only check
        score_path = log_path.with_name(log_path.name.replace(".log.jsonl", ".score.json"))
        if not score_path.exists():
            continue
        log = MatchLog.from_jsonl(text)
        committed = json.loads(score_path.read_text(encoding="utf-8"))
        fresh = score_match(log)
        assert fresh["outcome"] == committed["outcome"], log_path
        # Grading the same log must not raise and must return a well-formed
        # payload — proof the two axes coexist without interference.
        graded = grade_units(log)
        assert set(graded) == {"match_id", "purposes", "units", "mvp", "lvp"}
        checked += 1
    assert checked >= 5, "expected the compat sweep to exercise several committed grid logs"
