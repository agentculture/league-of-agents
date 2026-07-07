"""Acceptance tests for per-role vision (cycle-3 plan task t1, spec c12/h12).

Criteria under test:

* vision is a **pure function of (state, scenario)**: no RNG (the package-wide
  AST import ban in ``test_engine_state.py`` covers ``league/engine/vision.py``
  automatically), identical inputs yield identical visibility, and the input
  state is never mutated;
* the **scout sees strictly farther** than harvester and defender in skirmish
  scenarios — visibility as the specialization axis issue #1 names;
* team visibility is the **union over living units** (dead units see nothing),
  and the team-view filters expose exactly the units / resource nodes /
  control points inside that union — the shape fogged briefings, the knowledge
  fold, and the replay overlay will consume.
"""

from __future__ import annotations

import dataclasses

import pytest

from league.engine.scenario import get_scenario, instantiate
from league.engine.state import AgentSlot, state_to_json
from league.engine.vision import (
    TeamView,
    team_view,
    team_visible_cells,
    visible_cells,
    visible_control_points,
    visible_resource_nodes,
    visible_units,
)


def _roster(team: str, model: str = "colleague/qwen") -> tuple[AgentSlot, ...]:
    return (
        AgentSlot(id=f"{team}-scout", model=model, role="scout"),
        AgentSlot(id=f"{team}-harvester", model=model, role="harvester"),
        AgentSlot(id=f"{team}-defender", model=model, role="defender"),
    )


def _competitive_state():
    scenario = get_scenario("skirmish-1")
    state = instantiate(
        scenario,
        match_id="m-vision",
        seed=7,
        mode="competitive",
        teams=(
            ("blue", "Blue Foundry", _roster("blue")),
            ("red", "Red Relay", _roster("red", model="claude-sonnet-5")),
        ),
    )
    return scenario, state


def _unit(state, unit_id: str):
    return next(u for u in state.units if u.id == unit_id)


def _move_unit(state, unit_id: str, pos: tuple[int, int]):
    """Reposition one unit via dataclasses.replace — state stays immutable."""
    units = tuple(dataclasses.replace(u, pos=pos) if u.id == unit_id else u for u in state.units)
    return dataclasses.replace(state, units=units)


def _manhattan(a: tuple[int, int], b: tuple[int, int]) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


# --- vision radius is a role stat; the scout is the eyes -----------------


def test_vision_is_a_role_stat_and_scout_sees_strictly_farther() -> None:
    scenario = get_scenario("skirmish-1")
    scout = scenario.stats_for("scout").vision
    harvester = scenario.stats_for("harvester").vision
    defender = scenario.stats_for("defender").vision
    assert scout > harvester, "scout must out-see the harvester (specialization axis)"
    assert scout > defender, "scout must out-see the defender (specialization axis)"
    assert min(scout, harvester, defender) >= 1, "every role sees at least its neighbours"


def test_scout_visibility_is_a_strict_superset_from_the_same_cell() -> None:
    """Same position, different role: the scout's view strictly contains the others'."""
    scenario, state = _competitive_state()
    center = (6, 5)
    state = _move_unit(state, "blue-u1", center)  # scout
    state = _move_unit(state, "blue-u2", center)  # harvester
    state = _move_unit(state, "blue-u3", center)  # defender
    scout_view = visible_cells(state, scenario, "blue-u1")
    for other in ("blue-u2", "blue-u3"):
        other_view = visible_cells(state, scenario, other)
        assert other_view < scout_view, f"{other} should see strictly less than the scout"


# --- visible_cells: Manhattan radius, grid-clipped ------------------------


def test_visible_cells_is_exactly_the_manhattan_ball_clipped_to_grid() -> None:
    scenario, state = _competitive_state()
    state = _move_unit(state, "blue-u3", (6, 5))  # defender, mid-board
    unit = _unit(state, "blue-u3")
    radius = scenario.stats_for("defender").vision
    expected = frozenset(
        (x, y)
        for x in range(state.grid_width)
        for y in range(state.grid_height)
        if _manhattan((x, y), unit.pos) <= radius
    )
    assert visible_cells(state, scenario, "blue-u3") == expected
    assert unit.pos in expected, "a unit always sees its own cell"


def test_visible_cells_clip_at_the_grid_edge() -> None:
    scenario, state = _competitive_state()
    # Blue scout spawns at (0,0): the Manhattan ball must be quarter-clipped.
    cells = visible_cells(state, scenario, "blue-u1")
    radius = scenario.stats_for("scout").vision
    assert all(0 <= x < state.grid_width and 0 <= y < state.grid_height for x, y in cells)
    assert all(_manhattan((x, y), (0, 0)) <= radius for x, y in cells)
    full_ball = (radius * radius) + ((radius + 1) * (radius + 1))
    assert len(cells) < full_ball, "corner vision must be smaller than the open-field ball"


