"""Continuous scenario registry — the maps, objectives, and economies the
continuous lane's matches run on (plan C7-t6, spec c10/h3).

This is the continuous sibling of the grid's ``league/engine/scenario.py`` and
it plays the same two roles: it is the coordination-pressure author (scenario
parameters, not resolver code, force the tradeoff — see
:func:`~tests.test_continuous_scenario._solo_lower_bound`'s arithmetic, mirrored
here in this module's docstring) and it is the single ``instantiate`` path both
match modes share (spec c18/h11's continuous analog — one scenario definition,
cooperative *or* competitive, never a fork).

Two lanes, one registry, zero ambiguity (spec c10/h3)
------------------------------------------------------
The continuous lane lands *beside* the grid engine, never over it (two-lane
honesty, spec c11/h11) — so its scenario registry must never collide with the
grid's. The discipline is DATA, not special-casing: every continuous scenario
id is prefixed :data:`CONTINUOUS_ID_PREFIX` (``"c-"``), enforced on the
dataclass itself (:meth:`CScenario.__post_init__` raises on a non-conforming
id, so the rule cannot be forgotten by a future scenario author) — never by a
registry function inspecting *which* module answered the lookup. The grid's
hand-authored ids (``skirmish-1``, ``skirmish-2``, ``recon-1``) and its
generated ids (``gen-<seed>-<token>``, ``league.engine.genscenario``) never
start with ``"c-"``, so the two id spaces are disjoint by construction;
``tests/test_continuous_scenario.py::
test_no_id_collides_between_grid_and_continuous_registries`` checks it both
ways against the live grid registry, not a hard-coded snapshot of its ids.

``instantiate`` mirrors ``league.engine.scenario.instantiate`` field-for-field
(team-count validation, the roster-role multiset check, the per-role queue
that lets a scenario field more than one unit of the same role
deterministically) — the continuous positions (:class:`~league.engine.
continuous.space.Pos`) and the timeline's ``clock``/``time_limit`` are the only
things that differ from the grid shape.

``c-skirmish-1``: a race by construction
-----------------------------------------
The board is small on purpose: one control point, ``cp-crossing``, sits at
(5, 4) — roughly central on a 10x8 board. Blue's defender spawns one unit west
of it (a real move is required); blue's harvester spawns at a resource node
that is *also* the delivery mission's square, so gather -> deliver never needs
to travel. Red's harvester spawns already camped ON the post (no travel at
all); red's defender parks in a far corner and never receives a useful order —
this scenario deliberately fields only ONE live contest per side so the
canonical scripted match (t6's determinism gate) stays legible turn-by-event.

Scout does not field in this roster at all (human-reviewed amendment, cycle 7,
pre-publish: "scouts should not be able to take posts — only be the 'eyes'").
Scout keeps its full gather/carry/deliver contract and its widest-among-
executors vision unchanged — only its ``can_take_post`` is withdrawn (see
``league/engine/continuous/roles.py``) — but a scenario built specifically to
race for a control point needs a racer that can actually take one, so this
scenario's contested-crossing role is now the **defender**, the faster of the
two roles left able to take a post at all (``take_post_duration`` 6, vs
harvester's 10).

The race is forced by the default role table's own numbers (:data:`~league.
engine.continuous.roles.DEFAULT_CROLE_STATS`), not by scripting an unfair
fight: red's harvester starts taking the post at ``t=0`` (``take_post_duration
10`` -> would complete at ``t=10``); blue's defender must first travel one unit
(``move_rate_mu 500``, exact distance 1000 mu -> ``move_duration`` = 2) before
it can even start its own take at ``t=2`` (``take_post_duration 6`` -> completes
at ``t=8``). Red's harvester has a 2-time-unit HEAD START on the take itself —
it starts taking at ``t=0``, a full 2 time-units before blue's defender even
arrives and starts its OWN take at ``t=2`` — yet blue's defender still
completes first (``8 < 10``): a genuine race the scenario's role speeds make
happen by arithmetic, not narration. The harvester watches from the takers
list as blue's take completes and its own attempt is cancelled and fails:
``action_failed`` with reason ``"post taken by a faster agent"``.

Coordination pressure, proven by arithmetic (mirrors the grid scenarios' style)
--------------------------------------------------------------------------------
``time_limit`` is 20. A single unit — even the defender, the faster of the two
remaining post-takers — cannot both win the race and run the economy within
that budget if it had to do both serially: move to the post (2) + take it (6)
+ travel from the post to the resource node (exact distance 5 units ->
``move_duration`` = 10) + gather (10) + deliver (8) = **36 > 20**. (The
harvester attempting the same solo path fares no better: its own
take/gather/deliver durations — 10, 8, 6 — are a permutation of the defender's
6, 10, 8, so its serial total is also 2 + 10 + 10 + 8 + 6 = 36. The default
role table splits post-taking speed and economy speed between the two roles
symmetrically, not by accident — neither role can solo both jobs, whichever
one you pick.) The actual roster splits the labor across the defender (race)
and the harvester (economy) running in PARALLEL on their own timeline entries;
the canonical scripted match (``tests/test_determinism_gate_continuous.py``)
finishes both the hold and the deliver missions by ``t=14 < 20`` — comfortably
inside the limit specialization buys, and outside the limit a single unit could
reach. ``tests/test_continuous_scenario.py::
test_solo_unit_cannot_win_the_race_and_run_the_economy_in_time`` computes the
36 from the scenario's own positions and the defender's own role stats — never
a hard-coded literal — so retuning the board or the role table re-checks the
inequality rather than silently invalidating the claim.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from league.engine.continuous.roles import CRoleStats, build_role_table
from league.engine.continuous.space import SCALE, Pos, from_units
from league.engine.continuous.state import (
    CAgentSlot,
    CControlPoint,
    CMatchState,
    CMission,
    CResourceNode,
    CTeamState,
    CUnit,
)

#: The cross-lane id discipline (spec c10/h3): every continuous scenario id
#: must start with this prefix. See the module docstring for the full
#: rationale; :meth:`CScenario.__post_init__` enforces it on construction.
CONTINUOUS_ID_PREFIX = "c-"


@dataclass(frozen=True)
class CScenario:
    """A continuous-lane scenario: the board, economy, objectives, and role
    table one ``instantiate`` call turns into a ``pending`` :class:`~league.
    engine.continuous.state.CMatchState`.

    Mirrors ``league.engine.scenario.Scenario`` field-for-field where the
    concept is shared (``modes``, ``unit_roles``, ``spawns``,
    ``control_points``, ``missions``, ``resource_nodes``); ``width``/``height``
    are the board extent in milliunits (the continuous analog of
    ``grid_width``/``grid_height``), ``time_limit`` replaces ``turn_limit``,
    and ``role_table`` replaces ``role_stats`` — built via
    :func:`~league.engine.continuous.roles.build_role_table`, the validated
    override mechanism, so a scenario can field a different speed table
    without any code change (spec c7's second acceptance half).
    """

    id: str
    name: str
    description: str
    width: int
    height: int
    time_limit: int
    modes: tuple[str, ...]
    unit_roles: tuple[str, ...]
    role_table: tuple[tuple[str, CRoleStats], ...]
    spawns: tuple[tuple[Pos, ...], ...]
    control_points: tuple[CControlPoint, ...]
    missions: tuple[CMission, ...]
    resource_nodes: tuple[CResourceNode, ...] = field(default=())

    def __post_init__(self) -> None:
        if not self.id.startswith(CONTINUOUS_ID_PREFIX):
            raise ValueError(
                f"continuous scenario id {self.id!r} must start with "
                f"{CONTINUOUS_ID_PREFIX!r} — the cross-lane discipline that keeps "
                "continuous and grid scenario ids disjoint by data, not special-casing"
            )

    def stats_for(self, role: str) -> CRoleStats:
        """Look up ``role``'s stats in this scenario's table; unknown roles
        fail loudly (mirrors the grid's ``Scenario.stats_for``)."""
        for name, stats in self.role_table:
            if name == role:
                return stats
        raise ValueError(f"unknown role {role!r} in scenario {self.id!r}")


def _c_skirmish_1() -> CScenario:
    cp_pos = from_units(5, 4)
    econ_pos = from_units(1, 1)
    return CScenario(
        id="c-skirmish-1",
        name="Continuous Skirmish 1 — The Contested Crossing",
        description=(
            "A 10x8 crossing with one control point roughly central. Blue's defender "
            "starts one unit from the post and blue's harvester starts on a "
            "resource node that doubles as the delivery square; red's harvester "
            "starts already camped ON the post and red's defender parks far away. "
            "The default role table's own speeds make the post a genuine race: "
            "the camped harvester starts first but the travelling defender still "
            "finishes first — a later start beats an earlier start when the "
            "starter is the slower-at-taking role."
        ),
        width=10 * SCALE,
        height=8 * SCALE,
        time_limit=20,
        modes=("cooperative", "competitive"),
        unit_roles=("defender", "harvester"),
        role_table=build_role_table(),
        spawns=(
            (from_units(4, 4), econ_pos),  # blue: defender 1 unit from the post; harvester home
            (
                from_units(9, 7),
                cp_pos,
            ),  # red: defender parked far away; harvester camped on the post
        ),
        control_points=(CControlPoint(id="cp-crossing", pos=cp_pos),),
        missions=(
            CMission(id="ms-hold", kind="hold", pos=cp_pos, amount=5, reward=8),
            CMission(id="ms-supply", kind="deliver", pos=econ_pos, amount=3, reward=6),
        ),
        resource_nodes=(CResourceNode(id="rn-home", pos=econ_pos, remaining=3),),
    )


_CSCENARIOS = {s.id: s for s in (_c_skirmish_1(),)}


def cscenario_ids() -> tuple[str, ...]:
    return tuple(sorted(_CSCENARIOS))


def get_cscenario(scenario_id: str) -> CScenario:
    """Resolve a continuous scenario id to its definition.

    Raises a ``ValueError`` naming the known ids on an unknown lookup (mirrors
    the grid's ``get_scenario`` failure shape).
    """
    try:
        return _CSCENARIOS[scenario_id]
    except KeyError:
        raise ValueError(
            f"unknown continuous scenario {scenario_id!r}; known: " f"{', '.join(cscenario_ids())}"
        ) from None


def instantiate(
    scenario: CScenario,
    *,
    match_id: str,
    seed: int,
    mode: str,
    teams: Sequence[tuple[str, str, tuple[CAgentSlot, ...]]],
) -> CMatchState:
    """Build the clock-0 continuous match state for ``teams`` on ``scenario``.

    ``teams`` is ``(team_id, team_name, agent_slots)`` per side — competitive
    play needs exactly two sides, cooperative exactly one. Every roster must
    match the scenario's ``unit_roles`` one-to-one (a multiset comparison, so a
    scenario may repeat a role name); units are assigned deterministically via
    a per-role queue (roster order), exactly mirroring
    ``league.engine.scenario.instantiate`` so N agents sharing a role each get
    their own unit instead of a dict silently collapsing to the last one.
    """
    if mode not in scenario.modes:
        raise ValueError(f"scenario {scenario.id!r} does not support mode {mode!r}")
    required = 2 if mode == "competitive" else 1
    if len(teams) != required:
        raise ValueError(f"mode {mode!r} needs exactly {required} team(s), got {len(teams)}")

    team_states: list[CTeamState] = []
    units: list[CUnit] = []
    for side, (team_id, team_name, agents) in enumerate(teams):
        if sorted(a.role for a in agents) != sorted(scenario.unit_roles):
            raise ValueError(
                f"team {team_id!r} roster roles must match scenario roles "
                f"{sorted(scenario.unit_roles)}"
            )
        team_states.append(CTeamState(id=team_id, name=team_name, resources=0, agents=agents))
        spawn = scenario.spawns[side]
        by_role: dict[str, list[CAgentSlot]] = {}
        for agent in agents:
            by_role.setdefault(agent.role, []).append(agent)
        next_index = {role: 0 for role in by_role}
        for i, role in enumerate(scenario.unit_roles):
            index = next_index[role]
            agent = by_role[role][index]
            next_index[role] = index + 1
            units.append(
                CUnit(
                    id=f"{team_id}-u{i + 1}",
                    team_id=team_id,
                    agent_id=agent.id,
                    role=role,
                    pos=spawn[i],
                )
            )

    return CMatchState(
        match_id=match_id,
        scenario_id=scenario.id,
        seed=seed,
        mode=mode,
        clock=0,
        time_limit=scenario.time_limit,
        width=scenario.width,
        height=scenario.height,
        status="pending",
        winner=None,
        teams=tuple(team_states),
        units=tuple(units),
        control_points=scenario.control_points,
        missions=scenario.missions,
        resource_nodes=scenario.resource_nodes,
    )
