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


def test_stack_offsets_beyond_four_units_do_not_reuse_positions() -> None:
    """Human-review regression (Qodo 3534115613): STACK_OFFSETS only has
    patterns for 1-4 units, but a cell can hold more (3 units/team, 6 total,
    e.g. the deliver square doubling as a control point). The old
    ``offs[i % offs.length]`` clamped the pattern index to 4 and then wrapped
    with modulo, so a 5th/6th unit landed on an already-occupied offset and
    was occluded again — violating "nothing is ever occluded"."""
    from league.replay.html import _TEMPLATE

    # No index-wrapping reuse of offsets — every unit in a stack gets its own.
    assert "% offs.length" not in _TEMPLATE
    # The general case computes n distinct offsets on a circle, deterministically.
    assert "Math.cos(angle)" in _TEMPLATE and "Math.sin(angle)" in _TEMPLATE
    assert "(2 * Math.PI * i) / n - Math.PI / 2" in _TEMPLATE
    # The predefined aesthetic table is still used for the common n<=4 cases.
    assert "n <= STACK_OFFSETS.length ? STACK_OFFSETS[n - 1]" in _TEMPLATE


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


def test_both_themes_are_deliberately_designed() -> None:
    """C6-t4: dark is a *selected* set of steps, not an auto-flip — both themes
    carry their own surface, ink, and elevation tokens, and the manual toggle
    wins in both directions (a ``data-theme`` block per theme, not only the
    media query)."""
    html = render_html(_play_match())
    # Every theme block re-declares the load-bearing tokens (surface + ink +
    # elevation), so neither theme is a partial override of the other.
    for block in ("prefers-color-scheme: dark", ':root[data-theme="dark"]'):
        seg = html.split(block, 1)[1].split("}", 1)[0]
        assert "--surface" in seg and "--ink" in seg
    light_block = html.split(':root[data-theme="light"]', 1)[1].split("}", 1)[0]
    assert "--surface" in light_block and "--ink" in light_block
    # Depth is a designed, per-theme token (elevation differs light vs dark).
    assert "--shadow" in html


def test_team_colors_are_the_validated_categorical_hues() -> None:
    """C6-t4: team identity is the validated categorical pair (blue/red),
    stepped per surface — light ``#2a78d6``/``#e34948``, dark
    ``#3987e5``/``#e66767`` (validate_palette.js: all six checks PASS both
    modes)."""
    html = render_html(_play_match())
    for hexval in ("#2a78d6", "#e34948", "#3987e5", "#e66767"):
        assert hexval in html, f"validated team hue {hexval} missing"
    # Team identity is a categorical slot referenced by role, never raw hex.
    assert "--team-0" in html and "--team-1" in html


def test_status_colors_are_reserved_and_not_team_colors() -> None:
    """C6-t4: status hues (good/critical) come from the fixed status scale and
    are distinct from the categorical team hues — a status color never
    impersonates a team series (dataviz color-formula)."""
    html = render_html(_play_match())
    assert "#0ca30c" in html  # status good
    assert "#d03b3b" in html  # status critical
    # The status reds are a *different* hex than either team red.
    assert "#d03b3b" != "#e34948" and "#d03b3b" != "#e66767"


def test_motion_is_present_and_gated_by_reduced_motion() -> None:
    """C6-t4: purposeful motion ships — smooth unit movement between turns and
    celebratory keyframes — but every bit of it is disabled under
    ``prefers-reduced-motion: reduce``."""
    html = render_html(_play_match())
    assert "@keyframes" in html  # celebratory animation defined
    assert "transition:" in html  # smooth interpolation between turns
    # Units glide via a transform transition between frames.
    assert "transform" in html and "--move" in html
    # And all of it is honoured off under reduced motion.
    assert "prefers-reduced-motion: reduce" in html


def test_playback_speed_control_ships() -> None:
    """C6-t4: play/pause plus an adjustable speed (the directive's transport)."""
    html = render_html(_play_match())
    assert "btn-play" in html
    assert "data-speed" in html


def test_replay_render_is_byte_deterministic() -> None:
    """C6-t4 merge gate: the same log renders byte-identical HTML — no
    ``Date.now``/``Math.random`` leaks into generation, so a committed replay is
    reproducible."""
    log = _play_match()
    assert render_html(log) == render_html(log)
    # And no wall-clock / entropy source is baked into the generated document.
    html = render_html(log)
    for banned in ("Date.now(", "Math.random("):
        assert banned not in html, f"non-deterministic source {banned} in replay"


def test_board_marks_never_paint_text_with_team_color() -> None:
    """dataviz marks-and-anatomy: text wears text tokens; identity rides a
    colored *mark* beside the text, never the text fill itself. The score
    header names teams in ink with a swatch, not in team color."""
    from league.replay.html import _TEMPLATE

    # The old header coloured the team name text with the team hue — regression
    # guard that it does not come back.
    assert "color:${teamColor(t.id)}" not in _TEMPLATE
    assert 'style="color:${teamColor' not in _TEMPLATE
