"""Harness rejection feedback + legal-actions citation (plan task t2).

Criteria under test (spec c8/h5):

* a seat whose order is rejected sees the engine's own rejection reason,
  verbatim, in its own NEXT turn's briefing — not the whole match, not other
  seats'. Without this a weak model just repeats the same illegal move for
  the whole match (19 of 53 orders in the season-0 coordination playtest);
* commander AND per-seat briefings both cite the `legal_actions` surface
  (league/engine/legal.py, exposed by `match show --json` — task t1) so
  legality is checkable *before* declaring, not just learned after rejection.
"""

from __future__ import annotations

import json
import sys
import textwrap

import pytest

from league.cli import main
from league.harness import build_driver, run_match
from league.store import Store

# The exact reason tick.py emits for a beyond-move-range target — the
# season-0 playtest's single biggest miss (10 of 19 rejected orders).
_REASON = "target beyond this role's move range"

_ECHO_PROMPT_AGENT = (
    "import sys, json; p = sys.stdin.read(); "
    "print(json.dumps({'actions': [], 'messages': [{'from': 'x', 'text': p}]}))"
)


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


# -- criterion 1: rejection feedback reaches the SAME seat's next briefing --

# blue-u1 is the scout (move=3, spawns at (0, 0) on skirmish-1). This script
# always declares the same out-of-range move for its own unit and reports,
# via a team message, whether ITS OWN prompt already quotes the reason the
# engine will reject that exact move with.
_REJECT_SCOUT_THEN_REPORT = textwrap.dedent(r"""
    import json, re, sys
    prompt = sys.stdin.read()
    unit = re.search(r"You control ONLY unit (\S+)", prompt).group(1)
    reason = "target beyond this role's move range"
    saw = reason in prompt
    if unit == "blue-u1":
        action = {"unit_id": unit, "action": "move", "to": [4, 0]}
    else:
        action = {"unit_id": unit, "action": "hold"}
    print(json.dumps({
        "action": action,
        "messages": [{"from": unit, "text": "SEEN" if saw else "NOT-SEEN"}],
    }))
    """).strip()


def test_seat_next_turn_prompt_cites_own_rejection_reason_verbatim(arena, capsys) -> None:
    team_blue = {
        "id": "blue",
        "name": "Blue Foundry",
        "driver": {
            "type": "command",
            "per_seat": True,
            "argv": [sys.executable, "-c", _REJECT_SCOUT_THEN_REPORT],
        },
        "agents": [
            {"id": "blue-1", "model": "test:reject", "role": "scout"},
            {"id": "blue-2", "model": "test:reject", "role": "harvester"},
            {"id": "blue-3", "model": "test:reject", "role": "defender"},
        ],
    }
    team_red = {
        "id": "red",
        "name": "Red Relay",
        "driver": {"type": "bot"},
        "agents": [
            {"id": "red-1", "model": "bot:greedy", "role": "scout"},
            {"id": "red-2", "model": "bot:greedy", "role": "harvester"},
            {"id": "red-3", "model": "bot:greedy", "role": "defender"},
        ],
    }
    config = {
        "match": {
            "scenario": "skirmish-1",
            "mode": "competitive",
            "seed": 7,
            "id": "m-reject-fb",
        },
        "teams": [team_blue, team_red],
        "max_rounds": 2,
    }
    run_match(config)
    capsys.readouterr()

    log = Store().load_match("m-reject-fb")

    # Turn 1: nothing to report yet. Turn 2: the SAME seat's prompt quotes
    # the engine's own reason for the mistake it made on turn 1 — verbatim.
    seat_reports = [
        e.data["text"]
        for e in log.events
        if e.kind == "message_sent" and e.data.get("from") == "blue-1"
    ]
    assert seat_reports == ["NOT-SEEN", "SEEN"]

    rejections = [
        e.data
        for e in log.events
        if e.kind == "action_rejected" and e.data.get("unit_id") == "blue-u1"
    ]
    assert rejections
    assert rejections[0]["reason"] == _REASON


