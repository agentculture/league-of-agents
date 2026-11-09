"""The Crown (a public center objective) and the economy knobs on generated boards."""

import dataclasses

from league.engine.genscenario import GenParams, generate, parse_generated_id, scenario_id
from league.engine.scenario import instantiate
from league.engine.state import AgentSlot, MatchState, state_to_json
from league.engine.tick import outcome_points, resolve_turn, start_match

BASE = GenParams(grid_width=13, grid_height=11, turn_limit=20)
CROWNED = dataclasses.replace(BASE, crown_value=4, crown_turns=3)


def _roster(team: str) -> tuple[AgentSlot, ...]:
    return (
        AgentSlot(id=f"{team}-1", model="m", role="scout"),
        AgentSlot(id=f"{team}-2", model="m", role="harvester"),
        AgentSlot(id=f"{team}-3", model="m", role="defender"),
    )


def _match(params=CROWNED):
    scenario = generate(5, params)
    state = instantiate(
        scenario,
        match_id="m-crown",
        seed=0,
        mode="competitive",
        teams=(("blue", "Blue", _roster("blue")), ("red", "Red", _roster("red"))),
    )
    state, _ = start_match(state)
    return scenario, state


def _place(state: MatchState, unit_id: str, pos) -> MatchState:
    units = tuple(
        dataclasses.replace(u, pos=tuple(pos)) if u.id == unit_id else u for u in state.units
    )
    return dataclasses.replace(state, units=units)


def _hold(scenario, state, turns):
    for _ in range(turns):
        state, _ = resolve_turn(state, scenario, {})
    return state


def test_default_ids_unchanged_and_new_knobs_round_trip():
    assert scenario_id(5, BASE) == "gen-5-w13y11t20c1r1m1k2"
    params = dataclasses.replace(BASE, node_stock=5, deliver_amount=9, crown_value=4, crown_turns=6)
    sid = scenario_id(5, params)
    assert sid == "gen-5-w13y11t20c1r1m1k2s5d9x4z6"
    assert parse_generated_id(sid) == (5, params)
    scenario = generate(5, params)
    assert all(n.remaining == 5 for n in scenario.resource_nodes)
    assert next(m for m in scenario.missions if m.kind == "deliver").amount == 9
    assert (scenario.crown.pos, scenario.crown.value, scenario.crown.hold_turns) == ((6, 5), 4, 6)


def test_crown_free_state_json_has_no_crown_key():
    scenario, state = _match(BASE)
    assert scenario.crown is None and '"crown"' not in state_to_json(state)


def test_sole_hold_for_hold_turns_takes_the_crown_once():
    scenario, state = _match()
    state = _place(state, "blue-u3", scenario.crown.pos)
    state = _hold(scenario, state, 2)
    assert state.crown.taken_by is None and dict(state.crown.hold) == {"blue": 2}
    state = _hold(scenario, state, 1)
    assert state.crown.taken_by == "blue"
    assert outcome_points(state)["blue"] == 4
    state = _hold(scenario, state, 3)  # taken once: no further award
    assert outcome_points(state)["blue"] == 4


def test_contest_resets_and_scouts_count_for_nothing():
    scenario, state = _match()
    state = _place(state, "blue-u3", scenario.crown.pos)
    state = _place(state, "red-u1", scenario.crown.pos)  # red scout: ignored
    state = _hold(scenario, state, 2)
    assert dict(state.crown.hold) == {"blue": 2}
    state = _place(state, "red-u2", scenario.crown.pos)  # red harvester: contests
    state = _hold(scenario, state, 1)
    assert state.crown.hold == ()
    state = _hold(scenario, state, 5)
    assert state.crown.taken_by is None
