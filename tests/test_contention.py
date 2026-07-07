"""Delivery contention: deny, and same-team co-delivery, as explicit rules
(plan c8-t3, spec c12/h3/c4/h17/c7).

These are scripted-case tests that construct each contested delivery directly
rather than hoping a live match wanders into one (the honesty condition this
task exists to satisfy). Two rules are under test:

1. **Deny.** An enemy unit present at the delivery site at the instant a
   delivery would complete denies it: an explicit ``action_failed`` with
   reason ``"delivery denied by enemy presence at the site"`` — the resources
   stay on the unit (never banked) and the unit is freed for a fresh decision,
   exactly like every other interrupted/failed action in this resolver. See
   ``league/engine/continuous/resolve.py``'s "Delivery contention" docstring
   section for the rule and why DENY was chosen over delaying-and-retrying.
2. **Same-team co-delivery.** Two teammates completing a delivery at the
   identical instant are never contenders for each other (the check only ever
   looks at *other*-team units) — both succeed, ordered only by the
   timeline's existing canonical ``(completion_time, team_id, unit_id)``
   tie-break.

The last two tests in this file assert the acceptance criterion that matters
most for the "additive" half of the plan task: the committed continuous
determinism fixture (``tests/fixtures/determinism_continuous.hash``) is
untouched, because the canonical scripted match (``c-skirmish-1``) never
contests a delivery — these new rules only ever fire when contention actually
occurs.
"""

from __future__ import annotations

from league.engine.continuous import (
    CAgentSlot,
    CMatchState,
    CMission,
    CTeamState,
    CUnit,
    build_role_table,
    cstate_hash,
    from_units,
    resolve_match,
)
from tests.test_determinism_gate_continuous import FIXTURE, compute_final_hash

ROLE_TABLE = build_role_table()


# --------------------------------------------------------------------------- #
# Builders (mirrors tests/test_continuous_resolve.py's style)
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
    missions=(),
    time_limit=1000,
):
    return CMatchState(
        match_id="cm-contention",
        scenario_id="contention-1",
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
        control_points=(),
        missions=tuple(missions),
        resource_nodes=(),
    )


def _find(state, uid):
    return next(u for u in state.units if u.id == uid)


def _pick(menu, kind):
    for entry in menu["actions"]:
        if entry["kind"] == kind:
            return entry
    return None


def _once_pick(target_uid, kind):
    """A decider that returns ``target_uid``'s first legal menu entry of
    ``kind`` on its first decision point, and parks every unit (including a
    later decision point for ``target_uid`` itself) after that."""
    fired = {"done": False}

    def decide(uid, state, menu):
        if uid == target_uid and not fired["done"]:
            fired["done"] = True
            return _pick(menu, kind)
        return None

    return decide


# --------------------------------------------------------------------------- #
# Rule 1 — an enemy at the site denies the delivery
# --------------------------------------------------------------------------- #
def _contested_state(time_limit=1000):
    """Blue's harvester is already carrying and already standing on the
    deliver mission's square; red's harvester camps the exact same square and
    never moves — a defended delivery site by construction."""
    return _state(
        teams=(
            _team("blue", "Blue", (_slot("blue-harv", "harvester"),)),
            _team("red", "Red", (_slot("red-block", "harvester"),)),
        ),
        units=(
            _unit("blue-harv", "blue", "harvester", from_units(0, 0), carrying=2),
            _unit("red-block", "red", "harvester", from_units(0, 0)),
        ),
        missions=(CMission(id="dm", kind="deliver", pos=from_units(0, 0), amount=2, reward=5),),
        time_limit=time_limit,
    )


def test_enemy_presence_at_delivery_site_denies_the_delivery() -> None:
    res = resolve_match(_contested_state(), ROLE_TABLE, _once_pick("blue-harv", "deliver"))
    events = res.log.events

    started = [e for e in events if e.kind == "action_started" and e.data["unit_id"] == "blue-harv"]
    assert len(started) == 1 and started[0].data["kind"] == "deliver"

    # The reason string is exact (spec h3: "every contested-delivery outcome
    # is an explicit log event with a reason").
    failed = [e for e in events if e.kind == "action_failed"]
    assert len(failed) == 1
    assert failed[0].data == {
        "unit_id": "blue-harv",
        "reason": "delivery denied by enemy presence at the site",
    }
    # The denial fires at the delivery's own completion instant (start + the
    # harvester's deliver_duration, 6), exactly like the race loser's failure
    # fires at the winner's completion instant.
    assert failed[0].game_time == started[0].data["start_time"] + 6

    assert not any(e.kind == "resource_delivered" for e in events)
    assert not any(e.kind == "mission_completed" for e in events)


