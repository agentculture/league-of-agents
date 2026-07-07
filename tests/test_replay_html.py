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
from pathlib import Path

from league.engine.events import MatchLog
from league.engine.scoring import score_match
from league.engine.state import state_hash
from league.replay import build_assessor_guide, build_replay_data, render_html
from tests.test_engine_scoring import _play_match

_PLAYTESTS = Path(__file__).resolve().parent.parent / "docs" / "playtests"


def _committed_log(rel: str) -> MatchLog:
    return MatchLog.from_jsonl((_PLAYTESTS / rel).read_text(encoding="utf-8"))


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


# --------------------------------------------------------------------------- #
# C6-t5 — the embedded assessor guide (spec c6, honesty h6). The replay must
# TEACH a human to judge coordination quality, phase by phase, from THIS
# match's own facts — real turns, unit ids, and mission names, not boilerplate.
# --------------------------------------------------------------------------- #


def test_assessor_guide_is_embedded_in_data_and_panel() -> None:
    """The guide is a first-class fold output and a rendered panel — the same
    server-computed facts flow into build_replay_data and the HTML block."""
    log = _play_match()
    data = build_replay_data(log)
    assert "guide" in data
    guide = data["guide"]
    for section in ("scenario", "phases", "key_moments", "judging", "checklist", "deep_link_turns"):
        assert section in guide, f"missing guide section {section!r}"

    html = render_html(log)
    # The panel renders from M.guide (server-computed), not client recomputation.
    assert "M.guide" in html
    assert 'id="guide"' in html
    # It is a collapsible panel in the wave-0 card system.
    assert "<details" in html and "<summary" in html
    # Embedded JSON carries the guide — same fold, byte-for-byte.
    assert _extract_embedded(html)["guide"] == json.loads(json.dumps(guide))


def test_assessor_guide_scenario_facts_are_derived_from_the_log() -> None:
    """Section (a): objectives, win condition, and roles come from THIS
    scenario + log, not a generic template."""
    guide = build_replay_data(_play_match())["guide"]
    sc = guide["scenario"]
    assert sc["id"] == "skirmish-1"
    assert sc["mode"] == "competitive"
    assert sc["turn_limit"] == 30
    obj_ids = {o["id"] for o in sc["objectives"]}
    assert obj_ids == {"ms-supply", "ms-outpost"}
    supply = next(o for o in sc["objectives"] if o["id"] == "ms-supply")
    assert supply["kind"] == "deliver" and supply["amount"] == 6 and supply["reward"] == 10
    outpost = next(o for o in sc["objectives"] if o["id"] == "ms-outpost")
    assert outpost["kind"] == "hold"
    roles = {r["role"] for r in sc["roles"]}
    assert {"scout", "harvester", "defender"} <= roles
    # The win condition and coordination pressure are real prose, not empty.
    assert "outcome" in sc["win_condition"].lower()
    assert sc["coordination_pressure"]
    assert any("30-turn" in line or "control point" in line for line in sc["coordination_pressure"])


def test_assessor_guide_key_moments_cite_real_turns_units_missions() -> None:
    """Section (b): every key moment is a clickable #tN into a real frame and
    names real entities from this match's log (first capture, mission done)."""
    log = _committed_log("season-0/orchestrator.log.jsonl")
    data = build_replay_data(log)
    moments = data["guide"]["key_moments"]
    assert moments
    frame_turns = {f["turn"] for f in data["frames"]}
    for m in moments:
        assert m["turn"] in frame_turns
        assert m["anchor"] == f"#t{m['turn']}"
    kinds = {m["kind"] for m in moments}
    assert "first_capture" in kinds
    assert "mission_completed" in kinds
    real_missions = {e.data["mission_id"] for e in log.events if e.kind == "mission_completed"}
    completed_titles = " ".join(m["title"] for m in moments if m["kind"] == "mission_completed")
    assert any(mid in completed_titles for mid in real_missions)
    real_cps = {e.data["cp_id"] for e in log.events if e.kind == "control_point_captured"}
    cap_title = next(m["title"] for m in moments if m["kind"] == "first_capture")
    assert any(cp in cap_title for cp in real_cps)


