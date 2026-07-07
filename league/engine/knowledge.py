"""Per-team knowledge — what each team has *seen* and been *told*, folded from the log.

This is the substrate fogged briefings (a seat's world model), the replay
knowledge overlay, and fog auditing stand on (spec c13, h4, h13). Like scoring,
it is a **read-side projection**: knowledge is *derived* from the event log and
the scenario — it is never stored in :class:`~league.engine.state.MatchState`,
never written into the log, and has zero effect on ``state_hash`` or the
determinism fixture. Everything here is a pure function of its inputs — no RNG,
no clock (the package-wide AST import ban applies) — so re-folding the same log
always reproduces the same per-team knowledge.

**Fold shape.** ``knowledge_by_turn(log, scenario)`` returns, per team, one
:class:`KnowledgeFrame` per replay frame: index 0 is the initial state's
knowledge, then one frame per event-turn group in ``(turn, seq)`` order —
exactly the grouping ``league.replay.build_replay_data`` uses, so the overlay
can zip its frames with these one-to-one. Briefings take the last frame
(``latest_knowledge``); a live harness can advance incrementally with
``fold_knowledge(prev, events, state_after, scenario)`` without re-scanning
the log.

**Seen.** Ground truth of a sighting is the state *after* the turn resolves:
each frame runs :func:`league.engine.vision.team_view` on the post-turn state
and records every visible unit / resource node / control point as a ``seen``
fact stamped with that turn. Vision conventions carry over — a team always
knows its own units; enemies and furniture only while they stand on a visible
cell. A ``seen`` fact persists after the entity leaves vision (that is the
point: knowledge is *last-seen* facts, which may be stale) and is only ever
replaced by a newer sighting. ``cells_seen`` accumulates the union of the
team's visible cells across all frames — ground the team has ever surveyed.

**Told.** A ``message_sent`` event is knowledge the *sending team* was given
(messages are a team channel; the other team never hears them). Parsing is
deliberately conservative and centralized in :func:`_mentions`: a message
conveys an entity **only** when its exact id appears as a standalone token
(``rn-west``, ``red-u1``) — no coordinate guessing, no prose interpretation
(``"the western node"`` teaches nothing). A ``told`` fact carries *identity
only*: id, and the static attributes fixed at instantiation (a unit's team and
role — roster metadata is match config; a node's or control point's position —
map furniture never moves). Dynamic board state is never leaked by a mention:
a told unit has ``pos=None``/``alive=None``, a told node ``remaining=None``,
a told control point ``owner=None`` (for a *told* fact ``None`` means
"unknown"; for a *seen* control point ``owner=None`` means witnessed-unowned —
``source`` disambiguates). Told facts fill gaps and refresh earlier told
facts; they never downgrade a ``seen`` fact, because a bare mention adds
nothing a sighting already gave.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

from league.engine.events import Event, MatchLog, fold_events
from league.engine.scenario import Scenario
from league.engine.state import MatchState
from league.engine.vision import team_view

SOURCE_SEEN = "seen"
SOURCE_TOLD = "told"
_SOURCES = (SOURCE_SEEN, SOURCE_TOLD)


def _check_source(source: str) -> None:
    if source not in _SOURCES:
        raise ValueError(f"unknown knowledge source {source!r}; expected one of {_SOURCES}")


@dataclass(frozen=True)
class KnownUnit:
    """One unit as a team knows it. ``pos``/``alive`` are ``None`` when told-only."""

    id: str
    team_id: str
    role: str
    pos: tuple[int, int] | None
    alive: bool | None
    turn: int
    source: str

    def __post_init__(self) -> None:
        _check_source(self.source)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "team_id": self.team_id,
            "role": self.role,
            "pos": list(self.pos) if self.pos is not None else None,
            "alive": self.alive,
            "turn": self.turn,
            "source": self.source,
        }


@dataclass(frozen=True)
class KnownNode:
    """A resource node as known. ``remaining`` is ``None`` when told-only."""

    id: str
    pos: tuple[int, int]
    remaining: int | None
    turn: int
    source: str

    def __post_init__(self) -> None:
        _check_source(self.source)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "pos": list(self.pos),
            "remaining": self.remaining,
            "turn": self.turn,
            "source": self.source,
        }


@dataclass(frozen=True)
class KnownControlPoint:
    """A control point as known. Told-only ⇒ ``owner`` unknown (``None``);
    seen ⇒ ``owner`` is the witnessed owner (``None`` = witnessed-unowned)."""

    id: str
    pos: tuple[int, int]
    owner: str | None
    turn: int
    source: str

    def __post_init__(self) -> None:
        _check_source(self.source)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "pos": list(self.pos),
            "owner": self.owner,
            "turn": self.turn,
            "source": self.source,
        }


@dataclass(frozen=True)
class KnowledgeFrame:
    """Everything one team knows at one turn boundary — facts in canonical id order."""

    team_id: str
    turn: int
    units: tuple[KnownUnit, ...]
    resource_nodes: tuple[KnownNode, ...]
    control_points: tuple[KnownControlPoint, ...]
    cells_seen: frozenset[tuple[int, int]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "team_id": self.team_id,
            "turn": self.turn,
            "units": [f.to_dict() for f in self.units],
            "resource_nodes": [f.to_dict() for f in self.resource_nodes],
            "control_points": [f.to_dict() for f in self.control_points],
            "cells_seen": sorted([x, y] for x, y in self.cells_seen),
        }


def _mentions(text: str, entity_ids: Iterable[str]) -> tuple[str, ...]:
    """Entity ids the text names — exact standalone tokens only, canonical order.

    The conservative told-parsing rule lives here and nowhere else: an id
    matches only when not embedded in a longer id-like token (``rn-westish``
    and ``xrn-west`` teach nothing about ``rn-west``). No NLP, no coordinate
    guessing.
    """
    hits = []
    for entity_id in sorted(set(entity_ids)):
        pattern = rf"(?<![A-Za-z0-9_-]){re.escape(entity_id)}(?![A-Za-z0-9_-])"
        if re.search(pattern, text):
            hits.append(entity_id)
    return tuple(hits)


def _told_pass(
    units: dict[str, KnownUnit],
    nodes: dict[str, KnownNode],
    cps: dict[str, KnownControlPoint],
    events: Iterable[Event],
    state: MatchState,
    team_id: str,
) -> None:
    """Fold this team's ``message_sent`` events into told facts (never downgrading seen)."""
    unit_by_id = {u.id: u for u in state.units}
    node_by_id = {n.id: n for n in state.resource_nodes}
    cp_by_id = {c.id: c for c in state.control_points}
    for event in events:
        if event.kind != "message_sent" or event.data.get("team_id") != team_id:
            continue
        text = str(event.data.get("text", ""))
        for entity_id in _mentions(text, (*unit_by_id, *node_by_id, *cp_by_id)):
            if entity_id in unit_by_id:
                known = units.get(entity_id)
                if known is not None and known.source == SOURCE_SEEN:
                    continue
                unit = unit_by_id[entity_id]
                units[entity_id] = KnownUnit(
                    id=unit.id,
                    team_id=unit.team_id,
                    role=unit.role,
                    pos=None,
                    alive=None,
                    turn=event.turn,
                    source=SOURCE_TOLD,
                )
            elif entity_id in node_by_id:
                if entity_id in nodes and nodes[entity_id].source == SOURCE_SEEN:
                    continue
                node = node_by_id[entity_id]
                nodes[entity_id] = KnownNode(
                    id=node.id, pos=node.pos, remaining=None, turn=event.turn, source=SOURCE_TOLD
                )
            else:
                if entity_id in cps and cps[entity_id].source == SOURCE_SEEN:
                    continue
                cp = cp_by_id[entity_id]
                cps[entity_id] = KnownControlPoint(
                    id=cp.id, pos=cp.pos, owner=None, turn=event.turn, source=SOURCE_TOLD
                )


