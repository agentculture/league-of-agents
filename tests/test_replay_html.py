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
from league.engine.grades import (
    ON_ROLE_MULTIPLIER,
    PURPOSES,
    ROLE_HOME_PURPOSE,
    grade_units,
)
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
    """Team identity is the validated categorical clay (slot 0) vs violet
    (slot 1), stepped per surface — light ``#b65b38``/``#4b3ba6``, dark
    ``#cb6e44``/``#877ae0``. validate_palette.js (recorded in
    docs/replay-design.md) reports ALL CHECKS PASS both modes, worst adjacent
    CVD ΔE 86.7 light / 85.7 dark. Restyled from the old blue/red pair after
    the first human review of cycle 6."""
    html = render_html(_play_match())
    for hexval in ("#b65b38", "#4b3ba6", "#cb6e44", "#877ae0"):
        assert hexval in html, f"validated team hue {hexval} missing"
    # The old team reds are retired entirely (the old blue survives only as a
    # later extra slot, never the team-1 identity).
    assert "#e34948" not in html and "#e66767" not in html
    # Team identity is a categorical slot referenced by role, never raw hex.
    assert "--team-0" in html and "--team-1" in html


def test_status_colors_are_reserved_and_not_team_colors() -> None:
    """Status hues (good/critical) come from the fixed status scale and are
    distinct from the categorical team hues on both surfaces — a status color
    never impersonates a team series (dataviz color-formula)."""
    html = render_html(_play_match())
    assert "#0ca30c" in html  # status good (unchanged, fixed)
    assert "#d03b3b" in html  # status critical (unchanged, fixed)
    # The status hues are a *different* hex than any team hue in either mode.
    for team_hex in ("#b65b38", "#4b3ba6", "#cb6e44", "#877ae0"):
        assert "#d03b3b" != team_hex and "#0ca30c" != team_hex


def test_light_is_cream_and_dark_is_black_green() -> None:
    """The two first-class surfaces after the cycle-6 human review: light =
    Anthropic cream (warm paper + warm near-black ink), dark = Culture
    black-green (deep green-tinged black + green-tinged elevation)."""
    html = render_html(_play_match())
    assert "--plane: #f0eee5" in html and "--surface: #faf8f1" in html  # cream
    assert "--ink: #242019" in html  # warm near-black ink
    assert "--plane: #0c1210" in html and "--surface: #111a16" in html  # black-green
    assert "--ink: #eaf1ec" in html  # green-tinged near-white ink


def test_chrome_accent_is_distinct_chrome_not_a_team() -> None:
    """A restrained green ``--accent`` dresses chrome only (play button, slider,
    links) — light ``#1e7a4d`` / dark ``#46c79e`` (WCAG link contrast 4.6:1
    light / 8.4:1 dark) — and is never a team hue."""
    html = render_html(_play_match())
    assert "--accent: #1e7a4d" in html and "--accent: #46c79e" in html
    # Transport chrome references the accent token, not a team slot.
    assert "accent-color: var(--accent)" in html
    assert "background: var(--accent)" in html
    for team_hex in ("#b65b38", "#4b3ba6", "#cb6e44", "#877ae0"):
        assert "#1e7a4d" != team_hex and "#46c79e" != team_hex


def test_motion_is_present_and_gated_by_reduced_motion() -> None:
    """Purposeful motion ships — smooth unit movement between turns and
    celebratory keyframes — but every bit of it is disabled under
    ``prefers-reduced-motion: reduce``."""
    html = render_html(_play_match())
    assert "@keyframes" in html  # celebratory animation defined
    assert "transition:" in html  # smooth interpolation between turns
    # Units glide via a transform transition between frames.
    assert "transform" in html and "--move-dur" in html
    # And all of it is honoured off under reduced motion.
    assert "prefers-reduced-motion: reduce" in html


def test_playback_is_linear_gapless_and_paused_snaps() -> None:
    """Smooth-motion fix from the first human review of cycle 6: the reviewer
    saw a per-turn accelerate–decelerate lurch. The old glide used one eased
    transition scaled to 0.72x the interval, so every turn eased in, eased out,
    then paused. Playback now drives the glide with LINEAR timing whose duration
    equals the turn-advance interval (gapless, continuous waypoint-to-waypoint
    flow); a paused step snaps with a short eased transition; reduced motion
    collapses both to instant."""
    html = render_html(_play_match())
    # The glide reads duration + easing from tokens the JS flips by play state.
    assert "transition: transform var(--move-dur) var(--move-ease)" in html
    # Playing: linear, duration == the interval (SPEEDS[speed]).
    assert "'--move-ease', 'linear'" in html
    assert "SPEEDS[String(speed)] + 'ms'" in html
    # Paused: a short eased snap.
    assert "cubic-bezier(.34, .03, .24, 1)" in html
    # The old ease-scaled single duration is gone.
    assert "0.72" not in html
    assert "prefers-reduced-motion: reduce" in html


