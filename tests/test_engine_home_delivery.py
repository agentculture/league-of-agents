"""Home delivery: each team delivers at its own spawn corner, for its own
deliver mission; shared-center boards are unchanged."""

import dataclasses

from league.cli._commands.arena import _scenario_dict
from league.engine.genscenario import GenParams, generate, parse_generated_id, scenario_id
from league.engine.legal import legal_actions
from league.engine.scenario import instantiate
from league.engine.state import AgentSlot, MatchState
from league.engine.tick import resolve_turn, start_match
from league.harness import _rules_text

BASE = GenParams(grid_width=13, grid_height=11, turn_limit=20)
HOME = dataclasses.replace(BASE, home_delivery=1, crown_value=4)


def _roster(team: str):
    roles = ("scout", "harvester", "defender")
    return tuple(AgentSlot(id=f"{team}-{i}", model="m", role=r) for i, r in enumerate(roles, 1))


def _match(params=HOME):
    scenario = generate(5, params)
    state = instantiate(
        scenario,
        match_id="m-home",
        seed=0,
        mode="competitive",
        teams=(("blue", "Blue", _roster("blue")), ("red", "Red", _roster("red"))),
    )
    state, _ = start_match(state)
    return scenario, state


def _set(state: MatchState, unit_id: str, **changes) -> MatchState:
    units = tuple(dataclasses.replace(u, **changes) if u.id == unit_id else u for u in state.units)
    return dataclasses.replace(state, units=units)


def _harvester(state, team):
    return next(u for u in state.units if u.team_id == team and u.role == "harvester")


def _deliver(scenario, state, unit):
    return resolve_turn(
        state, scenario, {unit.team_id: {"actions": [{"unit_id": unit.id, "action": "deliver"}]}}
    )


def test_ids_and_mission_layout():
    assert scenario_id(5, BASE) == "gen-5-w13y11t20c1r1m1k2"
    sid = scenario_id(5, HOME)
    assert sid == "gen-5-w13y11t20c1r1m1k2x4h1"
    assert parse_generated_id(sid) == (5, HOME)
    scenario, state = _match()
    homes = {m.team_id: m.pos for m in state.missions if m.kind == "deliver"}
    assert homes == {"blue": scenario.spawns[0][0], "red": scenario.spawns[1][0]}
    assert state.crown.pos not in homes.values()


def test_deliver_only_at_own_home_and_both_can_complete():
    scenario, state = _match()
    blue, red = _harvester(state, "blue"), _harvester(state, "red")
    homes = {m.team_id: m for m in state.missions if m.kind == "deliver"}
    # At the enemy's home: rejected.
    wrong = _set(state, blue.id, pos=homes["red"].pos, carrying=3)
    _, events = _deliver(scenario, wrong, blue)
    reasons = [e.data["reason"] for e in events if e.kind == "action_rejected"]
    assert "not standing on your team's delivery square" in reasons
    # Each at its own home, enough to complete: both complete their own.
    amount = homes["blue"].amount
    state = _set(state, blue.id, pos=homes["blue"].pos, carrying=amount)
    state = _set(state, red.id, pos=homes["red"].pos, carrying=amount)
    orders = {
        t: {"actions": [{"unit_id": u.id, "action": "deliver"}]}
        for t, u in (("blue", blue), ("red", red))
    }
    state, _ = resolve_turn(state, scenario, orders)
    done = {m.team_id: m.completed_by for m in state.missions if m.kind == "deliver"}
    assert done == {"blue": ("blue",), "red": ("red",)}
    assert legal_actions(state, scenario, blue.id)["deliver"] is False  # now empty


def test_rules_text_follows_the_layout():
    home = _rules_text(_scenario_dict(generate(5, HOME)), fog=False)
    assert "Home delivery." in home
    assert "same cell as the deliver mission" not in home
    shared = _rules_text(
        _scenario_dict(generate(5, dataclasses.replace(BASE, crown_value=4))), fog=False
    )
    assert "Home delivery." not in shared
    assert "same cell as the deliver mission" in shared
