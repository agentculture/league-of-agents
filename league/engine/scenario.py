"""Scenario definitions — the maps, objectives, and economies matches run on.

One definition powers **both modes** (spec c18/h11): ``instantiate`` builds a
cooperative (one team vs the environment's turn limit) or competitive (two
teams) match from the same scenario object; there is no forked scenario code.

Scenario parameters are the coordination pressure (spec c16): role stats are
deliberately lopsided (fast scouts carry little, harvesters lumber), control
points outnumber what one unit can occupy, and the turn limit sits below the
best possible solo run — the tradeoff arithmetic is asserted in tests, not
just claimed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from league.engine.state import (
    AgentSlot,
    ControlPoint,
    MatchState,
    Mission,
    ResourceNode,
    TeamState,
    Unit,
)


@dataclass(frozen=True)
class RoleStats:
    """Per-role movement/carry/vision stats — the specialization lever.

    ``vision`` is the Manhattan radius a unit of this role can see
    (consumed by :mod:`league.engine.vision`); scouts see farther than
    anyone else, the visibility axis issue #1 names. Vision never affects
    movement or tick resolution — it only bounds what a unit *knows*.
    """

    move: int
    carry: int
    vision: int


@dataclass(frozen=True)
class Scenario:
    id: str
    name: str
    description: str
    grid_width: int
    grid_height: int
    turn_limit: int
    modes: tuple[str, ...]
    capture_hold_turns: int
    unit_roles: tuple[str, ...]
    role_stats: tuple[tuple[str, RoleStats], ...]
    spawns: tuple[tuple[tuple[int, int], ...], ...]
    control_points: tuple[ControlPoint, ...]
    missions: tuple[Mission, ...]
    resource_nodes: tuple[ResourceNode, ...]

    def stats_for(self, role: str) -> RoleStats:
        for name, stats in self.role_stats:
            if name == role:
                return stats
        raise ValueError(f"unknown role {role!r} in scenario {self.id!r}")


def _skirmish_1() -> Scenario:
    return Scenario(
        id="skirmish-1",
        name="Skirmish 1 — Relay Crossing",
        description=(
            "A 12x10 crossing with three control points, two missions, and two "
            "resource nodes on opposite edges. Built so no unit can do it all: "
            "scouts move fast but carry little, harvesters carry but crawl."
        ),
        grid_width=12,
        grid_height=10,
        turn_limit=30,
        modes=("cooperative", "competitive"),
        capture_hold_turns=2,
        unit_roles=("scout", "harvester", "defender"),
        role_stats=(
            # Vision radii keep the scout the eyes of the team: strictly
            # farther than every other role (spec c12 — visibility as the
            # specialization axis).
            ("scout", RoleStats(move=3, carry=1, vision=4)),
            ("harvester", RoleStats(move=2, carry=3, vision=2)),
            ("defender", RoleStats(move=2, carry=1, vision=2)),
        ),
        spawns=(
            ((0, 0), (1, 0), (0, 1)),
            ((11, 9), (10, 9), (11, 8)),
        ),
        control_points=(
            ControlPoint(id="cp-center", pos=(6, 5)),
            ControlPoint(id="cp-west", pos=(3, 8)),
            ControlPoint(id="cp-east", pos=(9, 2)),
        ),
        missions=(
            Mission(id="ms-supply", kind="deliver", pos=(6, 5), amount=6, reward=10),
            Mission(id="ms-outpost", kind="hold", pos=(9, 2), amount=3, reward=8),
        ),
        resource_nodes=(
            ResourceNode(id="rn-west", pos=(0, 5), remaining=12),
            ResourceNode(id="rn-east", pos=(11, 4), remaining=12),
        ),
    )


_SCENARIOS = {s.id: s for s in (_skirmish_1(),)}


def scenario_ids() -> tuple[str, ...]:
    return tuple(sorted(_SCENARIOS))


def get_scenario(scenario_id: str) -> Scenario:
    try:
        return _SCENARIOS[scenario_id]
    except KeyError:
        raise ValueError(
            f"unknown scenario {scenario_id!r}; known: {', '.join(scenario_ids())}"
        ) from None


def instantiate(
    scenario: Scenario,
    *,
    match_id: str,
    seed: int,
    mode: str,
    teams: Sequence[tuple[str, str, tuple[AgentSlot, ...]]],
) -> MatchState:
    """Build the turn-0 match state for ``teams`` on ``scenario``.

    ``teams`` is ``(team_id, team_name, agent_slots)`` per side. Competitive
    play needs exactly two sides, cooperative exactly one. Every agent roster
    must match the scenario's unit roles one-to-one — the roster *is* the
    role composition being compared across matches (spec c14/h7).
    """
    if mode not in scenario.modes:
        raise ValueError(f"scenario {scenario.id!r} does not support mode {mode!r}")
    required = 2 if mode == "competitive" else 1
    if len(teams) != required:
        raise ValueError(f"mode {mode!r} needs exactly {required} team(s), got {len(teams)}")

    team_states: list[TeamState] = []
    units: list[Unit] = []
    for side, (team_id, team_name, agents) in enumerate(teams):
        if sorted(a.role for a in agents) != sorted(scenario.unit_roles):
            raise ValueError(
                f"team {team_id!r} roster roles must match scenario roles "
                f"{sorted(scenario.unit_roles)}"
            )
        team_states.append(TeamState(id=team_id, name=team_name, resources=0, agents=agents))
        spawn = scenario.spawns[side]
        # Deterministic assignment: scenario role order, spawn slot order.
        by_role = {a.role: a for a in agents}
        for i, role in enumerate(scenario.unit_roles):
            agent = by_role[role]
            units.append(
                Unit(
                    id=f"{team_id}-u{i + 1}",
                    team_id=team_id,
                    agent_id=agent.id,
                    role=role,
                    pos=spawn[i],
                )
            )

    return MatchState(
        match_id=match_id,
        scenario_id=scenario.id,
        seed=seed,
        mode=mode,
        turn=0,
        turn_limit=scenario.turn_limit,
        grid_width=scenario.grid_width,
        grid_height=scenario.grid_height,
        status="pending",
        winner=None,
        teams=tuple(team_states),
        units=tuple(units),
        control_points=scenario.control_points,
        missions=scenario.missions,
        resource_nodes=scenario.resource_nodes,
    )
