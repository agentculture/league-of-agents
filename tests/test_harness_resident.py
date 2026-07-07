"""The resident driver: one long-lived session per seat for the whole match (t5).

Criteria under test (spec c6/h1):

* the SAME session serves every turn — session ids recorded per call collapse
  to one id per seat across the whole match;
* turn 1 is the full briefing (rules + scenario + role); turn N>1 is a DELTA
  only — no rules re-teach, but it carries new events since the seat last
  acted, the current compact state, teammate messages this turn, the seat's
  own rejections verbatim, and its own legal actions;
* per-seat session transcripts land under
  ``.league/matches/<id>/sessions/<agent-id>.jsonl`` for audit, and the team
  is labeled ``resident`` on the fairness axis (t6);
* bot/command drivers stay untouched (their tests elsewhere keep passing).

Tests inject a fake session transport (``SESSION_TRANSPORTS``) so no live
model endpoint is ever needed; the real claude-cli / colleague-direct
adapters are covered by transport-shape tests that stub subprocess/HTTP.
"""

from __future__ import annotations

import itertools
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

import pytest

import league.harness as harness
from league.harness import (
    ClaudeCliSession,
    ColleagueDirectSession,
    build_driver,
    driver_kind,
    run_match,
)
from league.store import Store

_RULES_MARKER = "Rules, briefly:"
_REASON = "target beyond this role's move range"

SCENARIO = {
    "roles": {"scout": {"move": 3, "carry": 1}},
    "grid": {"width": 12, "height": 10},
    "capture_hold_turns": 2,
    "turn_limit": 30,
}


@pytest.fixture()
def arena(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


# -- the fake session transport (no live endpoint, ever) ---------------------


class _FakeSession:
    """Scripted seat mind; records every prompt with the session id serving it."""

    def __init__(
        self,
        match_id: str,
        agent_id: str,
        serial: int,
        calls: list[dict[str, Any]],
        replies: list[dict[str, Any]],
    ) -> None:
        # The serial number is the tell: if the driver wrongly minted a new
        # session per turn, ids across one seat's calls would differ.
        self.session_id = f"fake-{agent_id}-{serial}"
        self.transport = "fake"
        self._agent_id = agent_id
        self._calls = calls
        self._replies = replies

    def send(self, prompt: str, *, timeout: float) -> str:
        self._calls.append(
            {"agent_id": self._agent_id, "session_id": self.session_id, "prompt": prompt}
        )
        reply = self._replies.pop(0) if self._replies else {"action": {"action": "hold"}}
        return json.dumps(reply)


def _fake_transport(calls: list[dict[str, Any]], scripts: dict[str, list[dict[str, Any]]]):
    serial = itertools.count(1)

    def factory(spec: Mapping[str, Any], match_id: str, agent_id: str) -> _FakeSession:
        return _FakeSession(match_id, agent_id, next(serial), calls, scripts.get(agent_id, []))

    return factory


def _config(match_id: str, max_rounds: int = 3) -> dict[str, Any]:
    return {
        "match": {"scenario": "skirmish-1", "mode": "competitive", "seed": 7, "id": match_id},
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
            {
                "id": "red",
                "name": "Red Relay",
                "driver": {"type": "bot"},
                "agents": [
                    {"id": "red-1", "model": "bot:greedy", "role": "scout"},
                    {"id": "red-2", "model": "bot:greedy", "role": "harvester"},
                    {"id": "red-3", "model": "bot:greedy", "role": "defender"},
                ],
            },
        ],
        "max_rounds": max_rounds,
    }


def _seat_prompts(calls: list[dict[str, Any]], agent_id: str) -> list[str]:
    return [c["prompt"] for c in calls if c["agent_id"] == agent_id]


# -- acceptance 1: one session per seat, rules taught exactly once -----------


