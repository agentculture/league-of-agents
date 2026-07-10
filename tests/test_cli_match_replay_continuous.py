"""CLI wiring for the continuous replay face (plan C7-t9, spec c12/c2).

``league match replay`` is extended, not duplicated into a new verb: the
log's OWN header shape is the authoritative lane signal, so a grid match that
merely named itself ``c-…`` still replays as grid (the
``CONTINUOUS_ID_PREFIX`` naming discipline only picks the error voice when no
log exists to sniff). A grid log falls through to the untouched grid path —
pinned byte-identical here too.

There is no continuous-lane store/creation CLI path yet (persistence is a
later cycle task), so these tests drop a log at the exact path the grid
``Store`` already uses (``.league/matches/<id>/log.jsonl`` — the store is
engine-agnostic about the file's shape, only about where it lives) to
exercise the CLI end to end, the same way a future harness/store task would.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from pathlib import Path

import pytest

from league.cli import main
from league.engine.continuous.events import CMatchLog
from league.engine.events import MatchLog
from league.replay.chtml import build_continuous_replay_data, render_chtml
from league.replay.html import render_html
from tests.test_replay_chtml import _GRID_HTML_SHA256, _GRID_LOG_REL, _PLAYTESTS, _race_log


@pytest.fixture()
def arena(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _write_log(match_id: str, raw: str) -> None:
    d = Path(".league") / "matches" / match_id
    d.mkdir(parents=True)
    (d / "log.jsonl").write_text(raw, encoding="utf-8")


def test_replay_detects_continuous_log_by_shape_even_without_c_prefix(arena, capsys) -> None:
    """A continuous log stored under a match id that does NOT start with 'c-'
    still routes to the continuous face — detection falls back to the log's
    own header shape (clock/width), never trusting naming alone."""
    log = _race_log()
    match_id = log.initial_state.match_id
    assert not match_id.startswith("c-")  # this test is specifically the no-prefix path
    _write_log(match_id, log.to_jsonl())

    assert main(["match", "replay", match_id]) == 0
    out = capsys.readouterr().out
    assert out.startswith("<!DOCTYPE html>")
    assert out == render_chtml(log)  # identical to calling the face directly
    assert "race-win" in out and "race-fail" in out


def test_replay_detects_continuous_log_by_c_prefix(arena, capsys) -> None:
    """A continuous log whose match id follows the 'c-' naming discipline
    routes to the continuous face — via the header sniff, which is
    authoritative for every log on disk; the prefix itself only picks the
    error voice when there is nothing to sniff."""
    log = _race_log()
    c_state = dataclasses.replace(log.initial_state, match_id="c-race-demo")
    c_log = CMatchLog(initial_state=c_state, events=log.events, driver_kinds=log.driver_kinds)
    _write_log("c-race-demo", c_log.to_jsonl())

    assert main(["match", "replay", "c-race-demo"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("<!DOCTYPE html>")
    assert out == render_chtml(c_log)


def test_grid_log_under_a_c_prefixed_id_still_replays_as_grid(arena, capsys) -> None:
    """Naming is never authority: the store's id validator does not reserve
    the 'c-' prefix, so a GRID match that merely named itself 'c-…' must
    still replay through the grid face — the log's own header shape outranks
    the id. Prefix-first routing made such a match unreplayable."""
    raw = (_PLAYTESTS / _GRID_LOG_REL).read_text(encoding="utf-8")
    _write_log("c-actually-grid", raw)

    assert main(["match", "replay", "c-actually-grid"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("<!DOCTYPE html>")
    assert out == render_html(MatchLog.from_jsonl(raw))  # the grid face, byte-identical
    assert "race-fail" not in out


def test_replay_json_mode_for_continuous_log(arena, capsys) -> None:
    log = _race_log()
    match_id = log.initial_state.match_id
    _write_log(match_id, log.to_jsonl())

    assert main(["match", "replay", match_id, "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data == json.loads(json.dumps(build_continuous_replay_data(log)))
    assert data["match_id"] == match_id
    assert data["race_moments"][0]["kind"] == "post_taken"
    assert data["race_moments"][1]["kind"] == "action_failed"


def test_replay_missing_continuous_match_is_a_clean_cli_error(arena, capsys) -> None:
    rc = main(["match", "replay", "c-nope"])
    assert rc == 1
    err = capsys.readouterr().err
    assert err.startswith("error:")
    assert "hint:" in err


# --------------------------------------------------------------------------- #
# `match show`/`match probe` on a continuous log (issue #28 item f): these two
# verbs are grid-lane-only today — a continuous log used to crash them with an
# opaque "unexpected: KeyError: 'turn'" (MatchState.from_dict expecting a grid
# header). They must instead exit non-zero with a clean, structured CliError
# naming the limitation, using the SAME lane-sniff score/replay already route
# on. Full continuous-lane support (new cmatch verbs) is a separate PR.
# --------------------------------------------------------------------------- #


def _minimal_continuous_header(match_id: str) -> str:
    """The smallest header shape ``_sniff_continuous_log`` recognizes as
    continuous-lane (``clock`` present, ``turn`` absent) — no event lines
    needed, since show/probe must refuse before ever trying to fully parse
    the log as either lane's dataclasses."""
    header = {
        "log_version": 1,
        "initial_state": {"match_id": match_id, "clock": 0, "width": 10},
        "driver_kinds": {},
    }
    return json.dumps(header) + "\n"


