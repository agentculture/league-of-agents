"""The thief: steal exactly 1 from an enemy carrier on the thief's cell, unless
an enemy defender is there; thief carry 1; thief-free boards are unchanged."""

import dataclasses

from league.cli._commands.arena import _scenario_dict
from league.engine.genscenario import GenParams, generate, parse_generated_id, scenario_id
from league.engine.legal import legal_actions
from league.engine.scenario import instantiate
from league.engine.state import AgentSlot, MatchState
from league.engine.tick import resolve_turn, start_match
from league.harness import _format_legal_actions, _rules_text, _verbs

BASE = GenParams(grid_width=13, grid_height=11, turn_limit=20)
THIEVES = dataclasses.replace(BASE, thieves=1)
FREE_CELL = (6, 1)  # no objective sits here on the seed-5 thief board


def _roster(team: str, params: GenParams):
    roles = ["scout", "harvester", "defender"] + ["thief"] * params.thieves
    return tuple(AgentSlot(id=f"{team}-{i}", model="m", role=r) for i, r in enumerate(roles, 1))


def _match(params=THIEVES):
    scenario = generate(5, params)
    state = instantiate(
        scenario,
        match_id="m-thief",
        seed=0,
        mode="competitive",
        teams=(("blue", "Blue", _roster("blue", params)), ("red", "Red", _roster("red", params))),
    )
    state, _ = start_match(state)
    return scenario, state


def _unit(state: MatchState, team: str, role: str):
    return next(u for u in state.units if u.team_id == team and u.role == role)


def _set(state: MatchState, unit_id: str, **changes) -> MatchState:
    units = tuple(dataclasses.replace(u, **changes) if u.id == unit_id else u for u in state.units)
    return dataclasses.replace(state, units=units)


def _steal_setup(victim_role="harvester", carrying=3):
    scenario, state = _match()
    thief = _unit(state, "blue", "thief")
    victim = _unit(state, "red", victim_role)
    state = _set(state, thief.id, pos=FREE_CELL)
    state = _set(state, victim.id, pos=FREE_CELL, carrying=carrying)
    return scenario, state, thief, victim


def _carry(state, unit_id):
    return next(u.carrying for u in state.units if u.id == unit_id)


def _rejections(events):
    return [e.data["reason"] for e in events if e.kind == "action_rejected"]


def _steal(scenario, state, thief, extra=(), red=(), **fields):
    orders = {
        "blue": {"actions": [{"unit_id": thief.id, "action": "steal", **fields}, *extra]},
        "red": {"actions": list(red)},
    }
    return resolve_turn(state, scenario, orders)


def test_thief_free_ids_and_role_table_unchanged():
    assert scenario_id(5, BASE) == "gen-5-w13y11t20c1r1m1k2"
    assert "thief" not in dict(generate(5, BASE).role_stats)
    sid = scenario_id(5, THIEVES)
    assert sid == "gen-5-w13y11t20c1r1m1k2f1"
    assert parse_generated_id(sid) == (5, THIEVES)
    scenario = generate(5, THIEVES)
    assert scenario.unit_roles == ("scout", "harvester", "defender", "thief")
    stats = scenario.stats_for("thief")
    assert (stats.carry, stats.can_steal, stats.can_gather, stats.can_capture) == (
        1,
        True,
        False,
        False,
    )


def test_steal_takes_exactly_one_from_a_harvester():
    scenario, state, thief, victim = _steal_setup()
    state, events = _steal(scenario, state, thief)
    assert (_carry(state, thief.id), _carry(state, victim.id)) == (1, 2)
    (stolen,) = [e for e in events if e.kind == "resource_stolen"]
    assert stolen.data == {
        "unit_id": thief.id,
        "victim_id": victim.id,
        "team_id": "blue",
        "amount": 1,
    }


def test_enemy_defender_on_the_cell_blocks_the_steal():
    scenario, state, thief, victim = _steal_setup()
    guard = _unit(state, "red", "defender")
    state = _set(state, guard.id, pos=FREE_CELL)
    state, events = _steal(scenario, state, thief)
    assert _carry(state, victim.id) == 3 and _carry(state, thief.id) == 0
    assert "an enemy defender guards this cell" in _rejections(events)