def test_side_panel_is_a_tabbed_deck() -> None:
    """Layout fix from the first human review of cycle 6: the reviewer had to
    scroll between the board and the assessor guide. The guide moved out of a
    bottom ``<details>`` into a tabbed side deck (Guide / Events / Teams /
    Score / Scorecard — the fifth tab is cycle-8 t8's per-unit scorecard) that
    uses the width and keeps the board in view. Tabs are real,
    keyboard-accessible buttons with aria-selected + roving tabindex; the guide
    is the default tab."""
    html = render_html(_play_match())
    assert 'role="tablist"' in html
    assert html.count('class="tab"') == 5  # five tab buttons (panels are .tabpanel)
    for pid in ("panel-guide", "panel-events", "panel-teams", "panel-score", "panel-scorecard"):
        assert f'id="{pid}"' in html
    assert 'aria-selected="true"' in html  # one tab starts selected
    assert 'id="tab-guide"' in html and "selectTab('guide'" in html
    # No bottom <details> guide panel anymore.
    assert "<details" not in html
    # The guide body and the feed/teams/scores/scorecard mounts still exist
    # for the server-computed content to render into.
    for mount in ("guide-body", "feed", "teams", "scores", "scorecard"):
        assert f'id="{mount}"' in html


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
    for section in (
        "scenario",
        "phases",
        "key_moments",
        "judging",
        "scorecard",
        "checklist",
        "deep_link_turns",
    ):
        assert section in guide, f"missing guide section {section!r}"

    html = render_html(log)
    # The panel renders from M.guide (server-computed), not client recomputation.
    assert "M.guide" in html
    # It is the default tab in the side deck (not a bottom <details> anymore).
    assert 'id="panel-guide"' in html and 'id="guide-body"' in html
    assert 'id="tab-guide"' in html and 'role="tablist"' in html
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


# --------------------------------------------------------------------------- #
# C8-t4 — the generative ambient score (spec c17, honesty h10/h12): WebAudio
# synthesis at play time, seeded from data already in the page, OFF by
# default. The rendered document stays byte-deterministic and self-contained;
# enabling the score is runtime behavior only and never changes the bytes.
# --------------------------------------------------------------------------- #

# The user's mood brief, verbatim — what the next human review rates against.
_MOOD_TARGET = "content and relaxed, but also curious and intrigued"


def test_ambient_audio_toggle_ships_in_transport_off_by_default() -> None:
    """Acceptance: a visible, accessible toggle in the transport, OFF by
    default — the off state is in the document's own bytes, and the control
    wears the transport's existing idiom (a real button, accent on-state)."""
    html = render_html(_play_match())
    btn = re.search(r'<button id="btn-audio".*?>', html, re.S)
    assert btn, "audio toggle button missing"
    tag = btn.group(0)
    assert 'aria-pressed="false"' in tag  # OFF by default, in the bytes
    assert "aria-label=" in tag  # accessible name
    # It lives in the board card's controls row (the transport bar) and wears
    # the same accent on-state as the play button — chrome, never a team hue.
    assert html.index('class="controls"') < btn.start() < html.index('id="match-data"')
    assert "#btn-play.on, #btn-audio.on" in html


def test_ambient_audio_is_synthesized_webaudio_never_an_asset() -> None:
    """Acceptance: no audio file, no external request — the score is WebAudio
    synthesis at play time (oscillators, gains, a filter, and a convolver
    whose impulse response is itself synthesized, never fetched)."""
    html = render_html(_play_match())
    for prim in ("createOscillator", "createGain", "createBiquadFilter", "createConvolver"):
        assert prim in html, f"WebAudio primitive {prim} missing"
    for banned in ("<audio", "data:audio", ".mp3", ".ogg", ".wav"):
        assert banned not in html, f"audio-asset marker {banned!r} found in replay"


