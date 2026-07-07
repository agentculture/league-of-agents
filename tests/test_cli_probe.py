"""``league match probe`` — the span-of-control probe's CLI surface (plan t7).

Wiring tests only: ``--json`` shape, text rendering, and clean error handling
for an unknown match id. The probe FORMULA itself (the evidence hierarchy,
named weights, degradation curve) is pinned on synthetic logs in
``tests/test_engine_probe.py``; this file only proves the CLI calls
``league.engine.probe.probe_match`` correctly and never leaks a traceback.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from league.cli import main
from league.engine.events import MatchLog
from league.harness import run_match
from league.store import Store
from tests.test_wave4 import BOT_TEAM_BLUE, BOT_TEAM_RED

_SEASON0 = pathlib.Path(__file__).resolve().parent.parent / "docs" / "playtests" / "season-0"


@pytest.fixture()
def arena(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _bot_config(match_id: str, seed: int = 7) -> dict:
    return {
        "match": {"scenario": "skirmish-1", "mode": "competitive", "seed": seed, "id": match_id},
        "teams": [BOT_TEAM_BLUE, BOT_TEAM_RED],
    }


def test_probe_json_shape_on_a_bot_match(arena, capsys) -> None:
    run_match(_bot_config("m-probe-1"))
    capsys.readouterr()
    rc = main(["match", "probe", "m-probe-1", "--json"])
    assert rc == 0
    report = json.loads(capsys.readouterr().out)
    assert report["version"] == "p0"
    assert set(report["teams"]) == {"blue", "red"}
    for team_id in ("blue", "red"):
        team = report["teams"][team_id]
        assert {
            "span",
            "roster_size",
            "evidence",
            "commanders",
            "score",
            "signals",
            "components",
        } <= set(team)
        # Bot drivers are whole-team calls: seat_latency proves it (both are
        # made-up "bot:greedy" drivers), span stays in the documented 0/1 band.
        assert team["evidence"] == "latency"
        assert team["span"] in (0, 1)


def test_probe_unknown_match_is_a_clean_cli_error(arena, capsys) -> None:
    rc = main(["match", "probe", "no-such-match"])
    assert rc == 1
    err = capsys.readouterr().err
    assert err.startswith("error:")
    assert "hint:" in err


def test_probe_text_rendering_includes_match_id_and_span(arena, capsys) -> None:
    run_match(_bot_config("m-probe-2"))
    capsys.readouterr()
    rc = main(["match", "probe", "m-probe-2"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "m-probe-2" in out
    assert "span" in out
    assert "blue" in out and "red" in out


def test_probe_on_committed_season0_orchestrator_log_via_the_cli(arena, capsys) -> None:
    """The acceptance integration check, through the public CLI surface: the
    real orchestrator playtest log (no seat_latency; predates plan C4-t1)
    fields 3 real per-seat subagents on the record alone."""
    log = MatchLog.from_jsonl((_SEASON0 / "orchestrator.log.jsonl").read_text())
    Store().create_match(log)
    capsys.readouterr()
    rc = main(["match", "probe", log.initial_state.match_id, "--json"])
    assert rc == 0
    report = json.loads(capsys.readouterr().out)
    assert report["teams"]["fable"]["span"] == 3
    assert report["teams"]["fable"]["evidence"] == "fallback"


def test_probe_overview_lists_the_verb(arena, capsys) -> None:
    rc = main(["match", "overview", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert "probe" in payload["verbs"]
