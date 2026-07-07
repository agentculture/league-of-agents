"""``league play`` — one-command preset launch (plan task t3, spec c3/h3/c7).

Criteria under test:

* every documented mode (solo-vs-bot, team-vs-bot, team-vs-team,
  orchestrator-vs-bot, resident-vs-bot) is reachable from exactly one CLI
  command, ``league play start <preset> [--apply]``;
* ``play`` exposes ``overview``, and every path resolves through the explain
  catalog;
* ``start`` is dry-run by default and only touches ``.league/`` with
  ``--apply`` — the same safe-by-default contract every other write verb in
  this repo follows.

``team-vs-team`` is the one bundled preset whose both sides are `bot-file`
strategies (``bots/rusher.py``) — no live process on either side — so it is
the preset this suite actually runs to completion with ``--apply``.
``solo-vs-bot``, ``orchestrator-vs-bot`` and ``resident-vs-bot`` drive a live
agent subprocess/session (``command``/``resident`` drivers pointed at the
real ``claude`` binary) and cannot run in CI; for those this suite proves
``start`` resolves and stages a launchable config WITHOUT ``--apply`` (no
process spawned, nothing written to ``.league/``) — the same "dry-run proves
it's launchable" contract ``tests/test_presets.py`` already holds the preset
registry itself to.
"""

from __future__ import annotations

import json

import pytest

from league.cli import main
from league.explain import known_paths
from league.presets import preset_names
from league.store import Store

# solo-vs-bot / orchestrator-vs-bot / resident-vs-bot all spawn a live
# `claude` subprocess or session when actually applied — never safe to
# --apply in CI. team-vs-bot is `per_seat`/stateless `command` too. Only
# team-vs-team (bot-file vs bot-file) is fully offline.
_OFFLINE_PRESET = "team-vs-team"
_LIVE_PRESETS = ("solo-vs-bot", "team-vs-bot", "orchestrator-vs-bot", "resident-vs-bot")


