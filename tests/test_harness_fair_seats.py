"""Fair-seat harness options: team-private events, shared system prompt, no token cap."""

from league import harness


def test_events_since_drops_other_teams_messages_and_plans(monkeypatch):
    log = {
        "events_by_turn": {
            "1": [
                {"kind": "message_sent", "data": {"team_id": "blue", "text": "ours"}},
                {"kind": "message_sent", "data": {"team_id": "red", "text": "theirs"}},
                {"kind": "plan_declared", "data": {"team_id": "red", "text": "their plan"}},
                {"kind": "unit_moved", "data": {"unit_id": "red-u1", "to": [1, 1]}},
            ]
        }
    }
    monkeypatch.setattr(harness, "_cli_json", lambda argv: log)
    kept = harness._events_since("m", 0, 1, "blue")
    texts = [e["data"].get("text") for e in kept]
    assert "ours" in texts
    assert "theirs" not in texts and "their plan" not in texts
    assert any(e["kind"] == "unit_moved" for e in kept), "public events stay visible"
    assert len(harness._events_since("m", 0, 1)) == 4, "no team_id keeps the old behaviour"


def test_claude_session_passes_system_prompt_and_args():
    s = harness.ClaudeCliSession(
        {"model": "m", "system_prompt": "SYS", "args": ["--effort", "medium"]}, "match", "a1"
    )
    argv = s._argv("--session-id")
    assert argv[argv.index("--system-prompt") + 1] == "SYS"
    assert argv[-2:] == ["--effort", "medium"]


def test_colleague_session_no_cap_and_system_prompt(monkeypatch):
    sent = {}

    def fake_post(url, payload, timeout):
        sent.update(payload)
        return {"choices": [{"message": {"content": "{}"}}]}

    monkeypatch.setattr(harness, "_http_post_json", fake_post)
    s = harness.ColleagueDirectSession(
        {"model": "m", "max_tokens": None, "system_prompt": "SYS", "top_p": 0.95}, "match", "a1"
    )
    s.send("hi", timeout=5)
    assert "max_tokens" not in sent
    assert sent["top_p"] == 0.95
    assert sent["messages"][0] == {"role": "system", "content": "SYS"}


def test_colleague_session_no_reasoning_fallback_raises_on_empty(monkeypatch):
    monkeypatch.setattr(
        harness,
        "_http_post_json",
        lambda url, payload, timeout: {
            "choices": [
                {
                    "finish_reason": "length",
                    "message": {"content": None, "reasoning_content": "thinking..."},
                }
            ],
            "usage": {"completion_tokens": 32768},
        },
    )
    s = harness.ColleagueDirectSession({"model": "m", "reasoning_fallback": False}, "match", "a1")
    try:
        s.send("hi", timeout=5)
    except RuntimeError as err:
        assert "finish_reason=length" in str(err)
    else:
        raise AssertionError("an empty answer must not pass as a reply")
    assert s._history[-1] == {"role": "assistant", "content": ""}
