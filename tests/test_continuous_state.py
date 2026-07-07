"""Acceptance tests for continuous match state + event vocabulary (plan C7-t3).

These are the merge gate for ``league/engine/continuous/state.py`` and
``league/engine/continuous/events.py``. Written before the implementation (TDD),
they pin the two acceptance criteria:

1. Frozen dataclasses for the continuous ``CMatchState`` with a stable
   ``cstate_hash``; the new event kinds (``action_started``, ``action_completed``,
   ``action_failed``, ``decision_point``, and the rest) fold deterministically —
   replaying a log reproduces the identical final state and hash, pinned against
   a committed constant (``_GOLDEN_STATE_HASH``). The contested-take race is
   representable *in state*: a control point carries concurrent ``takers``.
2. No binary float anywhere the continuous package exposes — a value scan over a
   rich sample state finds no ``float``, and a **source** scan over every module
   in ``league/engine/continuous/`` rejects float literals and ``float(...)``
   casts (generalizing ``space.py``'s own scan to the whole package).

The engine-wide AST import ban (``tests/test_engine_state.py``) already scans
``league/engine/`` recursively, so ``random``/``time``/``datetime``/``secrets``/
``uuid`` are forbidden here for free; this file adds the value + source float bans.
"""

from __future__ import annotations

import ast
import dataclasses
import json
from pathlib import Path

import pytest

from league.engine.continuous import (
    ACTION_KINDS,
    EVENT_KINDS,
    OBSERVATION_KINDS,
    TRANSITION_KINDS,
    CAction,
    CAgentSlot,
    CControlPoint,
    CEvent,
    CMatchLog,
    CMatchState,
    CMission,
    CResourceNode,
    CTeamState,
    CUnit,
    TakeAttempt,
    apply_event,
    cstate_from_json,
    cstate_hash,
    cstate_to_json,
    fold_events,
    from_units,
)

CONTINUOUS_DIR = Path(__file__).resolve().parent.parent / "league" / "engine" / "continuous"


# --------------------------------------------------------------------------- #
# Sample state — rich enough to exercise every shape (a contested take, an
# in-progress action with a spatial target, a completed mission).
# --------------------------------------------------------------------------- #
def sample_state() -> CMatchState:
    return CMatchState(
        match_id="cm-0001",
        scenario_id="drift-1",
        seed=1337,
        mode="competitive",
        clock=200,
        time_limit=1000,
        width=10 * 1000,
        height=8 * 1000,
        status="active",
        winner=None,
        teams=(
            CTeamState(
                id="blue",
                name="Blue Foundry",
                resources=3,
                agents=(
                    CAgentSlot(id="blue-scout", model="colleague/qwen", role="scout"),
                    CAgentSlot(id="blue-harvester", model="claude-sonnet-5", role="harvester"),
                ),
            ),
            CTeamState(
                id="red",
                name="Red Relay",
                resources=0,
                agents=(CAgentSlot(id="red-striker", model="claude-sonnet-5", role="striker"),),
            ),
        ),
        units=(
            CUnit(
                id="blue-u1",
                team_id="blue",
                agent_id="blue-scout",
                role="scout",
                pos=from_units(0, 0),
                action=CAction(
                    kind="take_post",
                    start_time=200,
                    completion_time=400,
                    target_id="cp-center",
                ),
            ),
            CUnit(
                id="blue-u2",
                team_id="blue",
                agent_id="blue-harvester",
                role="harvester",
                pos=from_units(1, 1),
                action=CAction(
                    kind="move",
                    start_time=150,
                    completion_time=250,
                    target_pos=from_units(0, 2),
                ),
                carrying=2,
            ),
            CUnit(
                id="red-u1",
                team_id="red",
                agent_id="red-striker",
                role="striker",
                pos=from_units(5, 5),
                action=CAction(
                    kind="take_post",
                    start_time=100,
                    completion_time=600,
                    target_id="cp-center",
                ),
                alive=True,
            ),
        ),
        control_points=(
            CControlPoint(
                id="cp-center",
                pos=from_units(3, 3),
                owner=None,
                # Two concurrent attempts on ONE post: the race, in state.
                takers=(
                    TakeAttempt(
                        unit_id="blue-u1", team_id="blue", start_time=200, completion_time=400
                    ),
                    TakeAttempt(
                        unit_id="red-u1", team_id="red", start_time=100, completion_time=600
                    ),
                ),
            ),
            CControlPoint(id="cp-east", pos=from_units(9, 4), owner="red"),
        ),
        missions=(
            CMission(id="ms-hold", kind="hold", pos=from_units(3, 3), amount=3, reward=8),
            CMission(
                id="ms-supply",
                kind="deliver",
                pos=from_units(1, 1),
                amount=3,
                reward=10,
                status="completed",
                completed_by=("blue",),
                completed_time=350,
            ),
        ),
        resource_nodes=(CResourceNode(id="rn-west", pos=from_units(0, 2), remaining=7),),
    )