def test_denied_delivery_does_not_bank_and_frees_the_unit_for_a_new_decision() -> None:
    res = resolve_match(_contested_state(), ROLE_TABLE, _once_pick("blue-harv", "deliver"))
    final = res.final_state

    blue = next(t for t in final.teams if t.id == "blue")
    assert blue.resources == 0  # never banked
    assert _find(final, "blue-harv").carrying == 2  # the carry stays on the unit
    assert _find(final, "blue-harv").action is None  # freed, not stuck mid-action

    dm = next(m for m in final.missions if m.id == "dm")
    assert dm.status == "open"  # a denied delivery cannot complete the mission

    # The unit really was offered a fresh decision point after the denial (the
    # cadence contract every other action_failed already honors).
    decision_times = [
        e.data["game_time"]
        for e in res.log.events
        if e.kind == "decision_point" and e.data["unit_id"] == "blue-harv"
    ]
    assert decision_times == [0, 6]


def test_contested_delivery_replays_deterministically() -> None:
    a = resolve_match(_contested_state(), ROLE_TABLE, _once_pick("blue-harv", "deliver"))
    b = resolve_match(_contested_state(), ROLE_TABLE, _once_pick("blue-harv", "deliver"))
    assert a.log.events == b.log.events
    assert cstate_hash(a.final_state) == cstate_hash(b.final_state)


def test_delivery_succeeds_once_the_contesting_enemy_moves_off_the_site() -> None:
    """Directional proof the rule really keys off CURRENT enemy presence, not
    a one-time flag: the same site, the same enemy — denied while camped,
    banked once it has genuinely moved off (its position only updates on its
    OWN move's completion, so the first attempt still finds it "at" the old
    square; the retried attempt, after the move has resolved, does not)."""
    state = _state(
        teams=(
            _team("blue", "Blue", (_slot("blue-harv", "harvester"),)),
            _team("red", "Red", (_slot("red-block", "harvester"),)),
        ),
        units=(
            _unit("blue-harv", "blue", "harvester", from_units(0, 0), carrying=2),
            _unit("red-block", "red", "harvester", from_units(0, 0)),
        ),
        missions=(CMission(id="dm", kind="deliver", pos=from_units(0, 0), amount=2, reward=5),),
        time_limit=50,
    )

    moved = {"done": False}

    def decide(uid, st, menu):
        if uid == "red-block" and not moved["done"]:
            moved["done"] = True
            return {"kind": "move", "target_pos": {"x": 0, "y": 4500}}
        if uid == "blue-harv":
            return _pick(menu, "deliver")
        return None

    res = resolve_match(state, ROLE_TABLE, decide)
    events = res.log.events

    failed = [e for e in events if e.kind == "action_failed"]
    assert len(failed) == 1
    assert failed[0].data == {
        "unit_id": "blue-harv",
        "reason": "delivery denied by enemy presence at the site",
    }
    assert failed[0].game_time == 6  # first attempt: red-block hasn't arrived at its new spot yet

    delivered = [e for e in events if e.kind == "resource_delivered"]
    assert len(delivered) == 1
    assert delivered[0].data == {"unit_id": "blue-harv", "team_id": "blue", "amount": 2}
    assert delivered[0].game_time == 12  # second attempt: red-block is gone by then

    final = res.final_state
    assert next(t for t in final.teams if t.id == "blue").resources == 2
    dm = next(m for m in final.missions if m.id == "dm")
    assert dm.status == "completed" and dm.completed_by == ("blue",)


