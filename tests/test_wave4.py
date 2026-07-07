"""Wave-4 acceptance tests: tracking (t9), fair rematch (t10), harness (t11).

Criteria under test:

* finished matches are queryable across repeated play — standings/history
  compute per-team and per-agent trends from the logs alone;
* rematch replays the identical scenario + seed with a different roster:
  apples-to-apples by construction;
* the harness plays a full match with live drivers through the CLI surface
  only, and swapping a driver is a config change, not a code change.
"""

from __future__ import annotations

import json
import sys

import pytest

from league.cli import main
from league.harness import build_driver, run_match

BOT_TEAM_BLUE = {
    "id": "blue",
    "name": "Blue Foundry",
    "driver": {"type": "bot"},
    "agents": [
        {"id": "blue-1", "model": "bot:greedy", "role": "scout"},
        {"id": "blue-2", "model": "bot:greedy", "role": "harvester"},
        {"id": "blue-3", "model": "bot:greedy", "role": "defender"},
    ],
}
BOT_TEAM_RED = {
    "id": "red",
    "name": "Red Relay",
    "driver": {"type": "bot"},
    "agents": [
        {"id": "red-1", "model": "bot:greedy", "role": "scout"},
        {"id": "red-2", "model": "bot:greedy", "role": "harvester"},
        {"id": "red-3", "model": "bot:greedy", "role": "defender"},
    ],
}