def test_ambient_audio_is_seeded_from_page_data_and_lazy() -> None:
    """Acceptance: the score is seeded from data already in the page (match id
    + seed) through a small deterministic PRNG — same match, same music — and
    the AudioContext is created lazily on the enabling gesture, never at load
    (browser autoplay policy, and audio must stay off by default)."""
    html = render_html(_play_match())
    assert "mulberry32" in html
    assert "audioSeed" in html
    assert "M.match_id + '|' + M.seed" in html
    for banned in ("Math.random(", "Date.now("):
        assert banned not in html
    # Exactly one construction site, inside the enable path only.
    assert html.count("new (window.AudioContext") == 1


def test_guide_carries_the_ambient_mood_brief() -> None:
    """Acceptance: the mood brief is written into the guide as what the
    reviewer should rate — quoted verbatim — with the seeding provenance
    naming THIS match, so the determinism claim is checkable in-page."""
    log = _play_match()
    listening = build_replay_data(log)["guide"]["listening"]
    assert listening["mood_target"] == _MOOD_TARGET
    assert log.initial_state.match_id in listening["how"]
    assert str(log.initial_state.seed) in listening["how"]
    html = render_html(log)
    assert _MOOD_TARGET in html
    assert "G.listening" in html  # the guide renderer lays the section out


def test_ambient_audio_keeps_the_document_deterministic_and_offline() -> None:
    """Acceptance: the document stays byte-deterministic and self-contained —
    the score is runtime synthesis, so nothing about it (enabled or not) can
    change the rendered bytes, and no external reference sneaks in with it."""
    log = _play_match()
    a, b = render_html(log), render_html(log)
    assert a == b
    body = a.split("</head>", 1)[1].replace("http://www.w3.org/2000/svg", "")
    for needle in ("http://", "https://", "fetch(", "XMLHttpRequest", "@import", "url("):
        assert needle not in body, f"external-request marker {needle!r} found in replay body"


# --------------------------------------------------------------------------- #
# C8-t8 — the replay surfaces the scorecard (spec c6/h6, c2/h15): MVP/LVP and
# per-unit grades in a Scorecard deck tab, plus a guide section that explains
# EXACTLY what the grade weighs. The reviewer test: payload, replay and guide
# alone name the best/worst unit and why — the deck renders every unit's
# breakdown, the guide names the buckets, event kinds, multiplier, tie-break.
# --------------------------------------------------------------------------- #


def test_scorecard_is_embedded_ranked_and_complete() -> None:
    """The payload carries a scorecard computed from the log alone via
    grade_units: every rostered unit, ranked by grade descending with the
    canonical (team_id, unit_id) tie-break, each with its full per-purpose
    breakdown — and the embedded JSON is the same fold, byte-comparable."""
    log = _committed_log("cycle-5/colleague-coop.log.jsonl")
    data = build_replay_data(log)
    sc = data["scorecard"]
    grades = grade_units(log)

    expected_order = sorted(
        grades["units"],
        key=lambda uid: (-grades["units"][uid]["grade"], grades["units"][uid]["team_id"], uid),
    )
    assert [u["unit_id"] for u in sc["units"]] == expected_order
    assert sc["purposes"] == list(PURPOSES)
    for u in sc["units"]:
        entry = grades["units"][u["unit_id"]]
        assert u["team_id"] == entry["team_id"]
        assert u["role"] == entry["role"]
        assert u["grade"] == entry["grade"]
        assert u["breakdown"] == entry["breakdown"]
        assert set(u["breakdown"]) == set(PURPOSES)  # every unit's FULL breakdown
    ranked_grades = [u["grade"] for u in sc["units"]]
    assert ranked_grades == sorted(ranked_grades, reverse=True)

    # MVP/LVP flags name the exact units grade_units names.
    assert sc["mvp"] == grades["mvp"] and sc["lvp"] == grades["lvp"]
    assert next(u["unit_id"] for u in sc["units"] if u["mvp"]) == grades["mvp"]["unit_id"]
    assert next(u["unit_id"] for u in sc["units"] if u["lvp"]) == grades["lvp"]["unit_id"]

    html = render_html(log)
    assert _extract_embedded(html)["scorecard"] == json.loads(json.dumps(sc))


def test_scorecard_tab_ships_in_the_deck() -> None:
    """A fifth tab, matching the deck's existing tab idiom exactly: a real
    role=tab button wired to a hidden-toggling panel, rendered by a draw
    function that lays out the server-computed M.scorecard (never client
    recomputation), with every unit's breakdown rendered."""
    html = render_html(_play_match())
    assert 'id="tab-scorecard"' in html
    assert 'aria-controls="panel-scorecard"' in html
    assert 'id="panel-scorecard"' in html
    assert 'id="scorecard"' in html  # the mount the draw function fills
    assert "M.scorecard" in html and "drawScorecard" in html
    # The deck renders every unit row and every purpose cell from the fold.
    assert "SC.units.forEach" in html and "SC.purposes.forEach" in html


