"""Wave-2 acceptance tests for the HTML replay (plan task t8).

Criteria under test:

* a single self-contained file — no external requests of any kind;
* the HTML and JSON projections render from the same log and agree on every
  turn's facts (the embedded data block IS the fold, byte-comparable);
* both themes ship (prefers-color-scheme default + manual override).
"""

from __future__ import annotations

import json
import re

from league.engine.scoring import score_match
from league.engine.state import state_hash
from league.replay import build_replay_data, render_html
from tests.test_engine_scoring import _play_match


def _extract_embedded(html: str) -> dict:
    match = re.search(r'<script id="match-data" type="application/json">(.*?)</script>', html, re.S)
    assert match, "embedded match-data block missing"
    return json.loads(match.group(1))


def test_single_file_no_external_requests() -> None:
    html = render_html(_play_match())
    assert html.startswith("<!DOCTYPE html>")
    # The SVG namespace URI is an identifier, not a request — allow exactly it.
    body = html.split("</head>", 1)[1].replace("http://www.w3.org/2000/svg", "")
    for needle in ("http://", "https://", "fetch(", "XMLHttpRequest", "@import", "url("):
        assert needle not in body, f"external-request marker {needle!r} found in replay body"


def test_projections_agree_on_every_turn(tmp_path) -> None:
    log = _play_match()
    html = render_html(log)
    embedded = _extract_embedded(html)
    data = build_replay_data(log)
    assert embedded == json.loads(json.dumps(data))  # same fold, same facts

    # Frame facts line up with the log's own fold, turn by turn.
    final = log.final_state()
    last = embedded["frames"][-1]
    assert last["turn"] == final.turn
    assert last["status"] == final.status
    assert last["winner"] == final.winner
    assert {u["id"]: tuple(u["pos"]) for u in last["units"]} == {u.id: u.pos for u in final.units}
    assert embedded["scores"] == json.loads(json.dumps(score_match(log)))

    # And the replay artifact round-trips through disk unchanged.
    path = tmp_path / "match.html"
    path.write_text(html, encoding="utf-8")
    assert _extract_embedded(path.read_text(encoding="utf-8")) == embedded


def test_frames_are_cumulative_folds() -> None:
    log = _play_match()
    data = build_replay_data(log)
    assert data["frames"][0]["turn"] == log.initial_state.turn
    assert len(data["frames"]) == len({e.turn for e in log.events}) + 1
    # Deterministic: building twice yields identical data.
    assert data == build_replay_data(log)
    assert state_hash(log.final_state()) == state_hash(log.final_state())


def test_user_controlled_fields_are_escaped_in_the_template() -> None:
    """Regression guard for stored XSS: no raw interpolation of user fields."""
    from league.replay.html import _TEMPLATE

    for raw in (
        "${t.name}",
        "${a.id}",
        "${a.model}",
        "${t.id} ·",
        "${d.team_id}",
        "${d.unit_id}",
        "${d.from}",
        "${d.cp_id}",
        "${d.mission_id}",
        "${d.reason}",
    ):
        assert raw not in _TEMPLATE, f"unescaped interpolation {raw!r} in replay template"


def test_stacked_units_fan_out_instead_of_occluding() -> None:
    """Human-review regression (season-0 h15): co-located units must all stay
    visible — the reviewer lost the scout under a defender and both carrying
    harvesters under the defenders parked on the shared delivery cell."""
    from league.replay.html import _TEMPLATE

    assert "STACK_OFFSETS" in _TEMPLATE
    # The renderer must group living units per cell before drawing.
    assert "byCell" in _TEMPLATE
    # Solitary units keep the full 12px radius; stacked ones shrink, never hide.
    assert "stack.length > 1 ? 9 : 12" in _TEMPLATE


def test_mission_targets_are_labeled_with_owner_on_completion() -> None:
    """Human-review regression (season-0 h15): the delivery square sits on a
    capturable control point, so an unlabeled drop ring read as 'delivering to
    the enemy base'. Every mission is labeled, and a completed one names and
    wears the color of the team that actually earned it — or lists every
    winner of a dual-award dead-heat (spec decision c15)."""
    from league.replay.html import _TEMPLATE

    assert "${m.id}: ${m.kind} ${m.amount}" in _TEMPLATE
    assert "${m.id} → ${m.completed_by.join(' + ')}" in _TEMPLATE
    assert "teamColor(m.completed_by[0])" in _TEMPLATE


def test_dual_award_missions_render_for_both_teams() -> None:
    """A dead-heat mission (spec decision c15) lists both winners and counts
    toward BOTH teams' mission tallies in the replay."""
    from league.replay.html import _TEMPLATE
    from tests.test_engine_scoring import _dead_heat_log

    data = build_replay_data(_dead_heat_log())
    supply = next(m for m in data["frames"][-1]["missions"] if m["id"] == "ms-supply")
    assert supply["status"] == "completed"
    assert supply["completed_by"] == ["blue", "red"]
    # The team panel counts missions by membership, never by identity —
    # a dual award shows up on both cards.
    assert "m.completed_by.includes(t.id)" in _TEMPLATE


def test_both_themes_ship() -> None:
    html = render_html(_play_match())
    assert "prefers-color-scheme: dark" in html
    assert 'data-theme="dark"' in html
    assert 'data-theme="light"' in html
    assert "theme-toggle" in html
