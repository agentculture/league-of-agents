"""``league match score`` gains the per-unit role-purpose scorecard, both
lanes (plan task t6, spec c6/c10/c15/h13).

Criteria under test (verbatim from the plan):

1. ``league match score <id> --json`` carries a ``units`` section (grade,
   per-purpose breakdown, mvp/lvp flags) beside the untouched team axes for
   grid logs, and the continuous score path exposes the same shape; text
   mode renders a readable scorecard; explain catalog updated
   (``test_every_catalog_path_resolves`` green — covered in ``tests/
   test_cli.py``, not duplicated here).
2. No ranking surface exists: grades never feed team scores and no
   cross-match aggregation verb appears (boundary test).

The grid path is exercised two ways: a live bot match (shape/text checks) and
a committed cycle-4 fixture (``docs/playtests/season-0/opener``) whose
``score.json`` is the pre-existing regression pin — every key it carries must
still equal the committed value bit-for-bit after the ``units`` axis lands.
The continuous path is exercised against the committed cycle-7 fixture
(``docs/playtests/cycle-7/race-live``) that ``tests/test_cgrades.py`` already
hand-traces, so the expected MVP/LVP/grades here are the SAME pinned numbers,
just read through the CLI instead of ``cgrade_units`` directly.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from league.cli import _build_parser, main
from league.engine.events import MatchLog
from league.engine.scoring import score_match
from league.engine.tempo import score_tempo
from league.harness import run_match
from tests.test_wave4 import BOT_TEAM_BLUE, BOT_TEAM_RED

PLAYTESTS = Path(__file__).resolve().parent.parent / "docs" / "playtests"
OPENER_LOG = PLAYTESTS / "season-0" / "opener.log.jsonl"
OPENER_SCORE = PLAYTESTS / "season-0" / "opener.score.json"
RACE_LIVE_LOG = PLAYTESTS / "cycle-7" / "race-live.log.jsonl"
RACE_LIVE_OUTCOME = PLAYTESTS / "cycle-7" / "race-live.outcome.json"


@pytest.fixture()
def arena(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _write_log(match_id: str, raw: str) -> None:
    d = Path(".league") / "matches" / match_id
    d.mkdir(parents=True)
    (d / "log.jsonl").write_text(raw, encoding="utf-8")


def _bot_config(match_id: str, seed: int = 7) -> dict:
    return {
        "match": {"scenario": "skirmish-1", "mode": "competitive", "seed": seed, "id": match_id},
        "teams": [BOT_TEAM_BLUE, BOT_TEAM_RED],
    }


def _score_json(match_id: str, *extra: str, capsys) -> dict:
    rc = main(["match", "score", match_id, *extra, "--json"])
    assert rc == 0
    return json.loads(capsys.readouterr().out)


_COMMON_UNIT_KEYS = {"team_id", "role", "home_purpose", "grade", "breakdown", "mvp", "lvp"}
_COMMON_SECTION_KEYS = {"match_id", "purposes", "units", "mvp", "lvp"}


# --------------------------------------------------------------------------- #
# 1a. Grid lane: units section shape, beside the untouched team axes.
# --------------------------------------------------------------------------- #


def test_grid_score_json_carries_units_section_beside_team_axes(arena, capsys) -> None:
    run_match(_bot_config("m-units-1"))
    capsys.readouterr()
    report = _score_json("m-units-1", capsys=capsys)

    # The pre-existing team axes are all still there, untouched in kind.
    assert {"match_id", "scenario_id", "mode", "turns_played", "winner"} <= set(report)
    assert {"outcome", "cooperation", "tempo"} <= set(report)

    assert "units" in report
    units = report["units"]
    assert set(units) == _COMMON_SECTION_KEYS
    assert units["purposes"] == ["economy", "control", "recon", "coordination"]
    assert units["units"], "expected at least one graded unit"
    for entry in units["units"].values():
        assert set(entry) == _COMMON_UNIT_KEYS
        assert set(entry["breakdown"]) == set(units["purposes"])

    # Exactly one unit is flagged mvp, exactly one lvp (unless they coincide —
    # not possible here since blue/red both fielded units and scored > 0).
    mvp_flagged = [uid for uid, e in units["units"].items() if e["mvp"]]
    lvp_flagged = [uid for uid, e in units["units"].items() if e["lvp"]]
    assert len(mvp_flagged) == 1
    assert len(lvp_flagged) == 1
    assert units["mvp"]["unit_id"] == mvp_flagged[0]
    assert units["lvp"]["unit_id"] == lvp_flagged[0]


def test_grid_score_text_mode_renders_a_readable_scorecard(arena, capsys) -> None:
    run_match(_bot_config("m-units-2"))
    capsys.readouterr()
    rc = main(["match", "score", "m-units-2"])
    assert rc == 0
    out = capsys.readouterr().out

    assert "units (role-purpose scorecard):" in out
    assert "[MVP]" in out
    assert "[LVP]" in out
    assert "grade" in out
    # Every purpose name appears somewhere in the per-unit breakdown lines.
    for purpose in ("economy", "control", "recon", "coordination"):
        assert purpose in out


# --------------------------------------------------------------------------- #
# 1b. Grid regression: the committed score.json's pre-existing keys are
#     bit-identical after the units axis lands — additive only.
# --------------------------------------------------------------------------- #


def test_grid_score_regression_committed_fixture_team_axes_are_bit_identical(arena, capsys) -> None:
    raw = OPENER_LOG.read_text(encoding="utf-8")
    match_id = MatchLog.from_jsonl(raw).initial_state.match_id
    _write_log(match_id, raw)
    capsys.readouterr()

    report = _score_json(match_id, capsys=capsys)
    committed = json.loads(OPENER_SCORE.read_text(encoding="utf-8"))

    # Every key the committed fixture carries must be present and IDENTICAL —
    # not just equal after re-serialization, but the exact same Python value.
    for key, value in committed.items():
        assert report[key] == value, f"team axis {key!r} drifted from the committed fixture"

    # The new axis is additive, appearing beside — not instead of — those keys.
    assert set(committed) <= set(report)
    assert "units" in report
    assert "tempo" in report  # pre-existing (t5) axis, also untouched by this task


def test_grid_score_units_and_cli_score_match_pure_functions_agree(arena, capsys) -> None:
    """Cross-check: the units section the CLI emits is exactly what calling
    ``grade_units`` on the identical log directly would produce (normalized),
    proving the CLI doesn't quietly recompute or mutate anything."""
    from league.cli._commands.match import _grid_units_section

    raw = OPENER_LOG.read_text(encoding="utf-8")
    match_id = MatchLog.from_jsonl(raw).initial_state.match_id
    _write_log(match_id, raw)
    capsys.readouterr()

    report = _score_json(match_id, capsys=capsys)
    direct = _grid_units_section(MatchLog.from_jsonl(raw))
    assert report["units"] == direct


