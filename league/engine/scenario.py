"""Scenario definitions — the maps, objectives, and economies matches run on.

One definition powers **both modes** (spec c18/h11): ``instantiate`` builds a
cooperative (one team vs the environment's turn limit) or competitive (two
teams) match from the same scenario object; there is no forked scenario code.

Scenario parameters are the coordination pressure (spec c16): role stats are
deliberately lopsided (fast scouts carry little, harvesters lumber), control
points outnumber what one unit can occupy, and the turn limit sits below the
best possible solo run — the tradeoff arithmetic is asserted in tests, not
just claimed.

Roles are **capability contracts, mirroring real coding work** (cycle-6 task
C6-t3, spec honesty h11 — the difference lives in engine data + legality, never
in prompt convention). Each role's software-work analog, documented next to its
stats below and in ``docs/roles.md``:

* **explorer** — *reconnaissance / code-reading*: extended vision and reach,
  ``carry=0``, ``can_gather=False``, ``can_capture=False``. It maps the board
  and hands intel to the planner; it never touches the economy and its
  occupancy never builds or contests a control-point streak (see
  :mod:`league.engine.tick` step 7 and :mod:`league.engine.legal`).
* **planner** — *architect / tech-lead*: ``move=1``, ``carry=0``, baseline
  vision, ``can_gather=False``, ``can_capture=False``. Weak on the board alone
  by design — it wins by coordinating through the existing plan/message
  channels (no new engine mechanic), so fielding one is a real tradeoff.
* **scout** — *quick reconnaissance pass*: fast, wide sight, light carry.
* **harvester** / **defender** — *implementers (executor class)*: they run the
  economy and hold objectives (``can_gather``/``can_capture`` both ``True``).

The two capability booleans default to ``True`` so every pre-existing role
(scout / harvester / defender) keeps its exact behaviour — the new roles are a
JOIN, not a replace (plan risk r4), and ``RoleStats`` is scenario config that
never enters ``MatchState``/``state_hash``, so adding these fields cannot
perturb the committed determinism fixture.
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
    """Per-role capability contract — the specialization lever.

    ``move``/``carry``/``vision`` are the quantitative levers; ``vision`` is
    the Manhattan radius a unit of this role can see (consumed by
    :mod:`league.engine.vision`). Vision never affects movement or tick
    resolution — it only bounds what a unit *knows*.

    ``can_gather`` and ``can_capture`` are **engine-enforced capability
    booleans** (spec honesty h11): a role with ``can_gather=False`` has its
    ``gather`` orders rejected by the tick and absent from ``legal_actions``;
    a role with ``can_capture=False`` never counts as an occupant of a control
    point, so its presence neither builds nor contests a capture streak. Both
    default to ``True`` so pre-existing roles are unchanged (the new roles are
    additive — a JOIN, not a replace).

    ``analog`` records the role's software-work analog (explorer =
    reconnaissance/code-reading, planner = architect/tech-lead, harvester /
    defender = implementers/executors) right next to the stats it explains —
    the same mapping ``docs/roles.md`` documents at length.
    """

    move: int
    carry: int
    vision: int
    can_gather: bool = True
    can_capture: bool = True
    analog: str = ""


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


def _skirmish_2() -> Scenario:
    """SKIRMISH-2 — the fogged board, and the h9 retest venue.

    Season 0 (docs/playtests/season-0/coordination.report.md) showed a solo
    strong mind with one action per turn beating a coordinated swarm on
    skirmish-1 by grinding a single delivery relay. skirmish-2 re-proves
    coordination-necessity by construction; the arithmetic is asserted from
    these parameters in ``tests/test_engine_skirmish2.py``:

    * **Solo action floor 20 > turn limit 16.** Best case for one mind at one
      action per turn, any unit split: ms-caravan needs ceil(10/3) = 4 trips,
      each at least gather + deliver + one node→delivery leg (ceil(2/3) = 1)
      + one return-or-approach leg (min(1, ceil(9/3)) = 1) = 16 actions; the
      hold point is ceil(10/3) = 4 moves from anywhere the relay touches.
    * **Coordinated finish turn 12, limit 16 = ceil(12 x 1.3).** Scout+
      harvester two-carrier relay lands 2/3/2/3 on turns 7/8/11/12 while the
      defender reaches cp-beacon on turn 7 and sits capture(2)+hold(4) — both
      missions on turn 12, ~33% headroom for imperfect live play.
    * **Fog:** the missions sit 12 apart — beyond twice even the scout's
      radius (4), so no single vantage watches both objectives at once.
    """
    return Scenario(
        id="skirmish-2",
        name="Skirmish 2 — Fogbound Crossing",
        description=(
            "A 14x12 crossing under fog: vision radii are small relative to the "
            "map (scout 4, others 2) and the delivery relay and the beacon hold "
            "sit twelve tiles apart — farther than any unit can see. The turn "
            "limit sits below the best one-action-per-turn solo run; splitting "
            "the relay from the hold is the only way home."
        ),
        grid_width=14,
        grid_height=12,
        turn_limit=16,
        modes=("cooperative", "competitive"),
        capture_hold_turns=2,
        unit_roles=("scout", "harvester", "defender"),
        role_stats=(
            # The scout stays the eyes of the team (strictly the largest
            # radius — spec c12) and carries a satchel worth relaying; the
            # harvester hauls but crawls; the defender walks and watches.
            ("scout", RoleStats(move=3, carry=2, vision=4)),
            ("harvester", RoleStats(move=2, carry=3, vision=2)),
            ("defender", RoleStats(move=2, carry=1, vision=2)),
        ),
        spawns=(
            ((0, 0), (1, 0), (0, 1)),
            ((13, 11), (12, 11), (13, 10)),
        ),
        control_points=(
            ControlPoint(id="cp-relay", pos=(7, 5)),
            ControlPoint(id="cp-beacon", pos=(12, 0)),
            ControlPoint(id="cp-well", pos=(1, 11)),
        ),
        missions=(
            # The delivery square is NOT a control point — the season-0 h15
            # review flagged the overlap as unreadable in the replay.
            Mission(id="ms-caravan", kind="deliver", pos=(6, 6), amount=10, reward=10),
            Mission(id="ms-beacon", kind="hold", pos=(12, 0), amount=4, reward=8),
        ),
        resource_nodes=(
            ResourceNode(id="rn-lowland", pos=(5, 5), remaining=12),
            ResourceNode(id="rn-highland", pos=(8, 6), remaining=12),
        ),
    )


def _recon_1() -> Scenario:
    """RECON-1 — the coding-reflective roster (cycle-6 task C6-t3).

    The first scenario to field the new capability-contract roles alongside the
    executor class: an **explorer** (recon/code-reading) that sees and reaches
    far but cannot touch the economy or hold a point, a **planner**
    (architect/tech-lead) that is near-helpless on the board yet coordinates the
    team through the plan/message channels, and two **implementers** — a
    harvester and a defender — that actually run the relay and hold the beacon.

    skirmish-1/2 are untouched by this addition; recon-1 simply coexists in the
    catalog. Geometry echoes skirmish-2 (a fogged crossing) so the board reads
    familiarly while the roster is what is new.
    """
    return Scenario(
        id="recon-1",
        name="Recon 1 — Read, Plan, Execute",
        description=(
            "A 14x12 crossing fielding the coding-reflective roster: an explorer "
            "(reconnaissance/code-reading) that ranges far but cannot gather or "
            "hold points, a planner (architect/tech-lead) that is weak on the "
            "board but coordinates through plan and messages, and two implementer "
            "executors (harvester + defender) that run the relay and hold the "
            "beacon. Roles are engine-enforced capability contracts, not prompt "
            "convention."
        ),
        grid_width=14,
        grid_height=12,
        turn_limit=20,
        modes=("cooperative", "competitive"),
        capture_hold_turns=2,
        unit_roles=("explorer", "planner", "harvester", "defender"),
        role_stats=(
            # explorer — reconnaissance / code-reading: strictly the farthest
            # sight AND reach on this board, but carry 0 and no economy/capture
            # rights (enforced in tick + legal, not by convention).
            (
                "explorer",
                RoleStats(
                    move=4,
                    carry=0,
                    vision=6,
                    can_gather=False,
                    can_capture=False,
                    analog="reconnaissance / code-reading: ranges far and sees far, "
                    "produces nothing directly and holds no ground",
                ),
            ),
            # planner — architect / tech-lead: crawls (move 1), carries nothing,
            # only baseline sight; its edge is coordinating the others through
            # the plan/message channels, so fielding it is a real tradeoff.
            (
                "planner",
                RoleStats(
                    move=1,
                    carry=0,
                    vision=2,
                    can_gather=False,
                    can_capture=False,
                    analog="architect / tech-lead: coordinates via plan + messages, "
                    "weak on the board alone",
                ),
            ),
            # harvester / defender — implementers (executor class): they run the
            # economy and hold objectives, the default capability contract.
            (
                "harvester",
                RoleStats(
                    move=2,
                    carry=3,
                    vision=2,
                    analog="implementer (executor class): hauls and delivers the payload",
                ),
            ),
            (
                "defender",
                RoleStats(
                    move=2,
                    carry=1,
                    vision=2,
                    analog="implementer (executor class): captures and holds objectives",
                ),
            ),
        ),
        spawns=(
            ((0, 0), (1, 0), (0, 1), (1, 1)),
            ((13, 11), (12, 11), (13, 10), (12, 10)),
        ),
        control_points=(
            ControlPoint(id="cp-alpha", pos=(7, 5)),
            ControlPoint(id="cp-beacon", pos=(12, 0)),
            ControlPoint(id="cp-well", pos=(1, 11)),
        ),
        missions=(
            Mission(id="ms-relay", kind="deliver", pos=(6, 6), amount=6, reward=10),
            Mission(id="ms-signal", kind="hold", pos=(12, 0), amount=3, reward=8),
        ),
        resource_nodes=(
            ResourceNode(id="rn-low", pos=(5, 5), remaining=12),
            ResourceNode(id="rn-high", pos=(8, 6), remaining=12),
        ),
    )


_SCENARIOS = {s.id: s for s in (_skirmish_1(), _skirmish_2(), _recon_1())}


def scenario_ids() -> tuple[str, ...]:
    return tuple(sorted(_SCENARIOS))


def get_scenario(scenario_id: str) -> Scenario:
    """Resolve a scenario id to its definition.

    Hand-authored scenarios (``skirmish-1``/``-2``) come from the bundled
    registry; a ``gen-<seed>-<token>`` id is re-derived on the fly by the
    seeded generator (``league.engine.genscenario``), whose id fully encodes
    seed+params — so the whole CLI/harness/replay stack resolves a generated
    board from its id (and hence from a match log) with no other change. A
    generated id whose params are out of range raises the generator's own
    precise ``ValueError`` (e.g. "grid_width must be odd"), not the generic
    unknown-scenario error.
    """
    try:
        return _SCENARIOS[scenario_id]
    except KeyError:
        pass
    # Lazy import breaks the scenario <-> genscenario module cycle (genscenario
    # imports Scenario/RoleStats from here at load time).
    from league.engine import genscenario

    parsed = genscenario.parse_generated_id(scenario_id)
    if parsed is not None:
        seed, params = parsed
        return genscenario.generate(seed, params)
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

    A scenario's ``unit_roles`` may repeat a role name (cycle-6 task C6-t2's
    roster-scale knob, e.g. two harvester slots) — the ``sorted(...) ==
    sorted(...)`` check above is already a MULTISET comparison, so counts per
    role must match, not just the set of names. The assignment below walks a
    per-role QUEUE of roster agents (in roster order) rather than a single
    dict keyed by role, so N agents sharing a role each get their own unit,
    deterministically, instead of a dict silently collapsing to the last one.
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
        # Deterministic assignment: scenario role order, spawn slot order,
        # roster order per role (a per-role queue, not a role->agent dict —
        # see the docstring note on duplicate-role scenarios).
        by_role: dict[str, list[AgentSlot]] = {}
        for agent in agents:
            by_role.setdefault(agent.role, []).append(agent)
        next_index = {role: 0 for role in by_role}
        for i, role in enumerate(scenario.unit_roles):
            index = next_index[role]
            agent = by_role[role][index]
            next_index[role] = index + 1
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
