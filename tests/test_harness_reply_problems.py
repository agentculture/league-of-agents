"""A resident seat's reply is read as fully as the harness can.

The case that motivated it: a message object missing its closing brace made
the whole reply invalid JSON, the old extractor fell through to the inner
action object, and the order vanished with no rejection and no notice. If
code can recover a reply, losing it is a harness fault, not a model fault:
the action, the messages and the plan are each recovered, the repair is kept
in the audit record, and the seat is told only when no action could be read.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from league import harness
from league.harness import _RESIDENT_NOTE, _parse_seat_reply, run_match
from league.store import Store
from tests.test_harness_resident import _config, _fake_transport

BROKEN = """{
  "action": {"unit_id": "blue-u3", "action": "deliver"},
  "messages": [
    {"from": "blue-3", "text": "delivering",
    {"from": "blue-3", "text": "second \\"quoted\\""}
  ],
  "plan": "deliver then park"
}"""


@pytest.fixture
def arena(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_valid_reply_needs_no_repair() -> None:
    reply = 'Sure: {"action": {"action": "hold"}, "plan": "p"}'
    assert _parse_seat_reply(reply) == ({"action": {"action": "hold"}, "plan": "p"}, None, None)


def test_broken_reply_is_recovered_whole_and_the_seat_is_not_blamed() -> None:
    result, seat_note, repair = _parse_seat_reply(BROKEN)
    assert result["action"] == {"unit_id": "blue-u3", "action": "deliver"}
    assert result["plan"] == "deliver then park"
    assert [m["text"] for m in result["messages"]] == ["delivering", 'second "quoted"']
    assert seat_note is None
    assert "line 5" in repair and "recovered action, 2 message(s), plan" in repair


def test_flat_action_is_read() -> None:
    result, seat_note, repair = _parse_seat_reply('{"action": "move", "to": [1, 2], "plan": "p"}')
    assert result == {"action": {"action": "move", "to": [1, 2]}, "plan": "p"}
    assert seat_note is None and repair


def test_unreadable_reply_idles_and_the_seat_is_told() -> None:
    result, seat_note, _ = _parse_seat_reply("no json here")
    assert result == {} and "no JSON object" in seat_note
    result, seat_note, _ = _parse_seat_reply('{"action": {"action": "move", "to": [1,')
    assert "action" not in result and "no action could be read" in seat_note


def test_rule_is_public() -> None:
    assert "JSON slip" in _RESIDENT_NOTE


def _run_with_reply(monkeypatch, match_id: str, first_reply: str) -> list[str]:
    calls: list[dict[str, Any]] = []
    factory = _fake_transport(calls, {})

    class Scripted:
        def __init__(self, base):
            self._base, self.session_id, self.transport = base, base.session_id, "fake"
            self.sent = 0

        def send(self, prompt: str, *, timeout: float) -> str:
            self._base.send(prompt, timeout=timeout)
            self.sent += 1
            return first_reply if self.sent == 1 else json.dumps({"action": {"action": "hold"}})

    def scripted(spec, mid, agent_id):
        base = factory(spec, mid, agent_id)
        return Scripted(base) if agent_id == "blue-1" else base

    monkeypatch.setitem(harness.SESSION_TRANSPORTS, "fake", scripted)
    run_match(_config(match_id, max_rounds=2))
    return [c["prompt"] for c in calls if c["agent_id"] == "blue-1"]


def test_driver_applies_a_recovered_reply_silently(arena, monkeypatch, capsys) -> None:
    broken = BROKEN.replace('"deliver"', '"hold"')
    prompts = _run_with_reply(monkeypatch, "m-reply-1", broken)
    assert "seat blue-1: repaired invalid JSON" in capsys.readouterr().err
    log = Store().load_match("m-reply-1")
    assert any(
        e.kind == "action_declared" and e.data.get("unit_id") == "blue-u1" and e.turn == 1
        for e in log.events
    ), "the recovered action was applied on turn 1"
    assert any(e.kind == "plan_declared" for e in log.events)
    assert "About your previous reply" not in prompts[1]
    records = Path(".league/matches/m-reply-1/sessions/blue-1.jsonl").read_text().splitlines()
    assert "repaired invalid JSON" in json.loads(records[0])["reply_problem"]


def test_driver_tells_the_seat_when_nothing_could_be_read(arena, monkeypatch, capsys) -> None:
    prompts = _run_with_reply(monkeypatch, "m-reply-2", "I will hold.")
    capsys.readouterr()
    assert "About your previous reply: your reply contained no JSON object" in prompts[1]
    assert "About your previous reply" not in prompts[0]


# -- plain-string messages (the seat reply format since the GLM vs Opus match) --


def test_seat_prompt_asks_for_plain_string_messages() -> None:
    assert '"messages": ["<optional message to your team>"' in harness._SEAT_PROMPT
    assert '{{"from"' not in harness._SEAT_PROMPT.split("Coordinate through messages")[1]


def test_fold_reads_strings_and_the_old_object_form() -> None:
    combined: dict[str, Any] = {"actions": [], "messages": []}
    reply = {"messages": ["go north", {"from": "someone-else", "text": "old form"}, "", 7]}
    harness._fold_seat_reply(combined, reply, "blue-u1", "blue-1")
    assert combined["messages"] == [
        {"from": "blue-1", "text": "go north"},
        {"from": "blue-1", "text": "old form"},
    ]


@pytest.mark.parametrize(
    "broken",
    [
        '{"action": {"action": "hold"}, "messages": ["a \\"x\\"", "b",], "plan": "p"}',
        '{"action": {"action": "hold"}, "messages": ["a \\"x\\"" "b"], "plan": "p"}',
    ],
)
def test_broken_string_messages_are_recovered(broken: str) -> None:
    result, seat_note, repair = _parse_seat_reply(broken)
    assert result["messages"] == ['a "x"', "b"] and result["plan"] == "p"
    assert result["action"] == {"action": "hold"} and seat_note is None and repair


# -- legal move targets are described exactly ----------------------------------


def test_long_move_lists_state_the_exact_manhattan_rule() -> None:
    pos = [18, 13]
    moves = [
        [x, y] for x in range(15, 21) for y in range(10, 17) if 0 < abs(x - 18) + abs(y - 13) <= 3
    ]
    line = harness._format_move_targets(moves, pos)
    assert "|x-18| + |y-13| <= 3" in line and "x in [" not in line
    assert harness._format_move_targets(moves) == json.dumps(moves), "no position: list them all"
    assert harness._format_move_targets([[1, 1]], pos) == "[[1, 1]]"


# -- passive capture notes are not rejections; steal rules spell out targets ---


def test_passive_capture_note_is_not_reported_as_a_rejection() -> None:
    rows = [
        {"unit_id": "red-u1", "reason": "this role cannot capture control points", "passive": True},
        {"unit_id": "red-u2", "reason": "target beyond this role's move range"},
    ]
    text = harness._format_rejections(rows)
    rejections, notes = text.split("NOTES (not rejections)")
    assert "red-u2: target beyond" in rejections and "red-u1" not in rejections
    assert "red-u1 stands on a control point" in notes and "carried out" in notes
    only_note = harness._format_rejections(rows[:1])
    assert "REJECTIONS" not in only_note and "NOTES (not rejections)" in only_note


def test_thief_rules_explain_named_targets_and_failed_steals() -> None:
    assert "A named target must be" in harness._THIEF_RULES
    assert "the thief stays where" in harness._THIEF_RULES


# -- fog sightings keep their turn in the compact state -------------------------


def test_compact_state_keeps_when_a_remembered_fact_was_seen() -> None:
    state = {
        "turn": 23,
        "units": [
            {
                "id": "blue-u1",
                "team_id": "blue",
                "role": "scout",
                "pos": [9, 7],
                "carrying": 1,
                "alive": True,
            },
            {
                "id": "red-u2",
                "team_id": "red",
                "role": "harvester",
                "pos": [12, 10],
                "carrying": 3,
                "alive": True,
                "source": "seen",
                "turn": 12,
            },
            {
                "id": "red-u4",
                "team_id": "red",
                "role": "defender",
                "pos": [8, 6],
                "alive": True,
                "source": "told",
                "turn": 20,
            },
        ],
        "control_points": [
            {"id": "cp-2a", "pos": [8, 6], "owner": "red", "source": "seen", "turn": 23}
        ],
        "resource_nodes": [
            {"id": "rn-2a", "pos": [9, 7], "remaining": 1, "source": "seen", "turn": 23}
        ],
    }
    out = harness._compact_state(state)
    units = {u["id"]: u for u in out["units"]}
    assert "seen_turn" not in units["blue-u1"]
    assert units["red-u2"]["seen_turn"] == 12 and "told" not in units["red-u2"]
    assert units["red-u4"]["seen_turn"] == 20 and units["red-u4"]["told"] is True
    assert (
        out["control_points"][0]["seen_turn"] == 23 and out["resource_nodes"][0]["seen_turn"] == 23
    )
    assert "Reading the fog" in harness._FOG_RULES
