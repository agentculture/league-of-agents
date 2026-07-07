"""Acceptance tests for the continuous action menu (plan C7-t5, the legal half).

These are the merge gate for ``league/engine/continuous/legal.py``. Written
before the implementation (TDD), they pin the continuous edition of the
legal<->resolver agreement (spec c9 acceptance): ``legal_actions_continuous``
reports every startable order *with its in-game duration*, and the resolver
accepts exactly what the menu offers — an action the menu shows always plans
(and therefore starts), an action it omits never plans (and therefore never
resolves). The resolver-side of the agreement lives in
``tests/test_continuous_resolve.py``; here we pin the menu itself and the shared
:func:`plan_action` oracle both sides consult.
"""

from __future__ import annotations

import pytest

from league.engine.continuous import (
    CAgentSlot,
    CControlPoint,
    CMatchState,
    CMission,
    CResourceNode,
    CTeamState,
    CUnit,
    build_role_table,
    from_units,
    legal_actions_continuous,
    move_duration,
    plan_action,
)

ROLE_TABLE = build_role_table()


# --------------------------------------------------------------------------- #
# Builders
# --------------------------------------------------------------------------- #
def _unit(uid, team, role, pos, carrying=0, alive=True):
    return CUnit(
        id=uid, team_id=team, agent_id=uid, role=role, pos=pos, carrying=carrying, alive=alive
    )


def _state(units, control_points=(), resource_nodes=(), missions=(), teams=None):
    teams = teams or (
        CTeamState(id="blue", name="Blue", resources=0, agents=(CAgentSlot("a", "m", "scout"),)),
        CTeamState(id="red", name="Red", resources=0, agents=(CAgentSlot("b", "m", "scout"),)),
    )
    return CMatchState(
        match_id="cm",
        scenario_id="legal-1",
        seed=1,
        mode="competitive",
        clock=0,
        time_limit=1000,
        width=20000,
        height=20000,
        status="active",
        winner=None,
        teams=teams,
        units=tuple(units),
        control_points=tuple(control_points),
        missions=tuple(missions),
        resource_nodes=tuple(resource_nodes),
    )


# --------------------------------------------------------------------------- #
# move_duration — exact integer arrival time
# --------------------------------------------------------------------------- #
def test_move_duration_is_exact_ceil_of_distance_over_speed() -> None:
    assert move_duration(0, 750) == 0  # already there
    # dist 1000 (one board unit) at 750 mu/tick -> ceil(1000/750) = 2
    assert move_duration(1000 * 1000, 750) == 2
    # dist 500 at 500 -> exactly 1 tick
    assert move_duration(500 * 500, 500) == 1
    # a non-perfect-square distance rounds UP so the mover reaches the target
    dsq = 2_000_000  # sqrt ~= 1414.21
    dur = move_duration(dsq, 500)
    assert dur == 3
    assert (500 * dur) ** 2 >= dsq  # the budget reaches the target
    assert (500 * (dur - 1)) ** 2 < dsq  # and it is minimal


def test_move_duration_rejects_nonpositive_speed() -> None:
    with pytest.raises(ValueError):
        move_duration(1000, 0)


# --------------------------------------------------------------------------- #
# The menu shape and per-kind legality
# --------------------------------------------------------------------------- #
def test_menu_offers_moves_toward_points_of_interest_with_durations() -> None:
    state = _state(
        units=[_unit("u", "blue", "scout", from_units(0, 0))],
        control_points=[CControlPoint(id="cp", pos=from_units(3, 0))],
        resource_nodes=[CResourceNode(id="n", pos=from_units(0, 4), remaining=5)],
    )
    menu = legal_actions_continuous(state, ROLE_TABLE, "u")
    moves = [a for a in menu["actions"] if a["kind"] == "move"]
    refs = {a["target_ref"] for a in moves}
    assert refs == {"cp", "n"}
    for a in moves:
        assert a["duration"] >= 1  # a real, positive time budget
    # scout move_rate 750: dist 3000 -> ceil(3000/750)=4; dist 4000 -> ceil(4000/750)=6
    by_ref = {a["target_ref"]: a["duration"] for a in moves}
    assert by_ref == {"cp": 4, "n": 6}


