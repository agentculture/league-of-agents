"""Acceptance tests for the continuous replay face (plan C7-t9, spec c12/c2).

Criteria under test:

1. The race — a faster agent snatching a contested post mid-capture — is
   VISIBLE: the winning ``post_taken`` and the loser's first-class
   ``action_failed`` are both present and carry distinct, assertable CSS
   markers (``race-win`` / ``race-fail``), never merged into one line.
2. The face is byte-deterministic from the log and self-contained (no
   external requests of any kind).
3. Grid replay stays byte-identical to before this task — pinned against a
   hash computed from ``league/replay/html.py`` BEFORE this task touched
   anything (that file is untouched; only the CLI's routing changed).

The race log is built in-test the way ``tests/test_continuous_resolve.py``'s
``_race_state``/``_race_decider`` do it: drive the real ``resolve_match`` on
the committed ``c-skirmish-1`` scenario with scripted deciders, so the log
under test is the engine's own truth, not a hand-authored fixture.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from league.engine.continuous.events import CMatchLog
from league.engine.continuous.resolve import ResolveResult, resolve_match
from league.engine.continuous.scenario import get_cscenario, instantiate
from league.engine.continuous.state import CAgentSlot
from league.engine.events import MatchLog
from league.replay.chtml import build_continuous_replay_data, render_chtml
from league.replay.html import render_html

_PLAYTESTS = Path(__file__).resolve().parent.parent / "docs" / "playtests"

# sha256 of render_html() on this committed grid log: the regression this pins
# is the continuous face (or its CLI routing) bending the grid path, which the
# continuous work must never touch. It is NOT a freeze on the grid face itself:
# a deliberate grid-renderer change (like the cycle-6 restyle, PR #18, which
# moved this pin from 5a1f8919… to its current value) legitimately regenerates
# it — recompute render_html() on the committed log and say so in the PR. The
# same applies one layer down: cycle-8 t10's grid scout eyes-only decision
# (docs/roles.md) changed scout's can_capture from true to false in
# league/engine/scenario.py — render_html() reads role stats live from the
# scenario, not just the log, so this committed log's rendered role-table
# bytes changed even though league/replay/html.py itself did not (moved from
# bfe89f92… to its current value; the log and its scored facts are untouched).
_GRID_LOG_REL = "cycle-5/colleague-coop.log.jsonl"
_GRID_HTML_SHA256 = "f6d5cf31ba116d6edf5508e4cd560092e006df3888d8501e9e33e69734d63e58"


def _committed_grid_log() -> MatchLog:
    return MatchLog.from_jsonl((_PLAYTESTS / _GRID_LOG_REL).read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# The in-test race log: c-skirmish-1, scripted, mirrors
# tests/test_continuous_resolve.py's _race_state/_race_decider pattern.
# --------------------------------------------------------------------------- #


def _pick(menu: dict, kind: str):
    for entry in menu["actions"]:
        if entry["kind"] == kind:
            return entry
    return None


def _pick_move_to(menu: dict, ref: str):
    for entry in menu["actions"]:
        if entry["kind"] == "move" and entry.get("target_ref") == ref:
            return entry
    return None


def _race_decider(unit_id: str, state, menu: dict):
    """The scripted race on c-skirmish-1: blue's defender (``blue-u1``) travels
    to the post and takes it, starting its take LATER than red's harvester
    (``red-u2``, already camped on the post at t=0) but completing FIRST — the
    exact race the brief names: red starts taking cp-crossing at t=0
    (would finish t=10), blue arrives t=2 and completes its own take at t=8."""
    if unit_id == "blue-u1":
        take = _pick(menu, "take_post")
        if take is not None:
            return take
        return _pick_move_to(menu, "cp-crossing")
    if unit_id == "red-u2":
        cp = next(c for c in state.control_points if c.id == "cp-crossing")
        return _pick(menu, "take_post") if cp.owner is None else None
    return None  # blue-u2 (harvester) and red-u1 (defender) park all match


def _race_result() -> ResolveResult:
    scenario = get_cscenario("c-skirmish-1")
    initial = instantiate(
        scenario,
        match_id="cm-race-demo",
        seed=7,
        mode="competitive",
        teams=(
            (
                "blue",
                "Blue Foundry",
                (
                    CAgentSlot(id="blue-u1", model="claude-sonnet-5", role="defender"),
                    CAgentSlot(id="blue-u2", model="claude-sonnet-5", role="harvester"),
                ),
            ),
            (
                "red",
                "Red Relay",
                (
                    CAgentSlot(id="red-u1", model="colleague/qwen", role="defender"),
                    CAgentSlot(id="red-u2", model="colleague/qwen", role="harvester"),
                ),
            ),
        ),
    )
    return resolve_match(initial, scenario.role_table, _race_decider)


def _race_log() -> CMatchLog:
    return _race_result().log


# --------------------------------------------------------------------------- #
# Sanity: the log under test really is the exact race the brief names.
# --------------------------------------------------------------------------- #


def test_race_log_is_the_exact_scripted_race() -> None:
    log = _race_log()
    taken = [e for e in log.events if e.kind == "post_taken"]
    failed = [e for e in log.events if e.kind == "action_failed"]
    assert len(taken) == 1 and taken[0].game_time == 8
    assert taken[0].data == {"cp_id": "cp-crossing", "team_id": "blue", "unit_id": "blue-u1"}
    assert len(failed) == 1 and failed[0].game_time == 8
    assert failed[0].data == {"unit_id": "red-u2", "reason": "post taken by a faster agent"}
    started = {
        (e.data["unit_id"], e.game_time, e.data["completion_time"])
        for e in log.events
        if e.kind == "action_started" and e.data["kind"] == "take_post"
    }
    assert ("red-u2", 0, 10) in started  # camped, starts first, would finish t=10
    assert ("blue-u1", 2, 8) in started  # arrives t=2, finishes first at t=8


# --------------------------------------------------------------------------- #
# Criterion 1 — the race is visible: distinct, assertable markers.
# --------------------------------------------------------------------------- #


def test_the_winning_take_and_losing_attempt_carry_distinct_css_markers() -> None:
    html = render_chtml(_race_log())
    assert 'class="cevt cevt-post_taken cevt-transition race-win"' in html
    assert 'class="cevt cevt-action_failed cevt-transition race-fail"' in html
    # And the two markers are genuinely different classes, not aliases.
    assert "race-win" != "race-fail"
    # The reason text — the loser's first-class record (spec h9) — is on the record.
    assert "post taken by a faster agent" in html
    # Both the winner and loser are named.
    assert "blue-u1" in html and "red-u2" in html and "cp-crossing" in html


def test_race_moments_are_a_first_class_machine_readable_pair() -> None:
    data = build_continuous_replay_data(_race_log())
    kinds = [m["kind"] for m in data["race_moments"]]
    assert kinds == ["post_taken", "action_failed"]
    win, loss = data["race_moments"]
    assert win == {
        "game_time": 8,
        "kind": "post_taken",
        "cp_id": "cp-crossing",
        "team_id": "blue",
        "unit_id": "blue-u1",
    }
    assert loss == {
        "game_time": 8,
        "kind": "action_failed",
        "unit_id": "red-u2",
        "reason": "post taken by a faster agent",
    }


def test_the_race_is_visible_on_the_board_mid_take_not_just_the_feed() -> None:
    """Between blue's take starting (t=2) and the race resolving (t=8), the
    board snapshot must show BOTH units contesting cp-crossing at once — the
    engine represents the race in state (concurrent ``takers``), and the face
    must not collapse that down to only one attempt."""
    data = build_continuous_replay_data(_race_log())
    mid_frame = next(f for f in data["frames"] if f["clock"] == 2)
    cp = next(c for c in mid_frame["control_points"] if c["id"] == "cp-crossing")
    taker_ids = {t["unit_id"] for t in cp["takers"]}
    assert taker_ids == {"blue-u1", "red-u2"}
    assert cp["owner"] is None  # nobody has finished yet at t=2

    final_frame = data["frames"][-1]
    cp_final = next(c for c in final_frame["control_points"] if c["id"] == "cp-crossing")
    assert cp_final["owner"] == "blue" and cp_final["takers"] == []

    html = render_chtml(_race_log())
    # Both units' contested rings are drawn (one dashed ring per taker).
    assert html.count('class="ctaker"') >= 2


def test_event_timeline_lists_every_transition_event_with_its_game_time() -> None:
    from league.engine.continuous.events import TRANSITION_KINDS

    data = build_continuous_replay_data(_race_log())
    transition_events = [e for e in data["events"] if e["kind"] in TRANSITION_KINDS]
    assert transition_events  # non-empty
    html = render_chtml(_race_log())
    for entry in transition_events:
        assert f'<span class="cevt-t">t={entry["game_time"]}</span>' in html


# --------------------------------------------------------------------------- #
# Criterion 2 — byte-determinism and self-containedness.
# --------------------------------------------------------------------------- #


def test_render_is_byte_deterministic() -> None:
    log = _race_log()
    assert render_chtml(log) == render_chtml(log)
    assert build_continuous_replay_data(log) == build_continuous_replay_data(log)
    html = render_chtml(log)
    for banned in ("Date.now(", "Math.random("):
        assert banned not in html


def test_two_fresh_race_replays_agree() -> None:
    """The scripted decider is pure, so two fresh resolves of the same
    scenario+script produce an identical log and identical HTML."""
    assert render_chtml(_race_log()) == render_chtml(_race_log())


def test_projections_agree_html_and_json() -> None:
    log = _race_log()
    html = render_chtml(log)
    match = re.search(
        r'<script id="cmatch-data" type="application/json">(.*?)</script>', html, re.S
    )
    assert match, "embedded cmatch-data block missing"
    embedded = json.loads(match.group(1))
    assert embedded == json.loads(json.dumps(build_continuous_replay_data(log)))


def test_self_contained_no_external_requests() -> None:
    html = render_chtml(_race_log())
    assert html.startswith("<!DOCTYPE html>")
    for needle in ("http://", "https://", "fetch(", "XMLHttpRequest", "@import", "url("):
        assert needle not in html, f"external-request marker {needle!r} found"


def test_unit_glyph_is_escaped_against_hostile_role_names() -> None:
    """The role-derived glyph rides through the same escaping as every other
    log-derived string: a hand-crafted log can put ANY text in a unit's role,
    and the first character of an unknown role becomes the glyph — so a
    hostile role name must never reach the SVG text node unescaped."""
    import dataclasses

    log = _race_log()
    units = tuple(
        dataclasses.replace(u, role="<script>alert(1)</script>") if u.id == "blue-u1" else u
        for u in log.initial_state.units
    )
    hostile_state = dataclasses.replace(log.initial_state, units=units)
    hostile = CMatchLog(
        initial_state=hostile_state, events=log.events, driver_kinds=log.driver_kinds
    )
    html = render_chtml(hostile)
    # The unknown role's first character "<" must render as its entity, never raw.
    assert 'class="cunit-glyph"><</text>' not in html
    assert 'class="cunit-glyph">&lt;</text>' in html
    assert "<script>alert(1)</script>" not in html


def test_output_round_trips_through_disk_unchanged(tmp_path) -> None:
    html = render_chtml(_race_log())
    path = tmp_path / "race.html"
    path.write_text(html, encoding="utf-8")
    assert path.read_text(encoding="utf-8") == html


# --------------------------------------------------------------------------- #
# Criterion 3 — the grid face is untouched.
# --------------------------------------------------------------------------- #


def test_grid_replay_is_byte_identical_to_before_this_task() -> None:
    """league/replay/html.py is on this task's do-not-touch list; this pins
    its output for a committed log against a hash captured before this task
    changed anything, so any future drift (in this task's CLI wiring or
    otherwise) that alters grid replay bytes fails loudly here."""
    html = render_html(_committed_grid_log())
    assert hashlib.sha256(html.encode("utf-8")).hexdigest() == _GRID_HTML_SHA256


def test_continuous_face_does_not_port_the_grid_faces_tween_gif_theme_machinery() -> None:
    """Regression guard: the continuous face must never import/port the grid
    face's tween/GIF/theme machinery (frame v4 pinned scope) — it only reads
    the grid face's validated color constants."""
    import league.replay.chtml as chtml_mod

    assert not hasattr(chtml_mod, "render_html")
    assert not hasattr(chtml_mod, "render_gif")
    html = render_chtml(_race_log())
    assert "theme-toggle" not in html
    assert "STACK_OFFSETS" not in html
