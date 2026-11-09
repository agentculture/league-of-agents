"""Immutable match state — the data model every other engine module builds on.

The state is a tree of frozen dataclasses with a **canonical JSON** projection:
``state_to_json`` always emits the same bytes for the same state (sorted keys,
compact separators), so ``state_hash`` is a stable fingerprint usable by the
determinism CI gate (same actions + same seed → same hash).

Nothing here mutates: engine transitions (wave 2's tick) produce *new* states
via ``dataclasses.replace``. Nothing here reads wall-clock time or global
randomness — time is the ``turn`` counter and randomness is the injected
``seed``, both plain fields.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

# Match lifecycle states (a stable vocabulary — agents parse these).
MATCH_STATUSES = ("pending", "active", "finished")
# Match modes share one engine path: cooperative = team(s) vs environment,
# competitive = team vs team. (Spec claim c18/h11.)
MATCH_MODES = ("cooperative", "competitive")
MISSION_KINDS = ("deliver", "hold")
MISSION_STATUSES = ("open", "completed")


@dataclass(frozen=True)
class AgentSlot:
    """One roster seat: which agent (and model) plays for a team.

    Roster metadata lives in match state so fair comparison (spec c14/h7) is
    checkable from the record: two matches identical except for ``model`` /
    composition are apples-to-apples by construction.
    """

    id: str
    model: str
    role: str

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "model": self.model, "role": self.role}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "AgentSlot":
        return cls(id=d["id"], model=d["model"], role=d["role"])


@dataclass(frozen=True)
class TeamState:
    id: str
    name: str
    resources: int
    agents: tuple[AgentSlot, ...] = field(default=())

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "resources": self.resources,
            "agents": [a.to_dict() for a in self.agents],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "TeamState":
        return cls(
            id=d["id"],
            name=d["name"],
            resources=d["resources"],
            agents=tuple(AgentSlot.from_dict(a) for a in d["agents"]),
        )


@dataclass(frozen=True)
class Unit:
    """A pawn on the grid, controlled by one agent seat of one team."""

    id: str
    team_id: str
    agent_id: str
    role: str
    pos: tuple[int, int]
    carrying: int = 0
    alive: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "team_id": self.team_id,
            "agent_id": self.agent_id,
            "role": self.role,
            "pos": list(self.pos),
            "carrying": self.carrying,
            "alive": self.alive,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Unit":
        return cls(
            id=d["id"],
            team_id=d["team_id"],
            agent_id=d["agent_id"],
            role=d["role"],
            pos=(d["pos"][0], d["pos"][1]),
            carrying=d["carrying"],
            alive=d["alive"],
        )


@dataclass(frozen=True)
class ControlPoint:
    """A point teams capture by occupying and **hold** over turns.

    ``hold`` maps team id → consecutive turns held; stored as a sorted tuple
    of pairs so the state stays hashable and its JSON canonical.
    """

    id: str
    pos: tuple[int, int]
    owner: str | None = None
    hold: tuple[tuple[str, int], ...] = field(default=())

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "pos": list(self.pos),
            "owner": self.owner,
            "hold": [[team, turns] for team, turns in self.hold],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ControlPoint":
        return cls(
            id=d["id"],
            pos=(d["pos"][0], d["pos"][1]),
            owner=d["owner"],
            hold=tuple((team, turns) for team, turns in d["hold"]),
        )


def _completed_by(value: Any) -> tuple[str, ...]:
    """Normalize a serialized ``completed_by`` to the canonical sorted tuple.

    Pre-dual-award logs (season 0) wrote ``null`` for open missions and a bare
    team-id string for completed ones; both still load. The canonical form is
    a sorted tuple so the JSON projection (and hence ``state_hash``) never
    depends on award order.
    """
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(sorted(value))


@dataclass(frozen=True)
class Mission:
    """An objective a team completes for score.

    v0 kinds: ``deliver`` (bring ``amount`` resources to ``pos``) and ``hold``
    (own the control point at ``pos`` for ``amount`` consecutive turns).

    ``completed_by`` is a canonically sorted tuple of team ids: usually one
    team, but a dead-heat is a dual award (spec decision c15) — every team
    that qualified on the completing turn is on it, each earning the full
    ``reward``.
    """

    id: str
    kind: str
    pos: tuple[int, int]
    amount: int
    reward: int
    status: str = "open"
    completed_by: tuple[str, ...] = field(default=())
    completed_turn: int | None = None
    # Home delivery (2026-11-06): a deliver mission owned by one team. The
    # scenario names the owner by side index (``side``); ``instantiate`` fills
    # in that side's ``team_id``. Both are None for a shared mission and are
    # omitted from the canonical JSON then, so existing hashes are unchanged.
    side: int | None = None
    team_id: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in MISSION_KINDS:
            raise ValueError(f"unknown mission kind {self.kind!r}; expected one of {MISSION_KINDS}")
        if self.status not in MISSION_STATUSES:
            raise ValueError(
                f"unknown mission status {self.status!r}; expected one of {MISSION_STATUSES}"
            )

    def to_dict(self) -> dict[str, Any]:
        out = {
            "id": self.id,
            "kind": self.kind,
            "pos": list(self.pos),
            "amount": self.amount,
            "reward": self.reward,
            "status": self.status,
            "completed_by": list(self.completed_by),
            "completed_turn": self.completed_turn,
        }
        if self.side is not None:
            out["side"] = self.side
        if self.team_id is not None:
            out["team_id"] = self.team_id
        return out

    def serves(self, team_id: str) -> bool:
        """Whether ``team_id`` may deliver to / complete this mission."""
        return self.team_id is None or self.team_id == team_id

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Mission":
        return cls(
            id=d["id"],
            kind=d["kind"],
            pos=(d["pos"][0], d["pos"][1]),
            amount=d["amount"],
            reward=d["reward"],
            status=d["status"],
            completed_by=_completed_by(d["completed_by"]),
            completed_turn=d["completed_turn"],
            side=d.get("side"),
            team_id=d.get("team_id"),
        )


@dataclass(frozen=True)
class ResourceNode:
    id: str
    pos: tuple[int, int]
    remaining: int

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "pos": list(self.pos), "remaining": self.remaining}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ResourceNode":
        return cls(id=d["id"], pos=(d["pos"][0], d["pos"][1]), remaining=d["remaining"])


@dataclass(frozen=True)
class Crown:
    """ "The Crown": a prominent center objective with a modest, fully public
    payoff. The first team to hold it alone (capture-capable units only, like a
    control point) for ``hold_turns`` consecutive turns takes it, once, for
    ``value`` points. Nothing about it is hidden; whether it is worth the units
    and turns it ties up is the players' call."""

    pos: tuple[int, int]
    value: int
    hold_turns: int
    taken_by: str | None = None
    taken_turn: int | None = None
    hold: tuple[tuple[str, int], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "pos": list(self.pos),
            "value": self.value,
            "hold_turns": self.hold_turns,
            "taken_by": self.taken_by,
            "taken_turn": self.taken_turn,
            "hold": [[team, turns] for team, turns in self.hold],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Crown":
        return cls(
            pos=(d["pos"][0], d["pos"][1]),
            value=d["value"],
            hold_turns=d["hold_turns"],
            taken_by=d.get("taken_by"),
            taken_turn=d.get("taken_turn"),
            hold=tuple((h[0], h[1]) for h in d.get("hold", ())),
        )


@dataclass(frozen=True)
class MatchState:
    """The complete, self-contained truth of a match at one turn boundary."""

    match_id: str
    scenario_id: str
    seed: int
    mode: str
    turn: int
    turn_limit: int
    grid_width: int
    grid_height: int
    status: str
    winner: str | None
    teams: tuple[TeamState, ...]
    units: tuple[Unit, ...]
    control_points: tuple[ControlPoint, ...]
    missions: tuple[Mission, ...]
    resource_nodes: tuple[ResourceNode, ...]
    # Optional, and omitted from the canonical JSON when absent, so every
    # crown-free state (all existing scenarios and logs) hashes unchanged.
    crown: Crown | None = None
    # Early end (2026-11-06): the leader's run of consecutive turns at or above
    # the board's relative-lead threshold, as ((team_id, turns),) or ().
    # Omitted from the canonical JSON when empty, so hashes are unchanged.
    lead_hold: tuple[tuple[str, int], ...] = ()

    def __post_init__(self) -> None:
        if self.mode not in MATCH_MODES:
            raise ValueError(f"unknown mode {self.mode!r}; expected one of {MATCH_MODES}")
        if self.status not in MATCH_STATUSES:
            raise ValueError(f"unknown status {self.status!r}; expected one of {MATCH_STATUSES}")

    def to_dict(self) -> dict[str, Any]:
        out = {
            "match_id": self.match_id,
            "scenario_id": self.scenario_id,
            "seed": self.seed,
            "mode": self.mode,
            "turn": self.turn,
            "turn_limit": self.turn_limit,
            "grid_width": self.grid_width,
            "grid_height": self.grid_height,
            "status": self.status,
            "winner": self.winner,
            "teams": [t.to_dict() for t in self.teams],
            "units": [u.to_dict() for u in self.units],
            "control_points": [c.to_dict() for c in self.control_points],
            "missions": [m.to_dict() for m in self.missions],
            "resource_nodes": [r.to_dict() for r in self.resource_nodes],
        }
        if self.crown is not None:
            out["crown"] = self.crown.to_dict()
        if self.lead_hold:
            out["lead_hold"] = [[t, n] for t, n in self.lead_hold]
        return out

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "MatchState":
        return cls(
            match_id=d["match_id"],
            scenario_id=d["scenario_id"],
            seed=d["seed"],
            mode=d["mode"],
            turn=d["turn"],
            turn_limit=d["turn_limit"],
            grid_width=d["grid_width"],
            grid_height=d["grid_height"],
            status=d["status"],
            winner=d["winner"],
            teams=tuple(TeamState.from_dict(t) for t in d["teams"]),
            units=tuple(Unit.from_dict(u) for u in d["units"]),
            control_points=tuple(ControlPoint.from_dict(c) for c in d["control_points"]),
            missions=tuple(Mission.from_dict(m) for m in d["missions"]),
            resource_nodes=tuple(ResourceNode.from_dict(r) for r in d["resource_nodes"]),
            crown=Crown.from_dict(d["crown"]) if d.get("crown") else None,
            lead_hold=tuple((t, int(n)) for t, n in d.get("lead_hold", ())),
        )


def state_to_json(state: MatchState) -> str:
    """Serialize to canonical JSON: same state → same bytes, always."""
    return json.dumps(state.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def state_from_json(payload: str) -> MatchState:
    return MatchState.from_dict(json.loads(payload))


def state_hash(state: MatchState) -> str:
    """A stable fingerprint of the state — the determinism gate compares these."""
    return hashlib.sha256(state_to_json(state).encode("utf-8")).hexdigest()