# --------------------------------------------------------------------------- #
# Criterion 1a — canonical JSON, stable hash, frozen, validated vocabulary
# --------------------------------------------------------------------------- #
def test_round_trip_is_byte_identical() -> None:
    state = sample_state()
    payload = cstate_to_json(state)
    restored = cstate_from_json(payload)
    assert restored == state
    assert cstate_to_json(restored) == payload


def test_canonical_json_is_sorted_and_compact() -> None:
    payload = cstate_to_json(sample_state())
    parsed = json.loads(payload)
    assert payload == json.dumps(parsed, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def test_state_hash_is_stable_and_sensitive() -> None:
    a, b = sample_state(), sample_state()
    assert cstate_hash(a) == cstate_hash(b)
    moved = dataclasses.replace(a, clock=a.clock + 1)
    assert cstate_hash(moved) != cstate_hash(a)


def test_takers_order_does_not_affect_hash() -> None:
    """The contested-take race must hash the same regardless of the order the two
    attempts were registered — ``canonical_takers`` keeps ``takers`` canonical."""
    state = sample_state()
    cp = next(c for c in state.control_points if c.id == "cp-center")
    reversed_cp = dataclasses.replace(cp, takers=tuple(reversed(cp.takers)))
    shuffled = dataclasses.replace(
        state,
        control_points=tuple(
            reversed_cp if c.id == "cp-center" else c for c in state.control_points
        ),
    )
    # Re-serialising through from_dict canonicalises the order, so the hashes match.
    assert cstate_hash(cstate_from_json(cstate_to_json(shuffled))) == cstate_hash(state)


def test_state_is_frozen() -> None:
    state = sample_state()
    with pytest.raises(dataclasses.FrozenInstanceError):
        state.clock = 99  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        state.units[0].pos = from_units(0, 0)  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        state.control_points[0].takers[0].completion_time = 1  # type: ignore[misc]


def test_invalid_vocabulary_rejected() -> None:
    state = sample_state()
    with pytest.raises(ValueError):
        dataclasses.replace(state, mode="deathmatch")
    with pytest.raises(ValueError):
        dataclasses.replace(state, status="paused")
    with pytest.raises(ValueError):
        CMission(id="x", kind="teleport", pos=from_units(0, 0), amount=1, reward=1)
    with pytest.raises(ValueError):
        CAction(kind="fly", start_time=0, completion_time=1)


def test_vocabulary_tuples_are_the_documented_shape() -> None:
    assert ACTION_KINDS == ("move", "gather", "take_post", "deliver")
    for required in ("action_started", "action_completed", "action_failed"):
        assert required in TRANSITION_KINDS
    assert "decision_point" in OBSERVATION_KINDS
    assert set(EVENT_KINDS) == set(TRANSITION_KINDS) | set(OBSERVATION_KINDS)
    # transition and observation kinds are disjoint
    assert not (set(TRANSITION_KINDS) & set(OBSERVATION_KINDS))


# --------------------------------------------------------------------------- #
# Criterion 2 — no binary float anywhere (value scan + source scan)
# --------------------------------------------------------------------------- #
def _iter_scalars(obj: object):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _iter_scalars(k)
            yield from _iter_scalars(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _iter_scalars(v)
    else:
        yield obj


def test_no_binary_float_in_any_exposed_state_value() -> None:
    """The honesty scan (h6): every scalar reachable from the canonical JSON of a
    rich state is an int / str / bool / None — never a binary ``float``."""
    checked = 0
    for scalar in _iter_scalars(sample_state().to_dict()):
        assert not isinstance(scalar, float), f"float leaked into state: {scalar!r}"
        assert scalar is None or isinstance(scalar, (int, str)), f"unexpected {type(scalar)}"
        checked += 1
    assert checked > 0


def test_continuous_package_source_has_no_float_literals_or_casts() -> None:
    """Generalises ``space.py``'s own scan to the WHOLE continuous package: no
    module contains a float literal or a ``float(...)`` cast, so exactness cannot
    be undone by a later edit anywhere in the lane."""
    modules = sorted(CONTINUOUS_DIR.glob("*.py"))
    assert {"state.py", "events.py", "space.py", "timeline.py"} <= {m.name for m in modules}
    offenders: list[str] = []
    for module in modules:
        tree = ast.parse(module.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, float):
                offenders.append(f"{module.name}: float literal {node.value!r}")
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "float"
            ):
                offenders.append(f"{module.name}: float() cast")
    assert not offenders, f"float discipline broken: {offenders}"


# --------------------------------------------------------------------------- #
# Criterion 1b — the fold: a scripted match, incl. the contested-take race
# --------------------------------------------------------------------------- #
def initial_state() -> CMatchState:
    """The starting state for the scripted determinism match: everyone idle."""
    return CMatchState(
        match_id="cm-race",
        scenario_id="drift-1",
        seed=7,
        mode="competitive",
        clock=0,
        time_limit=1000,
        width=10 * 1000,
        height=8 * 1000,
        status="pending",
        winner=None,
        teams=(
            CTeamState(
                id="blue",
                name="Blue Foundry",
                resources=0,
                agents=(
                    CAgentSlot(id="blue-scout", model="colleague/qwen", role="scout"),
                    CAgentSlot(id="blue-harvester", model="colleague/qwen", role="harvester"),
                ),
            ),
            CTeamState(
                id="red",
                name="Red Relay",
                resources=0,
                agents=(CAgentSlot(id="red-striker", model="claude-sonnet-5", role="striker"),),
            ),
        ),
        units=(
            CUnit(
                id="blue-u1",
                team_id="blue",
                agent_id="blue-scout",
                role="scout",
                pos=from_units(2, 2),
            ),
            CUnit(
                id="blue-u2",
                team_id="blue",
                agent_id="blue-harvester",
                role="harvester",
                pos=from_units(1, 1),
            ),
            CUnit(
                id="red-u1",
                team_id="red",
                agent_id="red-striker",
                role="striker",
                pos=from_units(5, 5),
            ),
        ),
        control_points=(CControlPoint(id="cp-center", pos=from_units(3, 3)),),
        missions=(
            CMission(id="ms-hold", kind="hold", pos=from_units(3, 3), amount=3, reward=8),
            CMission(id="ms-supply", kind="deliver", pos=from_units(1, 1), amount=3, reward=10),
        ),
        resource_nodes=(CResourceNode(id="rn-west", pos=from_units(0, 2), remaining=10),),
    )


def scripted_events() -> tuple[CEvent, ...]:
    """A canonical match that exercises every transition kind AND the race:

    the SLOW red-u1 starts taking cp-center first (completes t=600), the FAST
    blue-u1 starts later (completes t=400) and wins — red-u1's attempt fails with
    a first-class ``action_failed`` in the log (spec h9).
    """
    return (
        CEvent(0, 0, "match_started", {}),
        CEvent(0, 1, "plan_declared", {"team_id": "blue", "agent_id": "blue-scout", "text": "cap"}),
        # red-u1 (slow) begins taking the post first — one taker on the post.
        CEvent(
            100,
            2,
            "action_started",
            {
                "unit_id": "red-u1",
                "kind": "take_post",
                "start_time": 100,
                "completion_time": 600,
                "target_id": "cp-center",
            },
        ),
        CEvent(100, 3, "message_sent", {"team_id": "red", "from": "red-striker", "text": "mine"}),
        CEvent(
            100,
            4,
            "action_started",
            {
                "unit_id": "blue-u2",
                "kind": "move",
                "start_time": 100,
                "completion_time": 150,
                "target_pos": from_units(0, 2).to_dict(),
            },
        ),
        CEvent(
            150,
            5,
            "unit_moved",
            {
                "unit_id": "blue-u2",
                "from": from_units(1, 1).to_dict(),
                "to": from_units(0, 2).to_dict(),
            },
        ),
        CEvent(150, 6, "action_completed", {"unit_id": "blue-u2"}),
        CEvent(150, 7, "decision_point", {"unit_id": "blue-u2", "game_time": 150}),
        CEvent(
            150,
            8,
            "action_started",
            {
                "unit_id": "blue-u2",
                "kind": "gather",
                "start_time": 150,
                "completion_time": 250,
                "target_id": "rn-west",
            },
        ),
        # blue-u1 (fast) begins taking the SAME post later — now TWO takers race.
        CEvent(
            200,
            9,
            "action_started",
            {
                "unit_id": "blue-u1",
                "kind": "take_post",
                "start_time": 200,
                "completion_time": 400,
                "target_id": "cp-center",
            },
        ),
        CEvent(
            200,
            10,
            "seat_latency",
            {"team_id": "blue", "agent_id": "blue-scout", "unit_id": "blue-u1", "elapsed_ms": 42},
        ),
        CEvent(
            250,
            11,
            "resource_gathered",
            {"unit_id": "blue-u2", "node_id": "rn-west", "amount": 3},
        ),
        CEvent(250, 12, "action_completed", {"unit_id": "blue-u2"}),
        CEvent(
            250,
            13,
            "action_started",
            {
                "unit_id": "blue-u2",
                "kind": "move",
                "start_time": 250,
                "completion_time": 300,
                "target_pos": from_units(1, 1).to_dict(),
            },
        ),
        CEvent(
            300,
            14,
            "unit_moved",
            {
                "unit_id": "blue-u2",
                "from": from_units(0, 2).to_dict(),
                "to": from_units(1, 1).to_dict(),
            },
        ),
        CEvent(300, 15, "action_completed", {"unit_id": "blue-u2"}),
        CEvent(
            300,
            16,
            "action_started",
            {
                "unit_id": "blue-u2",
                "kind": "deliver",
                "start_time": 300,
                "completion_time": 350,
                "target_id": "blue",
            },
        ),
        CEvent(
            350,
            17,
            "resource_delivered",
            {"unit_id": "blue-u2", "team_id": "blue", "amount": 3},
        ),
        CEvent(350, 18, "action_completed", {"unit_id": "blue-u2"}),
        CEvent(350, 19, "mission_completed", {"mission_id": "ms-supply", "team_id": "blue"}),
        # t=400: the fast unit finishes first and takes the post.
        CEvent(
            400, 20, "post_taken", {"cp_id": "cp-center", "team_id": "blue", "unit_id": "blue-u1"}
        ),
        CEvent(400, 21, "action_completed", {"unit_id": "blue-u1"}),
        # the slow unit's attempt fails — the race made honest in the log.
        CEvent(
            400,
            22,
            "action_failed",
            {"unit_id": "red-u1", "reason": "post taken by a faster agent"},
        ),
        CEvent(400, 23, "decision_point", {"unit_id": "red-u1", "game_time": 400}),
        CEvent(500, 24, "mission_completed", {"mission_id": "ms-hold", "team_id": "blue"}),
        CEvent(500, 25, "match_finished", {"winner": "blue"}),
    )


def test_fold_reproduces_final_state_exactly() -> None:
    final = fold_events(initial_state(), scripted_events())

    assert final.status == "finished"
    assert final.winner == "blue"
    assert final.clock == 500  # the last event's game_time

    blue = next(t for t in final.teams if t.id == "blue")
    assert blue.resources == 3  # gathered 3, delivered 3

    u1 = next(u for u in final.units if u.id == "blue-u1")
    u2 = next(u for u in final.units if u.id == "blue-u2")
    red = next(u for u in final.units if u.id == "red-u1")
    assert u1.action is None and u2.action is None and red.action is None  # all idle
    assert u2.pos == from_units(1, 1)  # moved out and back
    assert u2.carrying == 0

    node = next(r for r in final.resource_nodes if r.id == "rn-west")
    assert node.remaining == 7

    center = next(c for c in final.control_points if c.id == "cp-center")
    assert center.owner == "blue"  # the faster agent took it
    assert center.takers == ()  # both attempts resolved (winner taken, loser failed)

    supply = next(m for m in final.missions if m.id == "ms-supply")
    assert supply.status == "completed" and supply.completed_by == ("blue",)
    assert supply.completed_time == 350
    hold = next(m for m in final.missions if m.id == "ms-hold")
    assert hold.completed_time == 500


def test_contested_take_is_representable_mid_race() -> None:
    """Fold only up to the moment both units are mid-take: the post carries BOTH
    attempts at once — the race is in state, not merely implied."""
    events = scripted_events()
    # events[9] is blue-u1's action_started (the second taker joins at t=200)
    up_to_race = events[: 9 + 1]
    mid = fold_events(initial_state(), up_to_race)
    center = next(c for c in mid.control_points if c.id == "cp-center")
    keys = {(t.unit_id, t.team_id, t.completion_time) for t in center.takers}
    assert keys == {("blue-u1", "blue", 400), ("red-u1", "red", 600)}
    assert center.owner is None  # nobody has taken it yet
    # canonical order: the sooner completion (blue-u1 @400) sorts first
    assert [t.unit_id for t in center.takers] == ["blue-u1", "red-u1"]


def test_action_failed_withdraws_the_losers_take_attempt() -> None:
    state = initial_state()
    state = apply_event(state, CEvent(0, 0, "match_started", {}))
    state = apply_event(
        state,
        CEvent(
            100,
            1,
            "action_started",
            {
                "unit_id": "red-u1",
                "kind": "take_post",
                "start_time": 100,
                "completion_time": 600,
                "target_id": "cp-center",
            },
        ),
    )
    center = next(c for c in state.control_points if c.id == "cp-center")
    assert [t.unit_id for t in center.takers] == ["red-u1"]
    red = next(u for u in state.units if u.id == "red-u1")
    assert red.action is not None and red.action.kind == "take_post"

    failed = apply_event(
        state, CEvent(400, 2, "action_failed", {"unit_id": "red-u1", "reason": "displaced"})
    )
    center = next(c for c in failed.control_points if c.id == "cp-center")
    assert center.takers == ()  # withdrawn
    red = next(u for u in failed.units if u.id == "red-u1")
    assert red.action is None  # idle again


# --------------------------------------------------------------------------- #
# Criterion 1c — the pinned determinism hash (committed IN the test, not a file)
# --------------------------------------------------------------------------- #
# The scripted match's final-state hash. Pure integers → platform-independent;
# a change means a state/fold rule changed (update knowingly). The fixture-FILE
# gate (a committed determinism.hash) is t6's job — here the constant lives in
# the test, as the task directs.
_GOLDEN_STATE_HASH = "5189d3055d0102d7126d4606fd73aef6303c8f98b30bf21c88ad9f81dc348ec1"


def test_scripted_sequence_matches_committed_hash() -> None:
    final = fold_events(initial_state(), scripted_events())
    assert cstate_hash(final) == _GOLDEN_STATE_HASH


def test_replaying_twice_is_deterministic() -> None:
    log = CMatchLog(initial_state=initial_state(), events=scripted_events())
    assert cstate_hash(log.final_state()) == cstate_hash(log.final_state())


# --------------------------------------------------------------------------- #
# Observational events never change board state
# --------------------------------------------------------------------------- #
def test_observational_events_leave_state_and_clock_unchanged() -> None:
    state = dataclasses.replace(sample_state(), clock=200)
    for kind, data in (
        ("decision_point", {"unit_id": "blue-u1", "game_time": 999}),
        ("message_sent", {"team_id": "blue", "from": "blue-scout", "text": "hi"}),
        ("plan_declared", {"team_id": "blue", "agent_id": "blue-scout", "text": "plan"}),
        ("seat_latency", {"team_id": "blue", "agent_id": "blue-scout", "elapsed_ms": 5}),
    ):
        # game_time far ahead of the clock — an observation must NOT advance it.
        after = apply_event(state, CEvent(999, 0, kind, data))
        assert after == state
        assert after.clock == 200


def test_transition_advances_the_clock_to_event_game_time() -> None:
    state = apply_event(initial_state(), CEvent(0, 0, "match_started", {}))
    assert state.clock == 0
    moved = apply_event(
        state,
        CEvent(
            120,
            1,
            "unit_moved",
            {
                "unit_id": "blue-u1",
                "from": from_units(2, 2).to_dict(),
                "to": from_units(2, 3).to_dict(),
            },
        ),
    )
    assert moved.clock == 120


# --------------------------------------------------------------------------- #
# Corruption is loud; the clock never runs backwards
# --------------------------------------------------------------------------- #
def test_unknown_event_kind_rejected() -> None:
    with pytest.raises(ValueError):
        CEvent(0, 0, "tea_break", {})


def test_corrupt_references_are_loud() -> None:
    state = apply_event(initial_state(), CEvent(0, 0, "match_started", {}))
    with pytest.raises(ValueError):
        apply_event(
            state,
            CEvent(
                1,
                1,
                "unit_moved",
                {
                    "unit_id": "ghost",
                    "from": from_units(0, 0).to_dict(),
                    "to": from_units(0, 1).to_dict(),
                },
            ),
        )


def test_clock_cannot_run_backwards() -> None:
    state = apply_event(initial_state(), CEvent(0, 0, "match_started", {}))
    forward = apply_event(state, CEvent(300, 1, "action_completed", {"unit_id": "blue-u1"}))
    assert forward.clock == 300
    with pytest.raises(ValueError, match="backwards|precedes"):
        apply_event(forward, CEvent(200, 2, "action_completed", {"unit_id": "blue-u2"}))


def test_event_game_time_and_seq_must_be_nonneg_ints() -> None:
    with pytest.raises(ValueError):
        CEvent(1.5, 0, "match_started", {})  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        CEvent(-1, 0, "match_started", {})
    with pytest.raises(ValueError):
        # bool is an int subclass but is not a game-time coordinate
        CEvent(True, 0, "match_started", {})  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        CEvent(0, -1, "match_started", {})


# --------------------------------------------------------------------------- #
# CMatchLog: JSONL round-trip byte-identical; driver_kinds metadata
# --------------------------------------------------------------------------- #
def test_jsonl_round_trip_is_byte_identical() -> None:
    log = CMatchLog(initial_state=initial_state(), events=scripted_events())
    payload = log.to_jsonl()
    restored = CMatchLog.from_jsonl(payload)
    assert restored == log
    assert restored.to_jsonl() == payload
    assert cstate_hash(restored.final_state()) == cstate_hash(log.final_state())


def test_driver_kinds_default_empty_and_round_trip() -> None:
    bare = CMatchLog(initial_state=initial_state(), events=scripted_events())
    assert bare.driver_kinds == {}

    log = CMatchLog(
        initial_state=initial_state(),
        events=scripted_events(),
        driver_kinds={"blue": "resident", "red": "bot"},
    )
    restored = CMatchLog.from_jsonl(log.to_jsonl())
    assert restored == log
    assert restored.driver_kinds == {"blue": "resident", "red": "bot"}
    # Metadata never leaks into the fold or the hash.
    assert cstate_hash(restored.final_state()) == cstate_hash(bare.final_state())


def test_from_jsonl_tolerates_logs_without_driver_kinds() -> None:
    log = CMatchLog(initial_state=initial_state(), events=scripted_events())
    payload = log.to_jsonl()
    # Strip the driver_kinds key from the header to mimic an older log.
    lines = payload.splitlines()
    header = json.loads(lines[0])
    del header["driver_kinds"]
    lines[0] = json.dumps(header, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    restored = CMatchLog.from_jsonl("\n".join(lines) + "\n")
    assert restored.driver_kinds == {}
    assert restored.final_state().status == "finished"


def test_wrong_log_version_rejected() -> None:
    from league.engine.continuous import LOG_VERSION

    log = CMatchLog(initial_state=initial_state(), events=())
    payload = log.to_jsonl().replace(f'"log_version":{LOG_VERSION}', '"log_version":99')
    with pytest.raises(ValueError):
        CMatchLog.from_jsonl(payload)


def test_empty_log_rejected() -> None:
    with pytest.raises(ValueError, match="empty"):
        CMatchLog.from_jsonl("")