# --- purity: no RNG, identical inputs -> identical visibility -------------


def test_vision_is_pure_and_deterministic() -> None:
    scenario, state = _competitive_state()
    before = state_to_json(state)
    first = visible_cells(state, scenario, "blue-u1")
    second = visible_cells(state, scenario, "blue-u1")
    assert first == second
    # A freshly instantiated identical state yields identical visibility.
    _, twin = _competitive_state()
    assert visible_cells(twin, scenario, "blue-u1") == first
    assert team_visible_cells(twin, scenario, "blue") == team_visible_cells(state, scenario, "blue")
    assert state_to_json(state) == before, "vision must never mutate the state"


# --- team union over living units -----------------------------------------


def test_team_visible_cells_is_the_union_over_living_units() -> None:
    scenario, state = _competitive_state()
    per_unit = [
        visible_cells(state, scenario, u.id) for u in state.units if u.team_id == "blue" and u.alive
    ]
    assert team_visible_cells(state, scenario, "blue") == frozenset().union(*per_unit)


def test_dead_units_see_nothing_and_drop_out_of_the_union() -> None:
    scenario, state = _competitive_state()
    units = tuple(
        dataclasses.replace(u, alive=False) if u.id == "blue-u1" else u for u in state.units
    )
    fogged = dataclasses.replace(state, units=units)
    assert visible_cells(fogged, scenario, "blue-u1") == frozenset()
    survivors = [
        visible_cells(fogged, scenario, u.id)
        for u in fogged.units
        if u.team_id == "blue" and u.alive
    ]
    assert team_visible_cells(fogged, scenario, "blue") == frozenset().union(*survivors)


# --- filtering state to what a team can see -------------------------------


def test_own_units_are_always_known_and_enemies_only_inside_vision() -> None:
    scenario, state = _competitive_state()
    # At spawn the sides are across the board from each other — out of sight.
    at_spawn = visible_units(state, scenario, "blue")
    assert [u.id for u in at_spawn] == ["blue-u1", "blue-u2", "blue-u3"]
    # March the red scout into the blue scout's radius: now blue sees it too.
    contact = _move_unit(state, "red-u1", (2, 2))
    seen = visible_units(contact, scenario, "blue")
    assert [u.id for u in seen] == ["blue-u1", "blue-u2", "blue-u3", "red-u1"]
    # ... and symmetrically red (vision is per-team, not global).
    assert "blue-u1" in {u.id for u in visible_units(contact, scenario, "red")}


def test_nodes_and_control_points_appear_only_inside_team_vision() -> None:
    scenario, state = _competitive_state()
    # At spawn (radii 4/2/2) nothing on skirmish-1 is inside blue's vision:
    # rn-west (0,5) is 5 from the scout at (0,0), 4 from the defender at (0,1).
    assert visible_resource_nodes(state, scenario, "blue") == ()
    assert visible_control_points(state, scenario, "blue") == ()
    # A scout at (2,6) sees rn-west (0,5) and cp-west (3,8), not cp-center (6,5).
    scouted = _move_unit(state, "blue-u1", (2, 6))
    assert [n.id for n in visible_resource_nodes(scouted, scenario, "blue")] == ["rn-west"]
    assert [c.id for c in visible_control_points(scouted, scenario, "blue")] == ["cp-west"]


def test_team_view_bundles_the_filters_into_one_consumable_shape() -> None:
    scenario, state = _competitive_state()
    scouted = _move_unit(state, "blue-u1", (2, 6))
    view = team_view(scouted, scenario, "blue")
    assert isinstance(view, TeamView)
    assert view.team_id == "blue"
    assert view.cells == team_visible_cells(scouted, scenario, "blue")
    assert view.units == visible_units(scouted, scenario, "blue")
    assert view.resource_nodes == visible_resource_nodes(scouted, scenario, "blue")
    assert view.control_points == visible_control_points(scouted, scenario, "blue")


# --- loud errors, never silent defaults ------------------------------------


def test_unknown_unit_and_team_are_loud_errors() -> None:
    scenario, state = _competitive_state()
    with pytest.raises(ValueError, match="unknown unit"):
        visible_cells(state, scenario, "ghost-u9")
    with pytest.raises(ValueError, match="unknown team"):
        team_visible_cells(state, scenario, "ghosts")