def test_same_session_serves_every_turn_of_the_match(arena, monkeypatch, capsys) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setitem(harness.SESSION_TRANSPORTS, "fake", _fake_transport(calls, {}))

    run_match(_config("m-resident-1"))
    capsys.readouterr()

    for agent_id in ("blue-1", "blue-2", "blue-3"):
        seat_calls = [c for c in calls if c["agent_id"] == agent_id]
        assert len(seat_calls) == 3, f"{agent_id} should be consulted every turn"
        assert (
            len({c["session_id"] for c in seat_calls}) == 1
        ), f"{agent_id} must be served by ONE session for the whole match"


def test_rules_appear_only_in_the_turn_one_payload(arena, monkeypatch, capsys) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setitem(harness.SESSION_TRANSPORTS, "fake", _fake_transport(calls, {}))

    run_match(_config("m-resident-2"))
    capsys.readouterr()

    for agent_id in ("blue-1", "blue-2", "blue-3"):
        prompts = _seat_prompts(calls, agent_id)
        assert len(prompts) == 3
        assert _RULES_MARKER in prompts[0]
        assert "Scenario:" in prompts[0]
        for later in prompts[1:]:
            assert _RULES_MARKER not in later, "turn N>1 must not re-teach the rules"
            assert "Scenario:" not in later, "turn N>1 must not resend the scenario"


# -- the delta briefing: events + rejections + legal actions + teammates -----


def test_delta_briefing_carries_own_rejection_events_legal_and_state(
    arena, monkeypatch, capsys
) -> None:
    calls: list[dict[str, Any]] = []
    scripts = {
        # blue-u1 is the scout (move=3) at (0, 0) on skirmish-1: [4, 0] is the
        # canonical out-of-range mistake the engine rejects with _REASON.
        "blue-1": [
            {"action": {"unit_id": "blue-u1", "action": "move", "to": [4, 0]}},
            {
                "action": {"unit_id": "blue-u1", "action": "hold"},
                "messages": [{"from": "blue-1", "text": "regroup-now"}],
            },
        ],
    }
    monkeypatch.setitem(harness.SESSION_TRANSPORTS, "fake", _fake_transport(calls, scripts))

    run_match(_config("m-resident-3"))
    capsys.readouterr()

    delta_1 = _seat_prompts(calls, "blue-1")[1]
    # Own rejection, the engine's reason verbatim (reuses the t2 formatting).
    assert "REJECTIONS from your last turn" in delta_1
    assert f"blue-u1: {_REASON}" in delta_1
    # Own legal actions, checkable before declaring.
    assert "Legal actions right now:" in delta_1
    assert "blue-u1: move to" in delta_1
    # New events since this seat last acted, read off the log via the CLI.
    assert "action_rejected" in delta_1
    # The current compact state, not the full scenario re-teach.
    assert "Compact current state (JSON):" in delta_1

    # The REJECTIONS section is scoped to the seat's OWN unit: a teammate may
    # see blue-u1's rejection in the shared event feed (the log is public),
    # but it is never presented as its own mistake to fix.
    delta_2 = _seat_prompts(calls, "blue-2")[1]
    assert "REJECTIONS from your last turn" not in delta_2

    # Teammate messages sent earlier THIS turn reach later seats' deltas.
    delta_3 = _seat_prompts(calls, "blue-3")[1]
    assert "regroup-now" in delta_3


# -- acceptance 3: per-seat transcripts + the residency label -----------------


def test_session_transcripts_are_recorded_per_seat(arena, monkeypatch, capsys) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setitem(harness.SESSION_TRANSPORTS, "fake", _fake_transport(calls, {}))

    run_match(_config("m-resident-4"))
    capsys.readouterr()

    for agent_id in ("blue-1", "blue-2", "blue-3"):
        path = Path(".league/matches/m-resident-4/sessions") / f"{agent_id}.jsonl"
        assert path.is_file(), f"no session transcript for {agent_id}"
        records = [json.loads(line) for line in path.read_text().splitlines()]
        assert [r["turn"] for r in records] == [1, 2, 3]
        prompts = _seat_prompts(calls, agent_id)
        for record, prompt in zip(records, prompts):
            assert record["sent"] == prompt
            assert json.loads(record["received"])  # what came back, verbatim
            assert record["transport"] == "fake"
        assert len({r["session_id"] for r in records}) == 1

    # The fairness axis (t6): the resident team is labeled as such in the log.
    assert Store().load_match("m-resident-4").driver_kinds == {"blue": "resident", "red": "bot"}


