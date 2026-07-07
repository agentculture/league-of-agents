"""Acceptance tests for the legal-actions surface (plan task t1).

Criteria under test:

* ``legal_actions`` is pure — derived from state + scenario only, sorted,
  no RNG — and reports move targets in range, gather/deliver/hold
  applicability per unit.
* A beyond-move-range target (the exact mistake that burned 19 of 53 orders
  in the season-0 coordination playtest — see
  docs/playtests/season-0/coordination.report.md) is absent from the
  reported move targets.
"""

from __future__ import annotations

import dataclasses

import pytest

from league.engine.legal import legal_actions
from league.engine.scenario import get_scenario, instantiate
from league.engine.state import AgentSlot, MatchState
from league.engine.tick import resolve_turn, start_match

SCENARIO = get_scenario("skirmish-1")


def _roster(team: str, model: str = "colleague/qwen") -> tuple[AgentSlot, ...]:
    return (
        AgentSlot(id=f"{team}-scout", model=model, role="scout"),
        AgentSlot(id=f"{team}-harvester", model=model, role="harvester"),
        AgentSlot(id=f"{team}-defender", model=model, role="defender"),
    )


def active_match(**overrides) -> MatchState:
    state = instantiate(
        SCENARIO,
        match_id="m-legal",
        seed=99,
        mode="competitive",
        teams=(
            ("blue", "Blue Foundry", _roster("blue")),
            ("red", "Red Relay", _roster("red", model="claude-sonnet-5")),
        ),
    )
    state, _ = start_match(state)
    return dataclasses.replace(state, **overrides) if overrides else state


def _replace_unit(state: MatchState, unit_id: str, **fields) -> MatchState:
    units = tuple(dataclasses.replace(u, **fields) if u.id == unit_id else u for u in state.units)
    return dataclasses.replace(state, units=units)


def test_move_targets_stay_within_role_move_stat_and_exclude_current_cell() -> None:
    state = active_match()
    # blue-u1 is the scout (move=3), spawned at (0, 0).
    actions = legal_actions(state, SCENARIO, "blue-u1")
    moves = actions["move"]

    assert list(moves) == sorted(moves)  # deterministic, sorted
    assert [0, 0] not in moves  # never the current cell
    for x, y in moves:
        assert abs(x - 0) + abs(y - 0) <= 3
        assert 0 <= x < state.grid_width
        assert 0 <= y < state.grid_height


def test_beyond_move_range_target_is_absent_from_legal_actions() -> None:
    """The exact miss that cost the swarm 10 rejected orders in playtest 2."""
    state = active_match()
    actions = legal_actions(state, SCENARIO, "blue-u1")  # scout, move=3, at (0, 0)
    # Manhattan distance from (0, 0) to (4, 0) is 4 — one past the scout's
    # move=3 stat. tick.py rejects this with "target beyond this role's move
    # range"; legal_actions must never have offered it in the first place.
    assert [4, 0] not in actions["move"]
    # A legal target at exactly the move stat is present, for contrast.
    assert [3, 0] in actions["move"]


def test_move_targets_are_deterministic_across_repeated_calls() -> None:
    state = active_match()
    first = legal_actions(state, SCENARIO, "red-u2")
    second = legal_actions(state, SCENARIO, "red-u2")
    assert first == second


def test_gather_true_on_resource_node_below_carry_capacity() -> None:
    state = active_match()
    # rn-west sits at (0, 5); move the scout there with capacity to spare.
    state = _replace_unit(state, "blue-u1", pos=(0, 5), carrying=0)
    actions = legal_actions(state, SCENARIO, "blue-u1")
    assert actions["gather"] is True


def test_gather_false_when_carrying_at_capacity() -> None:
    state = active_match()
    state = _replace_unit(state, "blue-u1", pos=(0, 5), carrying=1)  # scout carry=1
    actions = legal_actions(state, SCENARIO, "blue-u1")
    assert actions["gather"] is False


def test_gather_false_off_a_resource_node() -> None:
    state = active_match()
    actions = legal_actions(state, SCENARIO, "blue-u1")  # spawns at (0, 0), no node
    assert actions["gather"] is False


