"""Latency metadata in the match log — harness-side, never state (plan t1,
spec c10/h9).

Criteria under test:

* the harness records per-seat/per-team, per-turn wall-clock latency purely
  as ``seat_latency`` OBSERVATION events on the match log — ``MatchState``,
  ``state_hash``, and ``apply_event``'s fold are unchanged by their presence;
* replaying the SAME log with and without ``seat_latency`` events folds to
  the identical ``state_hash`` — the determinism CI gate's own committed
  fixture (``tests/fixtures/determinism.hash``) is untouched by this feature;
* every driver kind — ``bot``, ``bot-file``, ``command`` (plain, per-seat,
  and its orchestrator master), and ``resident`` — is measured the same way:
  a mutable sink threaded through the ``context`` mapping every driver
  already receives, never a new field on what a driver *returns* — so a
  driver exercised directly (no sink in ``context``, e.g. every pre-existing
  harness test) behaves exactly as before.
"""

from __future__ import annotations

import dataclasses
import itertools
import json
import sys
from typing import Any, Mapping

import pytest

import league.harness as harness
from league.engine.events import Event, apply_event
from league.engine.state import state_hash
from league.harness import build_driver, run_match
from league.store import Store
from tests.test_determinism_gate import FIXTURE, compute_final_hash, play_canonical_match
from tests.test_wave4 import BOT_TEAM_BLUE, BOT_TEAM_RED

SCENARIO = {
    "roles": {"scout": {"move": 3, "carry": 1}},
    "grid": {"width": 12, "height": 10},
    "capture_hold_turns": 2,
    "turn_limit": 30,
}

STATE = {
    "units": [
        {
            "id": "blue-u1",
            "agent_id": "blue-1",
            "team_id": "blue",
            "role": "scout",
            "pos": [0, 0],
            "carrying": 0,
            "alive": True,
        }
    ],
    "missions": [],
    "resource_nodes": [],
    "control_points": [],
}

_ECHO_AGENT = (
    "import sys, json; sys.stdin.read(); "
    "print(json.dumps({'actions': [{'unit_id': 'u', 'action': 'hold'}]}))"
)
_SEAT_ECHO_AGENT = (
    "import sys, json; sys.stdin.read(); "
    "print(json.dumps({'action': {'unit_id': 'blue-u1', 'action': 'hold'}}))"
)


