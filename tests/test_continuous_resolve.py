"""Acceptance tests for the continuous resolver with race semantics (plan C7-t5).

These are the merge gate for ``league/engine/continuous/resolve.py``. Written
before the implementation (TDD), they pin the two acceptance criteria:

1. **The race is engine truth (spec c9/h9).** ``test_scripted_race_*`` builds the
   exact scenario the spec names — a slower agent starts taking a post FIRST, a
   faster agent (different team) starts LATER and completes FIRST — and asserts
   the whole folded log: the winner's ``post_taken`` and the loser's first-class
   ``action_failed`` (with its reason) are both present, and the final state shows
   the winner as owner with zero residual takers.
2. **Interruption/contest rules are explicit engine rules, and the legal<->resolver
   agreement holds both ways.** The four contest cases each get a test; every menu
   action starts and resolves without a legality failure, and every illegal order
   is refused. Determinism is proven end to end (same script twice → identical log
   + hash) and against submission order (same choices from differently ordered
   menus → identical logs).

The decision function is a pure scripted callback here; the live harness (t7)
wraps real minds around the same ``decide(unit_id, state, menu)`` signature.
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
    cstate_hash,
    fold_events,
    from_units,
    legal_actions_continuous,
    outcome_points,
    resolve_match,
)
from league.engine.continuous.resolve import (
    IllegalContinuousAction,
    _hold_key,
    _Resolver,
)

ROLE_TABLE = build_role_table()


# --------------------------------------------------------------------------- #
# Builders
# --------------------------------------------------------------------------- #
def _slot(uid, role):
    return CAgentSlot(id=uid, model="colleague/qwen", role=role)


def _team(tid, name, roster, resources=0):
    return CTeamState(id=tid, name=name, resources=resources, agents=tuple(roster))


def _unit(uid, team, role, pos, carrying=0):
    return CUnit(id=uid, team_id=team, agent_id=uid, role=role, pos=pos, carrying=carrying)


def _state(
    *,
    mode="competitive",
    teams,
    units,
    control_points=(),
    missions=(),
    resource_nodes=(),
    time_limit=1000,
):
    return CMatchState(
        match_id="cm",
        scenario_id="resolve-1",
        seed=1,
        mode=mode,
        clock=0,
        time_limit=time_limit,
        width=20000,
        height=20000,
        status="pending",
        winner=None,
        teams=tuple(teams),
        units=tuple(units),
        control_points=tuple(control_points),
        missions=tuple(missions),
        resource_nodes=tuple(resource_nodes),
    )


def _find(state, uid):
    return next(u for u in state.units if u.id == uid)


def _pick(menu, kind):
    for entry in menu["actions"]:
        if entry["kind"] == kind:
            return entry
    return None


# --------------------------------------------------------------------------- #
# Criterion 1 — THE scripted race
# --------------------------------------------------------------------------- #
def _race_state():
    """A slow harvester (take_post_duration 10) camps the post; a fast scout
    (take_post_duration 5) must travel 1 unit in, so it starts its take LATER but
    finishes FIRST."""
    return _state(
        teams=(
            _team("blue", "Blue", (_slot("blue-scout", "scout"),)),
            _team("red", "Red", (_slot("red-harv", "harvester"),)),
        ),
        units=(
            _unit("blue-scout", "blue", "scout", from_units(2, 3)),  # 1 unit from the post
            _unit("red-harv", "red", "harvester", from_units(3, 3)),  # already on the post
        ),
        control_points=(CControlPoint(id="cp", pos=from_units(3, 3)),),
    )


def _race_decider(uid, state, menu):
    if uid == "blue-scout":
        return _pick(menu, "take_post") or _pick(menu, "move")
    if uid == "red-harv":
        cp = next(c for c in state.control_points if c.id == "cp")
        return _pick(menu, "take_post") if cp.owner is None else None
    return None


def test_scripted_race_event_sequence_is_exact() -> None:
    res = resolve_match(_race_state(), ROLE_TABLE, _race_decider)
    sequence = [(e.game_time, e.kind) for e in res.log.events]
    assert sequence == [
        (0, "match_started"),
        (0, "decision_point"),  # blue-scout (canonical order: blue before red)
        (0, "action_started"),  # blue-scout begins moving toward the post
        (0, "decision_point"),  # red-harv
        (0, "action_started"),  # red-harv begins its take FIRST (completion t=10)
        (2, "unit_moved"),  # blue-scout arrives at the post
        (2, "action_completed"),
        (2, "decision_point"),
        (2, "action_started"),  # blue-scout begins its take LATER (completion t=7)
        (7, "post_taken"),  # the faster scout finishes FIRST and takes the post
        (7, "action_completed"),
        (7, "action_failed"),  # the slower harvester's attempt fails mid-take
        (7, "decision_point"),  # both freed units get a decision point
        (7, "decision_point"),
        (7, "match_finished"),
    ]


def test_scripted_race_winner_and_loser_are_both_on_the_record() -> None:
    res = resolve_match(_race_state(), ROLE_TABLE, _race_decider)
    events = res.log.events

    taken = [e for e in events if e.kind == "post_taken"]
    assert len(taken) == 1
    assert taken[0].data == {"cp_id": "cp", "team_id": "blue", "unit_id": "blue-scout"}

    failed = [e for e in events if e.kind == "action_failed"]
    assert len(failed) == 1
    assert failed[0].data == {"unit_id": "red-harv", "reason": "post taken by a faster agent"}
    assert failed[0].game_time == 7  # the loser fails at the winner's completion instant

    # Contest case (a): the loser's attempt does NOT continue against the new
    # owner — it is withdrawn, the unit is idle, and it never becomes owner.
    final = res.final_state
    cp = next(c for c in final.control_points if c.id == "cp")
    assert cp.owner == "blue"
    assert cp.takers == ()  # zero residual takers
    assert _find(final, "red-harv").action is None
    assert final.status == "finished" and final.winner == "blue"


def test_scripted_race_is_representable_mid_take() -> None:
    """Fold the log up to the moment both units are mid-take: the post carries
    BOTH attempts at once (the race is in state, not implied)."""
    res = resolve_match(_race_state(), ROLE_TABLE, _race_decider)
    # events[8] is blue-scout's take_post action_started (the second taker joins).
    mid = fold_events(res.log.initial_state, res.log.events[: 8 + 1])
    cp = next(c for c in mid.control_points if c.id == "cp")
    keys = {(t.unit_id, t.team_id, t.completion_time) for t in cp.takers}
    assert keys == {("blue-scout", "blue", 7), ("red-harv", "red", 10)}
    assert cp.owner is None  # nobody has finished yet


def test_scripted_race_folds_back_to_final_state() -> None:
    res = resolve_match(_race_state(), ROLE_TABLE, _race_decider)
    assert cstate_hash(res.log.final_state()) == cstate_hash(res.final_state)


# --------------------------------------------------------------------------- #
# Criterion 2 — the four contest/interruption rules, each explicit
# --------------------------------------------------------------------------- #
def test_case_c_two_same_team_attempts_first_wins_second_benign_fails() -> None:
    """Two same-team units take one post: both count as concurrent takers, the
    first to complete wins, the second is cleared as a benign action_failed."""
    state = _state(
        teams=(
            _team("blue", "Blue", (_slot("blue-scout", "scout"), _slot("blue-harv", "harvester"))),
        ),
        units=(
            _unit("blue-scout", "blue", "scout", from_units(3, 3)),  # take_dur 5 -> wins
            _unit("blue-harv", "blue", "harvester", from_units(3, 3)),  # take_dur 10 -> loses
        ),
        control_points=(CControlPoint(id="cp", pos=from_units(3, 3)),),
        mode="cooperative",
    )

    def decide(uid, st, menu):
        cp = next(c for c in st.control_points if c.id == "cp")
        return _pick(menu, "take_post") if cp.owner is None else None

    res = resolve_match(state, ROLE_TABLE, decide)

    # Both are concurrent takers before either completes (events[:5] == through
    # both action_started at t=0).
    mid = fold_events(res.log.initial_state, res.log.events[:5])
    cp_mid = next(c for c in mid.control_points if c.id == "cp")
    assert {t.unit_id for t in cp_mid.takers} == {"blue-scout", "blue-harv"}

    taken = [e for e in res.log.events if e.kind == "post_taken"]
    assert len(taken) == 1 and taken[0].data["unit_id"] == "blue-scout"
    failed = [e for e in res.log.events if e.kind == "action_failed"]
    assert len(failed) == 1
    assert failed[0].data == {"unit_id": "blue-harv", "reason": "post already held by a teammate"}

    cp_final = next(c for c in res.final_state.control_points if c.id == "cp")
    assert cp_final.owner == "blue" and cp_final.takers == ()


def test_case_d_taking_your_own_post_is_refused_by_the_resolver() -> None:
    """Illegal never resolves: a take on a post the unit's team already owns is
    refused (mirrors the menu, which never offers it)."""
    state = _state(
        teams=(_team("blue", "Blue", (_slot("blue-scout", "scout"),)),),
        units=(_unit("blue-scout", "blue", "scout", from_units(3, 3)),),
        control_points=(CControlPoint(id="cp", pos=from_units(3, 3), owner="blue"),),
        mode="cooperative",
    )

    def decide(uid, st, menu):
        return {"kind": "take_post", "target_id": "cp"}  # off-menu, illegal

    with pytest.raises(IllegalContinuousAction):
        resolve_match(state, ROLE_TABLE, decide)


def test_case_b_fail_action_cancels_replaces_pending_order() -> None:
    """The interruption primitive: cancel a pending order (Timeline.cancel) and
    emit action_failed, withdrawing the take attempt and idling the unit, so a
    fresh order may replace it."""
    state = _state(
        teams=(_team("blue", "Blue", (_slot("u", "scout"),)),),
        units=(_unit("u", "blue", "scout", from_units(3, 3)),),
        control_points=(CControlPoint(id="cp", pos=from_units(3, 3)),),
        mode="cooperative",
    )
    r = _Resolver(state, ROLE_TABLE, lambda *a: None, None)
    r.emit(0, "match_started", {})
    r._start_action("u", {"kind": "take_post", "target_id": "cp"}, 0)

    cp = next(c for c in r.state.control_points if c.id == "cp")
    assert [t.unit_id for t in cp.takers] == ["u"] and "u" in r.timeline

    r.fail_action("u", "replaced by a new order", 3)

    cp = next(c for c in r.state.control_points if c.id == "cp")
    assert cp.takers == ()  # withdrawn
    assert "u" not in r.timeline  # timeline entry canceled
    assert _find(r.state, "u").action is None  # idle again
    assert r.events[-1].data == {"unit_id": "u", "reason": "replaced by a new order"}

    # a fresh order can now be started for the freed unit
    r._start_action("u", {"kind": "take_post", "target_id": "cp"}, 3)
    assert "u" in r.timeline


def test_case_a_owner_change_fails_every_other_live_attempt() -> None:
    """A three-way contest: whoever completes first takes the post; every OTHER
    live attempt fails immediately and does not continue against the new owner."""
    state = _state(
        teams=(
            _team("blue", "Blue", (_slot("blue-scout", "scout"),)),
            _team("red", "Red", (_slot("red-def", "defender"),)),
            _team("green", "Green", (_slot("green-harv", "harvester"),)),
        ),
        units=(
            _unit("blue-scout", "blue", "scout", from_units(3, 3)),  # take_dur 5 -> wins
            _unit("red-def", "red", "defender", from_units(3, 3)),  # take_dur 6 -> loses
            _unit("green-harv", "green", "harvester", from_units(3, 3)),  # take_dur 10 -> loses
        ),
        control_points=(CControlPoint(id="cp", pos=from_units(3, 3)),),
    )

    def decide(uid, st, menu):
        cp = next(c for c in st.control_points if c.id == "cp")
        return _pick(menu, "take_post") if cp.owner is None else None

    res = resolve_match(state, ROLE_TABLE, decide)
    failed = {
        e.data["unit_id"]: e.data["reason"] for e in res.log.events if e.kind == "action_failed"
    }
    assert failed == {
        "red-def": "post taken by a faster agent",
        "green-harv": "post taken by a faster agent",
    }
    cp = next(c for c in res.final_state.control_points if c.id == "cp")
    assert cp.owner == "blue" and cp.takers == ()


# --------------------------------------------------------------------------- #
# Economy: gather + deliver mirror the grid, in in-game duration
# --------------------------------------------------------------------------- #
def test_gather_then_deliver_banks_resources_and_completes_the_mission() -> None:
    state = _state(
        teams=(_team("blue", "Blue", (_slot("h", "harvester"),)),),
        units=(_unit("h", "blue", "harvester", from_units(0, 0)),),
        resource_nodes=(CResourceNode(id="n", pos=from_units(0, 0), remaining=5),),
        missions=(CMission(id="dm", kind="deliver", pos=from_units(0, 0), amount=2, reward=7),),
        mode="cooperative",
    )

    def decide(uid, st, menu):
        unit = _find(st, uid)
        if unit.carrying < 3 and _pick(menu, "gather"):
            return _pick(menu, "gather")
        return _pick(menu, "deliver")

    res = resolve_match(state, ROLE_TABLE, decide)
    final = res.final_state
    assert next(t for t in final.teams if t.id == "blue").resources == 3
    assert next(n for n in final.resource_nodes if n.id == "n").remaining == 2
    dm = next(m for m in final.missions if m.id == "dm")
    assert dm.status == "completed" and dm.completed_by == ("blue",)
    assert final.winner == "blue"  # cooperative, all missions resolved
    kinds = [e.kind for e in res.log.events]
    assert "resource_gathered" in kinds and "resource_delivered" in kinds


# --------------------------------------------------------------------------- #
# Hold missions: the uninterrupted-ownership window
# --------------------------------------------------------------------------- #
def test_hold_mission_completes_after_uninterrupted_ownership_window() -> None:
    state = _state(
        teams=(_team("blue", "Blue", (_slot("d", "defender"),)),),
        units=(_unit("d", "blue", "defender", from_units(3, 3)),),  # take_dur 6
        control_points=(CControlPoint(id="cp", pos=from_units(3, 3)),),
        missions=(CMission(id="hm", kind="hold", pos=from_units(3, 3), amount=4, reward=9),),
        mode="cooperative",
    )

    def decide(uid, st, menu):
        cp = next(c for c in st.control_points if c.id == "cp")
        return _pick(menu, "take_post") if cp.owner is None else None

    res = resolve_match(state, ROLE_TABLE, decide)
    hm = next(m for m in res.final_state.missions if m.id == "hm")
    assert hm.status == "completed" and hm.completed_by == ("blue",)
    # taken at t=6 (defender take_dur), window closes at t=6+4=10
    assert hm.completed_time == 10
    assert res.final_state.winner == "blue"


def test_hold_window_is_uninterrupted_a_retake_cancels_it() -> None:
    """White-box: blue takes the post, red re-takes before the window closes —
    blue's hold window is canceled, red's runs fresh, and the mission completes
    for RED (the uninterrupted holder), never blue."""
    state = _state(
        teams=(
            _team("blue", "Blue", (_slot("bu", "defender"),)),
            _team("red", "Red", (_slot("ru", "defender"),)),
        ),
        units=(_unit("bu", "blue", "defender", from_units(3, 3)),),
        control_points=(CControlPoint(id="cp", pos=from_units(3, 3)),),
        missions=(CMission(id="hm", kind="hold", pos=from_units(3, 3), amount=4, reward=9),),
    )
    r = _Resolver(state, ROLE_TABLE, lambda *a: None, None)
    r.emit(0, "match_started", {})

    # blue takes at t=2 -> window at t=6
    r.emit(2, "post_taken", {"cp_id": "cp", "team_id": "blue", "unit_id": "bu"})
    r._on_post_taken("cp", "blue", 2)
    assert _hold_key("cp") in r.timeline

    # red re-takes at t=4 (before t=6) -> blue window canceled, red window at t=8
    r.emit(4, "post_taken", {"cp_id": "cp", "team_id": "red", "unit_id": "ru"})
    r._on_post_taken("cp", "red", 4)
    holds = [e for e in r.timeline.pending() if e.unit_id == _hold_key("cp")]
    assert len(holds) == 1 and holds[0].completion_time == 8

    entry = r.timeline.advance()  # red's hold expiry at t=8
    r._resolve_hold_expiry(entry.action, entry.completion_time)
    hm = next(m for m in r.state.missions if m.id == "hm")
    assert hm.status == "completed" and hm.completed_by == ("red",)


# --------------------------------------------------------------------------- #
# The legal<->resolver agreement, resolver side
# --------------------------------------------------------------------------- #
def _agreement_state():
    return _state(
        teams=(_team("blue", "Blue", (_slot("u", "harvester"),)),),
        units=(_unit("u", "blue", "harvester", from_units(2, 2), carrying=1),),
        control_points=(CControlPoint(id="cp", pos=from_units(2, 2), owner=None),),
        resource_nodes=(
            CResourceNode(id="n", pos=from_units(2, 2), remaining=3),
            CResourceNode(id="far", pos=from_units(9, 9), remaining=5),  # a distant move target
        ),
        missions=(CMission(id="dm", kind="deliver", pos=from_units(2, 2), amount=2, reward=5),),
        mode="cooperative",
    )


def _once(target_uid, action):
    """A decider that returns ``action`` for ``target_uid``'s first decision, then
    parks everything."""
    fired = {"done": False}

    def decide(uid, state, menu):
        if uid == target_uid and not fired["done"]:
            fired["done"] = True
            return action
        return None

    return decide


def test_every_legal_menu_action_starts_and_resolves_without_failure() -> None:
    """'Legal always starts': each menu action, when chosen, produces an
    action_started and an action_completed for the unit — never an action_failed
    for a legality reason."""
    state = _agreement_state()
    menu = legal_actions_continuous(state, ROLE_TABLE, "u")
    assert {a["kind"] for a in menu["actions"]} == {"move", "gather", "take_post", "deliver"}
    for entry in menu["actions"]:
        res = resolve_match(state, ROLE_TABLE, _once("u", entry))
        kinds = [e.kind for e in res.log.events if e.data.get("unit_id") == "u"]
        assert "action_started" in kinds, entry
        assert "action_completed" in kinds, entry
        assert "action_failed" not in kinds, entry


def test_illegal_orders_never_resolve_they_are_refused() -> None:
    """'Illegal never resolves': an off-menu order raises rather than silently
    advancing game time."""
    state = _state(
        teams=(_team("blue", "Blue", (_slot("u", "scout"),)),),
        units=(_unit("u", "blue", "scout", from_units(0, 0)),),  # away, empty-handed
        control_points=(CControlPoint(id="cp", pos=from_units(9, 9)),),
        resource_nodes=(CResourceNode(id="n", pos=from_units(9, 9), remaining=5),),
        mode="cooperative",
    )
    for illegal in (
        {"kind": "gather", "target_id": "n"},  # not on the node
        {"kind": "take_post", "target_id": "cp"},  # not on the post
        {"kind": "deliver"},  # nothing to deliver
    ):
        with pytest.raises(IllegalContinuousAction):
            resolve_match(state, ROLE_TABLE, _once("u", illegal))


# --------------------------------------------------------------------------- #
# Determinism — the same script twice, and submission order irrelevance
# --------------------------------------------------------------------------- #
def _coop_scenario():
    return _state(
        teams=(_team("blue", "Blue", (_slot("hauler", "harvester"), _slot("holder", "defender"))),),
        units=(
            _unit("hauler", "blue", "harvester", from_units(0, 0)),
            _unit("holder", "blue", "defender", from_units(5, 5)),
        ),
        control_points=(CControlPoint(id="cp", pos=from_units(5, 5)),),
        resource_nodes=(CResourceNode(id="n", pos=from_units(0, 0), remaining=5),),
        missions=(
            CMission(id="dm", kind="deliver", pos=from_units(2, 2), amount=2, reward=5),
            CMission(id="hm", kind="hold", pos=from_units(5, 5), amount=4, reward=5),
        ),
        mode="cooperative",
    )


def _coop_decider(reverse=False):
    def decide(uid, state, menu):
        acts = list(reversed(menu["actions"])) if reverse else list(menu["actions"])
        unit = _find(state, uid)
        if uid == "holder":
            for a in acts:
                if a["kind"] == "take_post":
                    return a
            return None
        # hauler: gather to capacity, then carry to the deliver square and deliver
        if unit.carrying < 3:
            for a in acts:
                if a["kind"] == "gather":
                    return a
        for a in acts:
            if a["kind"] == "deliver":
                return a
        if unit.carrying > 0:
            for a in acts:
                if a["kind"] == "move" and a.get("target_ref") == "dm":
                    return a
        return None

    return decide


def test_replaying_the_same_script_is_deterministic() -> None:
    a = resolve_match(_coop_scenario(), ROLE_TABLE, _coop_decider())
    b = resolve_match(_coop_scenario(), ROLE_TABLE, _coop_decider())
    assert a.log.events == b.log.events
    assert cstate_hash(a.final_state) == cstate_hash(b.final_state)
    # the scenario actually did something worth checking
    assert a.final_state.status == "finished"
    assert all(m.status == "completed" for m in a.final_state.missions)


def test_submission_order_never_changes_resolution() -> None:
    """Two decision functions make the SAME choices from differently ordered menus
    (forward vs reversed scan) — the logs and hashes are identical, because the
    resolver derives everything from the choice, never the menu's order."""
    forward = resolve_match(_coop_scenario(), ROLE_TABLE, _coop_decider(reverse=False))
    reverse = resolve_match(_coop_scenario(), ROLE_TABLE, _coop_decider(reverse=True))
    assert forward.log.events == reverse.log.events
    assert cstate_hash(forward.final_state) == cstate_hash(reverse.final_state)


def test_outcome_points_tally_matches_the_grid_rule() -> None:
    res = resolve_match(_race_state(), ROLE_TABLE, _race_decider)
    points = outcome_points(res.final_state)
    assert points == {"blue": 2, "red": 0}  # blue owns one control point (CP_POINTS=2)


# --------------------------------------------------------------------------- #
# Guardrails
# --------------------------------------------------------------------------- #
def test_reserved_hold_prefix_unit_id_is_rejected() -> None:
    state = _state(
        teams=(_team("blue", "Blue", (_slot("x", "scout"),)),),
        units=(_unit("__hold__:cp", "blue", "scout", from_units(0, 0)),),
        mode="cooperative",
    )
    with pytest.raises(ValueError, match="reserved"):
        resolve_match(state, ROLE_TABLE, lambda *a: None)


def test_resolving_a_non_pending_match_raises() -> None:
    import dataclasses

    active = dataclasses.replace(
        _state(
            teams=(_team("blue", "Blue", (_slot("x", "scout"),)),),
            units=(_unit("x", "blue", "scout", from_units(0, 0)),),
            mode="cooperative",
        ),
        status="active",
    )
    with pytest.raises(ValueError):
        resolve_match(active, ROLE_TABLE, lambda *a: None)
