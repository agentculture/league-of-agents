"""External-driver stepwise resolution (issue #28): ``due_decisions`` and
``advance_external`` (``league/engine/continuous/resolve.py``).

This is the engine-level half of the ``cmatch`` noun group's parity proof:
driving a match ONE decision at a time through ``advance_external`` -- exactly
what ``cmatch act``/``cmatch tick`` do, minus the CLI/disk plumbing -- must
produce a log BYTE-IDENTICAL to a single synchronous ``resolve_match`` call
given the same decisions in the same (canonical) order. See
``tests/test_cli_cmatch.py`` for the same proof exercised through the actual
CLI verbs across separate process-like invocations.
"""

from __future__ import annotations

import pytest

from league.engine.continuous import (
    CAgentSlot,
    CControlPoint,
    CMatchState,
    CMission,
    CTeamState,
    CUnit,
    build_role_table,
    from_units,
    resolve_match,
)
from league.engine.continuous.events import CEvent, CMatchLog
from league.engine.continuous.resolve import (
    IllegalContinuousAction,
    NeedsExternalDecision,
    advance_external,
    due_decisions,
)

ROLE_TABLE = build_role_table()


# --------------------------------------------------------------------------- #
# Builders (mirror tests/test_continuous_resolve.py's own shape)
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
        scenario_id="stepwise-1",
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


def _pick(menu, kind):
    for entry in menu["actions"]:
        if entry["kind"] == kind:
            return entry
    return None


def _race_state():
    return _state(
        teams=(
            _team("blue", "Blue", (_slot("blue-defender", "defender"),)),
            _team("red", "Red", (_slot("red-harv", "harvester"),)),
        ),
        units=(
            _unit("blue-defender", "blue", "defender", from_units(2, 3)),
            _unit("red-harv", "red", "harvester", from_units(3, 3)),
        ),
        control_points=(CControlPoint(id="cp", pos=from_units(3, 3)),),
    )


def _race_decider(uid, state, menu):
    if uid == "blue-defender":
        return _pick(menu, "take_post") or _pick(menu, "move")
    if uid == "red-harv":
        cp = next(c for c in state.control_points if c.id == "cp")
        return _pick(menu, "take_post") if cp.owner is None else None
    return None


def _fresh_log(initial: CMatchState) -> CMatchLog:
    """The exact log ``cmatch new --apply`` persists: header + the one,
    unconditional ``match_started`` event every match opens with."""
    return CMatchLog(initial_state=initial, events=(CEvent(0, 0, "match_started", {}),))


def _drive_canonically(clog: CMatchLog, decider) -> tuple[CMatchLog, int]:
    """Answer every due unit, one call at a time, strictly in the order
    ``due_decisions`` reports (canonical order) -- the discipline
    ``cmatch act`` enforces at the CLI layer. Returns the final log and how
    many ``advance_external`` calls it took."""
    calls = 0
    while True:
        due = due_decisions(clog)
        if not due:
            return clog, calls
        target = due[0]

        def decide_external(unit_id, state, menu, _target=target):
            if unit_id == _target:
                return decider(unit_id, state, menu)
            raise NeedsExternalDecision(unit_id)

        clog, finished = advance_external(clog, ROLE_TABLE, decide_external)
        calls += 1
        if finished:
            return clog, calls


# --------------------------------------------------------------------------- #
# due_decisions
# --------------------------------------------------------------------------- #


def test_due_decisions_lists_every_unit_in_canonical_order_at_match_start() -> None:
    clog = _fresh_log(_race_state())
    assert due_decisions(clog) == ["blue-defender", "red-harv"]


def test_due_decisions_empty_before_match_started() -> None:
    """A bare header with zero events (status still 'pending') has nothing
    due -- the resolver never offers a decision before match_started."""
    clog = CMatchLog(initial_state=_race_state(), events=())
    assert due_decisions(clog) == []


def test_due_decisions_excludes_a_unit_that_was_asked_and_parked() -> None:
    """Parking is a terminal answer for that idle window: once asked, a unit
    stays idle forever (nothing else will make it idle again) but is no
    longer OWED a decision."""
    clog = _fresh_log(_race_state())
    clog, finished = advance_external(
        clog, ROLE_TABLE, lambda uid, state, menu: None if uid == "blue-defender" else _fail(uid)
    )
    assert finished is False
    assert due_decisions(clog) == ["red-harv"]  # blue-defender asked+parked, no longer due


def _fail(unit_id):
    raise NeedsExternalDecision(unit_id)


def test_due_decisions_empty_once_the_match_has_finished() -> None:
    ref = resolve_match(_race_state(), ROLE_TABLE, _race_decider)
    clog = CMatchLog(initial_state=_race_state(), events=ref.log.events)
    assert ref.final_state.status == "finished"
    assert due_decisions(clog) == []


# --------------------------------------------------------------------------- #
# advance_external -- the parity proof
# --------------------------------------------------------------------------- #


def test_advance_external_pauses_without_writing_a_dangling_decision_point() -> None:
    clog = _fresh_log(_race_state())
    new_log, finished = advance_external(clog, ROLE_TABLE, lambda *a: _fail(a[0]))
    assert finished is False
    assert new_log.events == clog.events  # no progress at all -- a clean no-op


