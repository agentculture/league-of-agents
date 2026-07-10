"""``league match probe`` — the span-of-control probe's CLI surface (plan t7).

Wiring tests only: ``--json`` shape, text rendering, and clean error handling
for an unknown match id. The probe FORMULA itself (the evidence hierarchy,
named weights, degradation curve) is pinned on synthetic logs in
``tests/test_engine_probe.py``; this file only proves the CLI calls
``league.engine.probe.probe_match`` correctly and never leaks a traceback.
"""

from __future__ import annotations

import dataclasses
import json
import pathlib

import pytest

from league.cli import main
from league.engine.events import MatchLog
from league.engine.scenario import get_scenario, instantiate
from league.engine.tick import resolve_turn, start_match
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


# --------------------------------------------------------------------------- #
# Passive capture-ineligibility does not leak into last_turn_rejections or
# realization_rate through the real CLI surface (issue #31).
# --------------------------------------------------------------------------- #


def _skirmish1_roster(team: str, model: str = "colleague/qwen") -> tuple:
    from league.engine.state import AgentSlot

    return (
        AgentSlot(id=f"{team}-scout", model=model, role="scout"),
        AgentSlot(id=f"{team}-harvester", model=model, role="harvester"),
        AgentSlot(id=f"{team}-defender", model=model, role="defender"),
    )


def _move_unit(state, unit_id: str, pos: tuple[int, int]):
    units = tuple(dataclasses.replace(u, pos=pos) if u.id == unit_id else u for u in state.units)
    return dataclasses.replace(state, units=units)


def test_show_stays_clean_for_a_scout_standing_on_a_control_point(arena, capsys) -> None:
    """The exact playtest shape (issue #31): blue's scout (can_capture=False
    on skirmish-1) parks alone on cp-east and holds every turn — a genuinely
    clean order — while the engine also fires a passive action_rejected from
    occupancy every turn. 'match show --json's last_turn_rejections must not
    surface it as a mistake."""
    scenario = get_scenario("skirmish-1")
    initial = instantiate(
        scenario,
        match_id="m-passive-cp",
        seed=1,
        mode="competitive",
        teams=(
            ("blue", "Blue Foundry", _skirmish1_roster("blue")),
            ("red", "Red Relay", _skirmish1_roster("red")),
        ),
    )
    state, all_events = start_match(initial)
    state = _move_unit(state, "blue-u1", (9, 2))  # scout onto cp-east, alone

    for _ in range(3):
        state, turn_events = resolve_turn(
            state, scenario, {"blue": {"actions": [{"unit_id": "blue-u1", "action": "hold"}]}}
        )
        all_events += turn_events

    # This turn's own passive rejection is real — proves the fixture actually
    # exercises the code path this test is pinning, not a vacuous pass.
    assert any(
        e.kind == "action_rejected" and e.data.get("passive") and e.turn == state.turn
        for e in all_events
    )

    log = MatchLog(initial_state=initial, events=all_events)
    Store().create_match(log)
    capsys.readouterr()

    assert main(["match", "show", "m-passive-cp", "--json"]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["last_turn_rejections"] == []
