"""The deterministic initiative timeline — completion times order the world.

This is the continuous lane's replacement for ``tick.py``'s uniform simultaneous
turn (spec c8/h8, decision c13). The grid engine gave every unit exactly one
action per turn, so speed could never be a strategic dimension. Here, every
action carries an in-game *duration*; the unit whose action finishes soonest
gets the next decision point, and a faster unit (shorter durations) therefore
acts again sooner — "more decision points per unit of game time" is not a
special rule, it is the arithmetic of the queue.

This module owns *time only* — never geometry. It imports nothing from
``space.py``; positions, distances and movement live in the spatial core and are
resolved elsewhere (t5). The timeline is a pure data structure with no game
rules, no I/O, and no randomness: you ``schedule`` completions, ``peek`` at the
next one, and ``advance`` to consume it.

Design decision — event queue, NOT micro-ticks (the frame's parked v3)
======================================================================
Two shapes were on the table:

* **Micro-ticks:** advance a global clock by a fixed small quantum and, at each
  step, check whether anything completed. Simple to picture, but it burns log
  volume and iteration on the vast majority of quanta where *nothing happens*,
  and it forces an arbitrary quantum choice that silently caps time resolution.
* **Event queue (chosen):** hold only the pending completions and jump straight
  to the earliest. Entries exist *only where something happens*, so the cost is
  proportional to decisions, not to elapsed game time, and there is no quantum
  to pick — durations may be any non-negative integers. Exact ordering falls out
  of a single total sort key.

We choose the event queue. Micro-ticks give nothing an event queue does not,
at strictly higher log and compute cost, and they would smear the crisp
"who finishes first" question the race semantics (t5) depend on across quantum
boundaries. The queue answers that question exactly.

Time is INTEGER game-time units — never floats, never wall-clock
================================================================
``completion_time`` is an opaque non-negative ``int`` (the intended convention
is *milliticks*; the concrete scale is the resolver/scenario's to pin in t4/t5,
not the timeline's). Integers keep ordering, equality and the eventual state
hash exact and platform-independent — the same reason the grid engine bans
``float``. ``bool`` is rejected even though it subclasses ``int``: a truth value
is not a game-time coordinate. Nothing here reads the wall clock; the daemon's
thinking-latency stays the out-of-game tempo axis and never enters game time.

The tie-break is total: ``(completion_time, team_id, unit_id)``
===============================================================
When two actions complete at the same instant, canonical order — the same
discipline ``tick.py`` uses for simultaneous moves — decides who is served
first: lowest ``completion_time``, then lowest ``team_id``, then lowest
``unit_id``. Because at most **one action is pending per unit** at any moment
(``schedule`` rejects a second, and ``unit_id`` is unique across live entries),
that triple is a *strict total order* over the queue — no two entries can ever
compare equal, so the pop sequence is fully determined by the entries alone.
Submission/insertion order is therefore irrelevant by construction: iteration
never trusts ``dict`` order, it sorts by this key explicitly. That is what makes
``test_submission_order_never_changes_resolution`` hold.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _require_nonneg_int(value: Any, label: str) -> None:
    # ``type(...) is int`` deliberately excludes ``bool`` (a truth value is not a
    # clock reading) and ``float`` (no binary floats in the continuous lane).
    if type(value) is not int:
        raise ValueError(f"{label} must be an int (game-time units), got {type(value).__name__}")
    if value < 0:
        raise ValueError(f"{label} must be non-negative, got {value}")


def _require_id(value: Any, label: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty string")


@dataclass(frozen=True)
class ScheduledAction:
    """One pending completion on the timeline.

    ``(completion_time, team_id, unit_id)`` — exposed as :attr:`key` — is the
    canonical ordering triple; it is a strict total order because at most one
    action is pending per unit. ``action`` is an OPAQUE payload the resolver
    attaches (what the unit is doing); the timeline never reads it, so ordering
    can never depend on it.
    """

    completion_time: int
    team_id: str
    unit_id: str
    action: Any = field(default=None, compare=False)

    def __post_init__(self) -> None:
        _require_nonneg_int(self.completion_time, "completion_time")
        _require_id(self.team_id, "team_id")
        _require_id(self.unit_id, "unit_id")

    @property
    def key(self) -> tuple[int, str, str]:
        """The canonical total-order key: ``(completion_time, team_id, unit_id)``."""
        return (self.completion_time, self.team_id, self.unit_id)


class Timeline:
    """A deterministic min-ordered queue of action completions.

    The public surface is intentionally small and forward-looking:

    * :meth:`schedule` — enqueue a completion (one pending per unit).
    * :meth:`peek` — the next completion without consuming it.
    * :meth:`advance` — consume and return the earliest completion (the next
      decision point); advances :attr:`now` to its time.
    * :meth:`pending` — every pending completion in canonical order (the
      "who is due next" initiative outlook t7's briefing will surface).
    * :meth:`cancel` — drop a unit's pending completion (the interruption
      primitive t5 needs when a taker is displaced mid-action).

    Ordering never relies on ``dict`` iteration order: every read sorts by the
    canonical key explicitly.
    """

    __slots__ = ("_pending", "_now")

    def __init__(self) -> None:
        # unit_id -> its single pending completion. Keying by unit_id is what
        # enforces "one pending action per unit" in O(1).
        self._pending: dict[str, ScheduledAction] = {}
        self._now: int = 0

    @property
    def now(self) -> int:
        """The game clock: the completion time of the last consumed action (0 initially)."""
        return self._now

    def __len__(self) -> int:
        return len(self._pending)

    def __contains__(self, unit_id: object) -> bool:
        return unit_id in self._pending

    def is_empty(self) -> bool:
        return not self._pending

    def schedule(self, entry: ScheduledAction) -> None:
        """Enqueue ``entry``. Raises if the unit already has a pending action or
        if the completion is in the past (before :attr:`now`)."""
        if entry.unit_id in self._pending:
            raise ValueError(
                f"unit {entry.unit_id!r} already has a pending action; "
                "one action may be pending per unit"
            )
        if entry.completion_time < self._now:
            raise ValueError(
                f"cannot schedule a completion at {entry.completion_time} "
                f"before now={self._now} (the past)"
            )
        self._pending[entry.unit_id] = entry

    def peek(self) -> ScheduledAction | None:
        """The earliest pending completion by canonical order, or ``None`` if empty.

        Non-mutating. The result is independent of insertion order because the
        canonical key is a strict total order over the pending set.
        """
        if not self._pending:
            return None
        return min(self._pending.values(), key=lambda e: e.key)

    def pending(self) -> tuple[ScheduledAction, ...]:
        """Every pending completion, canonical order — the initiative outlook."""
        return tuple(sorted(self._pending.values(), key=lambda e: e.key))

    def advance(self) -> ScheduledAction:
        """Consume and return the earliest completion; advance :attr:`now` to it.

        Raises ``ValueError`` on an empty timeline — draining past the end is a
        caller bug, not a silent no-op.
        """
        nxt = self.peek()
        if nxt is None:
            raise ValueError("advance() on an empty timeline")
        del self._pending[nxt.unit_id]
        self._now = nxt.completion_time
        return nxt

    def cancel(self, unit_id: str) -> ScheduledAction | None:
        """Drop and return a unit's pending completion, or ``None`` if it has none.

        The interruption primitive: when an in-progress action is cut short, its
        scheduled completion must leave the timeline before a fresh one is
        scheduled. Does not move :attr:`now`.
        """
        return self._pending.pop(unit_id, None)
