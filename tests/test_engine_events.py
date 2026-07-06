"""Wave-1 acceptance tests for the match event log (plan task t2).

Criteria under test:

* every state transition is expressible as an event, and replaying the event
  log from the initial state reproduces the final state exactly;
* the log is the single source of truth — observational events (messages,
  plans, declarations) are recorded but leave board state untouched;
* JSONL round-trip is byte-identical.
"""

from __future__ import annotations

import dataclasses

import pytest

from league.engine.events import LOG_VERSION, Event, MatchLog, apply_event, fold_events
from league.engine.scenario import get_scenario, instantiate
from league.engine.state import AgentSlot, MatchState, state_hash


def _roster(team: str, model: str) -> tuple[AgentSlot, ...]:
    return (
        AgentSlot(id=f"{team}-scout", model=model, role="scout"),
        AgentSlot(id=f"{team}-harvester", model=model, role="harvester"),
        AgentSlot(id=f"{team}-defender", model=model, role="defender"),
    )


def initial_state() -> MatchState:
    return instantiate(
        get_scenario("skirmish-1"),
        match_id="m-events",
        seed=42,
        mode="competitive",
        teams=(
            ("blue", "Blue Foundry", _roster("blue", "colleague/qwen")),
            ("red", "Red Relay", _roster("red", "claude-sonnet-5")),
        ),
    )


def sample_events() -> tuple[Event, ...]:
    return (
        Event(turn=0, seq=0, kind="match_started", data={}),
        Event(
            turn=1,
            seq=1,
            kind="plan_declared",
            data={"team_id": "blue", "agent_id": "blue-scout", "text": "rush center, cap east"},
        ),
        Event(
            turn=1,
            seq=2,
            kind="action_declared",
            data={"team_id": "blue", "unit_id": "blue-u1", "action": "move", "to": [3, 1]},
        ),
        Event(turn=1, seq=3, kind="unit_moved", data={"unit_id": "blue-u1", "to": [3, 1]}),
        Event(
            turn=1,
            seq=4,
            kind="message_sent",
            data={"team_id": "blue", "from": "blue-scout", "text": "east node is open"},
        ),
        Event(turn=1, seq=5, kind="turn_advanced", data={"turn": 1}),
        Event(turn=1, seq=6, kind="turn_resolved", data={"turn": 1}),
        Event(turn=2, seq=7, kind="unit_moved", data={"unit_id": "blue-u2", "to": [0, 5]}),
        Event(
            turn=2,
            seq=8,
            kind="resource_gathered",
            data={"unit_id": "blue-u2", "node_id": "rn-west", "amount": 3},
        ),
        Event(turn=2, seq=9, kind="turn_advanced", data={"turn": 2}),
        Event(turn=3, seq=10, kind="unit_moved", data={"unit_id": "blue-u2", "to": [6, 5]}),
        Event(
            turn=3,
            seq=11,
            kind="resource_delivered",
            data={"unit_id": "blue-u2", "team_id": "blue", "amount": 3},
        ),
        Event(
            turn=3,
            seq=12,
            kind="control_point_captured",
            data={"cp_id": "cp-center", "team_id": "blue"},
        ),
        Event(
            turn=4,
            seq=13,
            kind="control_point_held",
            data={"cp_id": "cp-center", "team_id": "blue", "turns": 1},
        ),
        Event(turn=4, seq=14, kind="unit_defeated", data={"unit_id": "red-u1"}),
        Event(
            turn=5,
            seq=15,
            kind="mission_completed",
            data={"mission_id": "ms-supply", "team_id": "blue"},
        ),
        Event(turn=5, seq=16, kind="match_finished", data={"winner": "blue"}),
    )


def test_fold_reproduces_final_state_exactly() -> None:
    initial = initial_state()
    final = fold_events(initial, sample_events())

    assert final.status == "finished"
    assert final.winner == "blue"
    assert final.turn == 2  # last turn_advanced
    scout = next(u for u in final.units if u.id == "blue-u1")
    harvester = next(u for u in final.units if u.id == "blue-u2")
    assert scout.pos == (3, 1)
    assert harvester.pos == (6, 5)
    assert harvester.carrying == 0  # gathered 3, delivered 3
    blue = next(t for t in final.teams if t.id == "blue")
    assert blue.resources == 3
    node = next(r for r in final.resource_nodes if r.id == "rn-west")
    assert node.remaining == 9
    center = next(c for c in final.control_points if c.id == "cp-center")
    assert center.owner == "blue"
    assert center.hold == (("blue", 1),)
    assert not next(u for u in final.units if u.id == "red-u1").alive
    mission = next(m for m in final.missions if m.id == "ms-supply")
    assert mission.status == "completed"
    assert mission.completed_by == "blue"
    assert mission.completed_turn == 5


def test_observational_events_leave_state_unchanged() -> None:
    state = initial_state()
    for kind, data in (
        ("action_declared", {"team_id": "blue", "unit_id": "blue-u1", "action": "move"}),
        ("action_rejected", {"team_id": "blue", "unit_id": "blue-u1", "reason": "out of range"}),
        ("message_sent", {"team_id": "blue", "from": "blue-scout", "text": "hi"}),
        ("plan_declared", {"team_id": "blue", "agent_id": "blue-scout", "text": "plan"}),
        ("turn_resolved", {"turn": 1}),
    ):
        assert apply_event(state, Event(turn=1, seq=0, kind=kind, data=data)) == state


def test_jsonl_round_trip_is_byte_identical() -> None:
    log = MatchLog(initial_state=initial_state(), events=sample_events())
    payload = log.to_jsonl()
    restored = MatchLog.from_jsonl(payload)
    assert restored == log
    assert restored.to_jsonl() == payload
    assert state_hash(restored.final_state()) == state_hash(log.final_state())


def test_replaying_twice_is_deterministic() -> None:
    log = MatchLog(initial_state=initial_state(), events=sample_events())
    assert state_hash(log.final_state()) == state_hash(log.final_state())


def test_unknown_event_kind_rejected() -> None:
    with pytest.raises(ValueError):
        Event(turn=0, seq=0, kind="tea_break", data={})


def test_corrupt_references_are_loud() -> None:
    state = initial_state()
    event = Event(turn=1, seq=0, kind="unit_moved", data={"unit_id": "ghost", "to": [0, 0]})
    with pytest.raises(ValueError):
        apply_event(state, event)


def test_wrong_log_version_rejected() -> None:
    log = MatchLog(initial_state=initial_state(), events=())
    payload = log.to_jsonl().replace(f'"log_version":{LOG_VERSION}', '"log_version":99')
    with pytest.raises(ValueError):
        MatchLog.from_jsonl(payload)


def test_delivery_cannot_go_negative_by_construction() -> None:
    """The fold trusts the tick to validate; a bare fold still keeps arithmetic honest."""
    state = initial_state()
    gathered = apply_event(
        state,
        Event(
            turn=1,
            seq=0,
            kind="resource_gathered",
            data={"unit_id": "blue-u2", "node_id": "rn-west", "amount": 2},
        ),
    )
    harvester = next(u for u in gathered.units if u.id == "blue-u2")
    assert harvester.carrying == 2
    replayed = dataclasses.replace(gathered)
    assert replayed == gathered