def test_own_defender_does_not_block():
    scenario, state, thief, victim = _steal_setup()
    state = _set(state, _unit(state, "blue", "defender").id, pos=FREE_CELL)
    state, _ = _steal(scenario, state, thief)
    assert _carry(state, thief.id) == 1


def test_defender_arriving_this_turn_blocks_and_victim_leaving_escapes():
    scenario, state, thief, victim = _steal_setup()
    guard = _unit(state, "red", "defender")
    state = _set(state, guard.id, pos=(FREE_CELL[0] + 1, FREE_CELL[1]))
    _, events = _steal(
        scenario, state, thief, red=[{"unit_id": guard.id, "action": "move", "to": list(FREE_CELL)}]
    )
    assert "an enemy defender guards this cell" in _rejections(events)

    scenario, state, thief, victim = _steal_setup()
    away = [FREE_CELL[0] + 1, FREE_CELL[1]]
    state, events = _steal(
        scenario, state, thief, red=[{"unit_id": victim.id, "action": "move", "to": away}]
    )
    assert _carry(state, victim.id) == 3
    assert "no enemy unit carrying cargo on this cell" in _rejections(events)


def test_full_thief_and_empty_or_wrong_target_are_rejected():
    scenario, state, thief, victim = _steal_setup()
    full = _set(state, thief.id, carrying=1)
    _, events = _steal(scenario, full, thief)
    assert "already carrying to capacity" in _rejections(events)

    empty = _set(state, victim.id, carrying=0)
    _, events = _steal(scenario, empty, thief)
    assert "no enemy unit carrying cargo on this cell" in _rejections(events)

    _, events = _steal(scenario, state, thief, target="red-u9")
    assert "red-u9 is not an enemy unit carrying cargo on this cell" in _rejections(events)


def test_named_target_picks_the_victim():
    scenario, state, thief, victim = _steal_setup()
    scout = _unit(state, "red", "scout")
    state = _set(state, scout.id, pos=FREE_CELL, carrying=2)
    state, _ = _steal(scenario, state, thief, target=scout.id)
    assert (_carry(state, scout.id), _carry(state, victim.id)) == (1, 3)


def test_non_thief_cannot_steal_and_thief_cannot_gather():
    scenario, state, thief, victim = _steal_setup()
    harvester = _unit(state, "blue", "harvester")
    state = _set(state, harvester.id, pos=FREE_CELL)
    _, events = _steal(scenario, state, harvester)
    assert "this role cannot steal" in _rejections(events)
    node = scenario.resource_nodes[0]
    state = _set(state, thief.id, pos=node.pos)
    _, events = resolve_turn(
        state, scenario, {"blue": {"actions": [{"unit_id": thief.id, "action": "gather"}]}}
    )
    assert "this role cannot gather resources" in _rejections(events)


def test_stolen_cargo_delivers_for_the_thief_team():
    scenario, state, thief, victim = _steal_setup()
    state, _ = _steal(scenario, state, thief)
    deliver = next(m for m in state.missions if m.kind == "deliver")
    state = _set(state, thief.id, pos=deliver.pos)
    state, _ = resolve_turn(
        state, scenario, {"blue": {"actions": [{"unit_id": thief.id, "action": "deliver"}]}}
    )
    blue = next(t for t in state.teams if t.id == "blue")
    assert blue.resources == 1


def test_legal_actions_and_prompt_mention_steal_only_with_a_thief():
    scenario, state, thief, _ = _steal_setup()
    legal = legal_actions(state, scenario, thief.id)
    assert legal["steal"] is True and legal["can_steal"] is True
    line = _format_legal_actions({thief.id: legal}, [thief.id])
    assert "steal: yes" in line
    harvester = _unit(state, "blue", "harvester")
    assert "steal" not in legal_actions(state, scenario, harvester.id)

    with_thief = _scenario_dict(scenario)
    assert _verbs(with_thief) == "move|gather|deliver|steal|hold"
    assert "The thief." in _rules_text(with_thief, fog=False)
    plain = _scenario_dict(generate(5, BASE))
    assert _verbs(plain) == "move|gather|deliver|hold"
    assert "The thief." not in _rules_text(plain, fog=False)
