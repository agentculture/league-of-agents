"""Issue #47: live seat output, per-seat tool/network settings, and the pi seat.

1. **In-progress output.** While a seat answers, ``.league/matches/<id>/live/
   <agent-id>.json`` grows (``thinking_so_far``/``response_so_far``), every
   version parses as JSON, and a final write carries ``done: true``.
2. **Seat settings.** Each seat's ``tools``/``network`` lands in
   ``.league/matches/<id>/seats.json`` and ``match show --json``'s ``seats``,
   failing closed for anything the harness can't verify.
3. **pi seats.** ``pi -p --mode json`` with no tools and no MCP, one persistent
   session per seat, reasoning text captured from ``thinking_delta`` events.

No test here touches a live model, pi, claude or HTTP endpoint: transports are
faked and the process/HTTP helpers are monkeypatched.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import league.harness as harness
from league.cli import main
from league.harness import (
    ClaudeCliSession,
    ColleagueDirectSession,
    LiveSeatWriter,
    PiSession,
    run_match,
    seat_settings,
)
from league.store import Store


@pytest.fixture()
def arena(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _read_live(match_id: str, agent_id: str) -> dict[str, Any]:
    return json.loads(Store().live_seat_path(match_id, agent_id).read_text(encoding="utf-8"))


# -- 1. LiveSeatWriter -------------------------------------------------------


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_live_writer_writes_start_throttled_updates_and_done(arena) -> None:
    clock, store = _Clock(), Store()
    writer = LiveSeatWriter(store, "m1", "blue-1", 4, interval=5.0, clock=clock)
    first = _read_live("m1", "blue-1")
    assert first["turn"] == 4 and first["done"] is False and first["thinking_so_far"] == ""

    clock.now = 2.0
    writer.update("think a", "")
    assert _read_live("m1", "blue-1")["thinking_so_far"] == ""  # throttled

    clock.now = 5.5
    writer.update("think a b", "resp")
    snap = _read_live("m1", "blue-1")
    assert snap["thinking_so_far"] == "think a b" and snap["response_so_far"] == "resp"
    assert snap["done"] is False

    writer.finish(reply="resp full")
    done = _read_live("m1", "blue-1")
    assert done["done"] is True and done["response_so_far"] == "resp"
    assert not list(store.live_dir("m1").glob(".*.tmp"))  # atomic: no temp left behind


def test_live_writer_finish_with_error_marks_done(arena) -> None:
    writer = LiveSeatWriter(Store(), "m1", "blue-2", 1, clock=_Clock())
    writer.finish(error="the seat could not answer this turn")
    rec = _read_live("m1", "blue-2")
    assert rec["done"] is True and rec["error"].startswith("the seat")


# -- resident driver + live output ------------------------------------------


class _StreamingSession:
    streams = True

    def __init__(self, agent_id: str, seen: list[dict[str, Any]], fail: bool = False) -> None:
        self.session_id = f"s-{agent_id}"
        self.transport = "fake-stream"
        self._agent_id = agent_id
        self._seen = seen
        self._fail = fail
        self.last_reasoning = "full reasoning"

    def send(self, prompt: str, *, timeout: float, on_progress=None) -> str:
        if self._fail:
            raise RuntimeError("boom")
        assert on_progress is not None
        match_dir = next(Path(".league/matches").iterdir())
        for i in range(3):
            on_progress(f"thinking {i}", "")
            path = match_dir / "live" / f"{self._agent_id}.json"
            self._seen.append(json.loads(path.read_text(encoding="utf-8")))  # always parses
        reply = json.dumps({"action": {"action": "hold"}})
        on_progress("thinking 2", reply)
        return reply


def _config(match_id: str, transport: str, *, live: bool, max_rounds: int = 1) -> dict[str, Any]:
    return {
        "match": {"scenario": "skirmish-1", "mode": "competitive", "seed": 7, "id": match_id},
        "live_output": live,
        "live_interval": 0,
        "teams": [
            {
                "id": "blue",
                "name": "Blue",
                "driver": {"type": "resident", "transport": transport},
                "agents": [
                    {"id": "blue-1", "model": "fake:mind", "role": "scout"},
                    {"id": "blue-2", "model": "fake:mind", "role": "harvester"},
                    {"id": "blue-3", "model": "fake:mind", "role": "defender"},
                ],
            },
            {
                "id": "red",
                "name": "Red",
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


def test_resident_live_output_grows_and_ends_done(arena, monkeypatch) -> None:
    seen: list[dict[str, Any]] = []
    monkeypatch.setitem(
        harness.SESSION_TRANSPORTS, "fake-stream", lambda s, m, a: _StreamingSession(a, seen)
    )
    run_match(_config("m-live", "fake-stream", live=True))
    assert seen and all(rec["turn"] == 1 for rec in seen)
    assert [r["thinking_so_far"] for r in seen[:3]] == ["thinking 0", "thinking 1", "thinking 2"]
    final = _read_live("m-live", "blue-1")
    assert final["done"] is True and json.loads(final["response_so_far"])["action"]
    # reasoning reaches the session transcript too
    rec = json.loads(
        Store().session_transcript_path("m-live", "blue-1").read_text().splitlines()[0]
    )
    assert rec["reasoning"] == "full reasoning"


def test_live_output_is_off_unless_configured(arena, monkeypatch) -> None:
    seen: list[dict[str, Any]] = []

    class _Plain(_StreamingSession):
        def send(self, prompt: str, *, timeout: float, on_progress=None) -> str:
            assert on_progress is None
            return json.dumps({"action": {"action": "hold"}})

    monkeypatch.setitem(harness.SESSION_TRANSPORTS, "fake-plain", lambda s, m, a: _Plain(a, seen))
    run_match(_config("m-off", "fake-plain", live=False))
    assert not Store().live_dir("m-off").exists()


def test_failed_seat_writes_done_with_error(arena, monkeypatch, capsys) -> None:
    monkeypatch.setitem(
        harness.SESSION_TRANSPORTS,
        "fake-fail",
        lambda s, m, a: _StreamingSession(a, [], fail=True),
    )
    run_match(_config("m-fail", "fake-fail", live=True))
    rec = _read_live("m-fail", "blue-1")
    assert rec["done"] is True and "error" in rec


def test_non_streaming_transport_gets_no_live_file(arena, monkeypatch) -> None:
    class _Old:
        transport = "old"

        def __init__(self, agent_id: str) -> None:
            self.session_id = f"o-{agent_id}"

        def send(self, prompt: str, *, timeout: float) -> str:  # no on_progress at all
            return json.dumps({"action": {"action": "hold"}})

    monkeypatch.setitem(harness.SESSION_TRANSPORTS, "old", lambda s, m, a: _Old(a))
    run_match(_config("m-old", "old", live=True))
    assert not Store().live_dir("m-old").exists()


# -- transports: streaming parsers ------------------------------------------


def test_colleague_streams_reasoning_and_content(monkeypatch) -> None:
    chunks = [
        {"choices": [{"delta": {"reasoning_content": "Let me "}}]},
        {"choices": [{"delta": {"reasoning_content": "think."}}]},
        {"choices": [{"delta": {"content": '{"action": '}}]},
        {"choices": [{"delta": {"content": '{"action": "hold"}}'}, "finish_reason": "stop"}]},
        {"choices": [], "usage": {"completion_tokens": 9, "reasoning_tokens": 4}},
    ]
    sent: dict[str, Any] = {}

    def fake_stream(url, payload, timeout):
        sent.update(payload)
        yield from chunks

    monkeypatch.setattr(harness, "_http_post_stream", fake_stream)
    progress: list[tuple[str, str]] = []
    s = ColleagueDirectSession({"model": "glm"}, "m", "blue-1")
    reply = s.send("go", timeout=5, on_progress=lambda t, r: progress.append((t, r)))
    assert sent["stream"] is True and sent["stream_options"] == {"include_usage": True}
    assert progress[1][0] == "Let me think." and progress[-1][1].endswith("}}")
    assert json.loads(reply) == {"action": {"action": "hold"}}
    assert s.last_reasoning == "Let me think." and s.last_finish_reason == "stop"
    assert s.last_usage["completion_tokens"] == 9


def test_colleague_without_progress_keeps_the_plain_request(monkeypatch) -> None:
    seen: dict[str, Any] = {}

    def fake_post(url, payload, timeout):
        seen.update(payload)
        return {
            "choices": [
                {"message": {"content": "{}", "reasoning_content": "r"}, "finish_reason": "stop"}
            ]
        }

    monkeypatch.setattr(harness, "_http_post_json", fake_post)
    s = ColleagueDirectSession({"model": "glm"}, "m", "blue-1")
    assert s.send("go", timeout=5) == "{}"
    assert "stream" not in seen and s.last_reasoning == "r"


def _feed(lines: list[dict[str, Any]], code: int = 0, captured: dict | None = None):
    def fake(argv, prompt, timeout, on_line, *, cwd=None):
        if captured is not None:
            captured.update(argv=argv, prompt=prompt, cwd=cwd)
        for line in lines:
            on_line(json.dumps(line))
        return code, "" if code == 0 else "bad"

    return fake


def test_claude_streaming_forwards_text_and_returns_result(monkeypatch) -> None:
    lines = [
        {"type": "system", "subtype": "init"},
        {
            "type": "stream_event",
            "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "{"}},
        },
        {
            "type": "stream_event",
            "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "}"}},
        },
        {"type": "result", "result": "{}", "usage": {"output_tokens": 3}, "is_error": False},
    ]
    captured: dict[str, Any] = {}
    monkeypatch.setattr(harness, "_stream_process", _feed(lines, captured=captured))
    progress: list[tuple[str, str]] = []
    s = ClaudeCliSession({"model": "claude-sonnet-5-5", "args": ["--tools", ""]}, "m", "red-1")
    assert s.send("go", timeout=5, on_progress=lambda t, r: progress.append((t, r))) == "{}"
    assert progress == [("", "{"), ("", "{}")]  # no thinking text from claude -p
    assert "--output-format" in captured["argv"] and "stream-json" in captured["argv"]
    assert s.last_usage == {"output_tokens": 3} and s.last_reasoning is None


def test_claude_streaming_error_result_raises(monkeypatch) -> None:
    lines = [{"type": "result", "result": "nope", "is_error": True}]
    monkeypatch.setattr(harness, "_stream_process", _feed(lines))
    s = ClaudeCliSession({}, "m", "red-1")
    s._started = True
    with pytest.raises(RuntimeError):
        s.send("go", timeout=5, on_progress=lambda t, r: None)


# -- 3. pi seats ---------------------------------------------------------------


def _pi_events(thinking: list[str], text: list[str], usage: dict | None = None) -> list[dict]:
    upd = lambda kind, delta: {  # noqa: E731
        "type": "message_update",
        "usage": usage or {},
        "assistantMessageEvent": {"type": kind, "delta": delta},
    }
    events = [{"type": "session"}, {"type": "agent_start"}]
    events += [upd("thinking_delta", t) for t in thinking]
    events += [upd("text_delta", t) for t in text]
    events.append(
        {
            "type": "turn_end",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "".join(thinking)},
                    {"type": "text", "text": "".join(text)},
                ],
            },
        }
    )
    return events


def test_pi_argv_has_no_tools_no_mcp_no_context_and_a_persistent_session(arena) -> None:
    s = PiSession({"model": "lobes/worker", "system_prompt": "same for all"}, "m-pi", "blue-1")
    argv = s._argv()
    for flag in ("--no-tools", "--no-mcp", "--no-context-files", "--no-prompt-templates"):
        assert flag in argv
    assert argv[argv.index("--mode") + 1] == "json"
    assert argv[argv.index("--session-id") + 1] == s.session_id
    assert "pi-sessions" in argv[argv.index("--session-dir") + 1]
    assert argv[argv.index("--system-prompt") + 1] == "same for all"
    again = PiSession({"model": "lobes/worker"}, "m-pi", "blue-1")
    assert again.session_id == s.session_id  # same seat resumes the same session


@pytest.mark.parametrize("flag", ["--tools", "-t", "--no-builtin-tools", "--mcp"])
def test_pi_refuses_tool_flags(flag) -> None:
    with pytest.raises(ValueError):
        PiSession({"model": "lobes/worker", "args": [flag, "bash"]}, "m", "blue-1")


def test_pi_send_captures_reasoning_usage_and_streams(arena, monkeypatch) -> None:
    usage = {"input": 1400, "output": 40, "reasoning": 30}
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        harness,
        "_stream_process",
        _feed(
            _pi_events(["Plan: ", "hold."], ['{"action": ', '{"action": "hold"}}'], usage),
            captured=captured,
        ),
    )
    progress: list[tuple[str, str]] = []
    s = PiSession({"model": "lobes/worker"}, "m-pi", "blue-1")
    reply = s.send("brief", timeout=5, on_progress=lambda t, r: progress.append((t, r)))
    assert json.loads(reply) == {"action": {"action": "hold"}}
    assert captured["prompt"] == "brief"  # prompt goes in on stdin
    assert Path(captured["cwd"]).is_dir()
    assert s.last_reasoning == "Plan: hold."
    assert s.last_usage == {"prompt_tokens": 1400, "completion_tokens": 40, "reasoning_tokens": 30}
    assert progress[1] == ("Plan: hold.", "") and progress[-1][1].endswith("}}")


def test_pi_empty_answer_or_failure_raises(arena, monkeypatch) -> None:
    monkeypatch.setattr(harness, "_stream_process", _feed(_pi_events(["x"], [])))
    with pytest.raises(RuntimeError):
        PiSession({"model": "lobes/worker"}, "m-pi", "blue-1").send("b", timeout=5)
    monkeypatch.setattr(harness, "_stream_process", _feed([], code=1))
    with pytest.raises(RuntimeError):
        PiSession({"model": "lobes/worker"}, "m-pi", "blue-1").send("b", timeout=5)


def test_pi_nemotron_preset_resolves_to_a_pi_seat_team() -> None:
    from league.presets import registry, resolve_preset

    config = resolve_preset(next(p for p in registry() if p.name == "pi-nemotron-vs-bot"))
    team = next(t for t in config["teams"] if t["driver"].get("transport") == "pi")
    assert team["driver"]["model"] == "lobes/worker"
    assert all(seat_settings(team["driver"], a)["tools"] is False for a in team["agents"])


# -- 2. seat settings --------------------------------------------------------


@pytest.mark.parametrize(
    ("spec", "agent", "tools", "network"),
    [
        ({"type": "bot"}, {}, False, False),
        ({"type": "bot-file", "strategy": "rusher"}, {}, False, False),
        ({"type": "resident", "transport": "colleague", "model": "glm"}, {}, False, False),
        ({"type": "resident", "transport": "pi", "model": "lobes/worker"}, {}, False, False),
        ({"type": "resident", "transport": "claude", "args": ["--tools", ""]}, {}, False, False),
        ({"type": "resident", "transport": "claude", "args": ["--tools="]}, {}, False, False),
        ({"type": "resident", "transport": "claude"}, {}, True, True),
        ({"type": "resident", "transport": "claude", "args": ["--tools", "Bash"]}, {}, True, True),
        ({"type": "command", "argv": ["x"]}, {}, True, True),
        ({"type": "command", "argv": ["x"], "tools": False, "network": False}, {}, False, False),
        ({"type": "command", "argv": ["x"], "tools": False}, {"tools": True}, True, True),
        ({"type": "resident", "transport": "colleague"}, {"network": True}, False, True),
        ({"type": "resident", "transport": "claude"}, {"tools": False}, True, True),
    ],
)
def test_seat_settings_fail_closed(spec, agent, tools, network) -> None:
    got = seat_settings(spec, agent)
    assert (got["tools"], got["network"]) == (tools, network)


def test_run_match_records_seats_and_match_show_reports_them(arena, monkeypatch, capsys) -> None:
    class _Hold:
        transport = "hold"

        def __init__(self, agent_id: str) -> None:
            self.session_id = f"h-{agent_id}"

        def send(self, prompt: str, *, timeout: float) -> str:
            return json.dumps({"action": {"action": "hold"}})

    monkeypatch.setitem(harness.SESSION_TRANSPORTS, "fake-hold", lambda s, m, a: _Hold(a))
    cfg = _config("m-seats", "fake-hold", live=False)
    run_match(cfg)
    seats = json.loads(Store().seats_path("m-seats").read_text())
    assert set(seats) == {"blue-1", "blue-2", "blue-3", "red-1", "red-2", "red-3"}
    assert seats["red-1"] == {
        "team_id": "red",
        "model": "bot:greedy",
        "tools": False,
        "network": False,
        "runtime": "bot",
    }
    assert seats["blue-1"]["tools"] is True  # an unknown transport fails closed
    capsys.readouterr()
    assert main(["match", "show", "m-seats", "--json"]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["seats"] == seats


def test_match_show_seats_is_empty_without_a_harness(arena, capsys) -> None:
    assert Store().read_seats("nope") == {}


# -- the real subprocess streamer --------------------------------------------


def test_stream_process_streams_lines_and_reads_stdin() -> None:
    import sys

    script = (
        "import sys, time\n"
        "data = sys.stdin.read()\n"
        "for i in range(3):\n"
        "    print(f'{i}:{len(data)}', flush=True)\n"
        "print('err', file=sys.stderr)\n"
    )
    lines: list[str] = []
    big = "x" * 300_000  # larger than one argv entry may be
    code, err = harness._stream_process([sys.executable, "-c", script], big, 30, lines.append)
    assert code == 0 and lines == ["0:300000", "1:300000", "2:300000"] and "err" in err


def test_stream_process_times_out_and_kills() -> None:
    import subprocess
    import sys

    with pytest.raises(subprocess.TimeoutExpired):
        harness._stream_process(
            [sys.executable, "-c", "import time; time.sleep(30)"], "", 0.5, lambda line: None
        )
