"""Orchestrator mode for real (cycle-3 plan task t6, spec c4/c6/h3/h5).

Criteria under test:

* the log records ``map_read=full`` for the master's team and the
  ``unit_comms`` flag per team; ``match show --json`` surfaces both
  (mirroring the ``driver_kinds`` fairness-axis pattern from cycle-2 t6);
* with comms OFF, a ground unit's briefing contains master messages only
  (teammate unit messages filtered out); with comms ON, teammate messages
  appear too — both tested;
* the master's briefing gets ground truth when its team's declared
  ``map_read`` is ``"full"`` under fog, while every ground unit's briefing
  stays fogged regardless.
"""

from __future__ import annotations

import json
import sys
import textwrap

import pytest

from league.cli import main
from league.harness import run_match
from league.store import Store


@pytest.fixture()
def arena(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


# -- acceptance 1: `match new --map-read/--unit-comms` recorded in the log --
# -- and echoed by `match show --json` (mirrors test_residency.py's pattern) -


def _register(team: str) -> list[str]:
    return [
        "team",
        "register",
        team,
        "--name",
        f"Team {team}",
        "--agent",
        f"{team}-1:m:scout",
        "--agent",
        f"{team}-2:m:harvester",
        "--agent",
        f"{team}-3:m:defender",
    ]


def test_match_new_records_map_read_and_unit_comms_via_cli(arena, capsys) -> None:
    assert main(_register("fable") + ["--apply"]) == 0
    assert main(_register("baseline") + ["--apply"]) == 0
    capsys.readouterr()

    assert (
        main(
            [
                "match",
                "new",
                "--scenario",
                "skirmish-1",
                "--team",
                "fable",
                "--team",
                "baseline",
                "--map-read",
                "fable:full",
                "--map-read",
                "baseline:fog",
                "--unit-comms",
                "fable:off",
                "--unit-comms",
                "baseline:on",
                "--id",
                "m-orch-cli",
                "--apply",
                "--json",
            ]
        )
        == 0
    )
    created = json.loads(capsys.readouterr().out)
    assert created["map_read"] == {"fable": "full", "baseline": "fog"}
    assert created["unit_comms"] == {"fable": False, "baseline": True}

    # Projection 1: the stored match log header.
    log = Store().load_match("m-orch-cli")
    assert log.map_read == {"fable": "full", "baseline": "fog"}
    assert log.unit_comms == {"fable": False, "baseline": True}

    # Projection 2: `league match show --json`.
    assert main(["match", "show", "m-orch-cli", "--json"]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["map_read"] == {"fable": "full", "baseline": "fog"}
    assert shown["unit_comms"] == {"fable": False, "baseline": True}
    # Declared metadata only — never engine state.
    assert "map_read" not in shown["state"]
    assert "unit_comms" not in shown["state"]


def test_match_new_map_read_and_unit_comms_are_optional(arena, capsys) -> None:
    """A match created without either flag simply has no recorded axes — the
    fields are metadata, not a requirement (same contract as --driver)."""
    assert main(_register("blue") + ["--apply"]) == 0
    assert main(_register("red") + ["--apply"]) == 0
    capsys.readouterr()
    assert (
        main(
            [
                "match",
                "new",
                "--scenario",
                "skirmish-1",
                "--team",
                "blue",
                "--team",
                "red",
                "--id",
                "m-orch-no-flags",
                "--apply",
                "--json",
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert main(["match", "show", "m-orch-no-flags", "--json"]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["map_read"] == {}
    assert shown["unit_comms"] == {}


def test_match_new_rejects_bad_map_read_and_unit_comms_flags(arena, capsys) -> None:
    assert main(_register("blue") + ["--apply"]) == 0
    capsys.readouterr()

    # Unknown team.
    rc = main(
        [
            "match",
            "new",
            "--scenario",
            "skirmish-1",
            "--team",
            "blue",
            "--map-read",
            "ghost:full",
            "--id",
            "m-bad-map-read-team",
            "--apply",
        ]
    )
    assert rc == 1
    assert "hint:" in capsys.readouterr().err

    # Unknown map-read kind.
    rc = main(
        [
            "match",
            "new",
            "--scenario",
            "skirmish-1",
            "--team",
            "blue",
            "--map-read",
            "blue:omniscient",
            "--id",
            "m-bad-map-read-kind",
            "--apply",
        ]
    )
    assert rc == 1
    assert "hint:" in capsys.readouterr().err

    # Bad format (no ':').
    rc = main(
        [
            "match",
            "new",
            "--scenario",
            "skirmish-1",
            "--team",
            "blue",
            "--map-read",
            "blue-full",
            "--id",
            "m-bad-map-read-format",
            "--apply",
        ]
    )
    assert rc == 1
    assert "hint:" in capsys.readouterr().err

    # Unknown team for --unit-comms.
    rc = main(
        [
            "match",
            "new",
            "--scenario",
            "skirmish-1",
            "--team",
            "blue",
            "--unit-comms",
            "ghost:off",
            "--id",
            "m-bad-comms-team",
            "--apply",
        ]
    )
    assert rc == 1
    assert "hint:" in capsys.readouterr().err

    # Unknown --unit-comms value.
    rc = main(
        [
            "match",
            "new",
            "--scenario",
            "skirmish-1",
            "--team",
            "blue",
            "--unit-comms",
            "blue:maybe",
            "--id",
            "m-bad-comms-value",
            "--apply",
        ]
    )
    assert rc == 1
    assert "hint:" in capsys.readouterr().err


# -- acceptance 2: comms off filters teammate messages from a seat's --------
# -- briefing (master messages still get through); comms on relays both -----

# Every ground seat: report the `from` list of "teammates already sent"
# messages it was shown BEFORE acting, then declare its own guidance message
# so the NEXT seat's report can prove (or disprove) the relay.
_GROUND_RELAY_AGENT = textwrap.dedent(r"""
    import json, re, sys
    prompt = sys.stdin.read()
    unit = re.search(r"You control ONLY unit (\S+)", prompt).group(1)
    agent = re.search(r"You are agent (\S+),", prompt).group(1)
    m = re.search(
        r"Messages your teammates already sent this turn:\n(.*?)\n\nCoordinate",
        prompt,
        re.S,
    )
    seen = json.loads(m.group(1)) if m else []
    senders = [x["from"] for x in seen]
    print(json.dumps({
        "action": {"unit_id": unit, "action": "hold"},
        "messages": [
            {"from": agent, "text": "seen:" + json.dumps(senders)},
            {"from": agent, "text": "hello from " + agent},
        ],
    }))
    """).strip()

_MASTER_GUIDE_AGENT = (
    "import sys, json; sys.stdin.read(); "
    "print(json.dumps({'messages': [{'text': 'fall back to cp-center'}]}))"
)


def _comms_config(match_id: str, *, unit_comms: bool) -> dict:
    return {
        "match": {"scenario": "skirmish-1", "mode": "competitive", "seed": 7, "id": match_id},
        "teams": [
            {
                "id": "blue",
                "name": "Blue Foundry",
                "unit_comms": unit_comms,
                "driver": {
                    "type": "command",
                    "per_seat": True,
                    "argv": [sys.executable, "-c", _GROUND_RELAY_AGENT],
                    "master": {
                        "argv": [sys.executable, "-c", _MASTER_GUIDE_AGENT],
                        "id": "blue-master",
                    },
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
        "max_rounds": 1,
    }


def _seat_seen_report(log, agent_id: str) -> list[str]:
    texts = [
        e.data["text"]
        for e in log.events
        if e.kind == "message_sent"
        and e.data.get("from") == agent_id
        and e.data["text"].startswith("seen:")
    ]
    assert texts, f"no seen: report logged from {agent_id}"
    return json.loads(texts[0][len("seen:") :])


def test_comms_off_filters_teammate_messages_master_still_reaches_units(arena, capsys) -> None:
    run_match(_comms_config("m-orch-comms-off", unit_comms=False))
    capsys.readouterr()

    log = Store().load_match("m-orch-comms-off")
    assert log.unit_comms == {"blue": False}
    # blue-1 (consulted first, right after the master) sees only the master.
    assert _seat_seen_report(log, "blue-1") == ["blue-master"]
    # blue-2 (consulted after blue-1) is master-mediated only: blue-1's own
    # guidance message never reaches it.
    assert _seat_seen_report(log, "blue-2") == ["blue-master"]

    # The master's own guidance really is on the log, attributed to it.
    master_texts = [
        e.data["text"]
        for e in log.events
        if e.kind == "message_sent" and e.data.get("from") == "blue-master"
    ]
    assert "fall back to cp-center" in master_texts
    # blue-1's guidance is still recorded (filtering only trims what a LATER
    # seat is shown, never what lands in the log).
    blue_1_texts = [
        e.data["text"]
        for e in log.events
        if e.kind == "message_sent" and e.data.get("from") == "blue-1"
    ]
    assert "hello from blue-1" in blue_1_texts


def test_comms_on_relays_teammate_messages_too(arena, capsys) -> None:
    run_match(_comms_config("m-orch-comms-on", unit_comms=True))
    capsys.readouterr()

    log = Store().load_match("m-orch-comms-on")
    assert log.unit_comms == {"blue": True}
    assert _seat_seen_report(log, "blue-1") == ["blue-master"]
    # blue-2 now sees BOTH the master and blue-1's two teammate messages
    # ("seen:..." plus its own guidance) — the unfiltered relay.
    assert _seat_seen_report(log, "blue-2") == ["blue-master", "blue-1", "blue-1"]


def test_no_master_and_comms_off_leaves_units_with_no_relay(arena, capsys) -> None:
    """An honest corner case, documented in league/harness.py: with no master
    configured, 'master-mediated only' means nobody relays anything."""
    config = _comms_config("m-orch-no-master", unit_comms=False)
    del config["teams"][0]["driver"]["master"]
    run_match(config)
    capsys.readouterr()

    log = Store().load_match("m-orch-no-master")
    assert _seat_seen_report(log, "blue-1") == []
    assert _seat_seen_report(log, "blue-2") == []


# -- the master's map-read capability under fog: "full" gets ground truth, --
# -- ground units stay fogged regardless (plan t6 DESIGN, spec c4/h3) -------

_MASTER_REPORT_AGENT = (
    "import sys, json; p = sys.stdin.read(); "
    "print(json.dumps({'messages': [{'text': 'FULL' if 'cp-east' in p else 'FOGGED'}]}))"
)

_GROUND_HOLD_AGENT = textwrap.dedent(r"""
    import json, re, sys
    prompt = sys.stdin.read()
    unit = re.search(r"You control ONLY unit (\S+)", prompt).group(1)
    saw = "cp-east" in prompt
    print(json.dumps({
        "action": {"unit_id": unit, "action": "hold"},
        "messages": [{"from": unit, "text": "SEEN-CP-EAST" if saw else "NOT-SEEN-CP-EAST"}],
    }))
    """).strip()


def _orchestrator_fog_config(match_id: str, *, map_read: str | None) -> dict:
    team: dict = {
        "id": "blue",
        "name": "Blue Foundry",
        "driver": {
            "type": "command",
            "per_seat": True,
            "argv": [sys.executable, "-c", _GROUND_HOLD_AGENT],
            "master": {
                "argv": [sys.executable, "-c", _MASTER_REPORT_AGENT],
                "id": "blue-master",
            },
        },
        "agents": [
            {"id": "blue-1", "model": "test:model", "role": "scout"},
            {"id": "blue-2", "model": "test:model", "role": "harvester"},
            {"id": "blue-3", "model": "test:model", "role": "defender"},
        ],
    }
    if map_read is not None:
        team["map_read"] = map_read
    return {
        "match": {"scenario": "skirmish-1", "mode": "competitive", "seed": 7, "id": match_id},
        "teams": [
            team,
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
        "max_rounds": 1,
        "fog": True,
    }


def _master_reports(log) -> list[str]:
    return [
        e.data["text"]
        for e in log.events
        if e.kind == "message_sent" and e.data.get("from") == "blue-master"
    ]


def _ground_reports(log) -> list[str]:
    # _fold_seat_reply attributes a seat's message to its AGENT id, never the
    # unit id the script itself declared as "from" — the harness's own
    # discipline (never trust a seat's self-reported sender).
    return [
        e.data["text"]
        for e in log.events
        if e.kind == "message_sent" and e.data.get("from") == "blue-1"
    ]


def test_master_gets_ground_truth_when_map_read_is_full_under_fog(arena, capsys) -> None:
    run_match(_orchestrator_fog_config("m-orch-full", map_read="full"))
    capsys.readouterr()

    log = Store().load_match("m-orch-full")
    assert log.map_read == {"blue": "full"}
    assert _master_reports(log) == ["FULL"]
    # Ground units stay fogged regardless of the master's declared capability
    # — cp-east (outside spawn vision on skirmish-1) is absent from their
    # briefing even though the master saw it.
    assert _ground_reports(log) == ["NOT-SEEN-CP-EAST"]


def test_master_stays_fogged_by_default_under_fog(arena, capsys) -> None:
    run_match(_orchestrator_fog_config("m-orch-default-fog", map_read=None))
    capsys.readouterr()

    log = Store().load_match("m-orch-default-fog")
    assert log.map_read == {}
    assert _master_reports(log) == ["FOGGED"]


# -- map_read also reaches the plain (non-per-seat) commander driver: one ---
# -- mind for the whole team, still honoring the declared capability --------

_COMMANDER_REPORT_AGENT = (
    "import sys, json; p = sys.stdin.read(); "
    "print(json.dumps({'actions': [], "
    "'messages': [{'from': 'blue-1', 'text': 'FULL' if 'cp-east' in p else 'FOGGED'}]}))"
)


def _commander_fog_config(match_id: str, *, map_read: str | None) -> dict:
    team: dict = {
        "id": "blue",
        "name": "Blue Foundry",
        "driver": {
            "type": "command",
            "argv": [sys.executable, "-c", _COMMANDER_REPORT_AGENT],
        },
        "agents": [
            {"id": "blue-1", "model": "test:model", "role": "scout"},
            {"id": "blue-2", "model": "test:model", "role": "harvester"},
            {"id": "blue-3", "model": "test:model", "role": "defender"},
        ],
    }
    if map_read is not None:
        team["map_read"] = map_read
    return {
        "match": {"scenario": "skirmish-1", "mode": "competitive", "seed": 7, "id": match_id},
        "teams": [
            team,
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
        "max_rounds": 1,
        "fog": True,
    }


def test_commander_driver_gets_ground_truth_when_map_read_is_full_under_fog(arena, capsys) -> None:
    run_match(_commander_fog_config("m-orch-commander-full", map_read="full"))
    capsys.readouterr()
    log = Store().load_match("m-orch-commander-full")
    assert log.map_read == {"blue": "full"}
    reports = [
        e.data["text"]
        for e in log.events
        if e.kind == "message_sent" and e.data.get("from") == "blue-1"
    ]
    assert reports == ["FULL"]


def test_commander_driver_stays_fogged_by_default_under_fog(arena, capsys) -> None:
    run_match(_commander_fog_config("m-orch-commander-fog", map_read=None))
    capsys.readouterr()
    log = Store().load_match("m-orch-commander-fog")
    assert log.map_read == {}
    reports = [
        e.data["text"]
        for e in log.events
        if e.kind == "message_sent" and e.data.get("from") == "blue-1"
    ]
    assert reports == ["FOGGED"]
