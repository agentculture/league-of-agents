"""Acceptance tests for the continuous scenario registry (plan C7-t6, spec c10/h3).

These are the merge gate for ``league/engine/continuous/scenario.py``. Written
before the implementation (TDD), they pin the two acceptance criteria:

1. A hand-authored continuous scenario (``c-skirmish-1``) ships with a real
   coordination-pressure argument: a solo unit doing the race THEN the economy
   serially cannot fit the time limit, computed from the scenario's own role
   data (never hard-coded), mirroring the grid scenarios'
   ``test_tradeoffs_are_forced_by_arithmetic`` style.
2. The scenario registry serves both lanes without ambiguity: a continuous
   scenario is distinguishable by DATA (its id prefix), never by special-
   casing — no id in the continuous registry ever collides with a grid id, and
   the discipline (``c-`` prefix) is enforced both ways.
"""

from __future__ import annotations

import dataclasses

import pytest

from league.engine.continuous.legal import move_duration
from league.engine.continuous.roles import CRoleStats, build_role_table
from league.engine.continuous.scenario import (
    CONTINUOUS_ID_PREFIX,
    CScenario,
    cscenario_ids,
    get_cscenario,
    instantiate,
)
from league.engine.continuous.space import dist_sq
from league.engine.continuous.state import CAgentSlot, cstate_hash
from league.engine.scenario import scenario_ids as grid_scenario_ids


def _slot(uid: str, role: str, model: str = "colleague/qwen") -> CAgentSlot:
    return CAgentSlot(id=uid, model=model, role=role)


def _roster(team: str, model: str = "colleague/qwen") -> tuple[CAgentSlot, ...]:
    return (
        _slot(f"{team}-defender", "defender", model),
        _slot(f"{team}-harvester", "harvester", model),
    )


# --------------------------------------------------------------------------- #
# Criterion 2 — the registry serves both lanes without ambiguity
# --------------------------------------------------------------------------- #
def test_c_skirmish_1_loads_by_id_with_required_furniture() -> None:
    scenario = get_cscenario("c-skirmish-1")
    assert scenario.id in cscenario_ids()
    assert scenario.id.startswith(CONTINUOUS_ID_PREFIX)
    assert len(scenario.control_points) >= 1
    assert len(scenario.missions) >= 2
    assert len(scenario.resource_nodes) >= 1
    assert set(scenario.modes) == {"cooperative", "competitive"}
    assert sorted(scenario.unit_roles) == ["defender", "harvester"]


def test_unknown_scenario_is_a_loud_error() -> None:
    with pytest.raises(ValueError, match="c-skirmish-1"):
        get_cscenario("does-not-exist")


def test_every_continuous_id_carries_the_prefix() -> None:
    """The shared discipline (spec c10/h3): every continuous scenario id starts
    with ``c-`` — the data-level marker that makes a continuous scenario
    distinguishable from a grid one without any special-casing."""
    for cid in cscenario_ids():
        assert cid.startswith(CONTINUOUS_ID_PREFIX)


def test_no_id_collides_between_grid_and_continuous_registries() -> None:
    """The registry serves both lanes without ambiguity: the two id spaces are
    disjoint, and no grid id accidentally carries the continuous prefix."""
    grid_ids = set(grid_scenario_ids())
    continuous_ids = set(cscenario_ids())
    assert grid_ids.isdisjoint(continuous_ids)
    assert not any(gid.startswith(CONTINUOUS_ID_PREFIX) for gid in grid_ids)


def test_a_non_prefixed_id_is_refused_by_construction() -> None:
    """A CScenario is distinguishable by DATA — the id discipline is enforced
    on the dataclass itself, not left to registry convention alone."""
    scenario = get_cscenario("c-skirmish-1")
    with pytest.raises(ValueError, match="c-"):
        dataclasses.replace(scenario, id="skirmish-1")


