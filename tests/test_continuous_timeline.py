"""Acceptance tests for the deterministic initiative timeline (plan task C7-t2).

These are the merge gate for ``league/engine/continuous/timeline.py``. Written
before the implementation (TDD), they pin the two acceptance criteria:

1. The timeline orders the world by action *completion time*: the earliest
   completion is the next decision point, and a faster agent (shorter action
   duration) demonstrably gets more decision points per unit of game time. The
   ``test_faster_agent_gets_more_decision_points`` test schedules two agents
   whose durations differ 2:1 and asserts the *exact* decision-point sequence,
   including the ``t=200`` tie that canonical order resolves.
2. Simultaneous completions break ties by canonical order ``(time, team_id,
   unit_id)``; ``test_submission_order_never_changes_resolution`` proves the
   same action set enqueued in different orders drains identically, and the
   ``hashlib``-seeded stress test enforces that over many shuffles.

Determinism discipline: every "random" order here is derived from ``hashlib``
(never the ``random`` module), so these tests are themselves reproducible.
"""

from __future__ import annotations

import hashlib

import pytest

from league.engine.continuous import ScheduledAction, Timeline


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _keys(entries) -> list[tuple[int, str, str]]:
    return [e.key for e in entries]


def _shuffled(entries: list[ScheduledAction], salt: str) -> list[ScheduledAction]:
    """A deterministic permutation seeded by ``hashlib`` (never ``random``)."""
    return sorted(
        entries,
        key=lambda e: hashlib.sha256(f"{salt}:{e.unit_id}".encode()).hexdigest(),
    )


def _drain(timeline: Timeline) -> list[ScheduledAction]:
    out: list[ScheduledAction] = []
    while not timeline.is_empty():
        out.append(timeline.advance())
    return out


# --------------------------------------------------------------------------- #
# Criterion 1 — completion-time ordering; faster acts more often
# --------------------------------------------------------------------------- #
def test_faster_agent_gets_more_decision_points() -> None:
    """A duration-100 agent gets ~2x the decision points of a duration-200 one.

    The property emerges purely from durations. We drive the timeline the way
    the resolver (t5) will: pop the earliest completion, then reschedule that
    unit's next action at ``completion_time + duration``. The fast unit ``a1``
    (team ``a``) sorts before the slow unit ``b1`` (team ``b``), so the ``t=200``
    tie — where BOTH complete at once — resolves to ``a1`` by canonical order.
    """
    duration = {"a1": 100, "b1": 200}
    team = {"a1": "a", "b1": "b"}
    tl = Timeline()
    tl.schedule(ScheduledAction(completion_time=100, team_id="a", unit_id="a1"))
    tl.schedule(ScheduledAction(completion_time=200, team_id="b", unit_id="b1"))

    sequence: list[tuple[str, int]] = []
    for _ in range(6):
        entry = tl.advance()
        sequence.append((entry.unit_id, entry.completion_time))
        nxt = entry.completion_time + duration[entry.unit_id]
        tl.schedule(
            ScheduledAction(completion_time=nxt, team_id=team[entry.unit_id], unit_id=entry.unit_id)
        )

    # The exact interleaving, including the t=200 and t=400 ties (canonical order
    # puts a1 before b1 at each tie).
    assert sequence == [
        ("a1", 100),
        ("a1", 200),
        ("b1", 200),
        ("a1", 300),
        ("a1", 400),
        ("b1", 400),
    ]
    fast = [t for u, t in sequence if u == "a1"]
    slow = [t for u, t in sequence if u == "b1"]
    assert len(fast) == 2 * len(slow)  # faster agent acts twice as often


def test_tie_break_is_canonical_not_speed() -> None:
    """The tie-break is (time, team_id, unit_id) — NOT "the faster one first".

    Same speeds as above, but now the SLOW agent's ids sort first. At the
    ``t=200`` tie the slow unit must win, proving the order comes from the ids,
    not the durations.
    """
    duration = {"a-fast": 100, "z-slow": 200}
    team = {"a-fast": "team-z", "z-slow": "team-a"}  # slow unit sorts first by team
    tl = Timeline()
    tl.schedule(ScheduledAction(completion_time=100, team_id="team-z", unit_id="a-fast"))
    tl.schedule(ScheduledAction(completion_time=200, team_id="team-a", unit_id="z-slow"))

    sequence: list[tuple[str, int]] = []
    for _ in range(4):
        entry = tl.advance()
        sequence.append((entry.unit_id, entry.completion_time))
        nxt = entry.completion_time + duration[entry.unit_id]
        tl.schedule(
            ScheduledAction(completion_time=nxt, team_id=team[entry.unit_id], unit_id=entry.unit_id)
        )

    # At t=200 the slow unit (team-a) is popped before the fast unit (team-z).
    assert sequence == [
        ("a-fast", 100),
        ("z-slow", 200),
        ("a-fast", 200),
        ("a-fast", 300),
    ]


