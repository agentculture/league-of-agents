"""Wave-2 acceptance tests for the tick engine (plan task t4).

Criteria under test:

* pure resolution: same inputs → identical outputs on repeated runs;
* no dependence on submission order — canonical (team, unit) order rules;
* documented v0 rules: one action per unit, validation-with-rejection-events,
  scarce gathers drain canonically, capture/hold/contest streaks, mission
  completion, end conditions, and the winner rule (including draws).
"""

from __future__ import annotations

import dataclasses

import pytest

from league.engine.scenario import get_scenario, instantiate
from league.engine.state import AgentSlot, MatchState, state_hash
from league.engine.tick import outcome_points, resolve_turn, start_match

SCENARIO = get_scenario("skirmish-1")


def _roster(team: str, model: str = "colleague/qwen") -> tuple[AgentSlot, ...]:
    return (
        AgentSlot(id=f"{team}-scout", model=model, role="scout"),
        AgentSlot(id=f"{team}-harvester", model=model, role="harvester"),
        AgentSlot(id=f"{team}-defender", model=model, role="defender"),
    )


def active_match(**overrides) -> MatchState:
    state = instantiate(
        SCENARIO,
        match_id="m-tick",
        seed=99,
        mode="competitive",
        teams=(
            ("blue", "Blue Foundry", _roster("blue")),
            ("red", "Red Relay", _roster("red", model="claude-sonnet-5")),
        ),
    )
    state, _ = start_match(state)
    return dataclasses.replace(state, **overrides) if overrides else state


def _move_unit(state: MatchState, unit_id: str, pos: tuple[int, int]) -> MatchState:
    units = tuple(dataclasses.replace(u, pos=pos) if u.id == unit_id else u for u in state.units)
    return dataclasses.replace(state, units=units)


def test_resolution_is_pure_and_deterministic() -> None:
    state = active_match()
    orders = {
        "blue": {
            "plan": "scout east, harvest west",
            "messages": [{"from": "blue-scout", "text": "moving out"}],
            "actions": [
                {"unit_id": "blue-u1", "action": "move", "to": [3, 1]},
                {"unit_id": "blue-u2", "action": "move", "to": [1, 2]},
            ],
        },
        "red": {"actions": [{"unit_id": "red-u1", "action": "move", "to": [9, 8]}]},
    }
    first_state, first_events = resolve_turn(state, SCENARIO, orders)
    second_state, second_events = resolve_turn(state, SCENARIO, orders)
    assert state_hash(first_state) == state_hash(second_state)
    assert first_events == second_events


def test_submission_order_is_irrelevant() -> None:
    state = active_match()
    blue_actions = [
        {"unit_id": "blue-u1", "action": "move", "to": [3, 1]},
        {"unit_id": "blue-u2", "action": "move", "to": [1, 2]},
    ]
    forward = {
        "blue": {"actions": blue_actions},
        "red": {"actions": [{"unit_id": "red-u1", "action": "move", "to": [9, 8]}]},
    }
    shuffled = {
        "red": {"actions": [{"unit_id": "red-u1", "action": "move", "to": [9, 8]}]},
        "blue": {"actions": list(reversed(blue_actions))},
    }
    a_state, a_events = resolve_turn(state, SCENARIO, forward)
    b_state, b_events = resolve_turn(state, SCENARIO, shuffled)
    assert state_hash(a_state) == state_hash(b_state)
    assert a_events == b_events


def test_invalid_orders_reject_loudly_and_do_nothing() -> None:
    state = active_match()
    orders = {
        "blue": {
            "actions": [
                {"unit_id": "blue-u1", "action": "move", "to": [99, 99]},  # off grid
                {"unit_id": "blue-u2", "action": "move", "to": [11, 9]},  # beyond range
                {"unit_id": "red-u1", "action": "move", "to": [9, 8]},  # not blue's unit
                {"unit_id": "blue-u3", "action": "gather"},  # not on a node
                {"unit_id": "blue-u3", "action": "deliver"},  # already acted + nothing held
            ]
        }
    }
    new_state, events = resolve_turn(state, SCENARIO, orders)
    rejected = [e for e in events if e.kind == "action_rejected"]
    assert len(rejected) == 5
    reasons = {e.data["reason"] for e in rejected}
    assert "target is off the grid" in reasons
    assert "target beyond this role's move range" in reasons
    assert "no such unit on this team" in reasons
    # Board unchanged apart from the clock.
    assert [u.pos for u in new_state.units] == [u.pos for u in state.units]
    assert new_state.turn == state.turn + 1