# -- driver plumbing ----------------------------------------------------------


def test_driver_kind_resident() -> None:
    assert driver_kind({"type": "resident", "transport": "claude"}) == "resident"


def test_build_driver_rejects_unknown_transport() -> None:
    with pytest.raises(ValueError, match="transport"):
        build_driver({"type": "resident", "transport": "nope"}, SCENARIO, [])


# -- the real adapters, no network: claude-cli ---------------------------------


class _SubprocessRecorder:
    def __init__(self, results: list[subprocess.CompletedProcess]) -> None:
        self.calls: list[dict[str, Any]] = []
        self._results = results

    def __call__(self, argv, **kwargs):
        self.calls.append({"argv": list(argv), "input": kwargs.get("input")})
        return self._results.pop(0)


def _completed(returncode: int = 0, stdout: str = '{"action": {"action": "hold"}}', stderr=""):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def test_claude_cli_session_starts_then_resumes_one_session(monkeypatch) -> None:
    recorder = _SubprocessRecorder([_completed(), _completed(stdout="second")])
    monkeypatch.setattr(harness.subprocess, "run", recorder)

    session = ClaudeCliSession({"model": "haiku"}, "m-x", "blue-1")
    assert session.transport == "claude-cli"
    assert re.fullmatch(
        r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-8[0-9a-f]{3}-[0-9a-f]{12}", session.session_id
    ), "driver-minted session ids must be valid UUIDs (the spike's fallback contract)"
    # Deterministic minting: the same (match, seat) resumes after a crash.
    assert ClaudeCliSession({}, "m-x", "blue-1").session_id == session.session_id
    assert ClaudeCliSession({}, "m-x", "blue-2").session_id != session.session_id

    first = session.send("turn one", timeout=5)
    second = session.send("turn two", timeout=5)
    assert first == '{"action": {"action": "hold"}}'
    assert second == "second"

    argv_1, argv_2 = recorder.calls[0]["argv"], recorder.calls[1]["argv"]
    assert argv_1[:2] == ["claude", "-p"]
    assert ["--session-id", session.session_id] == argv_1[2:4]
    assert ["--model", "haiku"] == argv_1[4:6]
    assert ["--resume", session.session_id] == argv_2[2:4]
    assert recorder.calls[0]["input"] == "turn one"
    assert recorder.calls[1]["input"] == "turn two"


def test_claude_cli_session_falls_back_to_resume_when_id_exists(monkeypatch) -> None:
    recorder = _SubprocessRecorder(
        [_completed(returncode=1, stderr="session id already in use"), _completed(stdout="ok")]
    )
    monkeypatch.setattr(harness.subprocess, "run", recorder)

    session = ClaudeCliSession({}, "m-x", "blue-1")
    assert session.send("turn one", timeout=5) == "ok"
    assert "--session-id" in recorder.calls[0]["argv"]
    assert "--resume" in recorder.calls[1]["argv"], "a crashed match resumes its seat session"


# -- the real adapters, no network: colleague-direct ---------------------------


