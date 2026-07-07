"""CYCLE-3 t4 acceptance tests — ``skirmish-2``, the fogged scenario.

This is the h9 retest board (docs/playtests/season-0/coordination.report.md):
on skirmish-1 a solo strong mind with **one action per turn** beat a
coordinated swarm by grinding the delivery relay with a single unit. The
season-0 failure was an *action-bandwidth* failure — the map never made one
action per turn insufficient. skirmish-2 re-proves coordination-necessity by
construction, and the proof is arithmetic over the scenario's own parameters
(never hard-coded board trivia):

* **Solo impossibility** — a floor on the total *actions* any one-action-per-
  turn mind needs to complete both missions, however it splits the work across
  its three units, exceeds the turn limit (``test_solo_mind_cannot_finish_...``).
* **Coordinated feasibility with headroom** — a scripted three-minds-acting-
  every-turn plan completes both missions well inside the limit; the limit
  carries ~30-40% headroom over that run (``test_coordinated_team_finishes...``).
* **Fog geometry** — vision radii are small relative to the map and the two
  missions sit farther apart than any single vantage can see, so no unit can
  watch both objectives at once (``test_fog_geometry_...``).
"""

from __future__ import annotations

import math

import pytest

from league.engine.scenario import Scenario, get_scenario, instantiate, scenario_ids
from league.engine.state import AgentSlot, MatchState
from league.engine.tick import resolve_turn, start_match


def _roster(team: str, model: str = "colleague/qwen") -> tuple[AgentSlot, ...]:
    return (
        AgentSlot(id=f"{team}-scout", model=model, role="scout"),
        AgentSlot(id=f"{team}-harvester", model=model, role="harvester"),
        AgentSlot(id=f"{team}-defender", model=model, role="defender"),
    )


def _manhattan(a: tuple[int, int], b: tuple[int, int]) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def test_loads_by_id_with_skirmish_1_style_furniture() -> None:
    scenario = get_scenario("skirmish-2")
    assert scenario.id in scenario_ids()
    assert len(scenario.control_points) >= 3
    assert sorted(m.kind for m in scenario.missions) == ["deliver", "hold"]
    assert len(scenario.resource_nodes) >= 2
    assert set(scenario.modes) == {"cooperative", "competitive"}
    assert sorted(scenario.unit_roles) == ["defender", "harvester", "scout"]
    # skirmish-1 is untouched: both boards coexist in the catalog.
    assert set(scenario_ids()) >= {"skirmish-1", "skirmish-2"}


def test_fog_geometry_no_single_vantage_covers_both_objectives() -> None:
    """Fog is why coordination must win: vision is small relative to the map.

    The scout stays the eyes of the team (strictly the largest radius — the
    t1 specialization axis), yet even the scout's radius cannot cover both
    missions from any square: the objectives sit farther apart than twice the
    largest vision radius.
    """
    scenario = get_scenario("skirmish-2")
    visions = {role: stats.vision for role, stats in scenario.role_stats}
    assert all(visions["scout"] > v for role, v in visions.items() if role != "scout")
    max_vision = max(visions.values())
    deliver = next(m for m in scenario.missions if m.kind == "deliver")
    hold = next(m for m in scenario.missions if m.kind == "hold")
    assert _manhattan(deliver.pos, hold.pos) > 2 * max_vision
    # Small relative to the map: no radius spans even half the short grid axis.
    assert 2 * max_vision < min(scenario.grid_width, scenario.grid_height) + 1


def test_instantiation_validates_like_skirmish_1() -> None:
    scenario = get_scenario("skirmish-2")
    coop = instantiate(
        scenario,
        match_id="m-s2",
        seed=3,
        mode="cooperative",
        teams=(("blue", "Blue Foundry", _roster("blue")),),
    )
    assert coop.scenario_id == "skirmish-2"
    assert [u.pos for u in coop.units] == list(scenario.spawns[0])
    comp = instantiate(
        scenario,
        match_id="m-s2c",
        seed=3,
        mode="competitive",
        teams=(
            ("blue", "Blue Foundry", _roster("blue")),
            ("red", "Red Relay", _roster("red", model="claude-sonnet-5")),
        ),
    )
    assert len(comp.units) == 2 * len(scenario.unit_roles)
    with pytest.raises(ValueError, match="exactly 2"):
        instantiate(
            scenario,
            match_id="m",
            seed=1,
            mode="competitive",
            teams=(("blue", "Blue", _roster("blue")),),
        )
    bad_roster = tuple(
        AgentSlot(id=f"x-{i}", model="m", role="scout") for i in range(len(scenario.unit_roles))
    )
    with pytest.raises(ValueError, match="roster roles"):
        instantiate(
            scenario,
            match_id="m",
            seed=1,
            mode="cooperative",
            teams=(("blue", "Blue", bad_roster),),
        )


