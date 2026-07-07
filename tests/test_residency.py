"""Cycle-2 acceptance tests for task t6: residency as a declared fairness axis.

Criteria under test (spec c10/h7):

* each team's driver kind ("bot", "stateless", or "resident" — how its minds
  were invoked, never game state) is recorded in the match log header and
  surfaced by ``league match show --json``;
* a match with one resident team and one stateless team is labeled as such in
  BOTH projections: the stored match log (``Store().load_match(...)``) and
  ``match show --json``.
"""

from __future__ import annotations

import json
import sys

import pytest

from league.cli import main
from league.harness import driver_kind, run_match
from league.store import Store

# A trivial subprocess "mind": reads the prompt, ignores it, declares no
# actions. Standing in for a real command driver so the test stays fast and
# hermetic while still exercising the real subprocess path.
_ECHO_AGENT = "import sys, json; sys.stdin.read(); print(json.dumps({'actions': []}))"


def _command_team(team_id: str, name: str, *, residency: str | None) -> dict:
    driver: dict = {"type": "command", "argv": [sys.executable, "-c", _ECHO_AGENT]}
    if residency is not None:
        driver["residency"] = residency
    return {
        "id": team_id,
        "name": name,
        "driver": driver,
        "agents": [
            {"id": f"{team_id}-1", "model": "test:echo", "role": "scout"},
            {"id": f"{team_id}-2", "model": "test:echo", "role": "harvester"},
            {"id": f"{team_id}-3", "model": "test:echo", "role": "defender"},
        ],
    }


@pytest.fixture()
def arena(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_driver_kind_maps_bot_and_command_specs() -> None:
    """The residency label is derived, not asked for: bot is always 'bot';
    command defaults to 'stateless' unless it opts into 'resident'."""
    assert driver_kind({"type": "bot"}) == "bot"
    assert driver_kind({"type": "command", "argv": ["x"]}) == "stateless"
    assert driver_kind({"type": "command", "argv": ["x"], "residency": "stateless"}) == "stateless"
    assert driver_kind({"type": "command", "argv": ["x"], "residency": "resident"}) == "resident"
    with pytest.raises(ValueError, match="unknown driver type"):
        driver_kind({"type": "telepathy"})
    with pytest.raises(ValueError, match="unknown residency"):
        driver_kind({"type": "command", "argv": ["x"], "residency": "eternal"})


def test_residency_is_recorded_in_both_projections(arena, capsys) -> None:
    """One resident team, one stateless team — the fairness axis is labeled
    identically in the stored log and in `match show --json`."""
    config = {
        "match": {
            "scenario": "skirmish-1",
            "mode": "competitive",
            "seed": 3,
            "id": "m-residency",
        },
        "teams": [
            _command_team("blue", "Blue Foundry", residency=None),  # default: stateless
            _command_team("red", "Red Relay", residency="resident"),
        ],
        "max_rounds": 1,
    }
    run_match(config)
    capsys.readouterr()

    # Projection 1: the stored match log header.
    log = Store().load_match("m-residency")
    assert log.driver_kinds == {"blue": "stateless", "red": "resident"}

    # Projection 2: `league match show --json`.
    assert main(["match", "show", "m-residency", "--json"]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["driver_kinds"] == {"blue": "stateless", "red": "resident"}

    # And it never leaked into engine state.
    assert "driver_kinds" not in shown["state"]


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


def test_match_new_records_driver_kinds_via_cli(arena, capsys) -> None:
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
                "--driver",
                "blue:stateless",
                "--driver",
                "red:resident",
                "--id",
                "m-driver",
                "--apply",
                "--json",
            ]
        )
        == 0
    )
    created = json.loads(capsys.readouterr().out)
    assert created["driver_kinds"] == {"blue": "stateless", "red": "resident"}

    assert main(["match", "show", "m-driver"]) == 0
    text = capsys.readouterr().out
    assert "driver stateless" in text
    assert "driver resident" in text

    assert main(["match", "show", "m-driver", "--json"]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["driver_kinds"] == {"blue": "stateless", "red": "resident"}


def test_match_new_driver_flag_is_optional(arena, capsys) -> None:
    """A match created without --driver simply has no recorded kinds — the
    field is metadata, not a requirement."""
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
                "m-no-driver",
                "--apply",
                "--json",
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert main(["match", "show", "m-no-driver", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["driver_kinds"] == {}


def test_match_new_rejects_bad_driver_flags(arena, capsys) -> None:
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
            "--driver",
            "ghost:resident",
            "--id",
            "m-bad-team",
            "--apply",
        ]
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert "hint:" in err

    # Unknown kind.
    rc = main(
        [
            "match",
            "new",
            "--scenario",
            "skirmish-1",
            "--team",
            "blue",
            "--driver",
            "blue:eternal",
            "--id",
            "m-bad-kind",
            "--apply",
        ]
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert "hint:" in err

    # Bad format (no ':').
    rc = main(
        [
            "match",
            "new",
            "--scenario",
            "skirmish-1",
            "--team",
            "blue",
            "--driver",
            "blue-resident",
            "--id",
            "m-bad-format",
            "--apply",
        ]
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert "hint:" in err