@pytest.fixture()
def arena(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


# -- the fold: seat_latency is a no-op, exactly like every other observation -


def test_seat_latency_event_is_a_fold_noop() -> None:
    log = play_canonical_match()
    state = log.final_state()
    event = Event(
        turn=1,
        seq=999,
        kind="seat_latency",
        data={"team_id": "blue", "agent_id": "blue-1", "unit_id": "blue-u1", "elapsed_ms": 1234},
    )
    assert apply_event(state, event) == state


def test_replaying_with_and_without_latency_events_yields_identical_hash() -> None:
    """The determinism proof (plan t1 acceptance #2): splice ``seat_latency``
    observation events into the canonical scripted match's log — the SAME
    log the CI gate itself replays — and confirm the final ``state_hash`` is
    untouched."""
    bare = play_canonical_match()
    seq = len(bare.events)
    latency_events = tuple(
        Event(
            turn=e.turn,
            seq=seq + i,
            kind="seat_latency",
            data={"team_id": "blue", "agent_id": None, "unit_id": None, "elapsed_ms": 17 + i},
        )
        for i, e in enumerate(bare.events)
        if e.kind == "turn_resolved"
    )
    assert latency_events, "the canonical script must actually resolve turns to splice into"
    with_latency = dataclasses.replace(bare, events=bare.events + latency_events)

    assert len(with_latency.events) > len(bare.events)
    assert state_hash(with_latency.final_state()) == state_hash(bare.final_state())
    assert with_latency.final_state() == bare.final_state()


def test_fixture_hash_is_unaffected_by_latency_metadata() -> None:
    """tests/fixtures/determinism.hash — the CI gate's own committed fixture —
    must equal the hash of the canonical match whether or not seat_latency
    events are spliced in; this feature does not regenerate it."""
    committed = FIXTURE.read_text(encoding="utf-8").strip()
    assert compute_final_hash() == committed

    bare = play_canonical_match()
    latency_event = Event(
        turn=1,
        seq=len(bare.events),
        kind="seat_latency",
        data={"team_id": "blue", "agent_id": None, "unit_id": None, "elapsed_ms": 7},
    )
    with_latency = dataclasses.replace(bare, events=bare.events + (latency_event,))
    assert state_hash(with_latency.final_state()) == committed


# -- every driver kind measures the same way: a sink in `context` -----------


def test_bot_driver_is_unaffected_when_no_sink_is_given() -> None:
    """No ``context``, no sink: a driver exercised directly (every existing
    harness test) behaves exactly as before latency support landed — no new
    key leaks into what the driver returns."""
    driver = build_driver(
        {"type": "command", "argv": [sys.executable, "-c", _ECHO_AGENT]}, SCENARIO
    )
    orders = driver(STATE, "blue", 1)
    assert orders == {"actions": [{"unit_id": "u", "action": "hold"}]}
    assert "_seat_latency" not in orders
    assert "_latency_sink" not in orders


def test_command_driver_records_latency_via_context_sink() -> None:
    driver = build_driver(
        {"type": "command", "argv": [sys.executable, "-c", _ECHO_AGENT]}, SCENARIO
    )
    sink: list[dict[str, Any]] = []
    orders = driver(STATE, "blue", 1, {"_latency_sink": sink})
    assert orders == {"actions": [{"unit_id": "u", "action": "hold"}]}, "orders contract unchanged"
    assert len(sink) == 1
    assert sink[0]["agent_id"] is None
    assert sink[0]["unit_id"] is None
    assert isinstance(sink[0]["elapsed_ms"], int)
    assert sink[0]["elapsed_ms"] >= 0


def test_command_driver_records_latency_even_when_the_seat_idles() -> None:
    """A driver that fails/idles still burned wall-clock time — that's real
    tempo data, not something to drop on the failure path."""
    failing = "import sys; sys.stdin.read(); sys.exit(1)"
    driver = build_driver({"type": "command", "argv": [sys.executable, "-c", failing]}, SCENARIO)
    sink: list[dict[str, Any]] = []
    orders = driver(STATE, "blue", 1, {"_latency_sink": sink})
    assert orders == {"actions": []}
    assert len(sink) == 1
    assert sink[0]["elapsed_ms"] >= 0


def test_per_seat_driver_records_latency_per_agent_and_master() -> None:
    agents = [{"id": "blue-1", "model": "test", "role": "scout"}]
    driver = build_driver(
        {
            "type": "command",
            "per_seat": True,
            "argv": [sys.executable, "-c", _SEAT_ECHO_AGENT],
            "master": {
                "argv": [
                    sys.executable,
                    "-c",
                    "import sys,json; sys.stdin.read(); " "print(json.dumps({'messages': []}))",
                ]
            },
        },
        SCENARIO,
        agents,
    )
    sink: list[dict[str, Any]] = []
    orders = driver(STATE, "blue", 1, {"_latency_sink": sink})
    assert [a["unit_id"] for a in orders["actions"]] == ["blue-u1"]
    assert "_seat_latency" not in orders

    # Default master id is f"{team_id}-master" (make_per_seat_driver).
    agent_ids = {rec["agent_id"] for rec in sink}
    assert agent_ids == {"blue-1", "blue-master"}
    seat_rec = next(rec for rec in sink if rec["agent_id"] == "blue-1")
    assert seat_rec["unit_id"] == "blue-u1"
    master_rec = next(rec for rec in sink if rec["agent_id"] != "blue-1")
    assert master_rec["unit_id"] is None
    for rec in sink:
        assert isinstance(rec["elapsed_ms"], int)
        assert rec["elapsed_ms"] >= 0


# -- the real run loop: latency lands in the persisted on-disk log ----------


def _bot_config(match_id: str, seed: int = 7) -> dict:
    return {
        "match": {"scenario": "skirmish-1", "mode": "competitive", "seed": seed, "id": match_id},
        "teams": [BOT_TEAM_BLUE, BOT_TEAM_RED],
    }


def test_run_match_records_seat_latency_events_in_the_log(arena) -> None:
    result = run_match(_bot_config("m-latency-1"))
    assert result["status"] == "finished"

    log = Store().load_match("m-latency-1")
    latency_events = [e for e in log.events if e.kind == "seat_latency"]
    # bot drivers are team-level (one call per team per turn) — one entry per
    # team per resolved turn.
    assert latency_events
    assert len(latency_events) == result["turns_played"] * 2
    seen_teams = set()
    for event in latency_events:
        assert event.data["team_id"] in {"blue", "red"}
        seen_teams.add(event.data["team_id"])
        assert event.data["agent_id"] is None
        assert event.data["unit_id"] is None
        assert isinstance(event.data["elapsed_ms"], int)
        assert event.data["elapsed_ms"] >= 0
    assert seen_teams == {"blue", "red"}

    # MatchState/state_hash are exactly as if the latency events never
    # existed: stripping them changes nothing.
    without_latency = dataclasses.replace(
        log, events=tuple(e for e in log.events if e.kind != "seat_latency")
    )
    assert state_hash(log.final_state()) == state_hash(without_latency.final_state())
    assert log.final_state() == without_latency.final_state()


def test_harness_verb_run_match_leaves_no_latency_when_no_teams_act(arena) -> None:
    """Guard rail: a match that never processes a turn (e.g. already
    finished) must not append an empty batch of latency events."""
    run_match(_bot_config("m-latency-2"))
    log_before = Store().load_match("m-latency-2")
    # Calling run_match again on an already-finished match should be a no-op.
    run_match(_bot_config("m-latency-2"))
    log_after = Store().load_match("m-latency-2")
    assert log_after.events == log_before.events


# -- resident (per-seat by definition): latency tagged with agent + unit ----


class _FakeSession:
    def __init__(self, match_id: str, agent_id: str, serial: int) -> None:
        self.session_id = f"fake-{agent_id}-{serial}"
        self.transport = "fake"

    def send(self, prompt: str, *, timeout: float) -> str:
        return json.dumps({"action": {"action": "hold"}})


def _fake_transport():
    serial = itertools.count(1)

    def factory(spec: Mapping[str, Any], match_id: str, agent_id: str) -> _FakeSession:
        return _FakeSession(match_id, agent_id, next(serial))

    return factory


def test_resident_driver_records_latency_per_seat_in_the_log(arena, monkeypatch, capsys) -> None:
    monkeypatch.setitem(harness.SESSION_TRANSPORTS, "fake", _fake_transport())
    config = {
        "match": {"scenario": "skirmish-1", "mode": "competitive", "seed": 7, "id": "m-latency-3"},
        "teams": [
            {
                "id": "blue",
                "name": "Blue Foundry",
                "driver": {"type": "resident", "transport": "fake"},
                "agents": [
                    {"id": "blue-1", "model": "fake:mind", "role": "scout"},
                    {"id": "blue-2", "model": "fake:mind", "role": "harvester"},
                    {"id": "blue-3", "model": "fake:mind", "role": "defender"},
                ],
            },
            BOT_TEAM_RED,
        ],
        "max_rounds": 2,
    }
    run_match(config)
    capsys.readouterr()

    log = Store().load_match("m-latency-3")
    latency_events = [e for e in log.events if e.kind == "seat_latency"]
    blue_events = [e for e in latency_events if e.data["team_id"] == "blue"]
    # One entry PER SEAT per turn for the resident team (3 seats x 2 turns).
    assert len(blue_events) == 6
    assert {e.data["agent_id"] for e in blue_events} == {"blue-1", "blue-2", "blue-3"}
    assert {e.data["unit_id"] for e in blue_events} == {"blue-u1", "blue-u2", "blue-u3"}

    red_events = [e for e in latency_events if e.data["team_id"] == "red"]
    assert len(red_events) == 2  # bot driver: one team-level entry per turn
    assert all(e.data["agent_id"] is None for e in red_events)
