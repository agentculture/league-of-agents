"""Structured output: with ``"structured_output": true`` in a resident
driver's spec, every seat's reply is constrained to the reply format's JSON
schema by the serving side: ``response_format`` for an OpenAI-compatible
server, ``--json-schema`` for the Claude CLI. Off by default, so existing
configs are unchanged."""

import json
from typing import Any

import pytest

from league import harness
from league.cli._commands.arena import _scenario_dict
from league.engine.genscenario import GenParams, generate
from league.harness import ClaudeCliSession, ColleagueDirectSession, _reply_schema, run_match
from tests.test_harness_resident import _config

THIEF = _scenario_dict(generate(5, GenParams(grid_width=13, grid_height=11, thieves=1)))
PLAIN = _scenario_dict(generate(5, GenParams(grid_width=13, grid_height=11)))


@pytest.fixture
def arena(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _enum(scenario: dict[str, Any]) -> list[str]:
    return _reply_schema(scenario)["properties"]["action"]["properties"]["action"]["enum"]


def test_schema_follows_the_board_verbs() -> None:
    verbs = _enum
    assert verbs(THIEF) == ["move", "gather", "deliver", "steal", "hold"]
    assert verbs(PLAIN) == ["move", "gather", "deliver", "hold"]
    schema = _reply_schema(PLAIN)
    assert schema["required"] == ["action"] and schema["additionalProperties"] is False
    assert schema["properties"]["messages"] == {"type": "array", "items": {"type": "string"}}


def test_colleague_session_sends_response_format_only_when_set(monkeypatch) -> None:
    posts: list[dict[str, Any]] = []

    def fake_post(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        posts.append(payload)
        return {"choices": [{"message": {"content": '{"action": {"action": "hold"}}'}}]}

    monkeypatch.setattr(harness, "_http_post_json", fake_post)
    session = ColleagueDirectSession({"model": "glm"}, "m", "blue-1")
    session.send("a", timeout=5)
    session.reply_schema = _reply_schema(PLAIN)
    session.send("b", timeout=5)
    assert "response_format" not in posts[0]
    assert posts[1]["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "seat_reply", "schema": _reply_schema(PLAIN)},
    }


def test_claude_session_passes_json_schema_only_when_set() -> None:
    session = ClaudeCliSession({"model": "claude-sonnet-5-5"}, "m", "red-1")
    assert "--json-schema" not in session._argv("--session-id")
    session.reply_schema = _reply_schema(PLAIN)
    argv = session._argv("--resume")
    assert json.loads(argv[argv.index("--json-schema") + 1]) == _reply_schema(PLAIN)


class _Recorder:
    transport = "fake"

    def __init__(self, spec, match_id, agent_id) -> None:
        self.session_id = f"fake-{agent_id}"
        self.reply_schema = None
        _Recorder.made.append(self)

    def send(self, prompt: str, *, timeout: float) -> str:
        return json.dumps({"action": {"action": "hold"}})


@pytest.mark.parametrize("flag, expect", [(True, True), (False, False), (None, False)])
def test_driver_arms_the_schema_from_the_spec(arena, monkeypatch, capsys, flag, expect) -> None:
    _Recorder.made = []
    monkeypatch.setitem(harness.SESSION_TRANSPORTS, "fake", _Recorder)
    config = _config(f"m-structured-{flag}", max_rounds=1)
    if flag is not None:
        config["teams"][0]["driver"]["structured_output"] = flag
    run_match(config)
    capsys.readouterr()
    assert _Recorder.made and all((s.reply_schema is not None) is expect for s in _Recorder.made)


def test_driver_rejects_a_non_boolean_knob(arena, monkeypatch) -> None:
    monkeypatch.setitem(harness.SESSION_TRANSPORTS, "fake", _Recorder)
    config = _config("m-structured-bad", max_rounds=1)
    config["teams"][0]["driver"]["structured_output"] = "yes"
    with pytest.raises(ValueError, match="structured_output"):
        run_match(config)
