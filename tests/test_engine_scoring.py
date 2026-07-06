"""Wave-2 acceptance tests for dual scoring (plan task t7).

Criteria under test:

* every finished match yields BOTH an outcome score and a cooperation score,
  computed from a canned log alone (the function takes nothing else);
* the per-signal breakdown is present, weighted as documented, and legible —
  a coordinated team outscores a hero-ball team on cooperation.
"""

from __future__ import annotations

import dataclasses

from league.engine.events import MatchLog
from league.engine.scenario import get_scenario, instantiate
from league.engine.scoring import WEIGHTS, score_match
from league.engine.state import AgentSlot
from league.engine.tick import resolve_turn, start_match

SCENARIO = get_scenario("skirmish-1")


def _roster(team: str, model: str = "colleague/qwen") -> tuple[AgentSlot, ...]:
    return (
        AgentSlot(id=f"{team}-scout", model=model, role="scout"),
        AgentSlot(id=f"{team}-harvester", model=model, role="harvester"),
        AgentSlot(id=f"{team}-defender", model=model, role="defender"),
    )


def _play_match() -> MatchLog:
    """Script a short match: blue coordinates, red hero-balls, clock runs out."""
    initial = instantiate(
        SCENARIO,
        match_id="m-score",
        seed=5,
        mode="competitive",
        teams=(
            ("blue", "Blue Foundry", _roster("blue")),
            ("red", "Red Relay", _roster("red", model="claude-sonnet-5")),
        ),
    )
    state, events = start_match(initial)
    all_events = list(events)

    turn_orders = [
        {
            "blue": {
                "plan": "harvester relays supply; scout screens; defender takes east",
                "messages": [{"from": "blue-scout", "text": "east lane clear"}],
                "actions": [
                    {"unit_id": "blue-u1", "action": "move", "to": [3, 1]},
                    {"unit_id": "blue-u2", "action": "move", "to": [1, 2]},
                    {"unit_id": "blue-u3", "action": "move", "to": [2, 2]},
                ],
            },
            "red": {
                "actions": [
                    {"unit_id": "red-u1", "action": "move", "to": [9, 8]},
                    {"unit_id": "red-u1", "action": "move", "to": [8, 8]},  # rejected
                ]
            },
        },
        {
            "blue": {
                "messages": [{"from": "blue-harvester", "text": "two more turns to node"}],
                "actions": [
                    {"unit_id": "blue-u1", "action": "move", "to": [6, 1]},
                    {"unit_id": "blue-u2", "action": "move", "to": [0, 3]},
                    {"unit_id": "blue-u3", "action": "move", "to": [4, 3]},
                ],
            },
            "red": {"actions": [{"unit_id": "red-u1", "action": "move", "to": [99, 8]}]},
        },
        {
            "blue": {
                "actions": [
                    {"unit_id": "blue-u1", "action": "move", "to": [9, 2]},
                    {"unit_id": "blue-u2", "action": "move", "to": [0, 5]},
                    {"unit_id": "blue-u3", "action": "move", "to": [6, 5]},
                ]
            },
            "red": {},
        },
        {
            "blue": {
                "actions": [
                    {"unit_id": "blue-u1", "action": "hold"},
                    {"unit_id": "blue-u2", "action": "gather"},
                    {"unit_id": "blue-u3", "action": "hold"},
                ]
            },
            "red": {},
        },
    ]
    for orders in turn_orders:
        state, events = resolve_turn(state, SCENARIO, orders, seq_start=len(all_events))
        all_events.extend(events)

    # Fast-forward the clock so the final tick closes the match.
    state = dataclasses.replace(state, turn=state.turn_limit - 1)
    closing = dataclasses.replace(
        MatchLog(initial_state=initial, events=tuple(all_events)).final_state(),
        turn=state.turn_limit - 1,
    )
    _, events = resolve_turn(closing, SCENARIO, {}, seq_start=len(all_events))
    all_events.extend(events)
    return MatchLog(initial_state=initial, events=tuple(all_events))


def test_both_scores_present_for_every_team_from_log_alone() -> None:
    log = _play_match()
    report = score_match(log)
    assert report["winner"] is not None
    for team in ("blue", "red"):
        assert set(report["outcome"][team]) == {"total", "missions", "control", "resources"}
        assert "score" in report["cooperation"][team]
        signals = report["cooperation"][team]["signals"]
        assert set(signals) == set(WEIGHTS)
        for value in signals.values():
            assert 0.0 <= value <= 1.0


def test_weights_are_documented_and_sum_to_one() -> None:
    assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9


def test_coordination_is_legible_in_the_score() -> None:
    """Blue (plans, messages, full-roster delegation) must outscore red (hero-ball)."""
    report = score_match(_play_match())
    blue = report["cooperation"]["blue"]
    red = report["cooperation"]["red"]
    assert blue["score"] > red["score"]
    assert blue["signals"]["delegation_spread"] > red["signals"]["delegation_spread"]
    assert blue["signals"]["communication"] > red["signals"]["communication"]
    assert blue["signals"]["plan_coherence"] > red["signals"]["plan_coherence"]
    assert blue["signals"]["discipline"] > red["signals"]["discipline"]


def test_outcome_reflects_the_board() -> None:
    log = _play_match()
    report = score_match(log)
    final = log.final_state()
    blue_cp = 2 * sum(1 for c in final.control_points if c.owner == "blue")
    assert report["outcome"]["blue"]["control"] == blue_cp
    assert report["outcome"]["blue"]["total"] >= report["outcome"]["blue"]["control"]
    assert report["turns_played"] == final.turn
