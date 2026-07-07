"""Immutable continuous-lane match state — the sibling of the grid ``state.py``.

This is the continuous arena's data model: the same discipline the grid engine
earned (frozen dataclasses, a **canonical JSON** projection, a stable
``cstate_hash``), but with continuous positions (:class:`~league.engine.
continuous.space.Pos`, integer milliunits) and an integer game **clock** in place
of the grid's integer ``turn``. Read this beside ``league/engine/state.py``: the
shapes are deliberately parallel so the two lanes stay legible together, while
the names carry a ``C`` prefix so nothing collides when both lanes are imported.

Why a separate module (spec c11/h11 — two engine lanes, both honest)
--------------------------------------------------------------------
The continuous lane lands *beside* the grid engine, never over it. Nothing here
imports the grid's ``MatchState``; the grid keeps working untouched. The only
shared substrate is the fixed-point spatial core (``space.py``) — positions are
:class:`Pos`, so canonical JSON, equality and the hash stay exact and
platform-independent (no binary float ever enters the state; the source scan in
``tests/test_continuous_state.py`` proves it package-wide).

Determinism invariants (identical to the grid's):

* **Nothing mutates.** Transitions (the resolver, t5) produce *new* states via
  ``dataclasses.replace`` — never in place.
* **Canonical JSON is stable.** ``cstate_to_json`` emits the same bytes for the
  same state (sorted keys, compact separators), so ``cstate_hash`` is a stable
  fingerprint the continuous determinism gate (t6) compares against.
* **No wall clock, no randomness.** Game time is the ``clock`` field (integer
  game-time units from the timeline); there is no seed-driven randomness in the
  engine at all (the AST import ban forbids ``random``/``time``/… package-wide).

The contested-take representation (spec c9/h9 — the whole point)
----------------------------------------------------------------
A control point carries ``takers``: a canonically ordered tuple of *concurrent*
:class:`TakeAttempt` records (``unit_id``, ``team_id``, ``start_time``,
``completion_time``). Two units from different teams taking the same post at once
are therefore both present **in state** — the race is representable, not implied.
The resolver (t5) reads these completion times to decide who finishes first; the
winner's attempt is cleared by ``post_taken`` and each loser's by
``action_failed`` (see ``events.py``). This is the minimal representation that
supports the spec's race semantics: a post tracks *many* concurrent attempts, not
one, because "first to finish takes it, the loser's attempt visibly fails" is
undecidable if only one attempt is representable.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from league.engine.continuous.space import Pos

# Match lifecycle states — a stable vocabulary agents parse (mirrors the grid).
MATCH_STATUSES = ("pending", "active", "finished")
# Cooperative = team(s) vs environment, competitive = team vs team (one engine).
MATCH_MODES = ("cooperative", "competitive")
# Mission kinds/statuses mirror the grid lane exactly.
MISSION_KINDS = ("deliver", "hold")
MISSION_STATUSES = ("open", "completed")
# The continuous action vocabulary a unit can be busy with. ``move`` carries a
# spatial ``target_pos``; ``gather``/``take_post``/``deliver`` carry an entity
# ``target_id`` (node / control-point / team). t5's resolver may extend this
# tuple, but every kind here already has a first-class event in ``events.py``.
ACTION_KINDS = ("move", "gather", "take_post", "deliver")


@dataclass(frozen=True)
class CAgentSlot:
    """One roster seat: which agent (and model) plays for a team.

    Mirrors the grid's ``AgentSlot`` so fair comparison (spec c14/h7) is
    checkable from the continuous record too: two matches identical except for
    ``model`` / composition are apples-to-apples by construction.
    """

    id: str
    model: str
    role: str

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "model": self.model, "role": self.role}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CAgentSlot":
        return cls(id=d["id"], model=d["model"], role=d["role"])


@dataclass(frozen=True)
class CTeamState:
    id: str
    name: str
    resources: int
    agents: tuple[CAgentSlot, ...] = field(default=())

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "resources": self.resources,
            "agents": [a.to_dict() for a in self.agents],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CTeamState":
        return cls(
            id=d["id"],
            name=d["name"],
            resources=d["resources"],
            agents=tuple(CAgentSlot.from_dict(a) for a in d["agents"]),
        )


@dataclass(frozen=True)
class CAction:
    """What a unit is busy doing until ``completion_time`` (``None`` == idle).

    ``kind`` is one of :data:`ACTION_KINDS`. ``start_time``/``completion_time``
    are integer game-time units (the timeline's clock) — the pair the replay
    (t9) interpolates a move over and the briefing (t7) surfaces as a time
    budget. ``target_pos`` names a spatial destination (``move``); ``target_id``
    names an entity target (``gather`` node, ``take_post`` control point,
    ``deliver`` team). Exactly which field a kind uses is a t5 rule, not a state
    rule — both are optional so the vocabulary covers every action kind.
    """

    kind: str
    start_time: int
    completion_time: int
    target_id: str | None = None
    target_pos: Pos | None = None

    def __post_init__(self) -> None:
        if self.kind not in ACTION_KINDS:
            raise ValueError(f"unknown action kind {self.kind!r}; expected one of {ACTION_KINDS}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "start_time": self.start_time,
            "completion_time": self.completion_time,
            "target_id": self.target_id,
            "target_pos": self.target_pos.to_dict() if self.target_pos is not None else None,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CAction":
        raw_pos = d["target_pos"]
        return cls(
            kind=d["kind"],
            start_time=d["start_time"],
            completion_time=d["completion_time"],
            target_id=d["target_id"],
            target_pos=Pos.from_dict(raw_pos) if raw_pos is not None else None,
        )


@dataclass(frozen=True)
class CUnit:
    """A unit at a continuous position, controlled by one agent seat.

    ``action`` is the unit's in-progress :class:`CAction` or ``None`` when the
    unit is idle and awaiting a decision point (the resolver clears it to
    ``None`` on ``action_completed`` / ``action_failed``).
    """

    id: str
    team_id: str
    agent_id: str
    role: str
    pos: Pos
    action: CAction | None = None
    carrying: int = 0
    alive: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "team_id": self.team_id,
            "agent_id": self.agent_id,
            "role": self.role,
            "pos": self.pos.to_dict(),
            "action": self.action.to_dict() if self.action is not None else None,
            "carrying": self.carrying,
            "alive": self.alive,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CUnit":
        raw_action = d["action"]
        return cls(
            id=d["id"],
            team_id=d["team_id"],
            agent_id=d["agent_id"],
            role=d["role"],
            pos=Pos.from_dict(d["pos"]),
            action=CAction.from_dict(raw_action) if raw_action is not None else None,
            carrying=d["carrying"],
            alive=d["alive"],
        )


@dataclass(frozen=True)
class TakeAttempt:
    """One in-progress attempt to take a control point — a competitor in a race.

    ``(completion_time, team_id, unit_id)`` — exposed as :attr:`key` — is the
    canonical ordering triple (the same one the timeline sorts by), so a control
    point's ``takers`` tuple has a stable order independent of who started when.
    """

    unit_id: str
    team_id: str
    start_time: int
    completion_time: int

    @property
    def key(self) -> tuple[int, str, str]:
        return (self.completion_time, self.team_id, self.unit_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "unit_id": self.unit_id,
            "team_id": self.team_id,
            "start_time": self.start_time,
            "completion_time": self.completion_time,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "TakeAttempt":
        return cls(
            unit_id=d["unit_id"],
            team_id=d["team_id"],
            start_time=d["start_time"],
            completion_time=d["completion_time"],
        )


def canonical_takers(takers: tuple[TakeAttempt, ...]) -> tuple[TakeAttempt, ...]:
    """Sort take attempts by their canonical key so the JSON (and hash) never
    depends on the order attempts were registered."""
    return tuple(sorted(takers, key=lambda t: t.key))


@dataclass(frozen=True)
class CControlPoint:
    """A post teams take. ``owner`` is the team currently holding it (or ``None``).

    ``takers`` holds every concurrent in-progress :class:`TakeAttempt`, in
    canonical order — this is how a contested take (spec c9/h9) is representable
    in state: two units racing for the same post are both listed here until the
    faster one completes (``post_taken`` clears its attempt and sets ``owner``)
    and the slower one's attempt fails (``action_failed`` clears it).
    """

    id: str
    pos: Pos
    owner: str | None = None
    takers: tuple[TakeAttempt, ...] = field(default=())

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "pos": self.pos.to_dict(),
            "owner": self.owner,
            "takers": [t.to_dict() for t in self.takers],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CControlPoint":
        return cls(
            id=d["id"],
            pos=Pos.from_dict(d["pos"]),
            owner=d["owner"],
            takers=canonical_takers(tuple(TakeAttempt.from_dict(t) for t in d["takers"])),
        )


@dataclass(frozen=True)
class CResourceNode:
    id: str
    pos: Pos
    remaining: int

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "pos": self.pos.to_dict(), "remaining": self.remaining}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CResourceNode":
        return cls(id=d["id"], pos=Pos.from_dict(d["pos"]), remaining=d["remaining"])


def _completed_by(value: Any) -> tuple[str, ...]:
    """Normalize a serialized ``completed_by`` to the canonical sorted tuple.

    ``None`` -> ``()``, a bare team id -> a one-tuple, a list -> a sorted tuple,
    so the JSON projection never depends on award order (mirrors the grid).
    """
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(sorted(value))


@dataclass(frozen=True)
class CMission:
    """An objective a team completes for score. ``completed_time`` is the game
    clock at completion (the continuous analog of the grid's ``completed_turn``).

    A dead-heat is a dual award (spec decision c15): every team that qualified is
    on ``completed_by`` (a canonically sorted tuple), each earning ``reward``.
    """

    id: str
    kind: str
    pos: Pos
    amount: int
    reward: int
    status: str = "open"
    completed_by: tuple[str, ...] = field(default=())
    completed_time: int | None = None

    def __post_init__(self) -> None:
        if self.kind not in MISSION_KINDS:
            raise ValueError(f"unknown mission kind {self.kind!r}; expected one of {MISSION_KINDS}")
        if self.status not in MISSION_STATUSES:
            raise ValueError(
                f"unknown mission status {self.status!r}; expected one of {MISSION_STATUSES}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "pos": self.pos.to_dict(),
            "amount": self.amount,
            "reward": self.reward,
            "status": self.status,
            "completed_by": list(self.completed_by),
            "completed_time": self.completed_time,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CMission":
        return cls(
            id=d["id"],
            kind=d["kind"],
            pos=Pos.from_dict(d["pos"]),
            amount=d["amount"],
            reward=d["reward"],
            status=d["status"],
            completed_by=_completed_by(d["completed_by"]),
            completed_time=d["completed_time"],
        )


@dataclass(frozen=True)
class CMatchState:
    """The complete, self-contained truth of a continuous match at one instant.

    ``clock`` is the integer game-time coordinate (the timeline's ``now``), the
    continuous analog of the grid's ``turn``; ``time_limit`` bounds it.
    ``width``/``height`` are the board extent **in milliunits** (the continuous
    analog of ``grid_width``/``grid_height``), so positions and bounds share the
    :class:`Pos` scale. ``seed`` is carried for reproducibility/fair-comparison
    metadata parity with the grid — the engine itself uses no randomness.
    """

    match_id: str
    scenario_id: str
    seed: int
    mode: str
    clock: int
    time_limit: int
    width: int
    height: int
    status: str
    winner: str | None
    teams: tuple[CTeamState, ...]
    units: tuple[CUnit, ...]
    control_points: tuple[CControlPoint, ...]
    missions: tuple[CMission, ...]
    resource_nodes: tuple[CResourceNode, ...]

    def __post_init__(self) -> None:
        if self.mode not in MATCH_MODES:
            raise ValueError(f"unknown mode {self.mode!r}; expected one of {MATCH_MODES}")
        if self.status not in MATCH_STATUSES:
            raise ValueError(f"unknown status {self.status!r}; expected one of {MATCH_STATUSES}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "match_id": self.match_id,
            "scenario_id": self.scenario_id,
            "seed": self.seed,
            "mode": self.mode,
            "clock": self.clock,
            "time_limit": self.time_limit,
            "width": self.width,
            "height": self.height,
            "status": self.status,
            "winner": self.winner,
            "teams": [t.to_dict() for t in self.teams],
            "units": [u.to_dict() for u in self.units],
            "control_points": [c.to_dict() for c in self.control_points],
            "missions": [m.to_dict() for m in self.missions],
            "resource_nodes": [r.to_dict() for r in self.resource_nodes],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CMatchState":
        return cls(
            match_id=d["match_id"],
            scenario_id=d["scenario_id"],
            seed=d["seed"],
            mode=d["mode"],
            clock=d["clock"],
            time_limit=d["time_limit"],
            width=d["width"],
            height=d["height"],
            status=d["status"],
            winner=d["winner"],
            teams=tuple(CTeamState.from_dict(t) for t in d["teams"]),
            units=tuple(CUnit.from_dict(u) for u in d["units"]),
            control_points=tuple(CControlPoint.from_dict(c) for c in d["control_points"]),
            missions=tuple(CMission.from_dict(m) for m in d["missions"]),
            resource_nodes=tuple(CResourceNode.from_dict(r) for r in d["resource_nodes"]),
        )


def cstate_to_json(state: CMatchState) -> str:
    """Serialize to canonical JSON: same state → same bytes, always."""
    return json.dumps(state.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def cstate_from_json(payload: str) -> CMatchState:
    return CMatchState.from_dict(json.loads(payload))


def cstate_hash(state: CMatchState) -> str:
    """A stable fingerprint of the state — the continuous determinism gate (t6)
    compares these, exactly as the grid gate compares ``state_hash``."""
    return hashlib.sha256(cstate_to_json(state).encode("utf-8")).hexdigest()
