"""Wave-1 acceptance tests for the v0 scenario (plan task t3).

Criteria under test:

* ``skirmish-1`` loads by id with at least 3 control points, 2 missions, and
  resource nodes, for two-team or team-vs-environment play;
* scenario parameters force tradeoffs — the solo-run arithmetic (computed from
  the scenario's own numbers, not hard-coded) exceeds the turn limit for every
  role, so no single unit can do it all (spec c16);
* cooperative and competitive variants share one definition and one engine
  path (spec c18/h11).
"""

from __future__ import annotations

import dataclasses
import math

import pytest

from league.engine.scenario import Scenario, get_scenario, instantiate, scenario_ids
from league.engine.state import AgentSlot, state_hash


def _roster(team: str, model: str = "colleague/qwen") -> tuple[AgentSlot, ...]:
    return (
        AgentSlot(id=f"{team}-scout", model=model, role="scout"),
        AgentSlot(id=f"{team}-harvester", model=model, role="harvester"),
        AgentSlot(id=f"{team}-defender", model=model, role="defender"),
    )


def test_loads_by_id_with_required_furniture() -> None:
    scenario = get_scenario("skirmish-1")
    assert scenario.id in scenario_ids()
    assert len(scenario.control_points) >= 3
    assert len(scenario.missions) >= 2
    assert len(scenario.resource_nodes) >= 1
    assert set(scenario.modes) == {"cooperative", "competitive"}


def test_unknown_scenario_is_a_loud_error() -> None:
    with pytest.raises(ValueError, match="skirmish-1"):
        get_scenario("does-not-exist")


def test_competitive_instantiation_is_deterministic() -> None:
    scenario = get_scenario("skirmish-1")
    teams = (
        ("blue", "Blue Foundry", _roster("blue")),
        ("red", "Red Relay", _roster("red", model="claude-sonnet-5")),
    )
    a = instantiate(scenario, match_id="m-1", seed=7, mode="competitive", teams=teams)
    b = instantiate(scenario, match_id="m-1", seed=7, mode="competitive", teams=teams)
    assert state_hash(a) == state_hash(b)
    assert a.status == "pending"
    assert a.turn == 0
    assert len(a.units) == 2 * len(scenario.unit_roles)
    blue_units = [u for u in a.units if u.team_id == "blue"]
    assert [u.pos for u in blue_units] == list(scenario.spawns[0])
    assert {u.agent_id for u in blue_units} == {a.id for a in _roster("blue")}


def test_cooperative_uses_the_same_definition() -> None:
    scenario = get_scenario("skirmish-1")
    solo = instantiate(
        scenario,
        match_id="m-coop",
        seed=7,
        mode="cooperative",
        teams=(("blue", "Blue Foundry", _roster("blue")),),
    )
    assert solo.mode == "cooperative"
    assert len(solo.teams) == 1
    assert solo.scenario_id == "skirmish-1"
    # Same furniture, same engine path — no forked scenario for the mode.
    assert solo.control_points == scenario.control_points
    assert solo.missions == scenario.missions


def test_team_count_and_roster_validation() -> None:
    scenario = get_scenario("skirmish-1")
    with pytest.raises(ValueError, match="exactly 2"):
        instantiate(
            scenario,
            match_id="m",
            seed=1,
            mode="competitive",
            teams=(("blue", "Blue", _roster("blue")),),
        )
    bad_roster = (
        AgentSlot(id="x-1", model="m", role="scout"),
        AgentSlot(id="x-2", model="m", role="scout"),
        AgentSlot(id="x-3", model="m", role="scout"),
    )
    with pytest.raises(ValueError, match="roster roles"):
        instantiate(
            scenario,
            match_id="m",
            seed=1,
            mode="cooperative",
            teams=(("blue", "Blue", bad_roster),),
        )
    competitive_only = dataclasses.replace(scenario, modes=("competitive",))
    with pytest.raises(ValueError, match="does not support"):
        instantiate(
            competitive_only,
            match_id="m",
            seed=1,
            mode="cooperative",
            teams=(("blue", "Blue", _roster("blue")),),
        )


def _manhattan(a: tuple[int, int], b: tuple[int, int]) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def _solo_lower_bound(scenario: Scenario, move: int, carry: int) -> int:
    """A conservative floor on turns for ONE unit to do everything.

    Ignores spawn travel and contention entirely — the real solo run is
    strictly slower, so `bound > turn_limit` proves impossibility.
    """
    total = 0
    deliver = next(m for m in scenario.missions if m.kind == "deliver")
    node_dist = min(_manhattan(n.pos, deliver.pos) for n in scenario.resource_nodes)
    trips = math.ceil(deliver.amount / carry)
    total += trips * (2 * math.ceil(node_dist / move) + 2)  # travel + gather + deliver

    hold = next(m for m in scenario.missions if m.kind == "hold")
    total += math.ceil(_manhattan(deliver.pos, hold.pos) / move) + hold.amount

    # Capture-and-hold every remaining control point, travelling between them.
    prev = hold.pos
    for cp in scenario.control_points:
        if cp.pos == hold.pos:
            continue
        total += math.ceil(_manhattan(prev, cp.pos) / move) + scenario.capture_hold_turns
        prev = cp.pos
    return total


def test_tradeoffs_are_forced_by_arithmetic() -> None:
    """No role's solo run fits the turn limit; holding all CPs needs bodies."""
    scenario = get_scenario("skirmish-1")
    # One unit occupies one square: holding every control point simultaneously
    # already requires more units than one.
    assert len(scenario.control_points) > 1

    bounds = {
        role: _solo_lower_bound(scenario, stats.move, stats.carry)
        for role, stats in scenario.role_stats
    }
    assert min(bounds.values()) > scenario.turn_limit, (
        f"a solo unit could finish everything within the turn limit: {bounds} "
        f"vs limit {scenario.turn_limit} — retune the scenario"
    )