def test_menu_gather_only_on_a_node_with_stock_and_spare_capacity() -> None:
    node = CResourceNode(id="n", pos=from_units(1, 1), remaining=5)
    on_node = _state(units=[_unit("u", "blue", "scout", from_units(1, 1))], resource_nodes=[node])
    assert any(
        a["kind"] == "gather" and a["target_id"] == "n"
        for a in legal_actions_continuous(on_node, ROLE_TABLE, "u")["actions"]
    )

    off_node = _state(units=[_unit("u", "blue", "scout", from_units(2, 2))], resource_nodes=[node])
    assert not any(
        a["kind"] == "gather"
        for a in legal_actions_continuous(off_node, ROLE_TABLE, "u")["actions"]
    )

    empty = CResourceNode(id="n", pos=from_units(1, 1), remaining=0)
    exhausted = _state(
        units=[_unit("u", "blue", "scout", from_units(1, 1))], resource_nodes=[empty]
    )
    assert not any(
        a["kind"] == "gather"
        for a in legal_actions_continuous(exhausted, ROLE_TABLE, "u")["actions"]
    )

    full = _state(
        units=[_unit("u", "blue", "scout", from_units(1, 1), carrying=1)], resource_nodes=[node]
    )  # scout carry == 1, already at capacity
    assert not any(
        a["kind"] == "gather" for a in legal_actions_continuous(full, ROLE_TABLE, "u")["actions"]
    )


def test_menu_take_post_gated_by_arrival_and_ownership() -> None:
    # "harvester" here, not "scout": scout is forbidden from taking posts at
    # all (human-reviewed amendment, cycle 7 pre-publish), so this test — which
    # is about arrival/ownership gating, not role capability — uses a role that
    # can actually take a post.
    cp_open = CControlPoint(id="cp", pos=from_units(3, 3), owner=None)
    at_open = _state(
        units=[_unit("u", "blue", "harvester", from_units(3, 3))], control_points=[cp_open]
    )
    assert any(
        a["kind"] == "take_post"
        for a in legal_actions_continuous(at_open, ROLE_TABLE, "u")["actions"]
    )

    away = _state(
        units=[_unit("u", "blue", "harvester", from_units(0, 0))], control_points=[cp_open]
    )
    assert not any(
        a["kind"] == "take_post" for a in legal_actions_continuous(away, ROLE_TABLE, "u")["actions"]
    )

    # contest case (d): a post the unit's OWN team owns is not offered...
    cp_ours = CControlPoint(id="cp", pos=from_units(3, 3), owner="blue")
    ours = _state(
        units=[_unit("u", "blue", "harvester", from_units(3, 3))], control_points=[cp_ours]
    )
    assert not any(
        a["kind"] == "take_post" for a in legal_actions_continuous(ours, ROLE_TABLE, "u")["actions"]
    )

    # ...but an ENEMY-owned post is a legal flip.
    cp_enemy = CControlPoint(id="cp", pos=from_units(3, 3), owner="red")
    enemy = _state(
        units=[_unit("u", "blue", "harvester", from_units(3, 3))], control_points=[cp_enemy]
    )
    assert any(
        a["kind"] == "take_post"
        for a in legal_actions_continuous(enemy, ROLE_TABLE, "u")["actions"]
    )


def test_menu_deliver_requires_carry_and_a_deliver_location() -> None:
    mission = CMission(id="dm", kind="deliver", pos=from_units(2, 2), amount=2, reward=5)
    carrying = _state(
        units=[_unit("u", "blue", "harvester", from_units(2, 2), carrying=2)], missions=[mission]
    )
    entry = [
        a
        for a in legal_actions_continuous(carrying, ROLE_TABLE, "u")["actions"]
        if a["kind"] == "deliver"
    ]
    assert entry and entry[0]["target_id"] == "blue" and entry[0]["mission_id"] == "dm"
    assert entry[0]["duration"] == 6  # harvester deliver_duration

    empty = _state(
        units=[_unit("u", "blue", "harvester", from_units(2, 2), carrying=0)], missions=[mission]
    )
    assert not any(
        a["kind"] == "deliver" for a in legal_actions_continuous(empty, ROLE_TABLE, "u")["actions"]
    )

    off = _state(
        units=[_unit("u", "blue", "harvester", from_units(5, 5), carrying=2)], missions=[mission]
    )
    assert not any(
        a["kind"] == "deliver" for a in legal_actions_continuous(off, ROLE_TABLE, "u")["actions"]
    )