# --------------------------------------------------------------------------- #
# instantiate(): mirrors the grid's instantiate contract
# --------------------------------------------------------------------------- #
def test_competitive_instantiation_is_deterministic() -> None:
    scenario = get_cscenario("c-skirmish-1")
    teams = (
        ("blue", "Blue Foundry", _roster("blue")),
        ("red", "Red Relay", _roster("red", model="claude-sonnet-5")),
    )
    a = instantiate(scenario, match_id="m-1", seed=7, mode="competitive", teams=teams)
    b = instantiate(scenario, match_id="m-1", seed=7, mode="competitive", teams=teams)
    assert cstate_hash(a) == cstate_hash(b)
    assert a.status == "pending"
    assert a.clock == 0
    assert a.time_limit == scenario.time_limit
    assert len(a.units) == 2 * len(scenario.unit_roles)
    blue_units = [u for u in a.units if u.team_id == "blue"]
    assert [u.pos for u in blue_units] == list(scenario.spawns[0])
    assert {u.agent_id for u in blue_units} == {s.id for s in _roster("blue")}


def test_cooperative_uses_the_same_definition() -> None:
    scenario = get_cscenario("c-skirmish-1")
    solo = instantiate(
        scenario,
        match_id="m-coop",
        seed=7,
        mode="cooperative",
        teams=(("blue", "Blue Foundry", _roster("blue")),),
    )
    assert solo.mode == "cooperative"
    assert len(solo.teams) == 1
    assert solo.scenario_id == "c-skirmish-1"
    assert solo.control_points == scenario.control_points
    assert solo.missions == scenario.missions


def test_team_count_and_roster_validation() -> None:
    scenario = get_cscenario("c-skirmish-1")
    with pytest.raises(ValueError, match="exactly 2"):
        instantiate(
            scenario,
            match_id="m",
            seed=1,
            mode="competitive",
            teams=(("blue", "Blue", _roster("blue")),),
        )
    bad_roster = (_slot("x-1", "scout"), _slot("x-2", "scout"))
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


# --------------------------------------------------------------------------- #
# Criterion 1 — coordination pressure proven by arithmetic (grid-scenario style)
# --------------------------------------------------------------------------- #
def _solo_lower_bound(scenario: CScenario) -> int:
    """A conservative floor on in-game time for ONE unit (the defender — the
    role this scenario's race is staged around, now that scout is forbidden
    from taking posts at all) to win the race THEN run the economy, entirely
    serially: move to the post, take it, travel to the resource node, gather,
    deliver. Ignores return travel and contention entirely — the real solo run
    is strictly slower, so ``bound > time_limit`` proves impossibility.
    Computed from the scenario's own spawns/positions/role data, never
    hard-coded.
    """
    defender = scenario.stats_for("defender")
    cp = scenario.control_points[0]
    node = scenario.resource_nodes[0]
    blue_defender_spawn = scenario.spawns[0][scenario.unit_roles.index("defender")]

    move_to_post = move_duration(dist_sq(blue_defender_spawn, cp.pos), defender.move_rate_mu)
    take = defender.take_post_duration
    move_to_node = move_duration(dist_sq(cp.pos, node.pos), defender.move_rate_mu)
    gather = defender.gather_duration
    deliver = defender.deliver_duration
    return move_to_post + take + move_to_node + gather + deliver


def test_solo_unit_cannot_win_the_race_and_run_the_economy_in_time() -> None:
    """No single unit can both win the post race and run the economy within
    the time limit — the tradeoff is forced by arithmetic, not narrative."""
    scenario = get_cscenario("c-skirmish-1")
    bound = _solo_lower_bound(scenario)
    assert bound > scenario.time_limit, (
        f"a solo unit could finish everything within the time limit: {bound} "
        f"vs limit {scenario.time_limit} — retune the scenario"
    )


def test_role_table_is_scenario_declared_data() -> None:
    """The role table is DATA on the scenario (roles.build_role_table's
    override mechanism), not a hard-coded resolver constant — a scenario could
    field a different table without any code change."""
    scenario = get_cscenario("c-skirmish-1")
    table = dict(scenario.role_table)
    assert isinstance(table["scout"], CRoleStats)
    assert isinstance(table["harvester"], CRoleStats)
    # role_table is exactly what build_role_table() produces — no bespoke
    # inline table hard-coded on the scenario itself.
    assert scenario.role_table == build_role_table()
