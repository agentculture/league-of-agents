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

``c-frontier-1``: fog, a shared delivery square, and a deliberately unfair race
--------------------------------------------------------------------------------
The cycle-8 scenario fields the full executor roster — scout, harvester,
defender per team — on a 12x9 board, and it is built around three pieces of
arithmetic (every duration below is ``move_duration``'s exact integer math on
the scenario's own positions and the default role table's own stats):

* **The head-on race is decided before it starts.** Blue's defender spawns at
  (3, 4): 3000 mu from the post at (6, 4) -> move 6, take 6, holds at
  ``t=12``. Red's defender spawns at (9, 5): ``ceil(ceil(sqrt(10_000_000)) /
  500)`` = move 7, take 6, ``t=13``. One time unit late, every time, by
  construction — the cycle-7 live finding ("reading the OPPONENT's role table
  is the skill gap") turned into a map. Red's winning lines are elsewhere:
  the post can be re-taken after blue's hold streak banks, and the economy
  can be denied.
* **One shared delivery square for both teams.** ``ms-supply`` banks at
  (6, 5) — one unit south of the post, nine time units' travel from either
  resource node. A delivery completing there while an enemy stands on the
  square is DENIED (``resolve.py``'s contention rule), so red's defender —
  move 6 from spawn to the square — can camp blue's bank from ``t=6``. Two
  beelining harvesters (gather 8, move 9, deliver 6) would both complete at
  ``t=23`` standing on the same square and deny EACH OTHER in canonical
  order: the standoff is the scenario's centerpiece, and breaking it takes
  timing, a detour, or a defender clearing the square — coordination, not
  reflexes.
* **Fog makes the standoff information-imperfect.** Executor vision is
  2000 mu; the shared square is 4124 mu from either node and 3163 mu from
  blue's defender spawn — no executor can see whether the bank is camped
  until it is already committed. A scout (4000 mu) posted mid-board reads
  the square from 1415 mu away. Under ``"fog": true`` the scout IS the
  difference between delivering blind and delivering informed.

Coordination pressure holds by the same style of arithmetic: ``time_limit``
is 30, and no single unit can complete both missions — the defender's serial
path costs 6 + 6 (post) + 8 (to a node) + 10 (gather) + 9 (to the square) +
8 (deliver) = **47 > 30**; the harvester's costs 8 + 9 + 6 (supply, ``t=23``)
+ 2 (to the post) + 10 (take) = **35 > 30**; the scout cannot take a post at
all (``can_take_post`` False). ``tests/test_cscenario_frontier.py`` computes
all three bounds from the scenario's own data, never literals.
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


def _c_frontier_1() -> CScenario:
    cp_pos = from_units(6, 4)
    supply_pos = from_units(6, 5)
    west_node = from_units(2, 4)
    east_node = from_units(10, 4)
    return CScenario(
        id="c-frontier-1",
        name="Continuous Frontier 1 — The Fogged Frontier",
        description=(
            "A 12x9 frontier built for fog: full 3-role rosters (scout, "
            "harvester, defender), one central control point, and a SINGLE "
            "shared delivery square one unit south of it — both teams bank "
            "their economy at the same contested spot. Blue's defender wins a "
            "head-on race for the post by exactly one time unit (move 6 + "
            "take 6 = 12, vs red's move 7 + take 6 = 13), so red's rational "
            "play is not the race it loses by arithmetic: red's defender can "
            "camp the shared delivery square from t=6 and deny. Executor "
            "vision (2000 mu) cannot see the square from either approach — "
            "only a scout (4000 mu) can tell a team whether their delivery "
            "walks into a denial."
        ),
        width=12 * SCALE,
        height=9 * SCALE,
        time_limit=30,
        modes=("cooperative", "competitive"),
        unit_roles=("scout", "harvester", "defender"),
        role_table=build_role_table(),
        spawns=(
            # blue: scout forward-west, harvester ON the west node, defender
            # three units from the post (move_duration 6 -> take completes t=12)
            (from_units(1, 4), west_node, from_units(3, 4)),
            # red: scout forward-east, harvester ON the east node, defender
            # offset a diagonal south-east of the post (move_duration 7 ->
            # take completes t=13) — the deliberate 1-time-unit asymmetry the
            # module docstring explains; its camp of the shared delivery
            # square is only move_duration 6 away
            (from_units(11, 4), east_node, from_units(9, 5)),
        ),
        control_points=(CControlPoint(id="cp-frontier", pos=cp_pos),),
        missions=(
            CMission(id="ms-hold", kind="hold", pos=cp_pos, amount=5, reward=8),
            CMission(id="ms-supply", kind="deliver", pos=supply_pos, amount=3, reward=6),
        ),
        resource_nodes=(
            CResourceNode(id="rn-west", pos=west_node, remaining=3),
            CResourceNode(id="rn-east", pos=east_node, remaining=3),
        ),
    )


_CSCENARIOS = {s.id: s for s in (_c_skirmish_1(), _c_frontier_1())}


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