def test_explorer_menu_has_only_moves_no_gather_take_or_deliver() -> None:
    """An explorer (can_gather=False, can_take_post=False, carry=0) can only move —
    its capability contract mirrored in the menu."""
    state = _state(
        units=[_unit("u", "blue", "explorer", from_units(1, 1))],
        control_points=[CControlPoint(id="cp", pos=from_units(1, 1))],
        resource_nodes=[CResourceNode(id="n", pos=from_units(1, 1), remaining=5)],
    )
    menu = legal_actions_continuous(state, ROLE_TABLE, "u")
    kinds = {a["kind"] for a in menu["actions"]}
    assert kinds <= {"move"}
    assert menu["can_gather"] is False and menu["can_take_post"] is False


def test_scout_menu_never_offers_take_post_but_still_gathers_and_delivers() -> None:
    """Scout (can_take_post=False, can_gather=True, carry=1) is forbidden from
    taking a post even standing right on an unowned one (human-reviewed
    amendment, cycle 7 pre-publish: "scouts should not be able to take posts —
    only be the 'eyes'") — but unlike the explorer, it keeps gather/deliver."""
    cp = CControlPoint(id="cp", pos=from_units(1, 1), owner=None)
    mission = CMission(id="dm", kind="deliver", pos=from_units(1, 1), amount=1, reward=1)
    node = CResourceNode(id="n", pos=from_units(1, 1), remaining=5)

    empty_handed = _state(
        units=[_unit("u", "blue", "scout", from_units(1, 1), carrying=0)],
        control_points=[cp],
        resource_nodes=[node],
        missions=[mission],
    )
    menu = legal_actions_continuous(empty_handed, ROLE_TABLE, "u")
    kinds = {a["kind"] for a in menu["actions"]}
    assert "take_post" not in kinds
    assert "gather" in kinds
    assert menu["can_gather"] is True and menu["can_take_post"] is False
    assert (
        plan_action(empty_handed, ROLE_TABLE, "u", {"kind": "take_post", "target_id": "cp"}) is None
    )

    carrying = _state(
        units=[_unit("u", "blue", "scout", from_units(1, 1), carrying=1)],
        control_points=[cp],
        resource_nodes=[node],
        missions=[mission],
    )
    kinds = {a["kind"] for a in legal_actions_continuous(carrying, ROLE_TABLE, "u")["actions"]}
    assert "take_post" not in kinds
    assert "deliver" in kinds


def test_menu_is_canonically_sorted_and_carries_role_context() -> None:
    state = _state(
        units=[_unit("u", "blue", "scout", from_units(0, 0))],
        control_points=[
            CControlPoint(id="cp2", pos=from_units(5, 0)),
            CControlPoint(id="cp1", pos=from_units(3, 0)),
        ],
    )
    menu = legal_actions_continuous(state, ROLE_TABLE, "u")
    keys = [(a["kind"], a.get("target_id", ""), a.get("target_pos")) for a in menu["actions"]]
    assert keys == sorted(keys, key=lambda k: (k[0], k[1], k[2]["x"], k[2]["y"]))
    assert menu["clock"] == 0 and menu["role"] == "scout"
    assert menu["move_rate_mu"] == 750 and menu["carry_capacity"] == 1


def test_unknown_unit_raises() -> None:
    state = _state(units=[_unit("u", "blue", "scout", from_units(0, 0))])
    with pytest.raises(ValueError):
        legal_actions_continuous(state, ROLE_TABLE, "ghost")


