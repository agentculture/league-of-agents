"""Fog view lists missions the team can actually know about, with live status.

Regression: the deliver mission sits on an empty cell (no control point or
resource node), so the old reveal rule (mission position must match a known
CP/node) never listed it, even with a unit standing on it; and missions were
read from the static scenario, so a completed mission still read "open".
"""

import dataclasses

from league.cli._commands.match import _fogged_state
from league.engine.genscenario import GenParams, generate
from league.engine.knowledge import KnowledgeFrame
from league.engine.scenario import instantiate
from league.engine.state import AgentSlot
from league.engine.tick import start_match

BASE = GenParams(grid_width=13, grid_height=11, turn_limit=20)


def _match(params=BASE):
    scenario = generate(5, params)

    def roster(t):
        roles = ("scout", "harvester", "defender")
        return tuple(AgentSlot(id=f"{t}-{i}", model="m", role=r) for i, r in enumerate(roles, 1))

    state = instantiate(
        scenario,
        match_id="m-fog",
        seed=0,
        mode="competitive",
        teams=(("blue", "Blue", roster("blue")), ("red", "Red", roster("red"))),
    )
    state, _ = start_match(state)
    return scenario, state


def _frame(cells=()):
    return KnowledgeFrame(
        team_id="blue",
        turn=0,
        units=(),
        resource_nodes=(),
        control_points=(),
        cells_seen=frozenset(cells),
    )


def _deliver(state):
    return next(m for m in state.missions if m.kind == "deliver")


def test_unseen_mission_stays_hidden():
    scenario, state = _match()
    view = _fogged_state(state, scenario, "blue", _frame())
    assert view["missions"] == []


def test_mission_on_a_seen_empty_cell_is_listed():
    scenario, state = _match()
    deliver = _deliver(state)
    view = _fogged_state(state, scenario, "blue", _frame([deliver.pos]))
    assert [m["id"] for m in view["missions"]] == [deliver.id]


def test_mission_on_the_announced_crown_cell_is_listed_unseen():
    scenario, state = _match(dataclasses.replace(BASE, crown_value=4))
    deliver = _deliver(state)
    assert state.crown.pos == deliver.pos
    view = _fogged_state(state, scenario, "blue", _frame())
    assert [m["id"] for m in view["missions"]] == [deliver.id]


def test_listed_mission_carries_live_status():
    scenario, state = _match()
    deliver = _deliver(state)
    done = dataclasses.replace(deliver, status="completed", completed_by=("red",), completed_turn=3)
    state = dataclasses.replace(
        state, missions=tuple(done if m.id == deliver.id else m for m in state.missions)
    )
    view = _fogged_state(state, scenario, "blue", _frame([deliver.pos]))
    (listed,) = view["missions"]
    assert (listed["status"], listed["completed_by"]) == ("completed", ["red"])