def test_advance_pops_in_completion_time_order() -> None:
    tl = Timeline()
    tl.schedule(ScheduledAction(completion_time=300, team_id="t", unit_id="c"))
    tl.schedule(ScheduledAction(completion_time=100, team_id="t", unit_id="a"))
    tl.schedule(ScheduledAction(completion_time=200, team_id="t", unit_id="b"))
    assert [e.completion_time for e in _drain(tl)] == [100, 200, 300]


def test_peek_is_nonmutating() -> None:
    tl = Timeline()
    tl.schedule(ScheduledAction(completion_time=50, team_id="t", unit_id="u1"))
    tl.schedule(ScheduledAction(completion_time=10, team_id="t", unit_id="u2"))
    first = tl.peek()
    assert first is not None and first.unit_id == "u2"
    assert tl.peek() == first  # idempotent
    assert len(tl) == 2  # nothing removed
    assert tl.advance() == first
    assert len(tl) == 1


def test_pending_returns_canonical_order() -> None:
    entries = [
        ScheduledAction(completion_time=200, team_id="b", unit_id="b1"),
        ScheduledAction(completion_time=200, team_id="a", unit_id="a1"),
        ScheduledAction(completion_time=100, team_id="z", unit_id="z1"),
    ]
    tl = Timeline()
    for e in entries:
        tl.schedule(e)
    assert _keys(tl.pending()) == [(100, "z", "z1"), (200, "a", "a1"), (200, "b", "b1")]


# --------------------------------------------------------------------------- #
# Criterion 2 — total tie-break; submission order can never change resolution
# --------------------------------------------------------------------------- #
def test_simultaneous_ties_break_by_team_then_unit() -> None:
    """All four complete at t=500; canonical (team_id, unit_id) orders them."""
    tl = Timeline()
    tl.schedule(ScheduledAction(completion_time=500, team_id="red", unit_id="r2"))
    tl.schedule(ScheduledAction(completion_time=500, team_id="blue", unit_id="b2"))
    tl.schedule(ScheduledAction(completion_time=500, team_id="red", unit_id="r1"))
    tl.schedule(ScheduledAction(completion_time=500, team_id="blue", unit_id="b1"))
    assert [(e.team_id, e.unit_id) for e in _drain(tl)] == [
        ("blue", "b1"),
        ("blue", "b2"),
        ("red", "r1"),
        ("red", "r2"),
    ]


def test_submission_order_never_changes_resolution() -> None:
    """The core determinism proof: same set, different enqueue orders, one drain.

    Includes ties at t=200 and t=400 so the tie-break — not just the primary
    time key — is exercised across every permutation.
    """
    entries = [
        ScheduledAction(completion_time=100, team_id="a", unit_id="a1"),
        ScheduledAction(completion_time=200, team_id="a", unit_id="a2"),
        ScheduledAction(completion_time=200, team_id="b", unit_id="b1"),
        ScheduledAction(completion_time=400, team_id="a", unit_id="a3"),
        ScheduledAction(completion_time=400, team_id="b", unit_id="b2"),
        ScheduledAction(completion_time=300, team_id="c", unit_id="c1"),
    ]
    canonical = _keys(sorted(entries, key=lambda e: e.key))

    for salt in ("alpha", "bravo", "charlie", "delta", "echo"):
        tl = Timeline()
        for e in _shuffled(entries, salt):
            tl.schedule(e)
        assert _keys(_drain(tl)) == canonical