# --------------------------------------------------------------------------- #
# 2a. Continuous lane: the score path now works (used to raise) and exposes
#     the SAME units shape as grid.
# --------------------------------------------------------------------------- #


def test_continuous_score_json_carries_units_section_same_shape_as_grid(arena, capsys) -> None:
    raw = RACE_LIVE_LOG.read_text(encoding="utf-8")
    _write_log("c-race-live", raw)
    capsys.readouterr()

    report = _score_json("c-race-live", capsys=capsys)

    assert report["match_id"] == "c-race-live"
    assert report["status"] == "finished"
    assert report["winner"] == "blue"
    # Outcome facts as the continuous engine already computes them today —
    # cross-checked against the committed outcome.json (t3's own fixture).
    outcome = json.loads(RACE_LIVE_OUTCOME.read_text(encoding="utf-8"))
    assert report["outcome"] == outcome["outcome_points"] == {"blue": 19, "red": 0}

    units = report["units"]
    assert set(units) == _COMMON_SECTION_KEYS
    assert units["purposes"] == ["race_hold", "economy", "eyes"]
    for entry in units["units"].values():
        assert set(entry) == _COMMON_UNIT_KEYS
        assert set(entry["breakdown"]) == set(units["purposes"])

    # The exact pinned numbers tests/test_cgrades.py hand-traces for this log.
    assert units["units"]["blue-u1"]["grade"] == 1150
    assert units["units"]["blue-u2"]["grade"] == 1200
    assert units["units"]["red-u1"]["grade"] == 250
    assert units["units"]["red-u2"]["grade"] == 0
    assert units["mvp"] == {"unit_id": "blue-u2", "team_id": "blue", "grade": 1200}
    assert units["lvp"] == {"unit_id": "red-u2", "team_id": "red", "grade": 0}
    assert units["units"]["blue-u2"]["mvp"] is True
    assert units["units"]["red-u2"]["lvp"] is True