def test_advance_external_one_decision_appends_exactly_that_units_events() -> None:
    clog = _fresh_log(_race_state())
    new_log, finished = advance_external(
        clog,
        ROLE_TABLE,
        lambda uid, state, menu: (_pick(menu, "move") if uid == "blue-defender" else _fail(uid)),
    )
    assert finished is False
    new_kinds = [e.kind for e in new_log.events[len(clog.events) :]]
    assert new_kinds == ["decision_point", "action_started"]
    # red-harv is still due (untouched) -- no dangling decision_point for it.
    assert due_decisions(new_log) == ["red-harv"]


def test_advance_external_matches_resolve_match_byte_for_byte() -> None:
    """THE external-driver parity proof: driving the scripted race one
    decision at a time, in canonical order, across separate
    ``advance_external`` calls (simulating separate CLI invocations reading
    from disk each time) produces the EXACT SAME event log --
    ``CEvent``-for-``CEvent`` -- as a single synchronous ``resolve_match``
    call with the identical decision function."""
    reference = resolve_match(_race_state(), ROLE_TABLE, _race_decider)

    clog = _fresh_log(_race_state())
    clog, calls = _drive_canonically(clog, _race_decider)

    assert calls > 1  # genuinely exercised more than one external round-trip
    assert clog.events == reference.log.events
    assert clog.final_state() == reference.final_state


def test_advance_external_matches_resolve_match_with_a_hold_mission() -> None:
    """The parity proof again, over a match with a HOLD mission -- the
    synthetic timeline entry (``_HoldExpiry``) that idles no unit at all and
    is never gated by any decision. Proves ``advance_external``'s pure
    from-scratch replay reconstructs the hold-ownership window correctly
    without any bespoke timeline/owned_since reconstruction of its own."""

    def state_builder():
        return _state(
            mode="cooperative",
            teams=(_team("blue", "Blue", (_slot("d", "defender"),)),),
            units=(_unit("d", "blue", "defender", from_units(3, 3)),),
            control_points=(CControlPoint(id="cp", pos=from_units(3, 3)),),
            missions=(CMission(id="hm", kind="hold", pos=from_units(3, 3), amount=4, reward=9),),
        )

    def decide(uid, state, menu):
        cp = next(c for c in state.control_points if c.id == "cp")
        return _pick(menu, "take_post") if cp.owner is None else None

    reference = resolve_match(state_builder(), ROLE_TABLE, decide)
    assert reference.final_state.winner == "blue"  # sanity: the mission does complete

    clog = _fresh_log(state_builder())
    clog, calls = _drive_canonically(clog, decide)

    assert calls >= 1
    assert clog.events == reference.log.events
    assert clog.final_state() == reference.final_state
    hm = next(m for m in clog.final_state().missions if m.id == "hm")
    assert hm.status == "completed" and hm.completed_by == ("blue",)


def test_advance_external_cascades_through_a_simultaneous_race_loss() -> None:
    """A single completion (the post race) can idle TWO units at once (the
    winner and every cascaded loser) -- both must show up in
    due_decisions/be answerable, in canonical order, and the whole thing
    still matches resolve_match byte for byte."""
    state = _state(
        teams=(
            _team("blue", "Blue", (_slot("bd", "defender"),)),
            _team("red", "Red", (_slot("rd", "defender"),)),
        ),
        units=(
            _unit("bd", "blue", "defender", from_units(3, 3)),  # already on the post
            _unit("rd", "red", "defender", from_units(3, 3)),  # also already on the post
        ),
        control_points=(CControlPoint(id="cp", pos=from_units(3, 3)),),
    )

    def decide(uid, st, menu):
        cp = next(c for c in st.control_points if c.id == "cp")
        return _pick(menu, "take_post") if cp.owner is None else None

    reference = resolve_match(state, ROLE_TABLE, decide)

    def rebuild():
        return _state(
            teams=(
                _team("blue", "Blue", (_slot("bd", "defender"),)),
                _team("red", "Red", (_slot("rd", "defender"),)),
            ),
            units=(
                _unit("bd", "blue", "defender", from_units(3, 3)),
                _unit("rd", "red", "defender", from_units(3, 3)),
            ),
            control_points=(CControlPoint(id="cp", pos=from_units(3, 3)),),
        )

    clog = _fresh_log(rebuild())
    clog, calls = _drive_canonically(clog, decide)

    assert calls > 1
    assert clog.events == reference.log.events
    assert clog.final_state() == reference.final_state


def test_advance_external_raises_the_resolvers_own_error_on_an_illegal_action() -> None:
    """``advance_external`` does not itself validate legality -- it hands
    whatever ``decide_external`` returns straight to the same resolver
    ``resolve_match`` uses, which refuses an illegal order loudly (never a
    silent no-op). Callers (``cmatch act``) are expected to pre-validate via
    ``plan_action`` for a clean CliError instead of relying on this."""
    clog = _fresh_log(_race_state())
    with pytest.raises(IllegalContinuousAction):
        advance_external(
            clog,
            ROLE_TABLE,
            lambda uid, state, menu: (
                {"kind": "take_post", "target_id": "no-such-cp"}
                if uid == "blue-defender"
                else _fail(uid)
            ),
        )


def test_advance_external_is_idempotent_on_an_already_finished_match() -> None:
    reference = resolve_match(_race_state(), ROLE_TABLE, _race_decider)
    clog = CMatchLog(initial_state=_race_state(), events=reference.log.events)
    new_log, finished = advance_external(clog, ROLE_TABLE, lambda *a: _fail(a[0]))
    assert finished is True
    assert new_log.events == clog.events  # nothing new to add
