"""Burden: on a board with cargo_slows, a unit carrying cargo moves 1 less
than its role's move stat (never below 1); boards without it are unchanged."""

import dataclasses

from league.cli._commands.arena import _scenario_dict
from league.engine.genscenario import GenParams, generate, parse_generated_id, scenario_id
from league.engine.legal import legal_actions
from league.engine.scenario import instantiate
from league.engine.state import AgentSlot, MatchState
from league.engine.tick import resolve_turn, start_match
from league.harness import _rules_text

BASE = GenParams(grid_width=13, grid_height=11, turn_limit=20, thieves=1)
BURDEN = dataclasses.replace(BASE, cargo_slows=1)


def _match(params):
    scenario = generate(5, params)
    roles = ("scout", "harvester", "defender", "thief")
    teams = tuple(
        (
            t,
            t.title(),
            tuple(AgentSlot(id=f"{t}-{i}", model="m", role=r) for i, r in enumerate(roles, 1)),
        )
        for t in ("blue", "red")
    )
    state = instantiate(scenario, match_id="m-burden", seed=0, mode="competitive", teams=teams)
    state, _ = start_match(state)
    return scenario, state


def _unit(state: MatchState, team: str, role: str):
    return next(u for u in state.units if u.team_id == team and u.role == role)


def _set(state: MatchState, unit_id: str, **changes) -> MatchState:
    units = tuple(dataclasses.replace(u, **changes) if u.id == unit_id else u for u in state.units)
    return dataclasses.replace(state, units=units)


def _reach(state, scenario, unit_id):
    unit = next(u for u in state.units if u.id == unit_id)
    return max(
        abs(x - unit.pos[0]) + abs(y - unit.pos[1])
        for x, y in legal_actions(state, scenario, unit_id)["move"]
    )


def test_ids_round_trip_and_old_ids_unchanged():
    assert scenario_id(5, BASE) == "gen-5-w13y11t20c1r1m1k2f1"
    sid = scenario_id(5, BURDEN)
    assert sid == "gen-5-w13y11t20c1r1m1k2f1b1"
    assert parse_generated_id(sid) == (5, BURDEN)
    assert generate(5, BASE).cargo_slows is False and generate(5, BURDEN).cargo_slows is True


def test_move_for_each_role():
    scenario = generate(5, BURDEN)
    assert [scenario.move_for(r, 1) for r in ("scout", "harvester", "defender", "thief")] == [
        2,
        1,
        1,
        2,
    ]
    assert [scenario.move_for(r, 0) for r in ("scout", "harvester", "defender", "thief")] == [
        3,
        2,
        2,
        3,
    ]
    plain = generate(5, BASE)
    assert plain.move_for("harvester", 3) == 2


def test_legal_moves_shrink_while_carrying():
    scenario, state = _match(BURDEN)
    scout = _unit(state, "blue", "scout")
    state = _set(state, scout.id, pos=(6, 5))
    assert _reach(state, scenario, scout.id) == 3
    loaded = _set(state, scout.id, carrying=1)
    assert _reach(loaded, scenario, scout.id) == 2


def test_tick_rejects_a_full_range_move_while_carrying_and_says_why():
    scenario, state = _match(BURDEN)
    scout = _unit(state, "blue", "scout")
    state = _set(state, scout.id, pos=(6, 5), carrying=1)
    orders = {"blue": {"actions": [{"unit_id": scout.id, "action": "move", "to": [9, 5]}]}}
    state2, events = resolve_turn(state, scenario, orders)
    (rej,) = [e for e in events if e.kind == "action_rejected"]
    assert rej.data["reason"] == "target beyond this unit's move range (2, slowed by its cargo)"
    assert next(u for u in state2.units if u.id == scout.id).pos == (6, 5)
    orders = {"blue": {"actions": [{"unit_id": scout.id, "action": "move", "to": [8, 5]}]}}
    state3, _ = resolve_turn(state, scenario, orders)
    assert next(u for u in state3.units if u.id == scout.id).pos == (8, 5)


def test_no_burden_board_keeps_full_range_with_cargo():
    scenario, state = _match(BASE)
    scout = _unit(state, "blue", "scout")
    state = _set(state, scout.id, pos=(6, 5), carrying=1)
    assert _reach(state, scenario, scout.id) == 3


def test_rules_text_states_burden_only_when_on():
    assert "Burden." in _rules_text(_scenario_dict(generate(5, BURDEN)), fog=False)
    assert "Burden." not in _rules_text(_scenario_dict(generate(5, BASE)), fog=False)
    assert "Burden:" in generate(5, BURDEN).description
