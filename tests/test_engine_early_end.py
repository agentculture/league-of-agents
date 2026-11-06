"""Early end: an out-of-reach lead ends the match; so does a lead of at least
N% of the most the gap could still close by, held K turns from turn T."""

import dataclasses

from league.cli._commands.arena import _scenario_dict
from league.engine.early_end import max_swing
from league.engine.genscenario import GenParams, generate, parse_generated_id, scenario_id
from league.engine.scenario import instantiate
from league.engine.state import AgentSlot, MatchState, state_to_json
from league.engine.tick import resolve_turn, start_match
from league.harness import _rules_text

BASE = GenParams(grid_width=13, grid_height=11, turn_limit=20)


def _roster(team: str):
    roles = ("scout", "harvester", "defender")
    return tuple(AgentSlot(id=f"{team}-{i}", model="m", role=r) for i, r in enumerate(roles, 1))


def _match(params):
    scenario = generate(5, params)
    state = instantiate(
        scenario,
        match_id="m-early",
        seed=0,
        mode="competitive",
        teams=(("blue", "Blue", _roster("blue")), ("red", "Red", _roster("red"))),
    )
    state, _ = start_match(state)
    return scenario, state


def _resources(state: MatchState, team: str, amount: int) -> MatchState:
    teams = tuple(
        dataclasses.replace(t, resources=amount) if t.id == team else t for t in state.teams
    )
    return dataclasses.replace(state, teams=teams)


def _kinds(events):
    return [e.kind for e in events]


def test_ids_round_trip_and_default_ids_unchanged():
    assert scenario_id(5, BASE) == "gen-5-w13y11t20c1r1m1k2"
    on = dataclasses.replace(BASE, early_end_pct=50)
    assert scenario_id(5, on) == "gen-5-w13y11t20c1r1m1k2q50"
    full = dataclasses.replace(BASE, early_end_pct=50, early_end_turns=2, early_end_from=10)
    sid = scenario_id(5, full)
    assert sid == "gen-5-w13y11t20c1r1m1k2q50j2v10"
    assert parse_generated_id(sid) == (5, full)
    assert generate(5, BASE).early_end is None


def test_off_by_default_emits_nothing_and_state_json_unchanged():
    scenario, state = _match(BASE)
    state = _resources(state, "blue", 100)
    state, events = resolve_turn(state, scenario, {})
    assert "lead_held" not in _kinds(events) and "match_decided" not in _kinds(events)
    assert state.status == "active"
    assert "lead_hold" not in state_to_json(state)


def test_out_of_reach_lead_ends_the_match_at_once():
    scenario, state = _match(dataclasses.replace(BASE, early_end_pct=90, early_end_from=0))
    state = dataclasses.replace(_resources(state, "blue", 100), turn=state.turn_limit - 3)
    state, events = resolve_turn(state, scenario, {})
    (decided,) = [e for e in events if e.kind == "match_decided"]
    assert decided.data["reason"] == "out_of_reach"
    assert decided.data["lead"] > decided.data["max_swing"]
    assert (state.status, state.winner) == ("finished", "blue")


def test_relative_lead_must_hold_for_k_turns():
    params = dataclasses.replace(BASE, early_end_pct=10, early_end_turns=2, early_end_from=0)
    scenario, state = _match(params)
    state = _resources(state, "blue", 20)
    state, events = resolve_turn(state, scenario, {})
    assert state.status == "active" and state.lead_hold == (("blue", 1),)
    state, events = resolve_turn(state, scenario, {})
    (decided,) = [e for e in events if e.kind == "match_decided"]
    assert decided.data["reason"] == "relative_lead" and decided.data["turns"] == 2
    assert (state.status, state.winner) == ("finished", "blue")


def test_run_resets_when_the_lead_falls_below_the_threshold():
    params = dataclasses.replace(BASE, early_end_pct=10, early_end_turns=3, early_end_from=0)
    scenario, state = _match(params)
    state, _ = resolve_turn(_resources(state, "blue", 20), scenario, {})
    assert state.lead_hold == (("blue", 1),)
    # Blue banked 10 for the deliver mission on turn 1; level the score.
    state = _resources(_resources(state, "blue", 0), "red", 10)
    state, events = resolve_turn(state, scenario, {})
    assert state.lead_hold == ()
    assert any(e.kind == "lead_held" and e.data["turns"] == 0 for e in events)


def test_no_run_before_from_turn():
    params = dataclasses.replace(BASE, early_end_pct=10, early_end_turns=1, early_end_from=5)
    scenario, state = _match(params)
    state, events = resolve_turn(_resources(state, "blue", 20), scenario, {})
    assert state.status == "active" and state.lead_hold == ()


def test_max_swing_shrinks_as_turns_run_out():
    scenario, state = _match(dataclasses.replace(BASE, early_end_pct=50))
    early = max_swing(state, scenario, "blue", "red")
    late = max_swing(dataclasses.replace(state, turn=state.turn_limit - 1), scenario, "blue", "red")
    assert early > late >= sum(n.remaining for n in state.resource_nodes)
    assert (
        max_swing(dataclasses.replace(state, turn=state.turn_limit), scenario, "blue", "red") == 0
    )


def test_rules_text_states_the_rule_only_when_on():
    on = _scenario_dict(generate(5, dataclasses.replace(BASE, early_end_pct=50)))
    assert "Early end." in _rules_text(on, fog=False) and "50%" in _rules_text(on, fog=False)
    assert "Early end." not in _rules_text(_scenario_dict(generate(5, BASE)), fog=False)