@pytest.fixture()
def arena(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


# --- overview / noun scaffolding -------------------------------------------


def test_play_overview_and_bare_noun(arena, capsys) -> None:
    assert main(["play", "overview"]) == 0
    text = capsys.readouterr().out
    assert "league play" in text
    assert main(["play"]) == 0  # bare noun falls back to its overview
    capsys.readouterr()


def test_play_overview_json_shape(arena, capsys) -> None:
    assert main(["play", "overview", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["noun"] == "play"
    assert {"list", "show", "start"} <= set(data["verbs"])


def test_every_play_path_has_a_catalog_entry() -> None:
    """The rubric convention CLAUDE.md documents: a new verb without a catalog
    entry fails ``test_every_catalog_path_resolves``. Assert directly that
    every registered ``play`` path is one of the paths that test iterates."""
    paths = set(known_paths())
    for verb in ("", "overview", "list", "show", "start"):
        path = ("play",) if not verb else ("play", verb)
        assert path in paths, f"missing explain catalog entry for {path}"


def test_every_catalog_path_still_resolves(arena, capsys) -> None:
    for path in known_paths():
        if path and path[0] == "play":
            rc = main(["explain", *path])
            assert rc == 0, f"explain {' '.join(path)} failed"
            capsys.readouterr()


# --- list / show ------------------------------------------------------------


def test_play_list_enumerates_every_bundled_preset(arena, capsys) -> None:
    assert main(["play", "list", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    names = [p["name"] for p in data["presets"]]
    assert names == list(preset_names())
    for mode in ("solo", "team-vs-bot", "team-vs-team", "orchestrator", "resident"):
        assert any(mode in n for n in names)

    assert main(["play", "list"]) == 0
    text = capsys.readouterr().out
    for name in preset_names():
        assert name in text


def test_play_show_resolves_the_exact_harness_config(arena, capsys) -> None:
    assert main(["play", "show", _OFFLINE_PRESET, "--json"]) == 0
    config = json.loads(capsys.readouterr().out)
    assert config["match"]["scenario"]
    assert len(config["teams"]) == 2
    for team in config["teams"]:
        assert team["driver"]["type"] == "bot-file"
        assert team["driver"]["strategy"] == "rusher"

    assert main(["play", "show", _OFFLINE_PRESET]) == 0
    text = capsys.readouterr().out
    assert _OFFLINE_PRESET in text
    assert "bot" in text


def test_play_show_unknown_preset_errors(arena, capsys) -> None:
    rc = main(["play", "show", "no-such-preset"])
    assert rc == 1
    err = capsys.readouterr().err
    assert err.startswith("error:")
    assert "hint:" in err


@pytest.mark.parametrize("name", preset_names())
def test_play_show_resolves_for_every_bundled_preset(name, arena, capsys) -> None:
    assert main(["play", "show", name, "--json"]) == 0
    config = json.loads(capsys.readouterr().out)
    assert config["match"]["scenario"]
    assert config["teams"]


# --- start: dry-run by default ---------------------------------------------


def test_play_start_is_dry_run_by_default(arena, capsys) -> None:
    assert main(["play", "start", _OFFLINE_PRESET, "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["applied"] is False
    assert payload["preset"] == _OFFLINE_PRESET
    assert "result" not in payload
    assert not (arena / ".league").exists()

    assert main(["play", "start", _OFFLINE_PRESET]) == 0
    assert "dry-run" in capsys.readouterr().out
    assert not (arena / ".league").exists()


def test_play_start_seed_and_id_overrides(arena, capsys) -> None:
    assert (
        main(
            [
                "play",
                "start",
                _OFFLINE_PRESET,
                "--seed",
                "12345",
                "--id",
                "m-my-custom-run",
                "--json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["seed"] == 12345
    assert payload["match_id"] == "m-my-custom-run"
    assert not (arena / ".league").exists()


def test_play_start_rejects_negative_seed(arena, capsys) -> None:
    rc = main(["play", "start", _OFFLINE_PRESET, "--seed", "-1"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "non-negative" in err
    assert "hint:" in err


def test_play_start_rejects_invalid_id_override(arena, capsys) -> None:
    rc = main(["play", "start", _OFFLINE_PRESET, "--id", "../escape"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "invalid match id" in err
    assert not (arena / ".league").exists()


def test_play_start_unknown_preset_errors(arena, capsys) -> None:
    rc = main(["play", "start", "no-such-preset"])
    assert rc == 1
    err = capsys.readouterr().err
    assert err.startswith("error:")
    assert "hint:" in err


@pytest.mark.parametrize("name", _LIVE_PRESETS)
def test_play_start_dry_run_resolves_for_every_live_preset(name, arena, capsys) -> None:
    """solo/team-vs-bot/orchestrator/resident presets drive a live command or
    resident session — never safe to --apply in CI. Proves the ONE-COMMAND
    launch path resolves and stages correctly (driver kinds included) without
    spawning anything: no ``.league/`` directory is created."""
    assert main(["play", "start", name, "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["applied"] is False
    assert payload["driver_kinds"]
    assert not (arena / ".league").exists()


# --- start --apply: the one preset that runs fully offline ------------------


def test_play_start_apply_runs_team_vs_team_to_completion_offline(arena, capsys) -> None:
    rc = main(["play", "start", _OFFLINE_PRESET, "--apply", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["applied"] is True
    result = payload["result"]
    assert result["status"] == "finished"
    assert result["turns_played"] > 0

    # The match actually landed on disk under the preset's derived id.
    assert result["match_id"] in Store().list_matches()
    log_path = arena / ".league" / "matches" / result["match_id"] / "log.jsonl"
    assert log_path.is_file()

    assert main(["match", "score", result["match_id"], "--json"]) == 0
    score = json.loads(capsys.readouterr().out)
    assert set(score["outcome"]) == {"blue", "red"}


def test_play_start_apply_text_mode(arena, capsys) -> None:
    assert main(["play", "start", _OFFLINE_PRESET, "--id", "m-play-text", "--apply"]) == 0
    out = capsys.readouterr().out
    assert "m-play-text" in out
