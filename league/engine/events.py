"""The match event log — the single source of truth every consumer reads.

Two design rules (spec c11/h4, c12/h5):

* **Every state transition is an event.** The tick engine never mutates state
  directly; it emits events and the fold (``apply_event``) produces the next
  state. Replaying a log from its initial state therefore reproduces the final
  state exactly — that fold *is* the replay, the determinism gate, and the
  scoring input.
* **Observational events carry the social record.** Declared actions,
  rejections, team messages, and declared plans don't change board state but
  are first-class events — cooperation scoring (t7) and the human replay (t8)
  are built from them.

The on-disk format is JSONL: line 1 is a header ``{"log_version", "initial_state"}``,
every following line one event, all canonical JSON.
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass
from typing import Any, Iterable

from league.engine.state import MatchState

LOG_VERSION = 1

# State-transition events: applying one changes the board.
TRANSITION_KINDS = (
    "match_started",
    "unit_moved",
    "resource_gathered",
    "resource_delivered",
    "control_point_captured",
    "control_point_held",
    "unit_defeated",
    "mission_completed",
    "turn_advanced",
    "match_finished",
)
# Observational events: the social/audit record; the fold leaves state as-is.
OBSERVATION_KINDS = (
    "action_declared",
    "action_rejected",
    "message_sent",
    "plan_declared",
    "turn_resolved",
)
EVENT_KINDS = TRANSITION_KINDS + OBSERVATION_KINDS


@dataclass(frozen=True)
class Event:
    """One fact about the match: ``(turn, seq)`` orders it, ``kind`` types it."""

    turn: int
    seq: int
    kind: str
    data: dict[str, Any]

    def __post_init__(self) -> None:
        if self.kind not in EVENT_KINDS:
            raise ValueError(f"unknown event kind {self.kind!r}")

    def to_dict(self) -> dict[str, Any]:
        return {"turn": self.turn, "seq": self.seq, "kind": self.kind, "data": self.data}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Event":
        return cls(turn=d["turn"], seq=d["seq"], kind=d["kind"], data=d["data"])


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


def apply_event(state: MatchState, event: Event) -> MatchState:
    """The pure fold step: one event in, the next state out.

    Observational kinds return ``state`` unchanged. Unknown ids raise — a log
    that references a missing entity is corrupt, and corruption must be loud.
    """
    kind, data = event.kind, event.data
    if kind in OBSERVATION_KINDS:
        return state
    if kind == "match_started":
        return dataclasses.replace(state, status="active")
    if kind == "unit_moved":
        to = (data["to"][0], data["to"][1])
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
    if kind == "control_point_captured":
        return dataclasses.replace(
            state,
            control_points=_replace_one(
                state.control_points, data["cp_id"], owner=data["team_id"], hold=()
            ),
        )
    if kind == "control_point_held":
        # turns == 0 (or an empty team) is the streak-reset form: contested
        # or abandoned points lose their consecutive-occupancy progress.
        team_id, turns = data["team_id"], data["turns"]
        hold = ((team_id, turns),) if team_id and turns > 0 else ()
        return dataclasses.replace(
            state,
            control_points=_replace_one(state.control_points, data["cp_id"], hold=hold),
        )
    if kind == "unit_defeated":
        return dataclasses.replace(
            state, units=_replace_one(state.units, data["unit_id"], alive=False)
        )
    if kind == "mission_completed":
        # A dead-heat is a dual award (spec decision c15): the tick emits one
        # completion event per qualifying team and the fold accumulates them
        # into a canonically sorted tuple — the outcome is id-neutral.
        mission = _find(state.missions, data["mission_id"])
        return dataclasses.replace(
            state,
            missions=_replace_one(
                state.missions,
                data["mission_id"],
                status="completed",
                completed_by=tuple(sorted({*mission.completed_by, data["team_id"]})),
                completed_turn=(
                    mission.completed_turn if mission.completed_turn is not None else event.turn
                ),
            ),
        )
    if kind == "turn_advanced":
        return dataclasses.replace(state, turn=data["turn"])
    if kind == "match_finished":
        return dataclasses.replace(state, status="finished", winner=data["winner"])
    raise ValueError(f"unhandled event kind {kind!r}")  # pragma: no cover


def fold_events(initial: MatchState, events: Iterable[Event]) -> MatchState:
    """Replay: fold every event over the initial state."""
    state = initial
    for event in events:
        state = apply_event(state, event)
    return state


@dataclass(frozen=True)
class MatchLog:
    """An initial state plus everything that happened — the whole match."""

    initial_state: MatchState
    events: tuple[Event, ...]

    def final_state(self) -> MatchState:
        return fold_events(self.initial_state, self.events)

    def to_jsonl(self) -> str:
        header = {"log_version": LOG_VERSION, "initial_state": self.initial_state.to_dict()}
        lines = [json.dumps(header, sort_keys=True, separators=(",", ":"), ensure_ascii=False)]
        lines.extend(
            json.dumps(e.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            for e in self.events
        )
        return "\n".join(lines) + "\n"

    @classmethod
    def from_jsonl(cls, payload: str) -> "MatchLog":
        lines = [line for line in payload.splitlines() if line.strip()]
        if not lines:
            raise ValueError("empty match log")
        header = json.loads(lines[0])
        version = header.get("log_version")
        if version != LOG_VERSION:
            raise ValueError(f"unsupported log_version {version!r}; expected {LOG_VERSION}")
        initial = MatchState.from_dict(header["initial_state"])
        events = tuple(Event.from_dict(json.loads(line)) for line in lines[1:])
        return cls(initial_state=initial, events=events)
