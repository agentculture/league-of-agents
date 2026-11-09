"""Control-point vision: an owned point watches its area for its owner, from
capture (not arrival) until the other team captures it, and the owner learns
of that capture the same turn."""

import dataclasses

from league.cli._commands.arena import _scenario_dict
from league.engine.genscenario import GenParams, generate, parse_generated_id, scenario_id
from league.engine.knowledge import fold_knowledge, initial_knowledge
from league.engine.scenario import instantiate
from league.engine.state import AgentSlot, MatchState
from league.engine.tick import resolve_turn, start_match
from league.engine.vision import team_visible_cells
from league.harness import _rules_text

BASE = GenParams(grid_width=13, grid_height=11, turn_limit=20)
WATCH = dataclasses.replace(BASE, cp_vision=2)


def _roster(team: str):
    roles = ("scout", "harvester", "defender")
    return tuple(AgentSlot(id=f"{team}-{i}", model="m", role=r) for i, r in enumerate(roles, 1))


def _match(params=WATCH):
    scenario = generate(5, params)
    state = instantiate(
        scenario,
        match_id="m-watch",
        seed=0,
        mode="competitive",
        teams=(("blue", "Blue", _roster("blue")), ("red", "Red", _roster("red"))),
    )
    state, _ = start_match(state)
    return scenario, state


def _set(state: MatchState, unit_id: str, **changes) -> MatchState:
    units = tuple(dataclasses.replace(u, **changes) if u.id == unit_id else u for u in state.units)
    return dataclasses.replace(state, units=units)


def _defender(state, team):
    return next(u for u in state.units if u.team_id == team and u.role == "defender")


def _far_corner_cell(scenario, cp):
    """A cell exactly 2 from the point (inside cp_vision 2), away from units."""
    x, y = cp.pos
    return next(
        (x + dx, y + dy)
        for dx, dy in ((2, 0), (-2, 0), (0, 2), (0, -2))
        if 0 <= x + dx < scenario.grid_width and 0 <= y + dy < scenario.grid_height
    )


def test_ids_round_trip_and_default_unchanged():
    assert scenario_id(5, BASE) == "gen-5-w13y11t20c1r1m1k2"
    sid = scenario_id(5, WATCH)
    assert sid == "gen-5-w13y11t20c1r1m1k2o2"
    assert parse_generated_id(sid) == (5, WATCH)
    assert generate(5, BASE).cp_vision == 0


def test_view_comes_with_capture_not_arrival_and_goes_with_loss():
    scenario, state = _match()
    cp = state.control_points[0]
    watch = _far_corner_cell(scenario, cp)
    blue = _defender(state, "blue")
    # Park every other unit far away so only the point can see `watch`.
    state = _set(state, blue.id, pos=cp.pos)
    assert watch in team_visible_cells(state, scenario, "blue")  # the defender itself sees it
    # Arrival alone: the point is not owned, so it grants nothing.
    assert cp.owner is None
    for _ in range(scenario.capture_hold_turns):
        state, _ = resolve_turn(state, scenario, {})
    assert next(c for c in state.control_points if c.id == cp.id).owner == "blue"
    # Walk away: the point keeps watching for blue.
    away = (0, 0) if cp.pos != (0, 0) else (scenario.grid_width - 1, 0)
    state = _set(state, blue.id, pos=away)
    assert watch in team_visible_cells(state, scenario, "blue")
    unowned = dataclasses.replace(
        state,
        control_points=tuple(dataclasses.replace(c, owner=None) for c in state.control_points),
    )
    assert watch not in team_visible_cells(unowned, scenario, "blue")  # it is the point's view

    # Red sits on it; blue sees red there during the streak, then loses it.
    red = _defender(state, "red")
    state = _set(state, red.id, pos=cp.pos)
    frame = initial_knowledge(state, scenario, "blue")
    assert any(u.id == red.id and u.pos == cp.pos for u in frame.units)
    for _ in range(scenario.capture_hold_turns):
        state, events = resolve_turn(state, scenario, {})
        frame = fold_knowledge(frame, events, state, scenario)
    assert next(c for c in state.control_points if c.id == cp.id).owner == "red"
    assert cp.pos not in team_visible_cells(state, scenario, "blue")
    known = next(c for c in frame.control_points if c.id == cp.id)
    assert (known.owner, known.turn) == ("red", state.turn)


def test_off_by_default_owned_points_see_nothing():
    scenario, state = _match(BASE)
    cp = state.control_points[0]
    owned = dataclasses.replace(
        state,
        control_points=tuple(
            dataclasses.replace(c, owner="blue") if c.id == cp.id else c
            for c in state.control_points
        ),
    )
    assert team_visible_cells(owned, scenario, "blue") == team_visible_cells(
        state, scenario, "blue"
    )


def test_rules_text_only_with_fog_and_cp_vision():
    watch = _scenario_dict(generate(5, WATCH))
    assert "Control points watch." in _rules_text(watch, fog=True)
    assert "Control points watch." not in _rules_text(watch, fog=False)
    assert "Control points watch." not in _rules_text(_scenario_dict(generate(5, BASE)), fog=True)