def test_continuous_score_text_mode_renders_a_readable_scorecard(arena, capsys) -> None:
    raw = RACE_LIVE_LOG.read_text(encoding="utf-8")
    _write_log("c-race-live", raw)
    capsys.readouterr()

    rc = main(["match", "score", "c-race-live"])
    assert rc == 0
    out = capsys.readouterr().out

    assert "c-race-live" in out
    assert "units (role-purpose scorecard):" in out
    assert "[MVP]" in out
    assert "[LVP]" in out
    assert "blue-u2" in out and "red-u2" in out
    for purpose in ("race_hold", "economy", "eyes"):
        assert purpose in out


def test_continuous_score_routes_by_header_shape_even_without_c_prefix(arena, capsys) -> None:
    """Mirrors ``cmd_match_replay``'s own test: naming is never authority, the
    log's header shape is (plan C7-t9's sniff-first discipline, reused here)."""
    import dataclasses

    from league.engine.continuous.events import CMatchLog

    raw = RACE_LIVE_LOG.read_text(encoding="utf-8")
    clog = CMatchLog.from_jsonl(raw)
    renamed = dataclasses.replace(clog.initial_state, match_id="not-c-prefixed")
    renamed_log = CMatchLog(initial_state=renamed, events=clog.events)
    _write_log("not-c-prefixed", renamed_log.to_jsonl())
    capsys.readouterr()

    report = _score_json("not-c-prefixed", capsys=capsys)
    assert report["match_id"] == "not-c-prefixed"
    assert "units" in report and report["units"]["purposes"] == ["race_hold", "economy", "eyes"]


# --------------------------------------------------------------------------- #
# 2b. The two lanes' units sections share EXACTLY the same shape (same keys),
#     only the purpose names and unit counts differ.
# --------------------------------------------------------------------------- #


def test_units_section_shape_is_identical_between_lanes(arena, capsys) -> None:
    grid_raw = OPENER_LOG.read_text(encoding="utf-8")
    grid_id = MatchLog.from_jsonl(grid_raw).initial_state.match_id
    _write_log(grid_id, grid_raw)
    capsys.readouterr()
    grid_report = _score_json(grid_id, capsys=capsys)

    _write_log("c-race-live", RACE_LIVE_LOG.read_text(encoding="utf-8"))
    capsys.readouterr()
    continuous_report = _score_json("c-race-live", capsys=capsys)

    assert set(grid_report["units"]) == set(continuous_report["units"]) == _COMMON_SECTION_KEYS
    grid_unit = next(iter(grid_report["units"]["units"].values()))
    continuous_unit = next(iter(continuous_report["units"]["units"].values()))
    assert set(grid_unit) == set(continuous_unit) == _COMMON_UNIT_KEYS
    # The purpose LISTS legitimately differ per lane — that's the one thing
    # the acceptance criterion says is allowed to differ.
    assert grid_report["units"]["purposes"] != continuous_report["units"]["purposes"]


# --------------------------------------------------------------------------- #
# 2c. Boundary: grades never feed team scores, and no ranking surface exists.
# --------------------------------------------------------------------------- #


