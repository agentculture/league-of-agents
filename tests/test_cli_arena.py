"""Wave-3 acceptance tests for the arena noun groups (plan task t5).

Criteria under test:

* every write verb (team register, match new/act/tick) defaults to dry-run and
  mutates only with --apply;
* every read verb supports --json; noun groups expose overview;
* the whole play loop works end-to-end through main(argv) alone.
"""

from __future__ import annotations

import json
from pathlib import Path

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


def test_arena_catalog_reads(arena, capsys) -> None:
    assert main(["arena", "list"]) == 0
    assert "skirmish-1" in capsys.readouterr().out
    assert main(["arena", "show", "skirmish-1", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["id"] == "skirmish-1"
    assert data["roles"]["scout"]["move"] == 3
    assert main(["arena", "overview", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["read_only"] is True
    assert main(["arena", "show", "nope"]) == 1
    err = capsys.readouterr().err
    assert err.startswith("error:")
    assert "hint:" in err


def test_arena_catalog_carries_skirmish_2_with_vision(arena, capsys) -> None:
    """The fogged scenario is in the catalog and `arena show` surfaces vision.

    skirmish-2's whole premise is per-role fog — an agent reading the board
    from the CLI must be able to see the radii it will be playing under.
    """
    assert main(["arena", "list"]) == 0
    assert "skirmish-2" in capsys.readouterr().out.splitlines()
    assert main(["arena", "show", "skirmish-2", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["id"] == "skirmish-2"
    visions = {role: stats["vision"] for role, stats in data["roles"].items()}
    assert all(visions["scout"] > v for role, v in visions.items() if role != "scout")
    assert main(["arena", "show", "skirmish-2"]) == 0
    text = capsys.readouterr().out
    assert "vision" in text


def test_team_register_is_dry_run_by_default(arena, capsys) -> None:
    assert main(_register("blue", "claude-sonnet-5")) == 0
    out = capsys.readouterr().out
    assert "dry-run" in out
    assert not (arena / ".league" / "teams" / "blue.json").exists()

    assert main(_register("blue", "claude-sonnet-5") + ["--apply", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["applied"] is True
    assert Path(payload["path"]).is_file()

    assert main(["team", "show", "blue", "--json"]) == 0
    team = json.loads(capsys.readouterr().out)
    assert [a["role"] for a in team["agents"]] == ["scout", "harvester", "defender"]


def test_match_play_loop_end_to_end(arena, capsys) -> None:
    assert main(_register("blue", "claude-sonnet-5") + ["--apply"]) == 0
    assert main(_register("red", "colleague/qwen") + ["--apply"]) == 0
    capsys.readouterr()

    # Dry-run first: nothing on disk.
    base = [
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
        "m-e2e",
    ]
    assert main(base) == 0
    assert "dry-run" in capsys.readouterr().out
    assert not (arena / ".league" / "matches").exists()

    assert main(base + ["--apply", "--json"]) == 0
    created = json.loads(capsys.readouterr().out)
    assert created["applied"] is True
    log_path = arena / ".league" / "matches" / "m-e2e" / "log.jsonl"
    assert log_path.is_file()

    # act dry-run stages nothing.
    act_blue = [
        "match",
        "act",
        "m-e2e",
        "--team",
        "blue",
        "--plan",
        "harvest west, hold center",
        "--action",
        "blue-u1:move:2,1",
        "--action",
        "blue-u2:move:1,2",
        "--message",
        "blue-1:rolling out",
    ]
    assert main(act_blue) == 0
    assert "dry-run" in capsys.readouterr().out
    assert main(["match", "show", "m-e2e", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["staged_teams"] == []

    # Stage blue: waiting on red; nothing resolved yet.
    assert main(act_blue + ["--apply", "--json"]) == 0
    staged = json.loads(capsys.readouterr().out)
    assert staged["resolves_turn"] is False
    # Stage red: turn resolves.
    assert (
        main(
            [
                "match",
                "act",
                "m-e2e",
                "--team",
                "red",
                "--action",
                "red-u1:move:9,8",
                "--apply",
                "--json",
            ]
        )
        == 0
    )
    resolved = json.loads(capsys.readouterr().out)
    assert resolved["resolves_turn"] is True
    assert resolved["resolution"]["turn"] == 1

    assert main(["match", "show", "m-e2e", "--json"]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["state"]["turn"] == 1
    moved = {u["id"]: u["pos"] for u in shown["state"]["units"]}
    assert moved["blue-u1"] == [2, 1]

    # tick dry-run does not advance; --apply resolves an empty turn.
    assert main(["match", "tick", "m-e2e"]) == 0
    assert "dry-run" in capsys.readouterr().out
    assert main(["match", "tick", "m-e2e", "--apply", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["resolution"]["turn"] == 2

    assert main(["match", "score", "m-e2e", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert set(report["outcome"]) == {"blue", "red"}
    assert set(report["cooperation"]) == {"blue", "red"}

    assert main(["match", "replay", "m-e2e"]) == 0
    html = capsys.readouterr().out
    assert html.startswith("<!DOCTYPE html>")
    assert '"match_id": "m-e2e"' in html or "m-e2e" in html

    assert main(["match", "list", "--json"]) == 0
    listed = json.loads(capsys.readouterr().out)["matches"]
    assert listed[0]["match_id"] == "m-e2e"


def test_match_new_requires_registered_teams(arena, capsys) -> None:
    rc = main(["match", "new", "--scenario", "skirmish-1", "--team", "ghost", "--apply"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "no registered team" in err
    assert "hint:" in err


def test_act_validates_team_membership(arena, capsys) -> None:
    assert main(_register("blue", "m") + ["--apply"]) == 0
    assert main(_register("red", "m") + ["--apply"]) == 0
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
                "m-x",
                "--apply",
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert main(["match", "act", "m-x", "--team", "ghost", "--apply"]) == 1
    err = capsys.readouterr().err
    assert "not in this match" in err


def test_replay_json_honors_the_read_contract(arena, capsys) -> None:
    assert main(_register("blue", "m") + ["--apply"]) == 0
    assert main(_register("red", "m") + ["--apply"]) == 0
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
                "m-rj",
                "--apply",
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert main(["match", "replay", "m-rj", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["match_id"] == "m-rj"
    assert "frames" in data and "scores" in data


def test_path_traversal_ids_are_rejected(arena, capsys) -> None:
    rc = main(["team", "register", "../evil", "--agent", "a:m:scout", "--apply"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "invalid team id" in err
    assert "hint:" in err
    assert not (arena / ".league").exists()
    assert main(_register("blue", "m") + ["--apply"]) == 0
    assert main(_register("red", "m") + ["--apply"]) == 0
    capsys.readouterr()
    rc = main(
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
            "../../oops",
            "--apply",
        ]
    )
    assert rc == 1
    assert "invalid match id" in capsys.readouterr().err
    assert not (arena / ".league" / "matches").exists()


def test_noun_overviews_resolve(arena, capsys) -> None:
    for noun in ("arena", "team", "match"):
        assert main([noun, "overview"]) == 0
        assert main([noun]) == 0  # bare noun falls back to its overview
    capsys.readouterr()