def _seen_pass(
    units: dict[str, KnownUnit],
    nodes: dict[str, KnownNode],
    cps: dict[str, KnownControlPoint],
    cells: set[tuple[int, int]],
    state: MatchState,
    scenario: Scenario,
    team_id: str,
) -> None:
    """Record everything visible in ``state`` as seen facts; sightings overwrite."""
    view = team_view(state, scenario, team_id)
    turn = state.turn
    for unit in view.units:
        units[unit.id] = KnownUnit(
            id=unit.id,
            team_id=unit.team_id,
            role=unit.role,
            pos=unit.pos,
            alive=unit.alive,
            turn=turn,
            source=SOURCE_SEEN,
        )
    for node in view.resource_nodes:
        nodes[node.id] = KnownNode(
            id=node.id, pos=node.pos, remaining=node.remaining, turn=turn, source=SOURCE_SEEN
        )
    for cp in view.control_points:
        cps[cp.id] = KnownControlPoint(
            id=cp.id, pos=cp.pos, owner=cp.owner, turn=turn, source=SOURCE_SEEN
        )
    cells |= view.cells


def _frame(
    team_id: str,
    turn: int,
    units: dict[str, KnownUnit],
    nodes: dict[str, KnownNode],
    cps: dict[str, KnownControlPoint],
    cells: set[tuple[int, int]],
) -> KnowledgeFrame:
    return KnowledgeFrame(
        team_id=team_id,
        turn=turn,
        units=tuple(units[k] for k in sorted(units)),
        resource_nodes=tuple(nodes[k] for k in sorted(nodes)),
        control_points=tuple(cps[k] for k in sorted(cps)),
        cells_seen=frozenset(cells),
    )