# --------------------------------------------------------------------------- #
# plan_action — the shared oracle: legal plans, illegal is None
# --------------------------------------------------------------------------- #
def test_plan_action_agrees_with_the_menu_forward_direction() -> None:
    """Everything the menu offers PLANS (non-None) — the 'legal always startable'
    half of the agreement, checked against a rich state."""
    state = _state(
        units=[_unit("u", "blue", "harvester", from_units(2, 2), carrying=1)],
        control_points=[CControlPoint(id="cp", pos=from_units(2, 2), owner=None)],
        resource_nodes=[CResourceNode(id="n", pos=from_units(2, 2), remaining=3)],
        missions=[CMission(id="dm", kind="deliver", pos=from_units(2, 2), amount=2, reward=5)],
    )
    menu = legal_actions_continuous(state, ROLE_TABLE, "u")
    assert menu["actions"]  # non-trivial
    for entry in menu["actions"]:
        plan = plan_action(state, ROLE_TABLE, "u", entry)
        assert plan is not None, f"menu offered {entry!r} but plan_action refused it"
        assert plan.kind == entry["kind"]
        assert plan.duration == entry["duration"]


def test_plan_action_refuses_illegal_orders_reverse_direction() -> None:
    """Orders the menu omits do NOT plan — the 'illegal never resolves' half."""
    state = _state(
        units=[
            _unit("u", "blue", "scout", from_units(0, 0)),  # away from everything, empty-handed
            _unit("x", "blue", "explorer", from_units(1, 1)),  # cannot gather / take
        ],
        control_points=[CControlPoint(id="cp", pos=from_units(1, 1), owner="blue")],
        resource_nodes=[CResourceNode(id="n", pos=from_units(9, 9), remaining=5)],
    )
    # gather while not on the node
    assert plan_action(state, ROLE_TABLE, "u", {"kind": "gather", "target_id": "n"}) is None
    # take a post the unit is not standing on
    assert plan_action(state, ROLE_TABLE, "u", {"kind": "take_post", "target_id": "cp"}) is None
    # deliver with nothing to deliver
    assert plan_action(state, ROLE_TABLE, "u", {"kind": "deliver"}) is None
    # explorer cannot take a post even standing on it (capability contract)
    assert plan_action(state, ROLE_TABLE, "x", {"kind": "take_post", "target_id": "cp"}) is None
    # explorer cannot gather even standing on a node
    node_here = CResourceNode(id="n2", pos=from_units(1, 1), remaining=5)
    with_node = _state(
        units=[_unit("x", "blue", "explorer", from_units(1, 1))], resource_nodes=[node_here]
    )
    assert plan_action(with_node, ROLE_TABLE, "x", {"kind": "gather", "target_id": "n2"}) is None
    # taking a post your own team already owns (contest case d) — "harvester",
    # not "scout": scout can never take a post at all now, which would mask
    # the ownership-refusal path this case is actually pinning.
    on_own = _state(
        units=[_unit("u", "blue", "harvester", from_units(1, 1))],
        control_points=[CControlPoint(id="cp", pos=from_units(1, 1), owner="blue")],
    )
    assert plan_action(on_own, ROLE_TABLE, "u", {"kind": "take_post", "target_id": "cp"}) is None
    # an unknown verb is illegal
    assert plan_action(state, ROLE_TABLE, "u", {"kind": "teleport"}) is None


def test_plan_move_is_legal_toward_any_far_target_but_not_the_current_spot() -> None:
    state = _state(units=[_unit("u", "blue", "scout", from_units(0, 0))])
    far = plan_action(state, ROLE_TABLE, "u", {"kind": "move", "target_pos": {"x": 9000, "y": 0}})
    assert far is not None and far.kind == "move" and far.duration >= 1
    here = plan_action(state, ROLE_TABLE, "u", {"kind": "move", "target_pos": {"x": 0, "y": 0}})
    assert here is None  # a zero-length move is not an action


def test_dead_unit_has_no_legal_actions() -> None:
    state = _state(
        units=[_unit("u", "blue", "scout", from_units(1, 1), alive=False)],
        control_points=[CControlPoint(id="cp", pos=from_units(1, 1))],
    )
    assert legal_actions_continuous(state, ROLE_TABLE, "u")["actions"] == []
    assert plan_action(state, ROLE_TABLE, "u", {"kind": "take_post", "target_id": "cp"}) is None
