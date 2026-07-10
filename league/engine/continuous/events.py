"""The continuous match event log — the single source of truth, timeline edition.

The sibling of the grid's ``events.py``, and it obeys the same two rules
(spec c11/h4, c12/h5): every state transition is an event, and observational
events carry the social/audit record without touching board state. The fold
(:func:`apply_event`) produces the next :class:`~league.engine.continuous.state.
CMatchState`; replaying a log from its initial state reproduces the final state
and hash exactly — that fold *is* the replay, the continuous determinism gate
(t6) and the scoring input.

Time model (the difference from the grid)
-----------------------------------------
A :class:`CEvent` is timestamped by an integer ``game_time`` (the timeline's
clock at which it happens) rather than the grid's ``turn``. Folding a
**transition** event advances ``state.clock`` to that ``game_time`` — game time
comes only from the event stream, never a wall clock — and ``game_time`` is
monotonic non-decreasing (the timeline never schedules into the past, so a
transition whose ``game_time`` precedes the current clock is a corrupt log and
raises). Observational events are pure no-ops: they never move the clock.

Event vocabulary (the fixed tuples ``EVENT_KINDS`` unions)
----------------------------------------------------------
Transition kinds (folding one changes the board):

* ``match_started`` — status → active.
* ``action_started`` ``{unit_id, kind, start_time, completion_time, target_id?,
  target_pos?}`` — the unit commits to an action (``state.units[unit].action``
  set). If ``kind == "take_post"`` this *also* registers the unit's
  :class:`~league.engine.continuous.state.TakeAttempt` on the target control
  point, so a contested race is present in state the moment both units start.
* ``action_completed`` ``{unit_id}`` — the unit's action finished; it goes idle
  (``action`` → ``None``). The *effect* (a move / gather / delivery / take) is a
  separate event emitted alongside it — this one only clears the action.
* ``action_failed`` ``{unit_id, reason}`` — the unit's action failed or was
  interrupted; it goes idle and any take attempt it had is withdrawn from every
  control point. ``reason`` is a free string (e.g. ``"post taken by a faster
  agent"``) — the first-class loser's-attempt record the race semantics require
  (spec h9).
* ``unit_moved`` ``{unit_id, from, to}`` — continuous move; ``pos`` → ``to``
  (``from`` is carried for the replay's interpolation, t9).
* ``resource_gathered`` ``{unit_id, node_id, amount}`` — carry += amount, node
  remaining -= amount.
* ``resource_delivered`` ``{unit_id, team_id, amount}`` — carry -= amount, team
  resources += amount.
* ``post_taken`` ``{cp_id, team_id, unit_id}`` — the winner takes the post:
  ``owner`` → team, and the winner's take attempt is cleared. Each *losing*
  attempt is cleared by its own ``action_failed`` (one event per unit).
* ``mission_completed`` ``{mission_id, team_id}`` — status → completed, team
  added to ``completed_by`` (dual-award safe), ``completed_time`` stamped from
  the event's ``game_time`` on the first completion.
* ``match_finished`` ``{winner}`` — status → finished, ``winner`` set.

Observation kinds (the fold leaves state exactly as-is — parity with the grid
log so scoring/probe can adapt later, spec boundary c11):

* ``decision_point`` ``{unit_id, game_time}`` — a unit became idle and its mind
  is owed a decision (the cadence signal t7's harness consumes).
* ``message_sent`` / ``plan_declared`` — the social record cooperation scoring
  reads.
* ``seat_latency`` ``{team_id, agent_id?, unit_id?, elapsed_ms}`` — harness
  instrumentation (wall-clock is measured only in ``league/harness.py``, never
  here); folding it is a no-op, as with the grid.

Resolver contract for t5 (documented, not enforced here): per completion, emit
the effect event, then ``action_completed`` **or** ``action_failed``, then a
``decision_point`` for the freed unit — the fold is order-tolerant within a
``game_time`` because these touch disjoint fields.

The on-disk format is JSONL: line 1 is a header
``{"log_version", "initial_state", "driver_kinds", "fog"}``; every following
line is one event, all canonical JSON. ``driver_kinds`` is the per-team
declared-residency label (spec c10/h7) — harness metadata only, never folded,
defaulting to ``{}`` so a log written before it existed still parses. ``fog``
(issue #35) records whether this match's briefings are fogged — again pure
harness/CLI metadata (fog is a briefing-layer projection, never an engine
rule), persisted so the stepwise ``cmatch`` loop can rebuild every later
briefing with the same projection ``run_cmatch`` would have used; it defaults
to ``False`` so a log written before it existed still parses.
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field
from typing import Any, Iterable

from league.engine.continuous.space import Pos
from league.engine.continuous.state import (
    CAction,
    CMatchState,
    TakeAttempt,
    canonical_takers,
)

LOG_VERSION = 1

# State-transition events: applying one changes the board.
TRANSITION_KINDS = (
    "match_started",
    "action_started",
    "action_completed",
    "action_failed",
    "unit_moved",
    "resource_gathered",
    "resource_delivered",
    "post_taken",
    "mission_completed",
    "match_finished",
)
# Observational events: the social/audit record; the fold leaves state as-is.
OBSERVATION_KINDS = (
    "decision_point",
    "message_sent",
    "plan_declared",
    "seat_latency",
)
EVENT_KINDS = TRANSITION_KINDS + OBSERVATION_KINDS


@dataclass(frozen=True)
class CEvent:
    """One fact about the match: ``(game_time, seq)`` orders it, ``kind`` types it.

    ``game_time`` is the integer game-time coordinate at which the event happens
    (the timeline's clock); ``seq`` is a monotonic sequence disambiguating events
    that share a ``game_time``. Both are validated as non-negative ints — a
    ``float`` or ``bool`` game-time coordinate is rejected, keeping the clock (and
    the state hash) exact and platform-independent.
    """

    game_time: int
    seq: int
    kind: str
    data: dict[str, Any]

    def __post_init__(self) -> None:
        _require_nonneg_int(self.game_time, "game_time")
        _require_nonneg_int(self.seq, "seq")
        if self.kind not in EVENT_KINDS:
            raise ValueError(f"unknown event kind {self.kind!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "game_time": self.game_time,
            "seq": self.seq,
            "kind": self.kind,
            "data": self.data,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CEvent":
        return cls(game_time=d["game_time"], seq=d["seq"], kind=d["kind"], data=d["data"])


def _require_nonneg_int(value: Any, label: str) -> None:
    # ``type(...) is int`` deliberately excludes ``bool`` (a truth value is not a
    # game-time coordinate) and any binary ``float`` (banned in this lane).
    if type(value) is not int:
        raise ValueError(f"{label} must be an int, got {type(value).__name__}")
    if value < 0:
        raise ValueError(f"{label} must be non-negative, got {value}")


def _replace_one(items: tuple, item_id: str, **changes) -> tuple:
    """Replace the element with ``id == item_id`` in a tuple of dataclasses."""
    out = []
    found = False
    for item in items:
        if item.id == item_id:
            out.append(dataclasses.replace(item, **changes))
            found = True
        else:
            out.append(item)
    if not found:
        raise ValueError(f"no element with id {item_id!r}")
    return tuple(out)


def _find(items: tuple, item_id: str):
    for item in items:
        if item.id == item_id:
            return item
    raise ValueError(f"no element with id {item_id!r}")


def _add_taker(control_points: tuple, cp_id: str, attempt: TakeAttempt) -> tuple:
    """Register ``attempt`` on control point ``cp_id`` (canonically re-sorted)."""
    cp = _find(control_points, cp_id)
    return _replace_one(control_points, cp_id, takers=canonical_takers(cp.takers + (attempt,)))


def _remove_taker(control_points: tuple, cp_id: str, unit_id: str) -> tuple:
    """Drop ``unit_id``'s take attempt from control point ``cp_id``."""
    cp = _find(control_points, cp_id)
    kept = tuple(t for t in cp.takers if t.unit_id != unit_id)
    return _replace_one(control_points, cp_id, takers=kept)


def _remove_takes_by_unit(control_points: tuple, unit_id: str) -> tuple:
    """Withdraw ``unit_id``'s take attempt from *every* control point.

    A unit has at most one action pending, so at most one take attempt — but the
    failure event need not name the post, so scanning all points keeps
    ``action_failed`` robust and self-contained.
    """
    out = []
    for cp in control_points:
        kept = tuple(t for t in cp.takers if t.unit_id != unit_id)
        out.append(dataclasses.replace(cp, takers=kept) if len(kept) != len(cp.takers) else cp)
    return tuple(out)


def apply_event(state: CMatchState, event: CEvent) -> CMatchState:
    """The pure fold step: one event in, the next state out.

    Observational kinds return ``state`` unchanged. A transition first advances
    the clock to ``event.game_time`` (monotonic — a backwards timestamp is a
    corrupt log and raises), then applies its board change. Unknown ids raise —
    a log that references a missing entity is corrupt, and corruption must be loud.
    """
    kind, data = event.kind, event.data
    if kind in OBSERVATION_KINDS:
        return state

    if event.game_time < state.clock:
        raise ValueError(
            f"event game_time {event.game_time} precedes clock {state.clock} (time ran backwards)"
        )
    state = dataclasses.replace(state, clock=event.game_time)

    if kind == "match_started":
        return dataclasses.replace(state, status="active")
    if kind == "action_started":
        unit = _find(state.units, data["unit_id"])
        raw_pos = data.get("target_pos")
        action = CAction(
            kind=data["kind"],
            start_time=data["start_time"],
            completion_time=data["completion_time"],
            target_id=data.get("target_id"),
            target_pos=Pos.from_dict(raw_pos) if raw_pos is not None else None,
        )
        new = dataclasses.replace(state, units=_replace_one(state.units, unit.id, action=action))
        if data["kind"] == "take_post":
            attempt = TakeAttempt(
                unit_id=unit.id,
                team_id=unit.team_id,
                start_time=data["start_time"],
                completion_time=data["completion_time"],
            )
            new = dataclasses.replace(
                new, control_points=_add_taker(new.control_points, data["target_id"], attempt)
            )
        return new
    if kind == "action_completed":
        return dataclasses.replace(
            state, units=_replace_one(state.units, data["unit_id"], action=None)
        )
    if kind == "action_failed":
        return dataclasses.replace(
            state,
            units=_replace_one(state.units, data["unit_id"], action=None),
            control_points=_remove_takes_by_unit(state.control_points, data["unit_id"]),
        )
    if kind == "unit_moved":
        to = Pos.from_dict(data["to"])
        return dataclasses.replace(state, units=_replace_one(state.units, data["unit_id"], pos=to))
    if kind == "resource_gathered":
        unit = _find(state.units, data["unit_id"])
        node = _find(state.resource_nodes, data["node_id"])
        amount = data["amount"]
        return dataclasses.replace(
            state,
            units=_replace_one(state.units, unit.id, carrying=unit.carrying + amount),
            resource_nodes=_replace_one(
                state.resource_nodes, node.id, remaining=node.remaining - amount
            ),
        )
    if kind == "resource_delivered":
        unit = _find(state.units, data["unit_id"])
        team = _find(state.teams, data["team_id"])
        amount = data["amount"]
        return dataclasses.replace(
            state,
            units=_replace_one(state.units, unit.id, carrying=unit.carrying - amount),
            teams=_replace_one(state.teams, team.id, resources=team.resources + amount),
        )
    if kind == "post_taken":
        taken = dataclasses.replace(
            state,
            control_points=_replace_one(state.control_points, data["cp_id"], owner=data["team_id"]),
        )
        return dataclasses.replace(
            taken,
            control_points=_remove_taker(taken.control_points, data["cp_id"], data["unit_id"]),
        )
    if kind == "mission_completed":
        # A dead-heat is a dual award (spec decision c15): one completion event
        # per qualifying team, accumulated into a canonically sorted tuple; the
        # completion time is stamped from game_time on the first award only.
        mission = _find(state.missions, data["mission_id"])
        return dataclasses.replace(
            state,
            missions=_replace_one(
                state.missions,
                data["mission_id"],
                status="completed",
                completed_by=tuple(sorted({*mission.completed_by, data["team_id"]})),
                completed_time=(
                    mission.completed_time
                    if mission.completed_time is not None
                    else event.game_time
                ),
            ),
        )
    if kind == "match_finished":
        return dataclasses.replace(state, status="finished", winner=data["winner"])
    raise ValueError(f"unhandled event kind {kind!r}")  # pragma: no cover


def fold_events(initial: CMatchState, events: Iterable[CEvent]) -> CMatchState:
    """Replay: fold every event over the initial state."""
    state = initial
    for event in events:
        state = apply_event(state, event)
    return state


@dataclass(frozen=True)
class CMatchLog:
    """An initial state plus everything that happened — the whole continuous match.

    ``driver_kinds`` is header metadata only (per-team declared residency, spec
    c10/h7): never folded, never part of ``cstate_hash``, defaulting to ``{}`` so
    a log that predates it still parses. ``fog`` (issue #35) is the same kind of
    metadata for the briefing projection: recorded so ``cmatch show``/``tick``
    fog every later briefing exactly as ``run_cmatch`` would, never folded,
    defaulting to ``False`` so a pre-fog log still parses.
    """

    initial_state: CMatchState
    events: tuple[CEvent, ...]
    driver_kinds: dict[str, str] = field(default_factory=dict)
    fog: bool = False

    def final_state(self) -> CMatchState:
        return fold_events(self.initial_state, self.events)

    def to_jsonl(self) -> str:
        header = {
            "log_version": LOG_VERSION,
            "initial_state": self.initial_state.to_dict(),
            "driver_kinds": dict(self.driver_kinds),
            "fog": self.fog,
        }
        lines = [json.dumps(header, sort_keys=True, separators=(",", ":"), ensure_ascii=False)]
        lines.extend(
            json.dumps(e.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            for e in self.events
        )
        return "\n".join(lines) + "\n"

    @classmethod
    def from_jsonl(cls, payload: str) -> "CMatchLog":
        lines = [line for line in payload.splitlines() if line.strip()]
        if not lines:
            raise ValueError("empty match log")
        header = json.loads(lines[0])
        version = header.get("log_version")
        if version != LOG_VERSION:
            raise ValueError(f"unsupported log_version {version!r}; expected {LOG_VERSION}")
        initial = CMatchState.from_dict(header["initial_state"])
        events = tuple(CEvent.from_dict(json.loads(line)) for line in lines[1:])
        driver_kinds = dict(header.get("driver_kinds", {}))
        fog = bool(header.get("fog", False))
        return cls(initial_state=initial, events=events, driver_kinds=driver_kinds, fog=fog)