@pytest.fixture()
def arena(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _bot_config(match_id: str, seed: int = 7) -> dict:
    return {
        "match": {"scenario": "skirmish-1", "mode": "competitive", "seed": seed, "id": match_id},
        "teams": [BOT_TEAM_BLUE, BOT_TEAM_RED],
    }


def test_harness_plays_a_full_match_via_the_cli(arena, capsys) -> None:
    result = run_match(_bot_config("m-bots-1"))
    assert result["status"] == "finished"
    assert result["turns_played"] >= 1
    assert set(result["score"]["outcome"]) == {"blue", "red"}
    assert set(result["score"]["cooperation"]) == {"blue", "red"}
    # The whole match exists as the standard on-disk artifacts.
    log = arena / ".league" / "matches" / "m-bots-1" / "log.jsonl"
    assert log.is_file()
    capsys.readouterr()


def test_harness_verb_is_dry_run_by_default(arena, capsys, tmp_path) -> None:
    config_path = tmp_path / "cfg.json"
    config_path.write_text(json.dumps(_bot_config("m-dry")), encoding="utf-8")
    assert main(["harness", "run", "--config", str(config_path)]) == 0
    assert "dry-run" in capsys.readouterr().out
    assert not (arena / ".league").exists()

    assert main(["harness", "run", "--config", str(config_path), "--apply", "--json"]) == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["status"] == "finished"


def test_swapping_a_driver_is_config_only(arena) -> None:
    """A 'command' driver is any subprocess: here a one-line echo agent."""
    echo_agent = (
        "import sys, json; sys.stdin.read(); "
        "print(json.dumps({'actions': [{'unit_id': 'red-u1', 'action': 'hold'}]}))"
    )
    scenario = {
        "roles": {},
        "grid": {"width": 12, "height": 10},
        "capture_hold_turns": 2,
        "turn_limit": 30,
    }
    driver = build_driver({"type": "command", "argv": [sys.executable, "-c", echo_agent]}, scenario)
    orders = driver(
        {"units": [], "missions": [], "resource_nodes": [], "control_points": []}, "red", 1
    )
    assert orders == {"actions": [{"unit_id": "red-u1", "action": "hold"}]}
    with pytest.raises(ValueError, match="unknown driver type"):
        build_driver({"type": "telepathy"}, scenario)


def test_standings_and_history_track_repeated_play(arena, capsys) -> None:
    run_match(_bot_config("m-track-1", seed=7))
    run_match(_bot_config("m-track-2", seed=11))
    capsys.readouterr()

    assert main(["standings", "--json"]) == 0
    table = json.loads(capsys.readouterr().out)
    assert table["matches_played"] == 2
    for team_id in ("blue", "red"):
        row = table["teams"][team_id]
        assert row["played"] == 2
        assert len(row["cooperation_trend"]) == 2
    agent = table["agents"]["blue-2"]
    assert agent["matches"] == 2
    assert agent["role"] == "harvester"
    assert agent["declared"] > 0

    assert main(["history", "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)["matches"]
    assert [r["match_id"] for r in rows] == ["m-track-1", "m-track-2"]
    for row in rows:
        for team_id in ("blue", "red"):
            assert "outcome" in row["teams"][team_id]
            assert "cooperation" in row["teams"][team_id]


def test_rematch_is_identical_but_for_the_roster(arena, capsys) -> None:
    run_match(_bot_config("m-orig", seed=13))
    capsys.readouterr()

    # Register a roster that differs ONLY in model labels.
    assert (
        main(
            [
                "team",
                "register",
                "green",
                "--name",
                "Green Mirror",
                "--agent",
                "green-1:claude-sonnet-5:scout",
                "--agent",
                "green-2:claude-sonnet-5:harvester",
                "--agent",
                "green-3:claude-sonnet-5:defender",
                "--apply",
            ]
        )
        == 0
    )
    capsys.readouterr()

    # Dry-run leaves no trace.
    assert main(["match", "rematch", "m-orig", "--swap"]) == 0
    assert "dry-run" in capsys.readouterr().out

    assert (
        main(["match", "rematch", "m-orig", "--swap", "--id", "m-swapped", "--apply", "--json"])
        == 0
    )
    swapped = json.loads(capsys.readouterr().out)
    assert swapped["teams"] == ["red", "blue"]
    assert swapped["seed"] == 13

    # A competitive rematch still needs exactly two teams.
    assert (
        main(["match", "rematch", "m-orig", "--team", "green", "--id", "m-green-bad", "--apply"])
        == 1
    )
    err = capsys.readouterr().err
    assert err.startswith("error:")
    assert "hint:" in err

    assert (
        main(
            [
                "match",
                "rematch",
                "m-orig",
                "--team",
                "green",
                "--team",
                "blue",
                "--id",
                "m-green",
                "--apply",
                "--json",
            ]
        )
        == 0
    )
    green = json.loads(capsys.readouterr().out)
    assert green["seed"] == 13

    # Identical initial conditions: same board furniture, same seed; only the
    # roster metadata differs.
    assert main(["match", "show", "m-orig", "--json"]) == 0
    orig_state = json.loads(capsys.readouterr().out)["state"]
    assert main(["match", "show", "m-green", "--json"]) == 0
    green_state = json.loads(capsys.readouterr().out)["state"]
    assert green_state["seed"] == orig_state["seed"]
    assert green_state["control_points"] == [
        {**cp, "owner": None, "hold": []} for cp in _fresh_cps(orig_state)
    ]
    assert green_state["resource_nodes"] == _fresh_nodes()
    assert green_state["missions"] == _fresh_missions()


def _fresh_cps(orig_state: dict) -> list[dict]:
    # The original match has been played; compare against pristine furniture.
    return [
        {"id": "cp-center", "pos": [6, 5], "owner": None, "hold": []},
        {"id": "cp-west", "pos": [3, 8], "owner": None, "hold": []},
        {"id": "cp-east", "pos": [9, 2], "owner": None, "hold": []},
    ]


def _fresh_nodes() -> list[dict]:
    return [
        {"id": "rn-west", "pos": [0, 5], "remaining": 12},
        {"id": "rn-east", "pos": [11, 4], "remaining": 12},
    ]


def _fresh_missions() -> list[dict]:
    return [
        {
            "id": "ms-supply",
            "kind": "deliver",
            "pos": [6, 5],
            "amount": 6,
            "reward": 10,
            "status": "open",
            "completed_by": [],
            "completed_turn": None,
        },
        {
            "id": "ms-outpost",
            "kind": "hold",
            "pos": [9, 2],
            "amount": 3,
            "reward": 8,
            "status": "open",
            "completed_by": [],
            "completed_turn": None,
        },
    ]
