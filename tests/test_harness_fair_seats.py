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
    # The failed exchange is dropped: no phantom user turn, no empty answer.
    assert s._history == []
    assert (s.last_finish_reason, s.last_usage) == ("length", {"completion_tokens": 32768})
    assert harness._turn_meta(s) == {
        "finish_reason": "length",
        "usage": {"completion_tokens": 32768},
    }


def test_colleague_session_empty_answer_with_fallback_also_leaves_history_clean(monkeypatch):
    monkeypatch.setattr(
        harness,
        "_http_post_json",
        lambda url, payload, timeout: {
            "choices": [{"finish_reason": "stop", "message": {"content": "<think>x</think>"}}],
        },
    )
    s = harness.ColleagueDirectSession({"model": "m", "system_prompt": "sys"}, "match", "a1")
    try:
        s.send("hi", timeout=5)
    except RuntimeError:
        pass
    else:
        raise AssertionError("an empty answer must not pass as a reply")
    assert s._history == [{"role": "system", "content": "sys"}]


def test_reasoning_fallback_parses_strictly():
    assert harness._spec_bool({"reasoning_fallback": "false"}, "reasoning_fallback", True) is False
    assert harness._spec_bool({}, "reasoning_fallback", True) is True
    try:
        harness._spec_bool({"reasoning_fallback": "no"}, "reasoning_fallback", True)
    except ValueError:
        pass
    else:
        raise AssertionError("an unparseable flag must be loud")


def test_claude_args_must_be_a_list():
    try:
        harness.ClaudeCliSession({"model": "m", "args": "--effort medium"}, "match", "a1")
    except ValueError as err:
        assert "must be a list" in str(err)
    else:
        raise AssertionError("a string args must not be split into characters")


def test_rules_text_team_play_matches_the_driver_mode():
    scenario = {"capture_hold_turns": 2}
    assert harness.TEAM_COMMANDER in harness._rules_text(scenario, False, harness.TEAM_COMMANDER)
    seats = harness._rules_text(scenario, False)
    assert harness.TEAM_SEATS in seats and "If exactly one team" in seats
    assert f"+ {harness.CP_POINTS} points per control point" in seats
    no_comms = harness._rules_text(scenario, False, harness.TEAM_SEATS_NO_COMMS)
    assert "Teammates do not read your" in no_comms


def test_team_private_events_cover_declared_and_rejected_orders():
    assert {"action_declared", "action_rejected"} <= harness._TEAM_PRIVATE_EVENTS


def test_rules_text_adds_crown_and_fog_paragraphs_only_when_present():
    base = {"capture_hold_turns": 2}
    plain = harness._rules_text(base, False)
    assert "The Crown" not in plain and "Fog of war is ON" not in plain
    both = harness._rules_text(
        {**base, "crown": {"pos": [6, 5], "value": 4, "hold_turns": 5}}, True
    )
    assert "for 4 points" in both and "5 consecutive turns" in both and "Fog of war is ON" in both


def test_compact_state_carries_the_crown():
    state = {"turn": 3, "teams": [], "units": [], "crown": {"pos": [6, 5], "value": 4}}
    assert harness._compact_state(state)["crown"]["value"] == 4
    assert "crown" not in harness._compact_state({**state, "crown": None})
