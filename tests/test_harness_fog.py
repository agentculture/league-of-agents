"""Fog-aware briefings (cycle-3 plan task t5, spec c5/h4).

Criteria under test:

* **the briefing boundary** — with fog on, a seat's briefing (the "Scenario:"
  block sent once, and every turn's "state"/legal-actions/delta) contains
  ONLY its team's vision + accumulated knowledge + teammate/master messages;
  an out-of-vision control point (and the mission that sits on it) is absent
  until a logged message names it, and then reaches EVERY seat on the team
  (team knowledge, not personal memory — league/engine/knowledge.py is
  team-scoped);
* ``match show --team <id> --fog --json`` is the public surface this is built
  on: additive (the plain response is untouched), team-scoped legal_actions/
  rejections, and a ``--fog`` without ``--team`` is a loud user error;
* the resident driver's delta becomes newly-seen/newly-told facts (the
  knowledge fold), not the raw event log, which would otherwise leak enemy
  moves regardless of vision;
* legal actions are unaffected by fog — a unit always knows its own;
* bots stay full-information under fog — the documented, temporary asymmetry
  (module docstring, ``league/harness.py``) — so a fogged match with a bot
  opponent still completes normally.
"""

from __future__ import annotations

import itertools
import json
import re
import sys
import textwrap
from typing import Any, Mapping

import pytest

import league.harness as harness
from league.cli import main
from league.harness import build_driver, run_match
from league.store import Store

# cp-east / ms-outpost sit at (9, 2) on skirmish-1 — outside both spawns'
# vision (proven in test_engine_vision / test_engine_knowledge), so a fresh
# team's knowledge starts empty of them.
_CP = "cp-east"
_MISSION_ON_CP = "ms-outpost"
_UNTOUCHED_CP = "cp-center"  # never mentioned; must stay unknown the whole match