def test_colleague_direct_session_holds_the_transcript(monkeypatch) -> None:
    posts: list[dict[str, Any]] = []
    replies = [
        # The Qwen gotcha, verbatim from the spike: a thinking model may return
        # content=None with the answer in reasoning_content.
        {"choices": [{"message": {"content": None, "reasoning_content": "<think>hmm</think>ACK"}}]},
        {"choices": [{"message": {"content": "EMBER-KITE-9"}}]},
    ]

    def fake_post(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        posts.append({"url": url, "payload": payload})
        return replies.pop(0)

    monkeypatch.setattr(harness, "_http_post_json", fake_post)

    spec = {"model": "qwen-test", "base_url": "http://localhost:8001/v1"}
    session = ColleagueDirectSession(spec, "m-x", "blue-1")
    assert session.transport == "colleague-direct"
    assert session.session_id.startswith("colleague-direct-")

    first = session.send("remember EMBER-KITE-9", timeout=5)
    assert first == "ACK", "content=None must fall back to reasoning_content, <think> stripped"

    second = session.send("what codeword?", timeout=5)
    assert second == "EMBER-KITE-9"

    # The driver-held transcript IS the session: request 2 threads request 1.
    assert posts[1]["url"] == "http://localhost:8001/v1/chat/completions"
    assert posts[1]["payload"]["model"] == "qwen-test"
    assert posts[1]["payload"]["messages"] == [
        {"role": "user", "content": "remember EMBER-KITE-9"},
        {"role": "assistant", "content": "ACK"},
        {"role": "user", "content": "what codeword?"},
    ]


def test_colleague_direct_send_failure_leaves_no_dangling_user_turn(monkeypatch) -> None:
    attempts = {"n": 0}

    def flaky_post(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise OSError("connection refused")
        return {"choices": [{"message": {"content": "ok"}}], "echo": payload["messages"]}

    monkeypatch.setattr(harness, "_http_post_json", flaky_post)

    session = ColleagueDirectSession({"model": "qwen-test"}, "m-x", "blue-1")
    with pytest.raises(RuntimeError):
        session.send("turn one", timeout=5)
    # The model never saw the failed message; the retry transcript stays clean.
    assert session.send("turn one again", timeout=5) == "ok"


# -- a seat that flakes idles without ending the session ----------------------


class _FlakyFirstSession(_FakeSession):
    def __init__(self, *args) -> None:
        super().__init__(*args)
        self._failed = False

    def send(self, prompt: str, *, timeout: float) -> str:
        if not self._failed and self._agent_id == "blue-1":
            self._failed = True
            raise RuntimeError("seat flaked")
        return super().send(prompt, timeout=timeout)


def test_flaky_seat_gets_the_full_briefing_again_not_a_delta(arena, monkeypatch, capsys) -> None:
    calls: list[dict[str, Any]] = []
    serial = itertools.count(1)

    def factory(spec, match_id, agent_id):
        return _FlakyFirstSession(match_id, agent_id, next(serial), calls, [])

    monkeypatch.setitem(harness.SESSION_TRANSPORTS, "fake", factory)

    run_match(_config("m-resident-5"))
    capsys.readouterr()

    # blue-1's first successful call is on turn 2 — it never saw the rules, so
    # it must be briefed in full then, not handed a delta it can't ground.
    prompts = _seat_prompts(calls, "blue-1")
    assert len(prompts) == 2
    assert _RULES_MARKER in prompts[0]
    assert _RULES_MARKER not in prompts[1]
    # And its transcript still recorded the failed attempt for audit.
    path = Path(".league/matches/m-resident-5/sessions/blue-1.jsonl")
    records = [json.loads(line) for line in path.read_text().splitlines()]
    assert records[0]["turn"] == 1
    assert "error" in records[0]


# -- command drivers stay stateless and untouched ------------------------------


def test_command_per_seat_driver_unchanged_by_resident_support() -> None:
    agents = [{"id": "blue-1", "model": "m", "role": "scout"}]
    echo = (
        "import sys, json; sys.stdin.read(); "
        "print(json.dumps({'action': {'unit_id': 'u', 'action': 'hold'}}))"
    )
    driver = build_driver(
        {"type": "command", "per_seat": True, "argv": [sys.executable, "-c", echo]},
        SCENARIO,
        agents,
    )
    state = {
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
    orders = driver(state, "blue", 1)
    assert [a["unit_id"] for a in orders["actions"]] == ["blue-u1"]
