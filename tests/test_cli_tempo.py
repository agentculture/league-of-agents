"""``league match score`` grows the tempo axis (plan task t5, spec c4/h4).

Criteria under test (the merge-gate's CLI half):

* ``score`` publishes tempo as a THIRD axis beside outcome and cooperation in
  both ``--json`` and text — never merged into either;
* every surface that prints a converted tempo score prints RAW latency beside it
  (the h4 honesty condition): the JSON ``converted`` block never appears without
  its sibling ``raw``, and the text line always carries the raw median;
* ``--substrate <team>=<name>`` declares a team's substrate for conversion; a
  malformed flag is a clean user error, not a traceback;
* a match with no latency (created but never played) degrades gracefully through
  the CLI too — tempo present, ``raw`` null, ``converted`` absent.
"""

from __future__ import annotations

import json

import pytest

from league.cli import main
from league.harness import run_match
from tests.test_wave4 import BOT_TEAM_BLUE, BOT_TEAM_RED


@pytest.fixture()
def arena(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _bot_config(match_id: str, seed: int = 7) -> dict:
    return {
        "match": {"scenario": "skirmish-1", "mode": "competitive", "seed": seed, "id": match_id},
        "teams": [BOT_TEAM_BLUE, BOT_TEAM_RED],
    }


def _score_json(match_id: str, *extra: str, capsys) -> dict:
    rc = main(["match", "score", match_id, *extra, "--json"])
    assert rc == 0
    return json.loads(capsys.readouterr().out)


def test_score_json_publishes_tempo_as_a_third_axis(arena, capsys) -> None:
    run_match(_bot_config("m-tempo-1"))
    capsys.readouterr()
    report = _score_json("m-tempo-1", capsys=capsys)

    # Three distinct axes, side by side — tempo merged into neither.
    assert {"outcome", "cooperation", "tempo"} <= set(report)
    assert set(report["tempo"]) == {"blue", "red"}
    for team_id in ("blue", "red"):
        payload = report["tempo"][team_id]
        assert payload["version"] == "t0"
        # Bot matches always carry seat_latency -> raw is populated.
        assert payload["raw"] is not None
        assert set(payload["raw"]) == {
            "median_ms",
            "mean_ms",
            "p95_ms",
            "turns_measured",
            "seats_measured",
        }
        # h4: converted never appears without raw beside it.
        assert "converted" in payload
        # No substrate declared -> identity conversion, loudly flagged.
        assert payload["converted"]["substrate_known"] is False
        assert payload["converted"]["caveat"]


def test_score_json_substrate_flag_declares_conversion(arena, capsys) -> None:
    run_match(_bot_config("m-tempo-2"))
    capsys.readouterr()
    report = _score_json(
        "m-tempo-2", "--substrate", "blue=cloud", "--substrate", "red=bot", capsys=capsys
    )

    blue = report["tempo"]["blue"]["converted"]
    assert blue["substrate"] == "cloud"
    assert blue["substrate_known"] is True
    assert blue["baseline_ms"] == 20_000
    red = report["tempo"]["red"]["converted"]
    assert red["substrate"] == "bot"
    assert red["substrate_known"] is True


def test_score_text_prints_raw_beside_converted_tempo(arena, capsys) -> None:
    run_match(_bot_config("m-tempo-3"))
    capsys.readouterr()
    rc = main(["match", "score", "m-tempo-3", "--substrate", "blue=cloud"])
    assert rc == 0
    out = capsys.readouterr().out
    # Every per-team line (they carry the cooperation score) shows a converted
    # tempo score AND its raw median beside it — the h4 honesty condition,
    # checkable in review.
    team_lines = [ln for ln in out.splitlines() if "cooperation" in ln]
    assert team_lines
    for line in team_lines:
        assert "tempo" in line, line
        assert "median" in line and "ms" in line, line


def test_score_text_marks_undeclared_substrate_as_unnormalized(arena, capsys) -> None:
    run_match(_bot_config("m-tempo-4"))
    capsys.readouterr()
    rc = main(["match", "score", "m-tempo-4"])  # no --substrate
    assert rc == 0
    out = capsys.readouterr().out
    assert "tempo" in out and "median" in out
    # Identity conversion is disclosed in text, not silently normalized.
    assert "unnormalized" in out.lower()


def test_score_bad_substrate_flag_is_a_clean_user_error(arena, capsys) -> None:
    run_match(_bot_config("m-tempo-5"))
    capsys.readouterr()
    rc = main(["match", "score", "m-tempo-5", "--substrate", "blue"])  # missing '=name'
    assert rc == 1
    err = capsys.readouterr().err
    assert err.startswith("error:")
    assert "hint:" in err


def test_score_substrate_flag_unknown_team_errors(arena, capsys) -> None:
    run_match(_bot_config("m-tempo-6"))
    capsys.readouterr()
    rc = main(["match", "score", "m-tempo-6", "--substrate", "green=cloud"])
    assert rc == 1
    err = capsys.readouterr().err
    assert err.startswith("error:")


def test_score_of_unplayed_match_degrades_gracefully(arena, capsys) -> None:
    """A match created but never played has no seat_latency events — scoring it
    still reports tempo, with raw null and converted absent (never a crash)."""
    assert (
        main(
            [
                "team",
                "register",
                "blue",
                "--name",
                "Blue",
                "--agent",
                "blue-1:m:scout",
                "--agent",
                "blue-2:m:harvester",
                "--agent",
                "blue-3:m:defender",
                "--apply",
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "team",
                "register",
                "red",
                "--name",
                "Red",
                "--agent",
                "red-1:m:scout",
                "--agent",
                "red-2:m:harvester",
                "--agent",
                "red-3:m:defender",
                "--apply",
            ]
        )
        == 0
    )
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
            "--seed",
            "3",
            "--id",
            "m-unplayed",
            "--apply",
        ]
    )
    assert rc == 0
    capsys.readouterr()

    report = _score_json("m-unplayed", capsys=capsys)
    assert "tempo" in report
    for payload in report["tempo"].values():
        assert payload["raw"] is None
        assert "converted" not in payload
        assert payload["version"] == "t0"