def test_show_on_a_continuous_log_is_a_clean_cli_error_not_a_traceback(arena, capsys) -> None:
    _write_log("c-minimal", _minimal_continuous_header("c-minimal"))

    rc = main(["match", "show", "c-minimal"])
    assert rc == 1
    err = capsys.readouterr().err
    assert err.startswith("error:")
    assert "hint:" in err
    assert "KeyError" not in err
    assert "Traceback" not in err
    assert "continuous" in err


def test_show_on_a_continuous_log_is_a_clean_cli_error_in_json_mode(arena, capsys) -> None:
    _write_log("c-minimal-json", _minimal_continuous_header("c-minimal-json"))

    rc = main(["match", "show", "c-minimal-json", "--json"])
    assert rc == 1
    err = capsys.readouterr().err
    payload = json.loads(err)
    assert payload["code"] == 1
    assert "continuous" in payload["message"]


def test_probe_on_a_continuous_log_is_a_clean_cli_error_not_a_traceback(arena, capsys) -> None:
    _write_log("c-minimal-probe", _minimal_continuous_header("c-minimal-probe"))

    rc = main(["match", "probe", "c-minimal-probe"])
    assert rc == 1
    err = capsys.readouterr().err
    assert err.startswith("error:")
    assert "hint:" in err
    assert "KeyError" not in err
    assert "Traceback" not in err
    assert "continuous" in err


def test_show_on_a_real_continuous_log_via_the_race_fixture_is_still_clean(arena, capsys) -> None:
    """Same check against a real, fully-formed continuous log (not just a bare
    header) — the race fixture already used elsewhere in this file."""
    log = _race_log()
    _write_log(log.initial_state.match_id, log.to_jsonl())

    rc = main(["match", "show", log.initial_state.match_id])
    assert rc == 1
    err = capsys.readouterr().err
    assert err.startswith("error:")
    assert "hint:" in err


def test_show_and_probe_on_a_grid_log_are_unaffected(arena, capsys) -> None:
    """The lane-sniff must not false-positive on a real grid log — show/probe
    keep working exactly as before."""
    raw = (_PLAYTESTS / _GRID_LOG_REL).read_text(encoding="utf-8")
    match_id = MatchLog.from_jsonl(raw).initial_state.match_id
    _write_log(match_id, raw)

    assert main(["match", "show", match_id]) == 0
    assert main(["match", "probe", match_id]) == 0


# --------------------------------------------------------------------------- #
# The grid path must stay byte-identical — no regression from the new routing.
# --------------------------------------------------------------------------- #


def test_grid_replay_through_cli_is_unchanged_by_the_new_routing(arena, capsys) -> None:
    raw = (_PLAYTESTS / _GRID_LOG_REL).read_text(encoding="utf-8")
    match_id = MatchLog.from_jsonl(raw).initial_state.match_id
    _write_log(match_id, raw)

    assert main(["match", "replay", match_id]) == 0
    out = capsys.readouterr().out
    assert out == render_html(MatchLog.from_jsonl(raw))
    assert hashlib.sha256(out.encode("utf-8")).hexdigest() == _GRID_HTML_SHA256


def test_grid_replay_json_through_cli_is_unaffected(arena, capsys) -> None:
    from league.replay.html import build_replay_data

    raw = (_PLAYTESTS / _GRID_LOG_REL).read_text(encoding="utf-8")
    log = MatchLog.from_jsonl(raw)
    _write_log(log.initial_state.match_id, raw)

    assert main(["match", "replay", log.initial_state.match_id, "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data == json.loads(json.dumps(build_replay_data(log)))


def test_sniff_continuous_log_reads_header_shape_directly() -> None:
    """Unit-level check of the detection primitive itself: continuous headers
    (clock/width) say yes, grid headers (turn/grid_width) and garbage say no."""
    from league.cli._commands.match import _sniff_continuous_log

    clog = _race_log()
    assert _sniff_continuous_log(clog.to_jsonl()) is True

    grid_raw = (_PLAYTESTS / _GRID_LOG_REL).read_text(encoding="utf-8")
    assert _sniff_continuous_log(grid_raw) is False

    assert _sniff_continuous_log("") is False
    assert _sniff_continuous_log("not json at all") is False
    assert _sniff_continuous_log("{}") is False
