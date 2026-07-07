"""Cooperation metric v1 — log-derived, content-aware scoring (plan task t1).

v0 (``tests/test_engine_scoring.py``) rewarded *cadence*: a team that messaged
every turn and declared any plan could bank a perfect cooperation score, so in
all three season-0 matches the losing team out-cooperated the winner. v1 keeps
the same four axes but scores *quality*:

* ``delegation_spread`` — roster evenness, now with a rejection penalty (a team
  whose orders bounce is not delegating well);
* ``message_utility`` — replaces cadence: a message scores only if its content
  correlates with a subsequent observable team action (moves toward a named
  cell, captures a named point, delivers after naming the supply mission);
* ``plan_fidelity`` — replaces plan *presence*: a declared plan scores only if
  the team's later actions realize its named referents;
* ``discipline`` — unchanged rejection tax, clamped at zero.

Every weight and penalty constant is pinned here (plan risk r1 is resolved *by*
these tests, not by prose). Per the h2 honesty rule the pins live on synthetic
logs — none is tuned so season-0 winners out-cooperate losers.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from league.engine.events import Event, MatchLog
from league.engine.scoring import (
    CORRELATION_WINDOW,
    PLAN_WINDOW,
    REJECTION_PENALTY,
    V1_WEIGHTS,
    WEIGHTS,
    score_match,
)
from league.engine.state import (
    AgentSlot,
    ControlPoint,
    MatchState,
    Mission,
    ResourceNode,
    TeamState,
    Unit,
)

_SEASON0 = pathlib.Path(__file__).resolve().parent.parent / "docs" / "playtests" / "season-0"


# --------------------------------------------------------------------------- #
# Synthetic-log builders. apply_event only raises on missing ids/unknown kinds,
# so hand-built transition events fold cleanly as long as they name real units,
# nodes, control points, and missions — realistic amounts are not required.
# --------------------------------------------------------------------------- #


def _team(tid: str, n: int) -> TeamState:
    agents = tuple(AgentSlot(id=f"{tid}-{i}", model="m", role="scout") for i in range(1, n + 1))
    return TeamState(id=tid, name=tid.title(), resources=0, agents=agents)


def _unit(tid: str, i: int, pos: tuple[int, int] = (0, 0), carrying: int = 0) -> Unit:
    return Unit(
        id=f"{tid}-u{i}",
        team_id=tid,
        agent_id=f"{tid}-{i}",
        role="scout",
        pos=pos,
        carrying=carrying,
    )


def _state(
    *,
    teams: tuple[TeamState, ...],
    units: tuple[Unit, ...],
    cps: tuple[ControlPoint, ...] = (),
    nodes: tuple[ResourceNode, ...] = (),
    missions: tuple[Mission, ...] = (),
) -> MatchState:
    return MatchState(
        match_id="m-v1",
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
        missions=missions,
        resource_nodes=nodes,
    )


def _log(initial: MatchState, triples: list[tuple[int, str, dict]]) -> MatchLog:
    """``(turn, kind, data)`` triples in chronological order → a MatchLog.

    ``seq`` is the tuple index; the v1 action index folds unit positions in log
    order, so the triples must be listed in the order events occurred.
    """
    events = tuple(
        Event(turn=turn, seq=i, kind=kind, data=data)
        for i, (turn, kind, data) in enumerate(triples)
    )
    return MatchLog(initial_state=initial, events=events)


def _declare(team: str, turn: int, unit: str) -> tuple[int, str, dict]:
    return (turn, "action_declared", {"team_id": team, "unit_id": unit, "action": "move"})


def _reject(team: str, turn: int, unit: str) -> tuple[int, str, dict]:
    return (turn, "action_rejected", {"team_id": team, "unit_id": unit, "reason": "illegal"})


def _msg(team: str, turn: int, text: str) -> tuple[int, str, dict]:
    return (turn, "message_sent", {"team_id": team, "from": f"{team}-1", "text": text})


def _plan(team: str, turn: int, text: str) -> tuple[int, str, dict]:
    return (turn, "plan_declared", {"team_id": team, "text": text})


def _move(unit: str, turn: int, to: tuple[int, int]) -> tuple[int, str, dict]:
    return (turn, "unit_moved", {"unit_id": unit, "to": list(to)})


def _capture(team: str, turn: int, cp: str) -> tuple[int, str, dict]:
    return (turn, "control_point_captured", {"team_id": team, "cp_id": cp})


def _deliver(team: str, turn: int, unit: str, amount: int = 3) -> tuple[int, str, dict]:
    return (turn, "resource_delivered", {"team_id": team, "unit_id": unit, "amount": amount})


# --------------------------------------------------------------------------- #
# 1. Weights, penalty, and windows are named constants (risk r1 resolved here).
# --------------------------------------------------------------------------- #


def test_v1_weights_are_named_and_sum_to_one() -> None:
    assert set(V1_WEIGHTS) == {
        "delegation_spread",
        "message_utility",
        "plan_fidelity",
        "discipline",
    }
    assert abs(sum(V1_WEIGHTS.values()) - 1.0) < 1e-9
    # The exact weight vector — every divergence from v0 traces to one of these.
    assert V1_WEIGHTS == {
        "delegation_spread": 0.30,
        "message_utility": 0.30,
        "plan_fidelity": 0.15,
        "discipline": 0.25,
    }


def test_v1_penalty_and_windows_are_pinned_constants() -> None:
    assert REJECTION_PENALTY == 0.5
    assert CORRELATION_WINDOW == 2
    assert PLAN_WINDOW == 4


# --------------------------------------------------------------------------- #
# 2. Rejected orders penalize delegation_spread (and discipline), by exactly
#    REJECTION_PENALTY * rejection_rate.
# --------------------------------------------------------------------------- #


def test_rejections_penalize_delegation_spread() -> None:
    initial = _state(
        teams=(_team("blue", 2), _team("red", 2)),
        units=(_unit("blue", 1), _unit("blue", 2), _unit("red", 1), _unit("red", 2)),
    )
    triples = [
        # blue: full roster acts twice (base_spread 1.0) but bounces one order.
        _declare("blue", 1, "blue-u1"),
        _declare("blue", 1, "blue-u2"),
        _reject("blue", 1, "blue-u1"),
        _declare("blue", 2, "blue-u1"),
        _declare("blue", 2, "blue-u2"),
        # red: identical delegation, zero rejections (the control).
        _declare("red", 1, "red-u1"),
        _declare("red", 1, "red-u2"),
        _declare("red", 2, "red-u1"),
        _declare("red", 2, "red-u2"),
        (2, "turn_advanced", {"turn": 2}),
    ]
    report = score_match(_log(initial, triples), version="v1")
    blue = report["cooperation"]["blue"]["signals"]
    red = report["cooperation"]["red"]["signals"]
    # rejection_rate = 1/4 = 0.25; penalty = REJECTION_PENALTY * 0.25 = 0.125.
    assert blue["delegation_spread"] == 0.875
    assert blue["discipline"] == 0.75
    # No rejections → base spread and discipline untouched.
    assert red["delegation_spread"] == 1.0
    assert red["discipline"] == 1.0
    assert blue["delegation_spread"] < red["delegation_spread"]


# --------------------------------------------------------------------------- #
# 3. message_utility scores content, not cadence.
# --------------------------------------------------------------------------- #


def test_message_utility_scores_content_not_cadence() -> None:
    """Two teams, the SAME message count — only content correlation differs."""
    initial = _state(
        teams=(_team("hi", 1), _team("lo", 1)),
        units=(_unit("hi", 1, pos=(0, 0)), _unit("lo", 1, pos=(0, 0))),
    )
    triples = [
        # hi: two callouts, each realized by a move toward the named cell.
        _msg("hi", 1, "push toward (9, 9)"),
        _move("hi-u1", 1, (4, 4)),
        _msg("hi", 2, "keep pressing (9, 9)"),
        _move("hi-u1", 2, (9, 9)),
        # lo: two messages of pure chatter — same cadence, zero utility.
        _msg("lo", 1, "good game everyone"),
        _msg("lo", 2, "nice one"),
        _move("lo-u1", 1, (4, 4)),  # lo moves too, but named nothing.
        (2, "turn_advanced", {"turn": 2}),
    ]
    report = score_match(_log(initial, triples), version="v1")
    hi = report["cooperation"]["hi"]
    lo = report["cooperation"]["lo"]
    assert hi["components"]["message_utility"]["messages"] == 2
    assert lo["components"]["message_utility"]["messages"] == 2  # identical cadence
    assert hi["signals"]["message_utility"] == 1.0
    assert lo["signals"]["message_utility"] == 0.0


def test_message_utility_covers_cell_point_unit_and_mission_referents() -> None:
    """One useful message per referent kind, plus one chatter miss → 3/4."""
    initial = _state(
        teams=(_team("blue", 2),),
        units=(_unit("blue", 1, pos=(0, 0)), _unit("blue", 2, pos=(0, 0), carrying=3)),
        cps=(ControlPoint(id="cp-center", pos=(6, 5)),),
        nodes=(ResourceNode(id="rn-west", pos=(0, 5), remaining=12),),
        missions=(Mission(id="ms-supply", kind="deliver", pos=(6, 5), amount=6, reward=10),),
    )
    triples = [
        _msg("blue", 1, "advance to (6, 6)"),  # cell → toward
        _move("blue-u1", 1, (3, 3)),
        _msg("blue", 2, "take cp-center now"),  # control point → capture
        _capture("blue", 2, "cp-center"),
        _msg("blue", 3, "blue-u2 haul and deliver to ms-supply"),  # unit + deliver mission
        _deliver("blue", 3, "blue-u2"),
        _msg("blue", 4, "good game"),  # no referent → miss
        (4, "turn_advanced", {"turn": 4}),
    ]
    report = score_match(_log(initial, triples), version="v1")
    comp = report["cooperation"]["blue"]["components"]["message_utility"]
    assert comp == {"messages": 4, "useful": 3, "value": 0.75}


# --------------------------------------------------------------------------- #
# 4. Pseudo-coordination: high volume + low correlation must score LOWER than
#    moderate volume + high correlation (the exact two-log ordering test).
# --------------------------------------------------------------------------- #


def test_pseudo_coordination_scores_lower_than_real_coordination() -> None:
    initial = _state(
        teams=(_team("cha", 2), _team("foc", 2)),
        units=(
            _unit("cha", 1, pos=(0, 0)),
            _unit("cha", 2, pos=(0, 0)),
            _unit("foc", 1, pos=(0, 0)),
            _unit("foc", 2, pos=(0, 0)),
        ),
    )
    chatter_fill = ["ok", "gg", "nice", "sure", "later", "yes", "no", "hmm", "wp"]
    triples: list[tuple[int, str, dict]] = []
    # Both teams delegate fully across three turns with zero rejections, so the
    # ONLY score difference is message_utility.
    for turn in (1, 2, 3):
        for team in ("cha", "foc"):
            triples.append(_declare(team, turn, f"{team}-u1"))
            triples.append(_declare(team, turn, f"{team}-u2"))
    # cha: 10 messages, exactly one correlated (0.1 utility).
    triples.append(_msg("cha", 1, "converge on (9, 9)"))
    triples.append(_move("cha-u1", 1, (4, 4)))
    for i, word in enumerate(chatter_fill):
        triples.append(_msg("cha", 1 + i % 3, word))
    # foc: 3 messages, every one correlated (1.0 utility).
    triples.append(_msg("foc", 1, "converge on (9, 9)"))
    triples.append(_move("foc-u1", 1, (4, 4)))
    triples.append(_msg("foc", 2, "keep pressing (9, 9)"))
    triples.append(_move("foc-u1", 2, (7, 7)))
    triples.append(_msg("foc", 3, "finish at (9, 9)"))
    triples.append(_move("foc-u1", 3, (9, 9)))
    triples.append((3, "turn_advanced", {"turn": 3}))

    report = score_match(_log(initial, triples), version="v1")
    cha = report["cooperation"]["cha"]
    foc = report["cooperation"]["foc"]
    assert cha["signals"]["message_utility"] == 0.1
    assert foc["signals"]["message_utility"] == 1.0
    assert foc["signals"]["message_utility"] > cha["signals"]["message_utility"]
    # Every other signal is identical, so the overall score ordering follows.
    # 0.3*1 + 0.3*u + 0.15*0 + 0.25*1  → cha 58, foc 85.
    assert cha["score"] == 58
    assert foc["score"] == 85
    assert foc["score"] > cha["score"]


# --------------------------------------------------------------------------- #
# 5. plan_fidelity: a declared plan scores only when its content is realized —
#    this is where v0 (plan presence) and v1 (plan fidelity) diverge.
# --------------------------------------------------------------------------- #


def test_plan_fidelity_rewards_realized_plans_only() -> None:
    initial = _state(
        teams=(_team("does", 1), _team("only", 1)),
        # 'only' starts sitting ON cp-center, then moves away from it.
        units=(_unit("does", 1, pos=(0, 0)), _unit("only", 1, pos=(6, 5))),
        cps=(ControlPoint(id="cp-center", pos=(6, 5)),),
    )
    triples = [
        _plan("does", 1, "capture cp-center"),
        _declare("does", 1, "does-u1"),
        _capture("does", 2, "cp-center"),  # plan realized within PLAN_WINDOW
        _plan("only", 1, "capture cp-center"),
        _declare("only", 1, "only-u1"),
        _move("only-u1", 1, (0, 0)),  # walks AWAY from cp-center; never captures
        (2, "turn_advanced", {"turn": 2}),
    ]
    log = _log(initial, triples)
    v1 = score_match(log, version="v1")
    assert v1["cooperation"]["does"]["signals"]["plan_fidelity"] == 1.0
    assert v1["cooperation"]["only"]["signals"]["plan_fidelity"] == 0.0
    # The v0 defect, on the record: 'only' declared a plan and acted, so v0's
    # plan_coherence credits it in full — the exact chatter v1 stops rewarding.
    v0 = score_match(log, version="v0")
    assert v0["cooperation"]["only"]["signals"]["plan_coherence"] == 1.0


# --------------------------------------------------------------------------- #
# 6. Payload shape: v1 is inspectable per-signal (h3); v0 is byte-identical.
# --------------------------------------------------------------------------- #


def test_v1_payload_carries_named_components_and_version() -> None:
    initial = _state(teams=(_team("blue", 1),), units=(_unit("blue", 1),))
    triples = [_declare("blue", 1, "blue-u1"), (2, "turn_advanced", {"turn": 2})]
    coop = score_match(_log(initial, triples), version="v1")["cooperation"]["blue"]
    assert coop["version"] == "v1"
    assert set(coop) == {"score", "signals", "components", "version"}
    assert set(coop["signals"]) == set(V1_WEIGHTS)
    assert set(coop["components"]) == set(V1_WEIGHTS)
    for name, comp in coop["components"].items():
        assert comp["value"] == coop["signals"][name]
    assert 0 <= coop["score"] <= 100
    for value in coop["signals"].values():
        assert 0.0 <= value <= 1.0


def test_v1_delegation_component_exposes_its_penalty() -> None:
    initial = _state(teams=(_team("blue", 2),), units=(_unit("blue", 1), _unit("blue", 2)))
    triples = [
        _declare("blue", 1, "blue-u1"),
        _declare("blue", 1, "blue-u2"),
        _reject("blue", 1, "blue-u1"),
        (2, "turn_advanced", {"turn": 2}),
    ]
    comp = score_match(_log(initial, triples), version="v1")["cooperation"]["blue"]["components"]
    delegation = comp["delegation_spread"]
    assert delegation["base_spread"] == 1.0
    assert delegation["rejection_rate"] == 0.5  # 1 rejected / 2 declared
    assert delegation["penalty"] == 0.25  # REJECTION_PENALTY * 0.5
    assert delegation["value"] == 0.75


# --------------------------------------------------------------------------- #
# 7. Version selection and the v0 regression guarantee.
# --------------------------------------------------------------------------- #


def test_default_version_is_v0_and_shape_is_unchanged() -> None:
    initial = _state(teams=(_team("blue", 1),), units=(_unit("blue", 1),))
    triples = [_declare("blue", 1, "blue-u1"), (2, "turn_advanced", {"turn": 2})]
    log = _log(initial, triples)
    default = score_match(log)
    explicit = score_match(log, version="v0")
    assert default == explicit
    coop = default["cooperation"]["blue"]
    assert set(coop) == {"score", "signals"}  # no components/version leak into v0
    assert set(coop["signals"]) == set(WEIGHTS)


def test_unknown_version_raises() -> None:
    initial = _state(teams=(_team("blue", 1),), units=(_unit("blue", 1),))
    log = _log(initial, [_declare("blue", 1, "blue-u1")])
    with pytest.raises(ValueError):
        score_match(log, version="v2")


@pytest.mark.parametrize("name", ["opener", "coordination", "orchestrator"])
def test_v0_reproduces_committed_season0_scores(name: str) -> None:
    """v0 output stays bit-identical to the committed *.score.json (regression)."""
    log = MatchLog.from_jsonl((_SEASON0 / f"{name}.log.jsonl").read_text())
    committed = json.loads((_SEASON0 / f"{name}.score.json").read_text())
    assert score_match(log, version="v0") == committed
    assert score_match(log) == committed  # default is v0


@pytest.mark.parametrize("name", ["opener", "coordination", "orchestrator"])
def test_v1_scores_season0_logs_without_crashing(name: str) -> None:
    """v1 runs on the real logs and returns the inspectable shape — outcomes are
    NOT asserted here (h2: v1 is not tuned to make winners out-cooperate)."""
    log = MatchLog.from_jsonl((_SEASON0 / f"{name}.log.jsonl").read_text())
    report = score_match(log, version="v1")
    for coop in report["cooperation"].values():
        assert coop["version"] == "v1"
        assert set(coop["signals"]) == set(V1_WEIGHTS)
        assert 0 <= coop["score"] <= 100
        for value in coop["signals"].values():
            assert 0.0 <= value <= 1.0