def test_one_action_per_unit_per_turn() -> None:
    state = active_match()
    orders = {
        "blue": {
            "actions": [
                {"unit_id": "blue-u1", "action": "move", "to": [2, 0]},
                {"unit_id": "blue-u1", "action": "move", "to": [3, 0]},
            ]
        }
    }
    _, events = resolve_turn(state, SCENARIO, orders)
    rejected = [e for e in events if e.kind == "action_rejected"]
    assert [e.data["reason"] for e in rejected] == ["unit already acted this turn"]


def test_gather_respects_capacity_and_canonical_scarcity() -> None:
    state = active_match()
    # Blue harvester (carry 3) and red harvester (carry 3) both on a node with 4.
    state = _move_unit(state, "blue-u2", (0, 5))
    state = _move_unit(state, "red-u2", (0, 5))
    nodes = tuple(
        dataclasses.replace(n, remaining=4) if n.id == "rn-west" else n
        for n in state.resource_nodes
    )
    state = dataclasses.replace(state, resource_nodes=nodes)
    orders = {
        "blue": {"actions": [{"unit_id": "blue-u2", "action": "gather"}]},
        "red": {"actions": [{"unit_id": "red-u2", "action": "gather"}]},
    }
    new_state, events = resolve_turn(state, SCENARIO, orders)
    gathered = {
        e.data["unit_id"]: e.data["amount"] for e in events if e.kind == "resource_gathered"
    }
    assert gathered == {"blue-u2": 3, "red-u2": 1}  # canonical order drains first
    node = next(n for n in new_state.resource_nodes if n.id == "rn-west")
    assert node.remaining == 0


def test_capture_then_hold_mission_completes() -> None:
    state = active_match()
    state = _move_unit(state, "blue-u3", (9, 2))  # defender parks on cp-east
    hold_needed = (
        SCENARIO.capture_hold_turns + next(m for m in SCENARIO.missions if m.kind == "hold").amount
    )
    captured_at = None
    completed_at = None
    for i in range(hold_needed):
        state, events = resolve_turn(
            state, SCENARIO, {"blue": {"actions": [{"unit_id": "blue-u3", "action": "hold"}]}}
        )
        if any(e.kind == "control_point_captured" for e in events):
            captured_at = i + 1
        if any(e.kind == "mission_completed" for e in events):
            completed_at = i + 1
    assert captured_at == SCENARIO.capture_hold_turns
    assert completed_at == hold_needed
    cp = next(c for c in state.control_points if c.id == "cp-east")
    assert cp.owner == "blue"
    mission = next(m for m in state.missions if m.id == "ms-outpost")
    assert mission.status == "completed"
    assert mission.completed_by == ("blue",)


def test_scout_occupancy_never_builds_a_capture_streak() -> None:
    """Cycle-8 t10 decision: the grid scout is eyes-only, exactly like the
    explorer/planner (tests/test_engine_roles.py) — its occupancy of a
    control point never builds or contests a streak."""
    state = active_match()
    state = _move_unit(state, "blue-u1", (9, 2))  # scout parks on cp-east
    captured = False
    for _ in range(SCENARIO.capture_hold_turns + 1):
        state, events = resolve_turn(
            state, SCENARIO, {"blue": {"actions": [{"unit_id": "blue-u1", "action": "hold"}]}}
        )
        if any(e.kind == "control_point_captured" for e in events):
            captured = True
    assert not captured
    cp = next(c for c in state.control_points if c.id == "cp-east")
    assert cp.owner is None
    assert cp.hold == ()


def test_scout_alone_on_a_point_gets_an_explicit_capture_rejection() -> None:
    """Not a silent skip: standing alone on a point a scout can never capture
    emits the engine's standard failure treatment — an ``action_rejected``
    event with a clear reason — every turn it recurs, mirroring how the
    continuous lane explicitly rejects its own eyes-only scout's take_post."""
    state = active_match()
    state = _move_unit(state, "blue-u1", (9, 2))  # cp-east
    state, events = resolve_turn(
        state, SCENARIO, {"blue": {"actions": [{"unit_id": "blue-u1", "action": "hold"}]}}
    )
    rejections = [e for e in events if e.kind == "action_rejected"]
    assert len(rejections) == 1
    reason = rejections[0]
    assert reason.data == {
        "team_id": "blue",
        "unit_id": "blue-u1",
        "reason": "this role cannot capture control points",
    }
    # It recurs: the scout is still there, still ineligible, next turn too.
    state, events = resolve_turn(
        state, SCENARIO, {"blue": {"actions": [{"unit_id": "blue-u1", "action": "hold"}]}}
    )
    assert [e.data["reason"] for e in events if e.kind == "action_rejected"] == [
        "this role cannot capture control points"
    ]