def test_team_axes_are_byte_identical_whether_or_not_units_is_computed(arena, capsys) -> None:
    """The strongest form of "grades never feed team scores": compute the
    team axes the OLD way (score_match + score_tempo directly, no grading
    involved at all) and compare against the CLI's report with the ``units``
    key stripped back out — they must be exactly equal."""
    raw = OPENER_LOG.read_text(encoding="utf-8")
    match_id = MatchLog.from_jsonl(raw).initial_state.match_id
    _write_log(match_id, raw)
    capsys.readouterr()

    with_units = _score_json(match_id, capsys=capsys)
    without_units = dict(with_units)
    del without_units["units"]

    log = MatchLog.from_jsonl(raw)
    independently_computed = score_match(log, version="v0")
    independently_computed["tempo"] = score_tempo(log, substrates={})
    assert without_units == independently_computed


def test_no_ranking_or_leaderboard_verb_exists_anywhere_in_the_cli() -> None:
    """No cross-match aggregation verb — ``rank``/``leaderboard``/``elo`` (or
    any spelling of them) — is registered under ANY noun, not just match/team.
    ``standings``/``history`` are pre-existing per-team TREND views computed
    from outcome/cooperation only (see ``league/track.py``) — legitimate and
    untouched; this test guards against a NEW grade-based ranking surface."""
    banned = {"rank", "ranking", "ranks", "leaderboard", "elo", "aggregate"}
    parser = _build_parser()
    top_action = parser._subparsers._group_actions[0]
    assert not (set(top_action.choices) & banned)
    for noun, subparser in top_action.choices.items():
        if subparser._subparsers is None:
            continue
        for action in subparser._subparsers._group_actions:
            offenders = set(action.choices) & banned
            assert not offenders, f"{noun!r} noun exposes a ranking verb: {offenders}"


def test_rank_is_not_a_recognized_match_or_team_verb(arena, capsys) -> None:
    """An unrecognized subcommand is an argparse-level failure — routed
    through ``_CliArgumentParser.error()`` (a clean ``SystemExit(1)`` with the
    structured error format), the same path ``test_unknown_command_errors``
    (tests/test_cli.py) pins for a bogus top-level verb."""
    for noun in ("match", "team"):
        capsys.readouterr()
        with pytest.raises(SystemExit) as exc:
            main([noun, "rank"])
        assert exc.value.code == 1
        err = capsys.readouterr().err
        assert err.startswith("error:")
        assert "hint:" in err


def test_grades_modules_are_not_imported_by_any_team_axis_or_trend_module() -> None:
    """The reverse direction of the AST boundary tests.test_grades.py already
    pins (grades.py imports no scoring/tempo/probe module): scoring.py,
    tempo.py, probe.py and track.py (standings/history) must not import
    EITHER grades module either — closing the loop on "grades never feed
    team scores" at the module-dependency level, not just by output diffing."""
    root = Path(__file__).resolve().parent.parent
    banned = {"league.engine.grades", "league.engine.continuous.grades"}
    checked = 0
    for rel in (
        "league/engine/scoring.py",
        "league/engine/tempo.py",
        "league/engine/probe.py",
        "league/track.py",
    ):
        path = root / rel
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        offenders = imported & banned
        assert not offenders, f"{rel} must not import {offenders}"
        checked += 1
    assert checked == 4


# --------------------------------------------------------------------------- #
# Edge case: a continuous match with no units to grade is a clean CliError,
# never an "unexpected: ValueError" leak.
# --------------------------------------------------------------------------- #


def test_continuous_score_of_a_rosterless_match_is_a_clean_cli_error(arena, capsys) -> None:
    import dataclasses

    from league.engine.continuous.events import CMatchLog

    clog = CMatchLog.from_jsonl(RACE_LIVE_LOG.read_text(encoding="utf-8"))
    empty_state = dataclasses.replace(clog.initial_state, units=(), teams=())
    empty_log = CMatchLog(initial_state=empty_state, events=())
    _write_log("c-empty", empty_log.to_jsonl())
    capsys.readouterr()

    rc = main(["match", "score", "c-empty"])
    assert rc == 1
    err = capsys.readouterr().err
    assert err.startswith("error:")
    assert "hint:" in err
    assert "unexpected" not in err.lower()
