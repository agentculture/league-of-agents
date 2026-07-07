"""The deterministic arena engine — the substrate agent teams play inside.

Design invariants (spec: docs/specs/2026-07-06-league-of-agents-runs-its-first-
observable-arena-s.md):

* **Determinism** — engine modules never read wall-clock time or global
  randomness; every stochastic choice flows through an injected seed. A test
  (``tests/test_engine_state.py::test_engine_never_imports_time_or_random``)
  enforces the import ban package-wide.
* **One source of truth** — match state serializes to canonical JSON;
  the event log (wave 1) is the only artifact scoring and replay consume.
"""

from league.engine.events import Event, MatchLog, apply_event, fold_events
from league.engine.scenario import Scenario, get_scenario, instantiate, scenario_ids
from league.engine.state import (
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

__all__ = [
    "AgentSlot",
    "ControlPoint",
    "Event",
    "MatchLog",
    "MatchState",
    "Mission",
    "ResourceNode",
    "Scenario",
    "TeamState",
    "Unit",
    "apply_event",
    "fold_events",
    "get_scenario",
    "instantiate",
    "scenario_ids",
    "state_from_json",
    "state_hash",
    "state_to_json",
]