def test_scout_alongside_a_capable_teammate_is_not_rejected_redundantly() -> None:
    """The rejection only fires when the scout's team has no OTHER occupant
    already covering the point — a capable teammate standing beside it means
    the team's occupancy is already decided, so the scout's own presence is
    genuinely irrelevant, not worth a redundant event."""
    state = active_match()
    state = _move_unit(state, "blue-u1", (9, 2))  # scout, cp-east
    state = _move_unit(state, "blue-u3", (9, 2))  # defender, same square
    state, events = resolve_turn(
        state,
        SCENARIO,
        {
            "blue": {
                "actions": [
                    {"unit_id": "blue-u1", "action": "hold"},
                    {"unit_id": "blue-u3", "action": "hold"},
                ]
            }
        },
    )
    assert not [e for e in events if e.kind == "action_rejected"]
    cp = next(c for c in state.control_points if c.id == "cp-east")
    assert cp.hold == (("blue", 1),)


def test_enemy_scout_does_not_contest_a_capture_streak() -> None:
    """The both-ways contrast for the eyes-only scout: it can neither BUILD a
    streak (proven above) NOR contest one. A blue defender captures cp-east
    with an enemy scout standing right there — a defender contesting the
    identical square resets the streak instead (test_contested_point_resets_
    the_streak already proves the contest side with two defenders)."""
    state = active_match()
    state = _move_unit(state, "blue-u3", (9, 2))  # blue defender
    state = _move_unit(state, "red-u1", (9, 2))  # red scout — should not count
    captured = False
    for _ in range(SCENARIO.capture_hold_turns):
        state, events = resolve_turn(
            state, SCENARIO, {"blue": {"actions": [{"unit_id": "blue-u3", "action": "hold"}]}}
        )
        if any(e.kind == "control_point_captured" for e in events):
            captured = True
    assert captured
    cp = next(c for c in state.control_points if c.id == "cp-east")
    assert cp.owner == "blue"


def test_contested_point_resets_the_streak() -> None:
    state = active_match()
    state = _move_unit(state, "blue-u3", (6, 5))
    state, _ = resolve_turn(
        state, SCENARIO, {"blue": {"actions": [{"unit_id": "blue-u3", "action": "hold"}]}}
    )
    cp = next(c for c in state.control_points if c.id == "cp-center")
    assert cp.hold == (("blue", 1),)
    # Red walks on: contested — streak resets.
    state = _move_unit(state, "red-u3", (6, 5))
    state, _ = resolve_turn(state, SCENARIO, {})
    cp = next(c for c in state.control_points if c.id == "cp-center")
    assert cp.hold == ()
    assert cp.owner is None


def test_deliver_mission_and_delivery_flow() -> None:
    state = active_match()
    # Harvester teleported onto the node, gathers, walks the relay, delivers.
    state = _move_unit(state, "blue-u2", (0, 5))
    state, events = resolve_turn(
        state, SCENARIO, {"blue": {"actions": [{"unit_id": "blue-u2", "action": "gather"}]}}
    )
    assert any(e.kind == "resource_gathered" for e in events)
    state = _move_unit(state, "blue-u2", (6, 5))
    state, events = resolve_turn(
        state, SCENARIO, {"blue": {"actions": [{"unit_id": "blue-u2", "action": "deliver"}]}}
    )
    assert any(e.kind == "resource_delivered" for e in events)
    blue = next(t for t in state.teams if t.id == "blue")
    assert blue.resources == 3
    # Top the team up to the mission amount: completion fires on the next tick.
    teams = tuple(dataclasses.replace(t, resources=6) if t.id == "blue" else t for t in state.teams)
    state = dataclasses.replace(state, teams=teams)
    state, events = resolve_turn(state, SCENARIO, {})
    completed = [e for e in events if e.kind == "mission_completed"]
    assert [e.data["team_id"] for e in completed] == ["blue"]
    assert state.status == "active"  # the hold mission is still open