def test_assessor_guide_differs_meaningfully_between_two_committed_logs() -> None:
    """Criterion 1: the guide is match-specific — two different committed logs
    produce guides whose framing, key moments, and judging genuinely diverge."""
    a = build_replay_data(_committed_log("season-0/orchestrator.log.jsonl"))["guide"]
    b = build_replay_data(_committed_log("cycle-5/colleague-coop.log.jsonl"))["guide"]
    # Mode framing differs (competitive vs cooperative win condition).
    assert a["scenario"]["mode"] == "competitive"
    assert b["scenario"]["mode"] == "cooperative"
    assert a["scenario"]["win_condition"] != b["scenario"]["win_condition"]
    # Different teams under judgment.
    assert set(a["judging"]) != set(b["judging"])
    # Key moments land on different turns and describe different play.
    assert [m["turn"] for m in a["key_moments"]] != [m["turn"] for m in b["key_moments"]]
    assert {m["title"] for m in a["key_moments"]} != {m["title"] for m in b["key_moments"]}
    assert a != b


def test_assessor_guide_deep_links_all_resolve_to_real_frames() -> None:
    """Criterion 2: every #tN the guide points at resolves to an existing
    frame — a reviewer can always scrub to it."""
    for rel in ("season-0/orchestrator.log.jsonl", "cycle-5/colleague-coop.log.jsonl"):
        data = build_replay_data(_committed_log(rel))
        frame_turns = {f["turn"] for f in data["frames"]}
        links = data["guide"]["deep_link_turns"]
        assert links, f"guide for {rel} points at no turns"
        for turn in links:
            assert turn in frame_turns, f"deep link #t{turn} has no frame in {rel}"


def test_assessor_guide_has_reviewer_checklist_with_phases_and_anchors() -> None:
    """Criterion 2: the 'how to review' checklist covers opening/midgame/endgame,
    teaches pseudo-coordination vs real delegation and where dead time/collisions
    show, and every item points at concrete scrub turns."""
    data = build_replay_data(_committed_log("season-0/orchestrator.log.jsonl"))
    checklist = data["guide"]["checklist"]
    phases = {c["phase"] for c in checklist}
    assert {"opening", "midgame", "endgame", "pseudo-vs-real", "dead-time"} <= phases
    blob = " ".join(c["check"] for c in checklist).lower()
    assert "pseudo" in blob and "delegation" in blob
    assert "dead time" in blob or "idle" in blob or "collision" in blob
    frame_turns = {f["turn"] for f in data["frames"]}
    referenced = [t for c in checklist for t in c["turns"]]
    assert referenced
    for turn in referenced:
        assert turn in frame_turns


def test_assessor_guide_judging_uses_cooperation_v1_with_match_numbers() -> None:
    """Section (c): the judging block explains the v1 signals with THIS match's
    real numbers, taken straight from score_match(..., version='v1')."""
    log = _committed_log("cycle-5/colleague-coop.log.jsonl")
    guide = build_replay_data(log)["guide"]
    v1 = score_match(log, version="v1")["cooperation"]
    assert set(guide["judging"]) == set(v1)
    for team_id, jt in guide["judging"].items():
        coop = v1[team_id]
        assert jt["cooperation_score"] == coop["score"]
        assert jt["signals"] == coop["signals"]
        assert set(jt["signals"]) == {
            "delegation_spread",
            "message_utility",
            "plan_fidelity",
            "discipline",
        }
        comp = coop["components"]["message_utility"]
        assert jt["message_utility"]["messages"] == comp["messages"]
        assert jt["message_utility"]["useful"] == comp["useful"]
        # The plain-language explanation embeds this match's real counts.
        assert str(comp["useful"]) in jt["message_utility"]["plain"]
        assert str(comp["messages"]) in jt["message_utility"]["plain"]


def test_assessor_guide_teaches_real_vs_pseudo_delegation_via_span() -> None:
    """h6/probe: the guide surfaces span-of-control evidence so a human can tell
    a mind that fielded real subagents from one narrating personas it never
    fielded — the orchestrator log's baseline shows span < roster."""
    guide = build_replay_data(_committed_log("season-0/orchestrator.log.jsonl"))["guide"]
    spans = {tid: jt["span"] for tid, jt in guide["judging"].items()}
    # fable fielded three real seats; baseline's 'delegation' is one mind.
    assert spans["fable"]["span"] == 3
    assert spans["baseline"]["span"] < spans["baseline"]["roster_size"]
    assert "pseudo" in spans["baseline"]["plain"].lower()


def test_assessor_guide_is_byte_deterministic() -> None:
    """Same log → identical guide and identical HTML (no wall-clock/entropy)."""
    log = _committed_log("season-0/orchestrator.log.jsonl")
    assert build_assessor_guide(log) == build_assessor_guide(log)
    assert build_replay_data(log)["guide"] == build_assessor_guide(log)
    assert render_html(log) == render_html(log)
