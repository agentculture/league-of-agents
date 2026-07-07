"""CLI wiring for the legal-actions surface (plan task t1).

Criteria under test:

* ``league match show --json`` contains ``legal_actions`` for every living
  unit, derived from state+scenario only.
* A beyond-move-range move target — the exact mistake that burned 19 of 53
  orders in the season-0 coordination playtest — is absent from a scout's
  reported legal move targets.
"""

from __future__ import annotations

import json

import pytest

from league.cli import main


@pytest.fixture()
def arena(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _register(team: str, model: str) -> list[str]:
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


def test_match_show_json_includes_legal_actions_for_every_living_unit(arena, capsys) -> None:
    assert main(_register("blue", "claude-sonnet-5") + ["--apply"]) == 0
    assert main(_register("red", "colleague/qwen") + ["--apply"]) == 0
    capsys.readouterr()

    assert main(_new_match("m-legal")) == 0
    capsys.readouterr()

    assert main(["match", "show", "m-legal", "--json"]) == 0
    shown = json.loads(capsys.readouterr().out)

    assert "legal_actions" in shown
    living_ids = {u["id"] for u in shown["state"]["units"] if u["alive"]}
    assert set(shown["legal_actions"]) == living_ids
    for unit_id in living_ids:
        entry = shown["legal_actions"][unit_id]
        assert entry["hold"] is True
        assert isinstance(entry["gather"], bool)
        assert isinstance(entry["deliver"], bool)
        assert isinstance(entry["move"], list)
        assert entry["move"] == sorted(entry["move"])


def test_match_show_json_omits_beyond_move_range_target(arena, capsys) -> None:
    """blue-u1 is the scout (move=3) spawned at (0, 0) on skirmish-1."""
    assert main(_register("blue", "claude-sonnet-5") + ["--apply"]) == 0
    assert main(_register("red", "colleague/qwen") + ["--apply"]) == 0
    capsys.readouterr()

    assert main(_new_match("m-legal-range")) == 0
    capsys.readouterr()

    assert main(["match", "show", "m-legal-range", "--json"]) == 0
    shown = json.loads(capsys.readouterr().out)

    scout_moves = shown["legal_actions"]["blue-u1"]["move"]
    # Manhattan distance from (0, 0) to (4, 0) is 4 — one past this role's
    # move stat of 3. This is the exact rejected order the harness never
    # explained back to the seat.
    assert [4, 0] not in scout_moves
    assert [3, 0] in scout_moves