def test_dead_heat_deliver_awards_both_teams_the_full_reward() -> None:
    """Regression for the season-0 orchestrator match (t16): both harvesters
    delivered the mission's sixth resource on the same turn and the old rule
    (larger total, then lexicographic team id) handed ms-supply to whichever
    id sorted first. Spec decision c15: a dead-heat is a DUAL AWARD — every
    qualifying team completes the mission for the full reward."""
    state = active_match()
    state = _move_unit(state, "blue-u2", (6, 5))
    state = _move_unit(state, "red-u2", (6, 5))
    units = tuple(
        dataclasses.replace(u, carrying=3) if u.id in ("blue-u2", "red-u2") else u
        for u in state.units
    )
    teams = tuple(dataclasses.replace(t, resources=3) for t in state.teams)
    state = dataclasses.replace(state, units=units, teams=teams)
    orders = {
        "blue": {"actions": [{"unit_id": "blue-u2", "action": "deliver"}]},
        "red": {"actions": [{"unit_id": "red-u2", "action": "deliver"}]},
    }
    state, events = resolve_turn(state, SCENARIO, orders)
    completed = [e for e in events if e.kind == "mission_completed"]
    assert [e.data["team_id"] for e in completed] == ["blue", "red"]
    assert {e.data["mission_id"] for e in completed} == {"ms-supply"}
    mission = next(m for m in state.missions if m.id == "ms-supply")
    assert mission.status == "completed"
    assert mission.completed_by == ("blue", "red")
    points = outcome_points(state)
    assert points["blue"] == points["red"] == mission.reward + 6  # full reward each


def test_dead_heat_award_ignores_total_margin() -> None:
    """The larger-total tiebreak is gone too: overshooting the amount claims
    nothing extra — every team at or over it completes for the full reward."""
    state = active_match()
    state = _move_unit(state, "blue-u2", (6, 5))
    state = _move_unit(state, "red-u2", (6, 5))
    units = tuple(
        dataclasses.replace(u, carrying=3) if u.id in ("blue-u2", "red-u2") else u
        for u in state.units
    )
    teams = tuple(  # blue lands on 6 exactly; red overshoots to 7
        dataclasses.replace(t, resources=3 if t.id == "blue" else 4) for t in state.teams
    )
    state = dataclasses.replace(state, units=units, teams=teams)
    orders = {
        "blue": {"actions": [{"unit_id": "blue-u2", "action": "deliver"}]},
        "red": {"actions": [{"unit_id": "red-u2", "action": "deliver"}]},
    }
    state, _ = resolve_turn(state, SCENARIO, orders)
    mission = next(m for m in state.missions if m.id == "ms-supply")
    assert mission.completed_by == ("blue", "red")
    points = outcome_points(state)
    assert points["blue"] == mission.reward + 6
    assert points["red"] == mission.reward + 7


def _mirror_match(side0: str, side1: str) -> MatchState:
    """Both seats play the identical script; only the team-id labels differ.

    The board is deliberately asymmetric in one physical way — side 0 owns a
    control point — so the finished match has a real winner the assertion can
    track across the renaming."""
    state = instantiate(
        SCENARIO,
        match_id="m-mirror",
        seed=7,
        mode="competitive",
        teams=((side0, "Side Zero", _roster(side0)), (side1, "Side One", _roster(side1))),
    )
    state, _ = start_match(state)
    state = _move_unit(state, f"{side0}-u2", (6, 5))
    state = _move_unit(state, f"{side1}-u2", (6, 5))
    units = tuple(
        dataclasses.replace(u, carrying=3) if u.id.endswith("-u2") else u for u in state.units
    )
    teams = tuple(dataclasses.replace(t, resources=3) for t in state.teams)
    cps = tuple(
        dataclasses.replace(c, owner=side0) if c.id == "cp-east" else c
        for c in state.control_points
    )
    state = dataclasses.replace(
        state, units=units, teams=teams, control_points=cps, turn=state.turn_limit - 2
    )
    orders = {
        side0: {"actions": [{"unit_id": f"{side0}-u2", "action": "deliver"}]},
        side1: {"actions": [{"unit_id": f"{side1}-u2", "action": "deliver"}]},
    }
    state, _ = resolve_turn(state, SCENARIO, orders)  # the dead-heat turn
    state, _ = resolve_turn(state, SCENARIO, {})  # the clock hits the limit
    assert state.status == "finished"
    return state


