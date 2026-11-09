"""A seat's thinking is kept in its audit record, never in its transcript.

* ``ColleagueDirectSession`` exposes the model's ``reasoning_content`` (or
  inline ``<think>`` text) as ``last_reasoning`` for the last reply only;
* the resident driver writes it to ``sessions/<agent>.jsonl`` as
  ``reasoning``, and leaves the key out for sessions that expose none, so
  Claude CLI records keep their shape;
* the reasoning is never sent back to the model.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from league import harness
from league.harness import ColleagueDirectSession, run_match
from tests.test_harness_resident import _config, _fake_transport, _FakeSession  # noqa: F401


@pytest.fixture
def arena(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _session(monkeypatch, replies: list[dict[str, Any]], posts: list[dict[str, Any]]):
    def fake_post(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        posts.append(payload)
        return replies.pop(0)

    monkeypatch.setattr(harness, "_http_post_json", fake_post)
    return ColleagueDirectSession({"model": "glm", "reasoning_fallback": False}, "m-x", "blue-1")


def test_reasoning_is_exposed_per_reply_and_never_threaded(monkeypatch) -> None:
    posts: list[dict[str, Any]] = []
    session = _session(
        monkeypatch,
        [
            {"choices": [{"message": {"content": "51", "reasoning_content": "17*3 is 51"}}]},
            {"choices": [{"message": {"content": "<think>add one</think>52"}}]},
            {"choices": [{"message": {"content": "53"}}]},
        ],
        posts,
    )
    assert session.send("17*3?", timeout=5) == "51"
    assert session.last_reasoning == "17*3 is 51"
    assert session.send("plus one?", timeout=5) == "52"
    assert session.last_reasoning == "add one"
    assert session.send("plus one again?", timeout=5) == "53"
    assert session.last_reasoning is None, "a reply without thinking must not keep the old one"
    sent = json.dumps(posts)
    assert "17*3 is 51" not in sent and "add one" not in sent


def test_empty_answer_still_reports_the_thinking(monkeypatch) -> None:
    session = _session(
        monkeypatch,
        [{"choices": [{"message": {"content": None, "reasoning_content": "ran out"}}]}],
        [],
    )
    with pytest.raises(RuntimeError):
        session.send("go", timeout=5)
    assert session.last_reasoning == "ran out"


class _ThinkingSession(_FakeSession):
    def send(self, prompt: str, *, timeout: float) -> str:
        reply = super().send(prompt, timeout=timeout)
        self.last_reasoning = f"thinking about turn {len(self._calls)}"
        return reply


def test_session_records_carry_reasoning_only_when_exposed(arena, monkeypatch, capsys) -> None:
    calls: list[dict[str, Any]] = []
    factory = _fake_transport(calls, {})

    def thinking_factory(spec, match_id, agent_id):
        base = factory(spec, match_id, agent_id)
        session = _ThinkingSession(match_id, agent_id, 0, calls, [])
        session.session_id = base.session_id
        return session

    monkeypatch.setitem(harness.SESSION_TRANSPORTS, "fake", thinking_factory)
    run_match(_config("m-reasoning-1", max_rounds=2))
    capsys.readouterr()
    path = Path(".league/matches/m-reasoning-1/sessions/blue-1.jsonl")
    records = [json.loads(line) for line in path.read_text().splitlines()]
    assert all(r["reasoning"].startswith("thinking about turn") for r in records)

    monkeypatch.setitem(harness.SESSION_TRANSPORTS, "fake", _fake_transport([], {}))
    run_match(_config("m-reasoning-2", max_rounds=2))
    capsys.readouterr()
    plain = Path(".league/matches/m-reasoning-2/sessions/blue-1.jsonl").read_text().splitlines()
    assert all("reasoning" not in json.loads(line) for line in plain)