# --------------------------------------------------------------------------- #
# Regression — an uncontested delivery is untouched by the new rule
# --------------------------------------------------------------------------- #
def test_uncontested_delivery_is_unaffected_by_the_new_rule() -> None:
    """No enemy anywhere near the site: the delivery banks exactly as it did
    before this task (the "additive for uncontested play" half of the
    acceptance criteria, exercised directly rather than only via the
    determinism fixture)."""
    state = _state(
        mode="cooperative",
        teams=(_team("blue", "Blue", (_slot("h", "harvester"),)),),
        units=(_unit("h", "blue", "harvester", from_units(0, 0), carrying=2),),
        missions=(CMission(id="dm", kind="deliver", pos=from_units(0, 0), amount=2, reward=5),),
    )

    res = resolve_match(state, ROLE_TABLE, _once_pick("h", "deliver"))
    events = res.log.events

    assert not any(e.kind == "action_failed" for e in events)
    delivered = [e for e in events if e.kind == "resource_delivered"]
    assert len(delivered) == 1
    assert delivered[0].data == {"unit_id": "h", "team_id": "blue", "amount": 2}

    final = res.final_state
    assert next(t for t in final.teams if t.id == "blue").resources == 2
    dm = next(m for m in final.missions if m.id == "dm")
    assert dm.status == "completed" and dm.completed_by == ("blue",)


# --------------------------------------------------------------------------- #
# Rule 2 — same-team simultaneous deliveries co-deliver, ordered canonically
# --------------------------------------------------------------------------- #
def test_same_team_simultaneous_deliveries_both_succeed_in_canonical_order() -> None:
    """Two teammates, already carrying and already on the same deliver
    square, both start delivering at t=0 and both complete at the identical
    instant (same role, same duration) — no contention between them, and the
    timeline's own canonical (time, team_id, unit_id) tie-break is what
    orders the two completions, exactly as it orders any other simultaneous
    pair in this resolver (the race included)."""
    state = _state(
        mode="cooperative",
        teams=(
            _team(
                "blue",
                "Blue",
                (_slot("blue-h1", "harvester"), _slot("blue-h2", "harvester")),
            ),
        ),
        units=(
            _unit("blue-h1", "blue", "harvester", from_units(0, 0), carrying=2),
            _unit("blue-h2", "blue", "harvester", from_units(0, 0), carrying=3),
        ),
        missions=(CMission(id="dm", kind="deliver", pos=from_units(0, 0), amount=100, reward=9),),
        time_limit=50,
    )

    def decide(uid, st, menu):
        return _pick(menu, "deliver")

    res = resolve_match(state, ROLE_TABLE, decide)
    events = res.log.events

    assert not any(e.kind == "action_failed" for e in events)
    delivered = [e for e in events if e.kind == "resource_delivered"]
    assert len(delivered) == 2
    by_unit = {e.data["unit_id"]: e for e in delivered}
    assert by_unit["blue-h1"].data == {"unit_id": "blue-h1", "team_id": "blue", "amount": 2}
    assert by_unit["blue-h2"].data == {"unit_id": "blue-h2", "team_id": "blue", "amount": 3}
    assert by_unit["blue-h1"].game_time == by_unit["blue-h2"].game_time == 6

    # Canonical (time, team_id, unit_id) order: "blue-h1" < "blue-h2" sorts
    # first, so its whole completion (effect + action_completed) is written
    # into the log strictly before blue-h2's, even though the instant ties.
    assert by_unit["blue-h1"].seq < by_unit["blue-h2"].seq
    completed = [e for e in events if e.kind == "action_completed"]
    assert [e.data["unit_id"] for e in completed] == ["blue-h1", "blue-h2"]

    final = res.final_state
    assert next(t for t in final.teams if t.id == "blue").resources == 5
    dm = next(m for m in final.missions if m.id == "dm")
    assert dm.status == "open"  # amount=100 not yet reached — co-delivery, not mission completion


# --------------------------------------------------------------------------- #
# The hard constraint: additive for uncontested play
# --------------------------------------------------------------------------- #
def test_canonical_scripted_match_has_no_contested_delivery_and_the_hash_holds() -> None:
    """The plan's hard constraint, asserted directly from this task's own test
    file (not just left to tests/test_determinism_gate_continuous.py): the
    committed continuous determinism hash is unchanged, because c-skirmish-1
    never contests a delivery — the new rule only fires when contention
    actually occurs."""
    assert FIXTURE.is_file()
    committed = FIXTURE.read_text(encoding="utf-8").strip()
    assert compute_final_hash() == committed
    assert committed == "96ae89c58d865b5973d1f15143114e221384880fce7c5356fd7d59d44312627d"