@pytest.fixture()
def arena(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _register(team: str, model: str = "test:model") -> list[str]:
    return [
        "team",
        "register",
        team,
        "--name",
        f"Team {team}",
        "--agent",
        f"{team}-1:{model}:scout",
        "--agent",
        f"{team}-2:{model}:harvester",
        "--agent",
        f"{team}-3:{model}:defender",
    ]


def _new_match(match_id: str) -> list[str]:
    return [
        "match",
        "new",
        "--scenario",
        "skirmish-1",
        "--team",
        "blue",
        "--team",
        "red",
        "--seed",
        "7",
        "--id",
        match_id,
        "--apply",
    ]


# -- acceptance 1: an out-of-vision objective reaches the briefing ONLY -----
# -- after a logged message names it -----------------------------------------

# A single team-level commander (not per-seat, so there is no intra-turn
# seat-to-seat message relay to confound the signal): every turn it reports
# whether ITS OWN incoming prompt already mentions cp-east, then always
# names it in a message. Turn 1's report reflects the briefing built BEFORE
# that message exists anywhere; turn 2's reflects the briefing built AFTER
# it was logged and folded into the team's knowledge.
_REPORT_THEN_NAME_CP = textwrap.dedent(r"""
    import json, sys
    prompt = sys.stdin.read()
    saw = "cp-east" in prompt
    print(json.dumps({
        "actions": [],
        "messages": [
            {"from": "blue-1", "text": "SEEN-CP-EAST" if saw else "NOT-SEEN-CP-EAST"},
            {"from": "blue-1", "text": "push toward cp-east now"},
        ],
    }))
    """).strip()


def _fog_config(match_id: str, *, fog: bool) -> dict:
    return {
        "match": {"scenario": "skirmish-1", "mode": "competitive", "seed": 7, "id": match_id},
        "teams": [
            {
                "id": "blue",
                "name": "Blue Foundry",
                "driver": {
                    "type": "command",
                    "argv": [sys.executable, "-c", _REPORT_THEN_NAME_CP],
                },
                "agents": [
                    {"id": "blue-1", "model": "test:model", "role": "scout"},
                    {"id": "blue-2", "model": "test:model", "role": "harvester"},
                    {"id": "blue-3", "model": "test:model", "role": "defender"},
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
        "max_rounds": 2,
        "fog": fog,
    }


def _cp_reports(log) -> list[str]:
    return [
        e.data["text"]
        for e in log.events
        if e.kind == "message_sent"
        and e.data.get("from") == "blue-1"
        and e.data["text"].endswith("CP-EAST")
    ]


def test_out_of_vision_objective_reaches_briefing_only_after_a_message_names_it(
    arena, capsys
) -> None:
    run_match(_fog_config("m-fog-boundary", fog=True))
    capsys.readouterr()

    log = Store().load_match("m-fog-boundary")
    reports = _cp_reports(log)
    assert reports == ["NOT-SEEN-CP-EAST", "SEEN-CP-EAST"], (
        "cp-east (an out-of-vision control point, never within either spawn's "
        "vision on skirmish-1) must be absent from turn 1's briefing — built "
        "before anyone named it — and present in turn 2's, built after the "
        "team's own turn-1 message named it and it was folded into knowledge"
    )

    # The message that did it really is on the log, turn 1, named verbatim.
    named = [
        e.data["text"]
        for e in log.events
        if e.kind == "message_sent" and e.data.get("from") == "blue-1" and e.turn == 1
    ]
    assert "push toward cp-east now" in named

    # Without fog, the SAME script would see the full board from turn 1 (the
    # scenario block alone lists every control point) — the negative control
    # that proves turn 1's "NOT-SEEN" above is fog's doing, not the script's.
    run_match(_fog_config("m-fog-boundary-off", fog=False))
    capsys.readouterr()
    off_log = Store().load_match("m-fog-boundary-off")
    assert _cp_reports(off_log)[0] == "SEEN-CP-EAST"

    # red never heard blue's message (messages are a team channel) and its
    # own units never went east: cp-east must never enter red's knowledge.
    assert main(["match", "show", "m-fog-boundary", "--team", "red", "--fog", "--json"]) == 0
    red_view = json.loads(capsys.readouterr().out)
    assert _CP not in {c["id"] for c in red_view["state"]["control_points"]}


# -- a per-seat team also composes with fog, including intra-turn relay -----
# -- (a teammate who never personally saw it learns it from a message) -----

_REPORT_CP_VISIBILITY = textwrap.dedent(r"""
    import json, re, sys
    prompt = sys.stdin.read()
    unit = re.search(r"You control ONLY unit (\S+)", prompt).group(1)
    saw = "cp-east" in prompt
    messages = [{"from": unit, "text": "SEEN-CP-EAST" if saw else "NOT-SEEN-CP-EAST"}]
    if unit == "blue-u1":
        messages.append({"from": unit, "text": "push toward cp-east now"})
    print(json.dumps({
        "action": {"unit_id": unit, "action": "hold"},
        "messages": messages,
    }))
    """).strip()


def _per_seat_fog_config(match_id: str) -> dict:
    return {
        "match": {"scenario": "skirmish-1", "mode": "competitive", "seed": 7, "id": match_id},
        "teams": [
            {
                "id": "blue",
                "name": "Blue Foundry",
                "driver": {
                    "type": "command",
                    "per_seat": True,
                    "argv": [sys.executable, "-c", _REPORT_CP_VISIBILITY],
                },
                "agents": [
                    {"id": "blue-1", "model": "test:model", "role": "scout"},
                    {"id": "blue-2", "model": "test:model", "role": "harvester"},
                    {"id": "blue-3", "model": "test:model", "role": "defender"},
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
        "max_rounds": 2,
        "fog": True,
    }


def _seat_cp_reports(log, agent_id: str) -> list[str]:
    return [
        e.data["text"]
        for e in log.events
        if e.kind == "message_sent"
        and e.data.get("from") == agent_id
        and e.data["text"].endswith("CP-EAST")
    ]


def test_per_seat_team_shares_one_teams_knowledge_not_personal_memory(arena, capsys) -> None:
    run_match(_per_seat_fog_config("m-fog-per-seat"))
    capsys.readouterr()
    log = Store().load_match("m-fog-per-seat")

    # blue-1 (the scout, consulted first each turn) reports what its own
    # briefing said BEFORE it has named anything this turn: not seen on
    # turn 1, seen on turn 2 (from the team's committed knowledge).
    assert _seat_cp_reports(log, "blue-1") == ["NOT-SEEN-CP-EAST", "SEEN-CP-EAST"]

    # blue-2 and blue-3 (harvester/defender) never go anywhere near cp-east
    # (9, 2) — they never personally see it. But they are consulted AFTER
    # blue-1 within the SAME turn, so blue-1's turn-1 message reaches them
    # immediately via the in-turn relay — proving messages are a real
    # channel, not just a knowledge-fold implementation detail — and by
    # turn 2 they see it from the team's knowledge too, same as blue-1.
    assert _seat_cp_reports(log, "blue-2") == ["SEEN-CP-EAST", "SEEN-CP-EAST"]
    assert _seat_cp_reports(log, "blue-3") == ["SEEN-CP-EAST", "SEEN-CP-EAST"]


def test_untold_control_point_stays_absent_the_whole_match(arena, capsys) -> None:
    run_match(_fog_config("m-fog-untouched", fog=True))
    capsys.readouterr()

    assert main(["match", "show", "m-fog-untouched", "--team", "blue", "--fog", "--json"]) == 0
    shown = json.loads(capsys.readouterr().out)
    cp_ids = {c["id"] for c in shown["state"]["control_points"]}
    assert _UNTOUCHED_CP not in cp_ids, "a control point nobody saw or named must stay unknown"


# -- the public surface: match show --team --fog --json --------------------


def test_fog_view_hides_unseen_furniture_and_enemy_units(arena, capsys) -> None:
    assert main(_register("blue") + ["--apply"]) == 0
    assert main(_register("red") + ["--apply"]) == 0
    capsys.readouterr()
    assert main(_new_match("m-fog-cli-1")) == 0
    capsys.readouterr()

    assert main(["match", "show", "m-fog-cli-1", "--team", "blue", "--fog", "--json"]) == 0
    shown = json.loads(capsys.readouterr().out)

    state = shown["state"]
    assert state["control_points"] == []
    assert state["missions"] == []
    assert state["resource_nodes"] == []
    # Own roster in full; no enemy unit at all (nothing of red's is visible
    # from blue's spawn on skirmish-1, and red is never "own").
    assert {u["id"] for u in state["units"]} == {"blue-u1", "blue-u2", "blue-u3"}
    for unit in state["units"]:
        assert unit["agent_id"], "a team's own units are always known in full"
    # Own economy known, the opponent's is not ours to report on.
    teams_by_id = {t["id"]: t for t in state["teams"]}
    assert teams_by_id["blue"]["resources"] == 0
    assert teams_by_id["red"]["resources"] is None
    assert "knowledge" in shown and shown["knowledge"]["team_id"] == "blue"


def test_fog_view_reveals_a_mission_once_its_control_point_is_told(arena, capsys) -> None:
    assert main(_register("blue") + ["--apply"]) == 0
    assert main(_register("red") + ["--apply"]) == 0
    capsys.readouterr()
    assert main(_new_match("m-fog-cli-2")) == 0
    capsys.readouterr()

    assert (
        main(
            [
                "match",
                "act",
                "m-fog-cli-2",
                "--team",
                "blue",
                "--message",
                f"blue-1:scout toward {_CP} soon",
                "--apply",
            ]
        )
        == 0
    )
    assert main(["match", "act", "m-fog-cli-2", "--team", "red", "--apply"]) == 0
    capsys.readouterr()

    assert main(["match", "show", "m-fog-cli-2", "--team", "blue", "--fog", "--json"]) == 0
    shown = json.loads(capsys.readouterr().out)
    state = shown["state"]

    cps = {c["id"]: c for c in state["control_points"]}
    assert _CP in cps and cps[_CP]["owner"] is None  # told-only: owner unknown
    missions = {m["id"] for m in state["missions"]}
    assert _MISSION_ON_CP in missions, "a mission on a now-known point is discoverable too"
    assert _UNTOUCHED_CP not in cps


def test_fog_requires_team(arena, capsys) -> None:
    assert main(_register("blue") + ["--apply"]) == 0
    assert main(_register("red") + ["--apply"]) == 0
    capsys.readouterr()
    assert main(_new_match("m-fog-cli-3")) == 0
    capsys.readouterr()

    rc = main(["match", "show", "m-fog-cli-3", "--fog", "--json"])
    assert rc != 0
    err = capsys.readouterr().err
    assert "--fog requires --team" in err


def test_plain_show_is_untouched_by_the_new_flags(arena, capsys) -> None:
    """Additive: the default (no --team/--fog) response keeps the full board."""
    assert main(_register("blue") + ["--apply"]) == 0
    assert main(_register("red") + ["--apply"]) == 0
    capsys.readouterr()
    assert main(_new_match("m-fog-cli-4")) == 0
    capsys.readouterr()

    assert main(["match", "show", "m-fog-cli-4", "--json"]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert "knowledge" not in shown
    cp_ids = {c["id"] for c in shown["state"]["control_points"]}
    assert {"cp-center", "cp-west", "cp-east"} <= cp_ids, "the plain view keeps the whole board"


# -- legal actions are unaffected by fog: a unit always knows its own moves --


def test_fog_legal_actions_are_scoped_but_present(arena, capsys) -> None:
    assert main(_register("blue") + ["--apply"]) == 0
    assert main(_register("red") + ["--apply"]) == 0
    capsys.readouterr()
    assert main(_new_match("m-fog-legal")) == 0
    capsys.readouterr()

    assert main(["match", "show", "m-fog-legal", "--team", "blue", "--fog", "--json"]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert set(shown["legal_actions"]) == {"blue-u1", "blue-u2", "blue-u3"}
    assert shown["legal_actions"]["blue-u1"]["move"], "a unit always knows its own legal moves"


# -- the commander (non-per-seat) briefing also gets the fogged view --------


_ECHO_STATE_AGENT = (
    "import sys, json; p = sys.stdin.read(); "
    "print(json.dumps({'actions': [], 'messages': [{'from': 'x', 'text': p}]}))"
)


def _scenario_block(prompt: str) -> str:
    """Just the "Scenario: {...}" line out of a _PROMPT/_SEAT_PROMPT render —
    isolates the once-per-match rules block from the per-turn state block
    (which legitimately carries its own, possibly-empty, "control_points"
    etc. keys) so the two are never confused by a bare substring check."""
    return prompt.split("\n\nLegal actions", 1)[0].split("\n\nCurrent match state", 1)[0]


# Deliberately no control_points/missions/resource_nodes keys in this dummy
# "state" — this test only cares about the once-per-match SCENARIO block.
_BARE_STATE = {"match_id": "", "units": [], "teams": []}


def test_commander_scenario_block_drops_furniture_under_fog(arena, capsys) -> None:
    assert main(["arena", "show", "skirmish-1", "--json"]) == 0
    scenario = json.loads(capsys.readouterr().out)

    driver = build_driver(
        {"type": "command", "argv": [sys.executable, "-c", _ECHO_STATE_AGENT]},
        scenario,
        fog=True,
    )
    orders = driver(_BARE_STATE, "blue", 1, {})
    scenario_block = _scenario_block(orders["messages"][0]["text"])
    assert '"control_points"' not in scenario_block
    assert '"missions"' not in scenario_block
    assert '"resource_nodes"' not in scenario_block
    assert "fog_of_war" in scenario_block


def test_commander_scenario_block_keeps_furniture_without_fog(arena, capsys) -> None:
    assert main(["arena", "show", "skirmish-1", "--json"]) == 0
    scenario = json.loads(capsys.readouterr().out)

    driver = build_driver(
        {"type": "command", "argv": [sys.executable, "-c", _ECHO_STATE_AGENT]}, scenario
    )
    orders = driver(_BARE_STATE, "blue", 1, {})
    scenario_block = _scenario_block(orders["messages"][0]["text"])
    assert '"control_points"' in scenario_block


# -- bots stay full-information under fog: a fogged match with a bot ---------
# -- opponent still completes normally (documented, temporary asymmetry) ----


def test_bot_vs_bot_match_completes_normally_under_fog(arena, capsys) -> None:
    config = {
        "match": {"scenario": "skirmish-1", "mode": "competitive", "seed": 7, "id": "m-fog-bots"},
        "teams": [
            {
                "id": "blue",
                "name": "Blue Foundry",
                "driver": {"type": "bot"},
                "agents": [
                    {"id": "blue-1", "model": "bot:greedy", "role": "scout"},
                    {"id": "blue-2", "model": "bot:greedy", "role": "harvester"},
                    {"id": "blue-3", "model": "bot:greedy", "role": "defender"},
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
        "max_rounds": 6,
        "fog": True,
    }
    result = run_match(config)
    capsys.readouterr()
    assert result["turns_played"] == 6
    assert result["status"] == "active"


# -- the resident driver's delta becomes newly-seen/newly-told facts, ------
# -- never the raw event log (which would leak enemy moves regardless of ---
# -- vision) ------------------------------------------------------------


class _FakeSession:
    """Mirrors tests/test_harness_resident.py's fake — a scripted seat mind,
    no live model endpoint, ever."""

    def __init__(
        self,
        agent_id: str,
        serial: int,
        calls: list[dict[str, Any]],
        replies: list[dict[str, Any]],
    ) -> None:
        self.session_id = f"fake-{agent_id}-{serial}"
        self.transport = "fake"
        self._agent_id = agent_id
        self._replies = replies
        self._calls = calls

    def send(self, prompt: str, *, timeout: float) -> str:
        self._calls.append({"agent_id": self._agent_id, "prompt": prompt})
        reply = self._replies.pop(0) if self._replies else {"action": {"action": "hold"}}
        return json.dumps(reply)


def _fake_transport(calls: list[dict[str, Any]], scripts: Mapping[str, list[dict[str, Any]]]):
    serial = itertools.count(1)

    def factory(spec: Mapping[str, Any], match_id: str, agent_id: str) -> _FakeSession:
        return _FakeSession(agent_id, next(serial), calls, list(scripts.get(agent_id, [])))

    return factory


def _seat_prompts(calls: list[dict[str, Any]], agent_id: str) -> list[str]:
    return [c["prompt"] for c in calls if c["agent_id"] == agent_id]


def _delta_payload(prompt: str) -> Any:
    match = re.search(r"New events since your last turn \(JSON\):\n(.*)\n", prompt)
    assert match, "delta prompt missing its events section"
    return json.loads(match.group(1))


def test_resident_delta_is_a_knowledge_fold_not_the_raw_event_log(arena, capsys) -> None:
    calls: list[dict[str, Any]] = []
    scripts = {
        # blue-1 (scout) names cp-east on turn 1, then goes quiet.
        "blue-1": [
            {"action": {"action": "hold"}, "messages": [{"from": "blue-1", "text": "cp-east ho"}]},
            {"action": {"action": "hold"}},
        ],
    }
    monkeypatch_transport = _fake_transport(calls, scripts)
    harness.SESSION_TRANSPORTS["fake"] = monkeypatch_transport
    try:
        config = {
            "match": {
                "scenario": "skirmish-1",
                "mode": "competitive",
                "seed": 7,
                "id": "m-fog-resident",
            },
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
            "max_rounds": 3,
            "fog": True,
        }
        run_match(config)
    finally:
        del harness.SESSION_TRANSPORTS["fake"]
    capsys.readouterr()

    prompts = _seat_prompts(calls, "blue-1")
    assert len(prompts) == 3  # turn 1 full briefing + 2 deltas

    turn_2_delta = _delta_payload(prompts[1])
    assert set(turn_2_delta) == {"units", "resource_nodes", "control_points"}, (
        "the fog delta is the knowledge fold's shape, never a raw list of "
        "engine events (which would leak enemy moves regardless of vision)"
    )
    assert any(
        c["id"] == "cp-east" for c in turn_2_delta["control_points"]
    ), "cp-east must show up as NEWLY known the turn right after it was named"

    turn_3_delta = _delta_payload(prompts[2])
    assert turn_3_delta["control_points"] == [], (
        "already-known facts must not be re-announced turn after turn — "
        "the delta is what CHANGED, not the whole knowledge frame again"
    )

    # A teammate who never went near cp-east and never got the message this
    # turn (blue-2/blue-3 have no script, so they just idle/hold with no
    # message) still has cp-east in ITS delta the turn after — team
    # knowledge, not personal memory.
    blue_2_turn_2_delta = _delta_payload(_seat_prompts(calls, "blue-2")[1])
    assert any(c["id"] == "cp-east" for c in blue_2_turn_2_delta["control_points"])
