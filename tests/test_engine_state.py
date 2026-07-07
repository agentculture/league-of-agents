"""Wave-0 acceptance tests for the engine state core (plan task t1).

Criteria under test:

* match state serializes to JSON and loads back byte-identical (round-trip);
* the engine package imports no wall-clock time and no global random — the
  import ban that makes determinism (spec c9) enforceable at the source level.
"""

from __future__ import annotations

import ast
import dataclasses
import json
from pathlib import Path

import pytest

from league.engine import (
    AgentSlot,
    ControlPoint,
    MatchState,
    Mission,
    ResourceNode,
    TeamState,
    Unit,
    state_from_json,
    state_hash,
    state_to_json,
)

ENGINE_DIR = Path(__file__).resolve().parent.parent / "league" / "engine"

# Modules whose import would smuggle wall-clock or ambient randomness into
# resolution. hashlib is fine (pure); secrets/uuid4 would not be.
_BANNED_MODULES = {"random", "time", "datetime", "secrets", "uuid"}


def sample_state() -> MatchState:
    return MatchState(
        match_id="m-0001",
        scenario_id="skirmish-1",
        seed=1337,
        mode="competitive",
        turn=3,
        turn_limit=40,
        grid_width=12,
        grid_height=10,
        status="active",
        winner=None,
        teams=(
            TeamState(
                id="blue",
                name="Blue Foundry",
                resources=7,
                agents=(
                    AgentSlot(id="blue-1", model="colleague/qwen", role="scout"),
                    AgentSlot(id="blue-2", model="claude-sonnet-5", role="harvester"),
                ),
            ),
            TeamState(
                id="red",
                name="Red Relay",
                resources=4,
                agents=(
                    AgentSlot(id="red-1", model="claude-sonnet-5", role="defender"),
                    AgentSlot(id="red-2", model="colleague/qwen", role="striker"),
                ),
            ),
        ),
        units=(
            Unit(id="u1", team_id="blue", agent_id="blue-1", role="scout", pos=(1, 1)),
            Unit(
                id="u2",
                team_id="blue",
                agent_id="blue-2",
                role="harvester",
                pos=(2, 3),
                carrying=2,
            ),
            Unit(id="u3", team_id="red", agent_id="red-1", role="defender", pos=(10, 8)),
            Unit(
                id="u4",
                team_id="red",
                agent_id="red-2",
                role="striker",
                pos=(9, 7),
                alive=False,
            ),
        ),
        control_points=(
            ControlPoint(id="cp1", pos=(6, 5), owner="blue", hold=(("blue", 2),)),
            ControlPoint(id="cp2", pos=(3, 8)),
            ControlPoint(id="cp3", pos=(9, 2), owner="red", hold=(("red", 1),)),
        ),
        missions=(
            Mission(id="ms1", kind="deliver", pos=(6, 5), amount=5, reward=10),
            Mission(
                id="ms2",
                kind="hold",
                pos=(9, 2),
                amount=3,
                reward=8,
                status="completed",
                completed_by=("red",),
                completed_turn=2,
            ),
        ),
        resource_nodes=(
            ResourceNode(id="rn1", pos=(0, 5), remaining=12),
            ResourceNode(id="rn2", pos=(11, 4), remaining=9),
        ),
    )


def test_round_trip_is_byte_identical() -> None:
    state = sample_state()
    payload = state_to_json(state)
    restored = state_from_json(payload)
    assert restored == state
    assert state_to_json(restored) == payload


def test_canonical_json_is_sorted_and_compact() -> None:
    payload = state_to_json(sample_state())
    parsed = json.loads(payload)
    assert payload == json.dumps(parsed, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def test_state_hash_is_stable_and_sensitive() -> None:
    a, b = sample_state(), sample_state()
    assert state_hash(a) == state_hash(b)
    moved = dataclasses.replace(a, turn=a.turn + 1)
    assert state_hash(moved) != state_hash(a)


def test_state_is_frozen() -> None:
    state = sample_state()
    with pytest.raises(dataclasses.FrozenInstanceError):
        state.turn = 99  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        state.units[0].pos = (0, 0)  # type: ignore[misc]


def test_invalid_vocabulary_rejected() -> None:
    state = sample_state()
    with pytest.raises(ValueError):
        dataclasses.replace(state, mode="deathmatch")
    with pytest.raises(ValueError):
        dataclasses.replace(state, status="paused")
    with pytest.raises(ValueError):
        Mission(id="x", kind="teleport", pos=(0, 0), amount=1, reward=1)


def test_engine_never_imports_time_or_random() -> None:
    """The determinism import ban, enforced over every engine module."""
    offenders: list[str] = []
    for module in sorted(ENGINE_DIR.rglob("*.py")):
        tree = ast.parse(module.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [(node.module or "").split(".")[0]]
            else:
                continue
            for name in names:
                if name in _BANNED_MODULES:
                    offenders.append(f"{module.name}: {name}")
    assert not offenders, f"banned nondeterministic imports in engine: {offenders}"
