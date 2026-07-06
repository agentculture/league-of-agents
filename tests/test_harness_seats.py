"""Harness per-seat and solo modes (wave-5 enablers for playtests t13/t14).

* per-seat: one independent mind per roster seat, each commanding only its own
  unit, coordinating through messages that later seats can read;
* solo: the handicap for the coordination-necessity playtest — one action per
  turn, enforced by the harness rather than trusted to the prompt.
"""

from __future__ import annotations

import sys
import textwrap

import pytest

from league.harness import build_driver

SCENARIO = {
    "roles": {"scout": {"move": 3, "carry": 1}},
    "grid": {"width": 12, "height": 10},
    "capture_hold_turns": 2,
    "turn_limit": 30,
}

STATE = {
    "units": [
        {
            "id": "blue-u1",
            "agent_id": "blue-1",
            "team_id": "blue",
            "role": "scout",
            "pos": [0, 0],
            "carrying": 0,
            "alive": True,
        },
        {
            "id": "blue-u2",
            "agent_id": "blue-2",
            "team_id": "blue",
            "role": "scout",
            "pos": [1, 0],
            "carrying": 0,
            "alive": True,
        },
    ],
    "missions": [],
    "resource_nodes": [],
    "control_points": [],
}

# A seat agent that parses its unit id out of the prompt and reports whether it
# could see its teammate's earlier message — coordination via the harness relay.
SEAT_AGENT = textwrap.dedent("""
    import json, re, sys
    prompt = sys.stdin.read()
    unit = re.search(r"you control only unit (\\S+)", prompt, re.I).group(1)
    agent = re.search(r"You are agent (\\S+),", prompt).group(1)
    saw = "relay-check" in prompt
    print(json.dumps({
        "action": {"unit_id": "spoofed-unit", "action": "hold"},
        "messages": [{"from": agent, "text": "relay-check" if not saw else "ack"}],
    }))
    """).strip()

SOLO_AGENT = (
    "import sys, json; sys.stdin.read(); "
    "print(json.dumps({'actions': ["
    "{'unit_id': 'blue-u1', 'action': 'hold'},"
    "{'unit_id': 'blue-u2', 'action': 'hold'},"
    "{'unit_id': 'blue-u3', 'action': 'hold'}]}))"
)


def test_per_seat_minds_coordinate_via_messages() -> None:
    agents = [
        {"id": "blue-1", "model": "test", "role": "scout"},
        {"id": "blue-2", "model": "test", "role": "scout"},
    ]
    driver = build_driver(
        {"type": "command", "per_seat": True, "argv": [sys.executable, "-c", SEAT_AGENT]},
        SCENARIO,
        agents,
    )
    orders = driver(STATE, "blue", 1)
    # Each seat commands exactly its own unit — spoofing is overwritten.
    assert [a["unit_id"] for a in orders["actions"]] == ["blue-u1", "blue-u2"]
    # The second seat saw the first seat's message (the relay works).
    texts = [m["text"] for m in orders["messages"]]
    assert texts == ["relay-check", "ack"]


def test_solo_handicap_is_enforced_not_asked() -> None:
    driver = build_driver(
        {"type": "command", "solo": True, "argv": [sys.executable, "-c", SOLO_AGENT]},
        SCENARIO,
    )
    orders = driver(STATE, "blue", 1)
    assert len(orders["actions"]) == 1


def test_per_seat_requires_command_type() -> None:
    with pytest.raises(ValueError):
        build_driver({"type": "bot", "per_seat": True, "argv": []}, SCENARIO, [])