def initial_knowledge(state: MatchState, scenario: Scenario, team_id: str) -> KnowledgeFrame:
    """The team's knowledge at the initial state: sightings only, no history."""
    units: dict[str, KnownUnit] = {}
    nodes: dict[str, KnownNode] = {}
    cps: dict[str, KnownControlPoint] = {}
    cells: set[tuple[int, int]] = set()
    _seen_pass(units, nodes, cps, cells, state, scenario, team_id)
    return _frame(team_id, state.turn, units, nodes, cps, cells)


def fold_knowledge(
    prev: KnowledgeFrame,
    events: Iterable[Event],
    state_after: MatchState,
    scenario: Scenario,
) -> KnowledgeFrame:
    """One incremental step: fold one turn's events onto ``prev``.

    ``events`` is the turn's batch (told facts come from its ``message_sent``
    entries); ``state_after`` is the post-turn state (the ground truth of
    sightings). Told is applied first, then seen — an entity both mentioned and
    sighted in the same turn ends up ``seen``.
    """
    units = {f.id: f for f in prev.units}
    nodes = {f.id: f for f in prev.resource_nodes}
    cps = {f.id: f for f in prev.control_points}
    cells = set(prev.cells_seen)
    _told_pass(units, nodes, cps, events, state_after, prev.team_id)
    _seen_pass(units, nodes, cps, cells, state_after, scenario, prev.team_id)
    return _frame(prev.team_id, state_after.turn, units, nodes, cps, cells)


def knowledge_by_turn(log: MatchLog, scenario: Scenario) -> dict[str, tuple[KnowledgeFrame, ...]]:
    """Per team, one knowledge frame per replay frame — the batch entry point.

    Frame 0 is the initial state's knowledge; each further frame folds one
    event-turn group (the same grouping ``build_replay_data`` snapshots), so
    the replay overlay can zip its frames with these one-to-one. Briefings
    want the last frame — see :func:`latest_knowledge`.
    """
    initial = log.initial_state
    grouped: dict[int, list[Event]] = {}
    for event in log.events:  # one pass; (turn, seq) order is the log order
        grouped.setdefault(event.turn, []).append(event)
    frames = {team.id: [initial_knowledge(initial, scenario, team.id)] for team in initial.teams}
    state = initial
    for turn in sorted(grouped):
        batch = tuple(grouped[turn])
        state = fold_events(state, batch)
        for team_frames in frames.values():
            team_frames.append(fold_knowledge(team_frames[-1], batch, state, scenario))
    return {team_id: tuple(team_frames) for team_id, team_frames in frames.items()}


def latest_knowledge(log: MatchLog, scenario: Scenario) -> dict[str, KnowledgeFrame]:
    """Each team's current knowledge — what a fogged briefing renders from."""
    return {
        team_id: team_frames[-1]
        for team_id, team_frames in knowledge_by_turn(log, scenario).items()
    }
