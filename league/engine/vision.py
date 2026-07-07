"""Per-role vision — the pure visibility substrate fog of war builds on.

Everything here is a **pure function of (state, scenario)**: no RNG, no clock
(the package-wide AST import ban applies), no mutation — identical inputs
always yield identical visibility. Vision uses the **Manhattan radius**, the
same metric movement resolves with, so "sees x tiles" and "moves x tiles"
measure the same distance.

This module is the substrate only: nothing in the tick, briefings, or scoring
reads it yet. Downstream increments consume the shapes exported here —
``visible_cells`` / ``team_visible_cells`` for fogged briefings and the
per-team knowledge fold, and ``TeamView`` (units / resource nodes / control
points filtered to a team's vision) for the replay overlay.

Semantics:

* a unit sees every in-grid cell within its role's ``vision`` radius of its
  position; a **dead unit sees nothing**;
* a team sees the **union over its living units**;
* a team always knows its **own units** (they report in), and sees another
  team's unit, a resource node, or a control point only while it stands on a
  visible cell.
"""

from __future__ import annotations

from dataclasses import dataclass

from league.engine.scenario import Scenario
from league.engine.state import ControlPoint, MatchState, ResourceNode, Unit


def _unit_by_id(state: MatchState, unit_id: str) -> Unit:
    for unit in state.units:
        if unit.id == unit_id:
            return unit
    raise ValueError(f"unknown unit {unit_id!r} in match {state.match_id!r}")


def visible_cells(
    state: MatchState, scenario: Scenario, unit_id: str
) -> frozenset[tuple[int, int]]:
    """All grid cells ``unit_id`` can see: the Manhattan ball, grid-clipped.

    A dead unit sees nothing (empty frozenset). An unknown unit id is a loud
    ``ValueError`` — never a silent empty view.
    """
    unit = _unit_by_id(state, unit_id)
    if not unit.alive:
        return frozenset()
    radius = scenario.stats_for(unit.role).vision
    ux, uy = unit.pos
    cells: set[tuple[int, int]] = set()
    for dx in range(-radius, radius + 1):
        span = radius - abs(dx)
        x = ux + dx
        if not 0 <= x < state.grid_width:
            continue
        for dy in range(-span, span + 1):
            y = uy + dy
            if 0 <= y < state.grid_height:
                cells.add((x, y))
    return frozenset(cells)


def team_visible_cells(
    state: MatchState, scenario: Scenario, team_id: str
) -> frozenset[tuple[int, int]]:
    """The team's combined vision: the union over its living units."""
    if all(team.id != team_id for team in state.teams):
        raise ValueError(f"unknown team {team_id!r} in match {state.match_id!r}")
    cells: set[tuple[int, int]] = set()
    for unit in state.units:
        if unit.team_id == team_id and unit.alive:
            cells |= visible_cells(state, scenario, unit.id)
    return frozenset(cells)


def visible_units(state: MatchState, scenario: Scenario, team_id: str) -> tuple[Unit, ...]:
    """Units the team can see, in canonical state order.

    Own units are always known — a team never loses track of its roster.
    Other teams' units are visible only while they stand on a visible cell.
    """
    cells = team_visible_cells(state, scenario, team_id)
    return tuple(unit for unit in state.units if unit.team_id == team_id or unit.pos in cells)


def visible_resource_nodes(
    state: MatchState, scenario: Scenario, team_id: str
) -> tuple[ResourceNode, ...]:
    """Resource nodes inside the team's vision, in canonical state order."""
    cells = team_visible_cells(state, scenario, team_id)
    return tuple(node for node in state.resource_nodes if node.pos in cells)


def visible_control_points(
    state: MatchState, scenario: Scenario, team_id: str
) -> tuple[ControlPoint, ...]:
    """Control points inside the team's vision, in canonical state order."""
    cells = team_visible_cells(state, scenario, team_id)
    return tuple(cp for cp in state.control_points if cp.pos in cells)


@dataclass(frozen=True)
class TeamView:
    """Everything one team can see at one turn boundary — one consumable shape.

    This is the projection downstream faces build on: fogged briefings, the
    per-team knowledge fold, and the replay's per-team overlay all start here.
    """

    team_id: str
    cells: frozenset[tuple[int, int]]
    units: tuple[Unit, ...]
    control_points: tuple[ControlPoint, ...]
    resource_nodes: tuple[ResourceNode, ...]


def team_view(state: MatchState, scenario: Scenario, team_id: str) -> TeamView:
    """Bundle the team's visible cells and filtered furniture into one view."""
    return TeamView(
        team_id=team_id,
        cells=team_visible_cells(state, scenario, team_id),
        units=visible_units(state, scenario, team_id),
        control_points=visible_control_points(state, scenario, team_id),
        resource_nodes=visible_resource_nodes(state, scenario, team_id),
    )