def test_gather_false_when_node_is_exhausted() -> None:
    state = active_match()
    nodes = tuple(
        dataclasses.replace(n, remaining=0) if n.id == "rn-west" else n
        for n in state.resource_nodes
    )
    state = dataclasses.replace(state, resource_nodes=nodes)
    state = _replace_unit(state, "blue-u1", pos=(0, 5), carrying=0)
    actions = legal_actions(state, SCENARIO, "blue-u1")
    assert actions["gather"] is False


def test_deliver_true_on_open_delivery_square_while_carrying() -> None:
    state = active_match()
    # ms-supply (deliver) sits at (6, 5).
    state = _replace_unit(state, "blue-u2", pos=(6, 5), carrying=2)
    actions = legal_actions(state, SCENARIO, "blue-u2")
    assert actions["deliver"] is True


def test_deliver_false_when_not_carrying_anything() -> None:
    state = active_match()
    state = _replace_unit(state, "blue-u2", pos=(6, 5), carrying=0)
    actions = legal_actions(state, SCENARIO, "blue-u2")
    assert actions["deliver"] is False


def test_deliver_false_off_the_delivery_square() -> None:
    state = active_match()
    state = _replace_unit(state, "blue-u2", pos=(6, 4), carrying=3)
    actions = legal_actions(state, SCENARIO, "blue-u2")
    assert actions["deliver"] is False


def _with_completed_supply_mission(state: MatchState) -> MatchState:
    missions = tuple(
        (
            dataclasses.replace(m, status="completed", completed_by=("blue",), completed_turn=1)
            if m.id == "ms-supply"
            else m
        )
        for m in state.missions
    )
    return dataclasses.replace(state, missions=missions)


def test_deliver_true_once_the_mission_is_completed_if_still_carrying() -> None:
    """resolve_turn accepts a deliver on a completed mission's square (the
    delivery still banks resource points) — legal_actions must agree,
    regression for Qodo comment 3534476060."""
    state = active_match()
    state = _replace_unit(state, "blue-u2", pos=(6, 5), carrying=2)
    state = _with_completed_supply_mission(state)
    actions = legal_actions(state, SCENARIO, "blue-u2")
    assert actions["deliver"] is True


def test_deliver_legality_agrees_with_resolve_turn_after_mission_completion() -> None:
    """Cross-check legal_actions() against resolve_turn()'s own validation:
    a carrying unit on a *completed* deliver mission's square must be
    reported legal, and resolve_turn must accept it with no rejection."""
    state = active_match()
    state = _replace_unit(state, "blue-u2", pos=(6, 5), carrying=2)
    state = _with_completed_supply_mission(state)

    actions = legal_actions(state, SCENARIO, "blue-u2")
    assert actions["deliver"] is True

    _, events = resolve_turn(
        state, SCENARIO, {"blue": {"actions": [{"unit_id": "blue-u2", "action": "deliver"}]}}
    )
    assert not [e for e in events if e.kind == "action_rejected"]
    assert any(e.kind == "resource_delivered" for e in events)


def test_deliver_legality_agrees_with_resolve_turn_when_not_carrying() -> None:
    """Inverse of the above: a non-carrying unit on the same completed
    mission's square is illegal in both legal_actions() and resolve_turn()."""
    state = active_match()
    state = _replace_unit(state, "blue-u2", pos=(6, 5), carrying=0)
    state = _with_completed_supply_mission(state)

    actions = legal_actions(state, SCENARIO, "blue-u2")
    assert actions["deliver"] is False

    _, events = resolve_turn(
        state, SCENARIO, {"blue": {"actions": [{"unit_id": "blue-u2", "action": "deliver"}]}}
    )
    rejected = [e for e in events if e.kind == "action_rejected"]
    assert [e.data["reason"] for e in rejected] == ["nothing to deliver"]


def test_hold_is_always_legal() -> None:
    state = active_match()
    for unit in state.units:
        assert legal_actions(state, SCENARIO, unit.id)["hold"] is True


def test_unknown_unit_raises_value_error() -> None:
    state = active_match()
    with pytest.raises(ValueError):
        legal_actions(state, SCENARIO, "ghost-u9")
