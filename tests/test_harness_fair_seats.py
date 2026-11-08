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


def test_compact_state_shows_each_missions_reward():
    """A seat must see what a mission is worth: the rules score "mission rewards",
    so the per-turn state carries each mission's reward next to its amount."""
    state = {
        "units": [],
        "control_points": [],
        "resource_nodes": [],
        "missions": [
            {
                "id": "ms-hold-2b",
                "kind": "hold",
                "pos": [20, 6],
                "amount": 3,
                "reward": 8,
                "status": "open",
            },
            {
                "id": "ms-deliver-a",
                "kind": "deliver",
                "pos": [0, 0],
                "amount": 10,
                "reward": 10,
                "status": "open",
                "team_id": "blue",
            },
        ],
    }
    missions = {m["id"]: m for m in harness._compact_state(state)["missions"]}
    assert missions["ms-hold-2b"]["reward"] == 8
    assert missions["ms-hold-2b"]["amount"] == 3
    assert missions["ms-deliver-a"]["reward"] == 10


def test_rules_say_where_the_reward_is():
    text = harness._rules_text({"capture_hold_turns": 2}, fog=False)
    assert '"reward"' in text and "not its" in text