# --- the coordination-necessity proof, part 1: solo impossibility ----------


def _solo_action_floor(scenario: Scenario) -> int:
    """A floor on total ACTIONS for a one-action-per-turn mind to win.

    The season-0 h9 "solo" was one mind commanding three units with **one
    action per turn total** — so the honest bound is on *actions across all
    units*, not on one unit's travel. Every component below is best-cased
    (max move, max carry, min distances), so the floor holds for ANY split of
    the work across units and any role mix; the real run is strictly slower.

    Deliver mission: each delivered batch is one *trip* carrying at most
    ``c_max``:

    * every trip needs 1 gather + 1 deliver action;
    * between its gather (on a node) and its deliver (on the mission square)
      the carrier walks at least the closest node→delivery distance:
      ``ceil(d_nd / m_max)`` move actions per trip;
    * every trip is also either a unit's FIRST trip (walk spawn→node first:
      ``ceil(d_sn / m_max)`` moves) or a repeat trip (walk delivery→node
      back: ``ceil(d_nd / m_max)`` moves) — at least the cheaper of the two.

    Hold mission: some unit must physically reach the hold point. Its final
    approach starts, at best, from the nearest square the delivery economy
    ever requires anyone to stand on (a spawn, a node, or the delivery
    square) — a segment no trip accounting above has counted.

    The hold *streak* itself is free for a solo mind (a parked unit accrues
    occupancy without spending actions), and that generosity is deliberate:
    the floor stays a floor.
    """
    m_max = max(stats.move for _, stats in scenario.role_stats)
    c_max = max(stats.carry for _, stats in scenario.role_stats)
    deliver = next(m for m in scenario.missions if m.kind == "deliver")
    hold = next(m for m in scenario.missions if m.kind == "hold")
    spawn_points = [pos for side in scenario.spawns for pos in side]

    d_nd = min(_manhattan(node.pos, deliver.pos) for node in scenario.resource_nodes)
    d_sn = min(
        _manhattan(spawn, node.pos) for spawn in spawn_points for node in scenario.resource_nodes
    )
    trips = math.ceil(deliver.amount / c_max)
    oneway = math.ceil(d_nd / m_max)
    approach_or_return = min(oneway, math.ceil(d_sn / m_max))
    deliver_floor = trips * (2 + oneway + approach_or_return)

    launch_points = spawn_points + [n.pos for n in scenario.resource_nodes] + [deliver.pos]
    hold_travel = math.ceil(min(_manhattan(p, hold.pos) for p in launch_points) / m_max)
    return deliver_floor + hold_travel


def test_solo_mind_cannot_finish_both_missions_inside_the_limit() -> None:
    """One action per turn, perfect play, any unit split: still out of turns.

    With skirmish-2's numbers: 4 trips x (gather + deliver + 1 leg + 1 leg)
    = 16 delivery actions, + ceil(10/3) = 4 moves to reach the hold point
    from anywhere the relay touches = a 20-action floor against a turn limit
    of 16. The season-0 h9 exploit — grind one relay solo — is arithmetically
    dead on this board.
    """
    scenario = get_scenario("skirmish-2")
    floor = _solo_action_floor(scenario)
    assert floor > scenario.turn_limit, (
        f"a solo one-action-per-turn mind could finish both missions: floor {floor} "
        f"vs turn limit {scenario.turn_limit} — retune the scenario"
    )


# --- the coordination-necessity proof, part 2: coordinated feasibility -----

_SCOUT, _HARVESTER, _DEFENDER = "blue-u1", "blue-u2", "blue-u3"