def test_team_id_swap_leaves_outcomes_mirror_identical() -> None:
    """No id-order bias: rename the teams of an otherwise identical scripted
    match and the outcome is the exact mirror image. Under the old dead-heat
    rule the lexicographically-first id took the mission in BOTH runs, so the
    same seat won or lost depending on what it was called."""
    a = _mirror_match("alpha", "zulu")  # side 0 sorts first
    b = _mirror_match("zulu", "alpha")  # side 0 sorts last
    points_a, points_b = outcome_points(a), outcome_points(b)
    assert points_a["alpha"] == points_b["zulu"]  # side 0's tally, either name
    assert points_a["zulu"] == points_b["alpha"]  # side 1's tally, either name
    assert a.winner == "alpha"  # side 0 wins on the extra control point…
    assert b.winner == "zulu"  # …whatever its id sorts like
    for state in (a, b):
        supply = next(m for m in state.missions if m.id == "ms-supply")
        assert supply.completed_by == ("alpha", "zulu")


def test_hold_mission_dead_heat_is_unreachable_by_construction() -> None:
    """Why there is no hold-mission dual-award path: a hold mission completes
    off its control point's streak, and ``ControlPoint.hold`` stores at most
    one ``(team, turns)`` entry — sole occupancy builds it, any contest resets
    it to ``()``. Two teams can therefore never satisfy the hold condition on
    the same turn. This test pins that structural premise so the documentation
    fails loudly if the streak model ever changes."""
    state = active_match()
    state = _move_unit(state, "blue-u3", (9, 2))
    state = _move_unit(state, "red-u3", (9, 2))
    cps = tuple(  # blue arrives with overwhelming prior progress on the books
        dataclasses.replace(c, owner="blue", hold=(("blue", 99),)) if c.id == "cp-east" else c
        for c in state.control_points
    )
    state = dataclasses.replace(state, control_points=cps)
    state, events = resolve_turn(state, SCENARIO, {})
    assert not [e for e in events if e.kind == "mission_completed"]
    cp = next(c for c in state.control_points if c.id == "cp-east")
    assert cp.hold == ()  # contested → the single-entry streak resets outright


def test_turn_limit_ends_the_match_with_a_winner() -> None:
    state = active_match()
    teams = tuple(dataclasses.replace(t, resources=5) if t.id == "blue" else t for t in state.teams)
    state = dataclasses.replace(state, teams=teams, turn=state.turn_limit - 1)
    state, events = resolve_turn(state, SCENARIO, {})
    assert state.status == "finished"
    assert state.winner == "blue"
    assert any(e.kind == "match_finished" for e in events)
    with pytest.raises(ValueError):
        resolve_turn(state, SCENARIO, {})


def test_equal_points_is_a_draw() -> None:
    state = active_match()
    state = dataclasses.replace(state, turn=state.turn_limit - 1)
    state, _ = resolve_turn(state, SCENARIO, {})
    assert state.status == "finished"
    assert outcome_points(state)["blue"] == outcome_points(state)["red"]
    assert state.winner == "draw"


def test_cooperative_win_and_loss() -> None:
    coop = instantiate(
        SCENARIO,
        match_id="m-coop",
        seed=1,
        mode="cooperative",
        teams=(("blue", "Blue Foundry", _roster("blue")),),
    )
    coop, _ = start_match(coop)
    # Loss: the clock runs out with missions open — finished, no winner.
    lost = dataclasses.replace(coop, turn=coop.turn_limit - 1)
    lost, _ = resolve_turn(lost, SCENARIO, {})
    assert lost.status == "finished"
    assert lost.winner is None
    # Win: all missions completed inside the limit.
    missions = tuple(
        dataclasses.replace(m, status="completed", completed_by=("blue",), completed_turn=1)
        for m in coop.missions
    )
    won = dataclasses.replace(coop, missions=missions)
    won, _ = resolve_turn(won, SCENARIO, {})
    assert won.status == "finished"
    assert won.winner == "blue"


def test_lifecycle_guards() -> None:
    pending = instantiate(
        SCENARIO,
        match_id="m-guard",
        seed=1,
        mode="competitive",
        teams=(
            ("blue", "Blue Foundry", _roster("blue")),
            ("red", "Red Relay", _roster("red")),
        ),
    )
    with pytest.raises(ValueError):
        resolve_turn(pending, SCENARIO, {})
    active, _ = start_match(pending)
    with pytest.raises(ValueError):
        start_match(active)