def test_commander_prompt_cites_teams_rejection_reason_verbatim(arena, capsys) -> None:
    assert main(_register("blue") + ["--apply"]) == 0
    assert main(_register("red") + ["--apply"]) == 0
    capsys.readouterr()
    assert main(_new_match("m-reject-cmd")) == 0
    capsys.readouterr()

    # Stage the exact out-of-range mistake for blue-u1; red does nothing.
    assert (
        main(
            [
                "match",
                "act",
                "m-reject-cmd",
                "--team",
                "blue",
                "--action",
                "blue-u1:move:4,0",
                "--apply",
            ]
        )
        == 0
    )
    assert main(["match", "act", "m-reject-cmd", "--team", "red", "--apply"]) == 0
    capsys.readouterr()

    assert main(["arena", "show", "skirmish-1", "--json"]) == 0
    scenario = json.loads(capsys.readouterr().out)
    assert main(["match", "show", "m-reject-cmd", "--json"]) == 0
    shown = json.loads(capsys.readouterr().out)

    assert shown["last_turn_rejections"] == [
        {"team_id": "blue", "unit_id": "blue-u1", "reason": _REASON}
    ]

    context = {
        "legal_actions": shown["legal_actions"],
        "rejections": shown["last_turn_rejections"],
    }
    driver = build_driver(
        {"type": "command", "argv": [sys.executable, "-c", _ECHO_PROMPT_AGENT]}, scenario
    )
    orders = driver(shown["state"], "blue", 2, context)
    prompt = orders["messages"][0]["text"]

    assert "REJECTIONS from your last turn" in prompt
    assert f"blue-u1: {_REASON}" in prompt


# -- criterion 2: briefings cite the legal_actions surface -------------------


def test_commander_prompt_cites_legal_actions_surface(arena, capsys) -> None:
    assert main(_register("blue") + ["--apply"]) == 0
    assert main(_register("red") + ["--apply"]) == 0
    capsys.readouterr()
    assert main(_new_match("m-legal-cmd")) == 0
    capsys.readouterr()

    assert main(["arena", "show", "skirmish-1", "--json"]) == 0
    scenario = json.loads(capsys.readouterr().out)
    assert main(["match", "show", "m-legal-cmd", "--json"]) == 0
    shown = json.loads(capsys.readouterr().out)
    context = {
        "legal_actions": shown["legal_actions"],
        "rejections": shown["last_turn_rejections"],
    }

    driver = build_driver(
        {"type": "command", "argv": [sys.executable, "-c", _ECHO_PROMPT_AGENT]}, scenario
    )
    orders = driver(shown["state"], "blue", 1, context)
    prompt = orders["messages"][0]["text"]

    assert "Legal actions right now:" in prompt
    # blue-u1 (scout, move=3, at (0, 0)) has 9 in-range cells — over the
    # 8-cell threshold, so it's summarized (count + bounds), not listed raw,
    # and the beyond-range mistake never appears as if it were legal.
    assert "blue-u1: move to 9 cells, x in [0, 3], y in [0, 3]; gather: no; deliver: no" in prompt
    assert "[4, 0]" not in prompt.split("Legal actions right now:")[1].split("\n\n")[0]
    # blue-u2 (harvester, move=2) has few enough targets to list in full.
    assert "blue-u2: move to [[0, 0], [0, 1]" in prompt


def test_per_seat_prompt_cites_only_its_own_units_legal_actions(arena, capsys) -> None:
    assert main(_register("blue") + ["--apply"]) == 0
    assert main(_register("red") + ["--apply"]) == 0
    capsys.readouterr()
    assert main(_new_match("m-legal-seat")) == 0
    capsys.readouterr()

    assert main(["arena", "show", "skirmish-1", "--json"]) == 0
    scenario = json.loads(capsys.readouterr().out)
    assert main(["match", "show", "m-legal-seat", "--json"]) == 0
    shown = json.loads(capsys.readouterr().out)
    context = {
        "legal_actions": shown["legal_actions"],
        "rejections": shown["last_turn_rejections"],
    }

    agents = [
        {"id": "blue-1", "model": "m", "role": "scout"},
        {"id": "blue-2", "model": "m", "role": "harvester"},
        {"id": "blue-3", "model": "m", "role": "defender"},
    ]
    driver = build_driver(
        {"type": "command", "per_seat": True, "argv": [sys.executable, "-c", _ECHO_PROMPT_AGENT]},
        scenario,
        agents,
    )
    orders = driver(shown["state"], "blue", 1, context)
    texts = [m["text"] for m in orders["messages"]]

    u1_prompt = next(t for t in texts if "You control ONLY unit blue-u1" in t)
    assert "blue-u1: move to 9 cells, x in [0, 3], y in [0, 3]" in u1_prompt
    # Scoped to its own unit only — no other seat's legal-actions line leaks in.
    assert "blue-u2:" not in u1_prompt
    assert "blue-u3:" not in u1_prompt