def test_scorecard_mvp_lvp_chips_reuse_the_chip_vocabulary() -> None:
    """MVP and LVP ride the existing chip vocabulary (the winner-chip
    precedent): a .chip with a status hue and a text label, never a team
    color, and the flags come from the same fold grade_units produced."""
    html = render_html(_play_match())
    assert "'chip sc-chip-mvp', 'MVP'" in html
    assert "'chip sc-chip-lvp', 'LVP'" in html
    assert ".sc-chip-mvp { color: var(--good)" in html
    assert ".sc-chip-lvp { color: var(--critical)" in html


def test_scorecard_marks_the_home_purpose_visibly() -> None:
    """Each unit row makes its HOME purpose visually obvious — the on-role
    bucket wears the sc-home emphasis plus a ×N tag naming the multiplier —
    and the payload's home_purpose matches the engine's own role mapping."""
    html = render_html(_play_match())
    assert "sc-home" in html
    assert "u.home_purpose === p" in html  # the home purpose is the marked one
    data = build_replay_data(_play_match())
    sc = data["scorecard"]
    assert sc["on_role_multiplier"] == ON_ROLE_MULTIPLIER
    for u in sc["units"]:
        assert u["home_purpose"] == ROLE_HOME_PURPOSE.get(u["role"])


def test_guide_scorecard_names_the_weights_and_the_verdict() -> None:
    """The guide explains EXACTLY what the grade weighs: the four buckets, the
    event kinds that feed them, the on-role ×2 multiplier and the MVP/LVP
    tie-break — and its verdict names THIS match's best and worst unit and
    why, so guide + deck alone answer the reviewer test."""
    log = _committed_log("cycle-5/colleague-coop.log.jsonl")
    guide = build_replay_data(log)["guide"]
    sc = guide["scorecard"]

    # The exact multiplier sentence (spec c10 — the user's own framing).
    assert (
        "A contribution on the unit's own role's home purpose counts ×2 (double); "
        "the identical contribution made off-role counts ×1 — still more than zero, "
        "always less than on-role."
    ) in sc["weights"]
    # The exact tie-break sentence.
    assert sc["tie_break"] == (
        "MVP is the unit with the highest grade, LVP the lowest; ties break "
        "canonically, ascending by (team_id, unit_id)."
    )
    # Every bucket AND the event kinds that feed it, named.
    for needle in (
        "economy",
        "control",
        "recon",
        "coordination",
        "resource_gathered",
        "resource_delivered",
        "control_point_captured",
        "control_point_held",
        "unit_moved",
        "message_sent",
    ):
        assert needle in sc["what"], f"guide scorecard section never names {needle!r}"

    # The verdict names this match's own MVP and LVP, with grades (the why).
    grades = grade_units(log)
    assert "MVP" in sc["verdict"] and "LVP" in sc["verdict"]
    assert grades["mvp"]["unit_id"] in sc["verdict"]
    assert grades["lvp"]["unit_id"] in sc["verdict"]
    assert str(grades["mvp"]["grade"]) in sc["verdict"]

    html = render_html(log)
    assert "G.scorecard" in html  # the guide renderer lays the section out


def test_scorecard_styles_ship_in_both_themes() -> None:
    """The scorecard chrome wears theme tokens only (no raw hex of its own),
    so both deliberately-designed themes style it — and the tokens it leans on
    exist in the fixed status scale and in both manual-override blocks."""
    html = render_html(_play_match())
    rules = re.findall(r"\.sc-[a-zA-Z0-9-]+[^{]*\{[^}]*\}", html)
    assert rules, "scorecard styles missing"
    blob = " ".join(rules)
    for token in ("var(--good)", "var(--critical)", "var(--ink)"):
        assert token in blob
    assert "#" not in blob  # tokens only — themed automatically in both modes
    # The status tokens are the fixed scale; the ink/chip tokens are
    # re-declared by both manual theme blocks, so the toggle wins both ways.
    assert "--good: #0ca30c" in html and "--critical: #d03b3b" in html
    for block in (':root[data-theme="dark"]', ':root[data-theme="light"]'):
        seg = html.split(block, 1)[1].split("}", 1)[0]
        assert "--ink" in seg and "--chip" in seg