def test_stress_shuffled_insertion_identical_pop_sequence() -> None:
    """Many entries (with ties), many hashlib-seeded shuffles → one pop order."""
    entries = [
        ScheduledAction(
            completion_time=(i % 10) * 10,  # deliberate ties across the tens
            team_id=f"t{i % 4}",
            unit_id=f"u{i:03d}",  # globally unique → one pending per unit holds
        )
        for i in range(120)
    ]
    canonical = _keys(sorted(entries, key=lambda e: e.key))

    for n in range(25):
        salt = hashlib.sha256(f"stress-{n}".encode()).hexdigest()
        tl = Timeline()
        for e in _shuffled(entries, salt):
            tl.schedule(e)
        assert _keys(_drain(tl)) == canonical


# --------------------------------------------------------------------------- #
# One pending action per unit — legality of the queue
# --------------------------------------------------------------------------- #
def test_one_pending_action_per_unit_enforced() -> None:
    tl = Timeline()
    tl.schedule(ScheduledAction(completion_time=100, team_id="t", unit_id="u1"))
    with pytest.raises(ValueError, match="pending"):
        tl.schedule(ScheduledAction(completion_time=150, team_id="t", unit_id="u1"))
    assert len(tl) == 1
    assert "u1" in tl


def test_cancel_removes_entry_and_allows_reschedule() -> None:
    """Interruption primitive (t5): cancel a unit's pending action, reschedule it."""
    tl = Timeline()
    a = ScheduledAction(completion_time=100, team_id="t", unit_id="u1")
    tl.schedule(a)
    assert tl.cancel("u1") == a
    assert "u1" not in tl and tl.is_empty()
    # cancelling an absent unit is a no-op returning None
    assert tl.cancel("ghost") is None
    # the freed unit can be scheduled again
    b = ScheduledAction(completion_time=250, team_id="t", unit_id="u1")
    tl.schedule(b)
    assert tl.advance() == b


# --------------------------------------------------------------------------- #
# Empty-timeline behaviour and the game clock
# --------------------------------------------------------------------------- #
def test_peek_on_empty_returns_none() -> None:
    assert Timeline().peek() is None


def test_advance_on_empty_raises() -> None:
    with pytest.raises(ValueError, match="empty"):
        Timeline().advance()


def test_now_tracks_last_completion_and_rejects_scheduling_in_the_past() -> None:
    tl = Timeline()
    assert tl.now == 0
    tl.schedule(ScheduledAction(completion_time=100, team_id="t", unit_id="u1"))
    tl.schedule(ScheduledAction(completion_time=300, team_id="t", unit_id="u2"))
    assert tl.advance().completion_time == 100
    assert tl.now == 100  # the clock is the last completion consumed
    # scheduling at-or-after now is fine (a zero-duration action lands at now)...
    tl.schedule(ScheduledAction(completion_time=100, team_id="t", unit_id="u3"))
    # ...but a completion before now is a bug and is rejected loudly.
    with pytest.raises(ValueError, match="before now|past"):
        tl.schedule(ScheduledAction(completion_time=50, team_id="t", unit_id="u4"))


# --------------------------------------------------------------------------- #
# Time is integer game-time; ids are meaningful
# --------------------------------------------------------------------------- #
def test_completion_time_must_be_a_nonnegative_int() -> None:
    with pytest.raises(ValueError):
        ScheduledAction(completion_time=1.5, team_id="t", unit_id="u1")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        ScheduledAction(completion_time=-1, team_id="t", unit_id="u1")
    with pytest.raises(ValueError):
        # bool is a subclass of int but is not a valid game-time value
        ScheduledAction(completion_time=True, team_id="t", unit_id="u1")  # type: ignore[arg-type]


def test_team_and_unit_ids_must_be_nonempty_strings() -> None:
    with pytest.raises(ValueError):
        ScheduledAction(completion_time=1, team_id="", unit_id="u1")
    with pytest.raises(ValueError):
        ScheduledAction(completion_time=1, team_id="t", unit_id="")


def test_opaque_action_payload_is_carried_through() -> None:
    """The timeline never interprets the payload, but preserves it for the resolver."""
    payload = {"kind": "take_post", "post_id": "cp3"}
    tl = Timeline()
    tl.schedule(ScheduledAction(completion_time=42, team_id="t", unit_id="u1", action=payload))
    assert tl.advance().action == payload


def test_canonical_key_shape() -> None:
    entry = ScheduledAction(completion_time=7, team_id="blue", unit_id="b1")
    assert entry.key == (7, "blue", "b1")