def _mv(unit_id: str, x: int, y: int) -> dict:
    return {"unit_id": unit_id, "action": "move", "to": [x, y]}


def _do(unit_id: str, verb: str) -> dict:
    return {"unit_id": unit_id, "action": verb}


# Three minds, every unit acting every turn (the coordination skirmish-2 pays
# for): scout + harvester run the two-carrier relay to ms-caravan while the
# defender walks to cp-beacon and sits out the capture-and-hold clock.
#
#   scout  (move 3, carry 2): spawn (0,0) -> rn-lowland (5,5) in 4, then
#          gather/step/deliver round trips of 4 turns -> +2 at t7, +2 at t11
#   harv   (move 2, carry 3): spawn (1,0) -> rn-lowland in 5, then round
#          trips -> +3 at t8, +3 at t12  => 10 delivered on turn 12
#   def    (move 2): spawn (0,1) -> cp-beacon (12,0) in 7; sole occupancy
#          t7..t12 -> streak 6 = capture(2) + hold(4) => ms-beacon on turn 12
#
# Both missions land on turn 12; the 16-turn limit = ceil(12 * 1.3) leaves
# the mandated ~30-40% headroom for imperfect live play.
_COORDINATED_SCRIPT: tuple[tuple[dict, ...], ...] = (
    (_mv(_SCOUT, 3, 0), _mv(_HARVESTER, 3, 0), _mv(_DEFENDER, 2, 1)),
    (_mv(_SCOUT, 5, 1), _mv(_HARVESTER, 5, 0), _mv(_DEFENDER, 4, 1)),
    (_mv(_SCOUT, 5, 4), _mv(_HARVESTER, 5, 2), _mv(_DEFENDER, 6, 1)),
    (_mv(_SCOUT, 5, 5), _mv(_HARVESTER, 5, 4), _mv(_DEFENDER, 8, 1)),
    (_do(_SCOUT, "gather"), _mv(_HARVESTER, 5, 5), _mv(_DEFENDER, 10, 1)),
    (_mv(_SCOUT, 6, 6), _do(_HARVESTER, "gather"), _mv(_DEFENDER, 12, 1)),
    (_do(_SCOUT, "deliver"), _mv(_HARVESTER, 6, 6), _mv(_DEFENDER, 12, 0)),
    (_mv(_SCOUT, 5, 5), _do(_HARVESTER, "deliver"), _do(_DEFENDER, "hold")),
    (_do(_SCOUT, "gather"), _mv(_HARVESTER, 5, 5), _do(_DEFENDER, "hold")),
    (_mv(_SCOUT, 6, 6), _do(_HARVESTER, "gather"), _do(_DEFENDER, "hold")),
    (_do(_SCOUT, "deliver"), _mv(_HARVESTER, 6, 6), _do(_DEFENDER, "hold")),
    (_do(_HARVESTER, "deliver"), _do(_DEFENDER, "hold")),
)


def _run_coordinated() -> tuple[MatchState, list]:
    scenario = get_scenario("skirmish-2")
    state = instantiate(
        scenario,
        match_id="m-s2-coord",
        seed=11,
        mode="cooperative",
        teams=(("blue", "Blue Foundry", _roster("blue")),),
    )
    state, events = start_match(state)
    log = list(events)
    for actions in _COORDINATED_SCRIPT:
        state, turn_events = resolve_turn(state, scenario, {"blue": {"actions": list(actions)}})
        log.extend(turn_events)
    return state, log


def test_coordinated_team_finishes_with_thirty_percent_headroom() -> None:
    scenario = get_scenario("skirmish-2")
    final, log = _run_coordinated()
    # The script is legal play, not luck: the engine rejected nothing.
    assert not [e for e in log if e.kind == "action_rejected"]
    assert final.status == "finished"
    assert final.winner == "blue"
    assert all(m.status == "completed" for m in final.missions)
    finish_turn = final.turn
    assert finish_turn == len(_COORDINATED_SCRIPT) == 12
    # Headroom: the limit clears the best coordinated run by >= 30%...
    assert scenario.turn_limit >= math.ceil(finish_turn * 1.3)
    # ...while staying below the solo action floor — both proofs bind at once.
    assert scenario.turn_limit < _solo_action_floor(scenario)
