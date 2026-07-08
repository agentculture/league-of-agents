"""Render a continuous match log as a self-contained HTML replay — the match
played back in full, movement and all (frame v5).

Frame v4 (plan C7-t9, spec c12/c2) shipped this face as *minimal-but-real*: a
static sequence of key-moment board snapshots, with the playback
generalization deliberately parked for a later cycle. The cycle-8 human
review un-parked it — the reviewer, watching the first fogged live match on
this face, on the record: "I can only see key moments and not a full replay /
video of the movements. We need full repeat." Frame v5 is that full replay:

* a **playable board** — one inline SVG redrawn along a continuous game-time
  clock, with a transport (play/pause, a scrubber over the whole match, step
  buttons that land on the old key moments, 0.5×–4× speed). A moving unit
  glides along the straight line its own action record names — the engine's
  ``CAction`` carries ``start_time``/``completion_time``/``target_pos``
  precisely so a replay can interpolate a move (see
  ``league/engine/continuous/state.py``); position between those instants is
  linear interpolation of exactly that record, never a recomputed rule. A
  contested control point still draws one dashed ring per concurrent taker
  (``CControlPoint.takers``), now at the moment playback reaches the race —
  and mission sites are drawn (a dashed square + id), so a delivery contest
  converges somewhere the eye can see;
* the **audio layer** (cycle-8 c17 + the audio-events amendment, inherited
  the moment this face grew a transport): the same seeded ambient bed the
  grid face plays — the seed is ``fnv1a(match_id + "|" + seed)`` in BOTH
  faces, so one match sounds the same everywhere — plus the event-motif
  layer, injected verbatim from :data:`league.replay.audio.EVENT_SOUND` (ONE
  canonical table, now three renderers) with
  :data:`league.replay.audio.CONTINUOUS_EVENT_SOUND_ALIAS` mapping this
  lane's kinds onto it (a won post IS a capture, a denial IS a rejection).
  OFF by default behind the transport's note toggle; motifs fire only when
  the advancing clock crosses an event — scrubbing and jumping are
  navigation, not time passing, and never replay skipped events;
* an **event timeline** — every event in canonical ``(game_time, seq)``
  order; ``post_taken`` rows carry the ``race-win`` marker, ``action_failed``
  rows the ``race-fail`` marker (two unmistakably distinct moments, never
  merged), and every row is a seek target — click it and the board jumps to
  that instant;
* a **header** and a **scorecard** (cycle-8 t8, spec c6/h6) — unchanged:
  server-rendered, static, the per-unit grades from
  :func:`league.engine.continuous.grades.cgrade_units` with MVP/LVP marked
  and one plain-text paragraph explaining exactly what the grade weighs.

The two-lane honesty (spec c11/h11) still holds: grid logs render through
the untouched grid face (its bytes are pinned), and this module imports only
the grid face's validated palette constants plus the lane-neutral audio
table — none of ``html.py``'s own machinery.

Determinism and self-containedness (matching the repo's replay conventions,
``docs/replay-design.md``): every byte here comes from the log via
``fold_events``/``apply_event`` — the event log is the single source of
truth, and this module never recomputes game logic, only formats it. No
``Date.now``/``Math.random``, no external request of any kind (no
``http(s)://``, ``fetch``, ``@import``, remote font/CDN) — a single
self-contained file, byte-identical for the same log, every time. Playback
wall-clock (``requestAnimationFrame`` timestamps, ``AudioContext`` time) is
runtime-only and never reaches the document's bytes.
"""

from __future__ import annotations

import json
from html import escape as _esc
from typing import Any

from league.engine.continuous.events import TRANSITION_KINDS, CMatchLog, fold_events
from league.engine.continuous.grades import (
    GRADE_UNIT,
    MOVE_POINTS_PER_BOARD_UNIT,
    OFF_ROLE_DEN,
    OFF_ROLE_NUM,
    POST_TAKEN_POINTS,
)
from league.engine.continuous.grades import PURPOSES as GRADE_PURPOSES
from league.engine.continuous.grades import (
    cgrade_units,
)
from league.engine.continuous.resolve import outcome_points
from league.engine.continuous.space import format_units
from league.engine.continuous.state import CMatchState
from league.replay.audio import CONTINUOUS_EVENT_SOUND_ALIAS, EVENT_SOUND
from league.replay.html import RESOURCE_COLOR, STATUS_CRITICAL, STATUS_GOOD, TEAM_COLORS

# Board render scale: the longer board edge maps to this many pixels; padding
# keeps markers off the frame edge. Pure presentation constants — never used
# in any comparison/decision (the engine's own milliunits stay the exact
# source of truth).
_BOARD_MAX_PX = 480
_BOARD_PAD_PX = 18
_UNIT_R = 10
_CP_R = 15
_NODE_R = 9
_MS_R = 12  # mission-marker half-size (frame v5 — the standoff square is watchable)

# The same geometry, handed to the page's own renderer: the client redraws
# the board along the playback clock with EXACTLY the constants the static
# starting frame was server-rendered with — one source, two drawers, no
# eyeballed second geometry.
_GEO = {
    "max_px": _BOARD_MAX_PX,
    "pad_px": _BOARD_PAD_PX,
    "unit_r": _UNIT_R,
    "cp_r": _CP_R,
    "node_r": _NODE_R,
    "ms_r": _MS_R,
}

# Presentational glyph convention, mirrored from the grid face's own mapping
# (``league/replay/html.py``'s ``GLYPH`` table) for a consistent look across
# both faces — a display convention, not game logic.
_ROLE_GLYPH = {"scout": "S", "harvester": "H", "defender": "D", "striker": "K", "support": "U"}

_TRANSITION = "transition"
_OBSERVATION = "observation"


# --------------------------------------------------------------------------- #
# The fold: every fact the face shows, derived from the log alone.
# --------------------------------------------------------------------------- #


def _snapshot(state: CMatchState) -> dict[str, Any]:
    """A serializable board snapshot — every field taken straight from the
    state's own canonical ``to_dict()``, never recomputed here."""
    return {
        "clock": state.clock,
        "status": state.status,
        "winner": state.winner,
        "teams": [t.to_dict() for t in state.teams],
        "units": [u.to_dict() for u in state.units],
        "control_points": [c.to_dict() for c in state.control_points],
        "missions": [m.to_dict() for m in state.missions],
        "resource_nodes": [r.to_dict() for r in state.resource_nodes],
    }


def _ordered_events(log: CMatchLog) -> list:
    """The log in its canonical ``(game_time, seq)`` order — the same total
    order the resolver's timeline breaks ties by. The resolver already emits
    in this order, but a renderer must never *trust* submission order, so this
    re-sorts explicitly (mirrors the engine's own tie-break discipline)."""
    return sorted(log.events, key=lambda e: (e.game_time, e.seq))


def _frames(log: CMatchLog) -> list[dict[str, Any]]:
    """One board snapshot per distinct game time, folded cumulatively — the
    continuous analog of the grid replay's per-turn frames
    (``league/replay/html.py``'s ``build_replay_data``)."""
    initial = log.initial_state
    grouped: dict[int, list] = {}
    for event in _ordered_events(log):
        grouped.setdefault(event.game_time, []).append(event)
    frames = [_snapshot(initial)]
    state = initial
    for t in sorted(grouped):
        state = fold_events(state, grouped[t])
        frames.append(_snapshot(state))
    return frames


def _event_entries(log: CMatchLog) -> list[dict[str, Any]]:
    return [
        {
            "game_time": e.game_time,
            "seq": e.seq,
            "kind": e.kind,
            "data": dict(e.data),
            "class": _TRANSITION if e.kind in TRANSITION_KINDS else _OBSERVATION,
        }
        for e in _ordered_events(log)
    ]


def _race_moments(log: CMatchLog) -> list[dict[str, Any]]:
    """The machine-readable race record: every ``post_taken`` (a win) and
    ``action_failed`` (a loss, first-class per spec h9) event, in order — the
    exact pair the acceptance criterion needs legible."""
    out = []
    for e in _ordered_events(log):
        if e.kind in ("post_taken", "action_failed"):
            out.append({"game_time": e.game_time, "kind": e.kind, **e.data})
    return out


def build_continuous_replay_data(log: CMatchLog) -> dict[str, Any]:
    """Everything the continuous replay face shows, derived from the log and
    nothing else — the same fold the HTML and ``--json`` projections share."""
    initial = log.initial_state
    final = log.final_state()
    return {
        "match_id": initial.match_id,
        "scenario_id": initial.scenario_id,
        "seed": initial.seed,
        "mode": initial.mode,
        "time_limit": initial.time_limit,
        "board": {"width": initial.width, "height": initial.height},
        "teams": [
            {"id": t.id, "name": t.name, "agents": [a.to_dict() for a in t.agents]}
            for t in initial.teams
        ],
        "control_points": [{"id": c.id, "pos": c.pos.to_dict()} for c in initial.control_points],
        "resource_nodes": [
            {"id": r.id, "pos": r.pos.to_dict(), "remaining": r.remaining}
            for r in initial.resource_nodes
        ],
        "frames": _frames(log),
        "events": _event_entries(log),
        "race_moments": _race_moments(log),
        # The per-unit scorecard (plan C8-t8, spec c6/h6): the continuous
        # lane's own grades engine, verbatim — cgrade_units is already a pure
        # function of the log, so the payload IS the engine's fold. Guarded
        # only for the degenerate unitless log (cgrade_units refuses those
        # loudly; a renderer should render, not crash).
        "grades": cgrade_units(log) if initial.units else None,
        "outcome": {
            "status": final.status,
            "winner": final.winner,
            "points": outcome_points(final),
        },
    }


# --------------------------------------------------------------------------- #
# Presentation helpers (formatting only — no game logic recomputed here).
# --------------------------------------------------------------------------- #


def _team_color(team_ids: list[str], team_id: str | None) -> str:
    if team_id is None:
        return "#8f8d87"
    try:
        idx = team_ids.index(team_id)
    except ValueError:
        idx = 0
    return TEAM_COLORS[idx % len(TEAM_COLORS)]


def _scale(width_mu: int, height_mu: int) -> float:
    longest = max(width_mu, height_mu, 1)
    return _BOARD_MAX_PX / longest


def _px(value_mu: int, scale: float) -> float:
    return _BOARD_PAD_PX + value_mu * scale


def _fmt_pos(pos: dict[str, int]) -> str:
    return f"({format_units(pos['x'])}, {format_units(pos['y'])})"


def _describe_event(entry: dict[str, Any]) -> str:
    """A one-line, human-readable description of one event — pure formatting
    of fields the log already carries, never a recomputed rule."""
    kind, data = entry["kind"], entry["data"]
    if kind == "match_started":
        return "Match starts."
    if kind == "decision_point":
        return f"{data['unit_id']} is asked for an order."
    if kind == "action_started":
        target = data.get("target_id")
        if target is None and data.get("target_pos") is not None:
            target = _fmt_pos(data["target_pos"])
        suffix = f" → {target}" if target else ""
        return (
            f"{data['unit_id']} begins {data['kind']}{suffix} "
            f"(completes t={data['completion_time']})"
        )
    if kind == "action_completed":
        return f"{data['unit_id']}'s action completes."
    if kind == "action_failed":
        return f"{data['unit_id']}'s action fails — {data['reason']}"
    if kind == "unit_moved":
        return f"{data['unit_id']} moves to {_fmt_pos(data['to'])}"
    if kind == "resource_gathered":
        return f"{data['unit_id']} gathers {data['amount']} from {data['node_id']}"
    if kind == "resource_delivered":
        return f"{data['unit_id']} delivers {data['amount']} to {data['team_id']}"
    if kind == "post_taken":
        return f"{data['team_id']}'s {data['unit_id']} TAKES {data['cp_id']}."
    if kind == "mission_completed":
        return f"Mission {data['mission_id']} completed by {data['team_id']}."
    if kind == "match_finished":
        return f"Match finished — winner: {data['winner']}."
    if kind == "message_sent":
        return f"{data.get('from', '?')}: {data.get('text', '')}"
    if kind == "plan_declared":
        return f"{data.get('from', data.get('team_id', '?'))} plan: {data.get('text', '')}"
    if kind == "seat_latency":
        who = data.get("unit_id") or data.get("agent_id") or data.get("team_id")
        return f"{who} seat latency recorded"
    return kind  # pragma: no cover - defensive, every known kind is handled above


# --------------------------------------------------------------------------- #
# Rendering — plain server-rendered HTML/SVG, no client-side templating.
# --------------------------------------------------------------------------- #


def _render_resource_nodes(frame: dict[str, Any], scale: float) -> list[str]:
    parts: list[str] = []
    for node in frame["resource_nodes"]:
        cx, cy = _px(node["pos"]["x"], scale), _px(node["pos"]["y"], scale)
        r = _NODE_R
        pts = (
            f"{cx:.1f},{cy - r:.1f} {cx + r:.1f},{cy:.1f} "
            f"{cx:.1f},{cy + r:.1f} {cx - r:.1f},{cy:.1f}"
        )
        parts.append(
            f'<polygon points="{pts}" class="cnode" fill="{RESOURCE_COLOR}">'
            f"<title>{_esc(node['id'])}: {node['remaining']} remaining</title></polygon>"
        )
        parts.append(
            f'<text x="{cx:.1f}" y="{cy + 3:.1f}" text-anchor="middle" class="cnode-num">'
            f"{node['remaining']}</text>"
        )
    return parts


def _render_missions(
    frame: dict[str, Any], scale: float, cp_squares: set[tuple[int, int]]
) -> list[str]:
    parts: list[str] = []
    for ms in frame["missions"]:
        # Frame v5: mission sites are drawn (a dashed square + id), so a
        # delivery contest — units converging on the shared bank — happens
        # somewhere the eye can see, not on an invisible coordinate.
        cx, cy = _px(ms["pos"]["x"], scale), _px(ms["pos"]["y"], scale)
        r = _MS_R
        done = ms["status"] != "open"
        status = ms["status"] + (f" — {', '.join(ms['completed_by'])}" if done else "")
        cls = "cmission cmission-done" if done else "cmission"
        parts.append(
            f'<rect x="{cx - r:.1f}" y="{cy - r:.1f}" width="{r * 2}" height="{r * 2}" '
            f'rx="3" class="{cls}">'
            f"<title>{_esc(ms['id'])} ({_esc(ms['kind'])} {ms['amount']} for "
            f"{ms['reward']}) — {_esc(status)}</title></rect>"
        )
        # A hold mission often sits ON a control point, whose own id renders
        # below — co-located labels split to two sides; otherwise below.
        above = (ms["pos"]["x"], ms["pos"]["y"]) in cp_squares
        label_y = cy - r - 5 if above else cy + r + 11
        parts.append(
            f'<text x="{cx:.1f}" y="{label_y:.1f}" text-anchor="middle" class="cms-id">'
            f"{_esc(ms['id'])}</text>"
        )
    return parts


def _render_control_points(frame: dict[str, Any], scale: float, team_ids: list[str]) -> list[str]:
    parts: list[str] = []
    for cp in frame["control_points"]:
        cx, cy = _px(cp["pos"]["x"], scale), _px(cp["pos"]["y"], scale)
        owner = cp["owner"]
        owner_color = _team_color(team_ids, owner)
        fill = owner_color if owner else "none"
        opacity = "0.28" if owner else "1"
        owned_by = f" — owned by {_esc(owner)}" if owner else " — unowned"
        stroke = owner_color if owner else "#8f8d87"
        parts.append(
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{_CP_R}" class="ccp" '
            f'fill="{fill}" fill-opacity="{opacity}" stroke="{stroke}">'
            f"<title>{_esc(cp['id'])}{owned_by}</title></circle>"
        )
        parts.append(
            f'<text x="{cx:.1f}" y="{cy + _CP_R + 11:.1f}" text-anchor="middle" class="ccp-id">'
            f"{_esc(cp['id'])}</text>"
        )
        for i, taker in enumerate(cp["takers"]):
            ring_r = _CP_R + 6 + i * 6
            color = _team_color(team_ids, taker["team_id"])
            parts.append(
                f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{ring_r}" class="ctaker" '
                f'stroke="{color}" fill="none">'
                f"<title>{_esc(taker['unit_id'])} taking — completes t="
                f"{taker['completion_time']}</title></circle>"
            )
    return parts


def _render_units(frame: dict[str, Any], scale: float, team_ids: list[str]) -> list[str]:
    parts: list[str] = []
    for unit in frame["units"]:
        if not unit["alive"]:
            continue
        cx, cy = _px(unit["pos"]["x"], scale), _px(unit["pos"]["y"], scale)
        color = _team_color(team_ids, unit["team_id"])
        glyph = _ROLE_GLYPH.get(unit["role"], unit["role"][:1].upper())
        action = unit["action"]
        if action is not None:
            title = f"{unit['id']} — {action['kind']}, completes t={action['completion_time']}"
        else:
            title = f"{unit['id']} — idle"
        parts.append(f'<g class="cunit"><title>{_esc(title)}</title>')
        if action is not None:
            parts.append(
                f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{_UNIT_R + 5}" class="cunit-busy" '
                f'stroke="{color}" fill="none"/>'
            )
        parts.append(
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{_UNIT_R}" fill="{color}" class="cunit-body"/>'
            f'<text x="{cx:.1f}" y="{cy + 4:.1f}" text-anchor="middle" class="cunit-glyph">'
            f"{_esc(glyph)}</text></g>"
        )
    return parts


def _render_board_svg(frame: dict[str, Any], board: dict[str, int], team_ids: list[str]) -> str:
    # Orchestrator: the board is four independent, watchable layers drawn in a
    # fixed back-to-front order (nodes, missions, control points, units). Each
    # layer is its own helper so this stays flat; the concatenation order — and
    # thus the output bytes — is the contract the replay tests pin.
    scale = _scale(board["width"], board["height"])
    w = _BOARD_PAD_PX * 2 + board["width"] * scale
    h = _BOARD_PAD_PX * 2 + board["height"] * scale
    parts: list[str] = [
        f'<svg viewBox="0 0 {w:.1f} {h:.1f}" class="cboard" role="img" '
        f'aria-label="board at t={frame["clock"]}">',
        f'<rect x="0" y="0" width="{w:.1f}" height="{h:.1f}" class="cboard-bg"/>',
    ]
    cp_squares = {(c["pos"]["x"], c["pos"]["y"]) for c in frame["control_points"]}
    parts.extend(_render_resource_nodes(frame, scale))
    parts.extend(_render_missions(frame, scale, cp_squares))
    parts.extend(_render_control_points(frame, scale, team_ids))
    parts.extend(_render_units(frame, scale, team_ids))
    parts.append("</svg>")
    return "".join(parts)


def _render_header(data: dict[str, Any]) -> str:
    outcome = data["outcome"]
    winner = outcome["winner"]
    winner_chip = (
        f'<span class="cchip cchip-winner">winner: {_esc(winner)}</span>' if winner else ""
    )
    points_str = ", ".join(f"{_esc(tid)}: {pts}" for tid, pts in sorted(outcome["points"].items()))
    return (
        '<header class="chdr">'
        "<h1>League of Agents — continuous replay</h1>"
        '<div class="cchips">'
        f'<span class="cchip">{_esc(data["match_id"])}</span>'
        f'<span class="cchip">{_esc(data["scenario_id"])}</span>'
        f'<span class="cchip">seed {data["seed"]}</span>'
        f'<span class="cchip">{_esc(data["mode"])}</span>'
        f'<span class="cchip">time limit {data["time_limit"]}</span>'
        f'<span class="cchip">status: {_esc(outcome["status"])}</span>'
        f"{winner_chip}"
        f'<span class="cchip">points — {_esc(points_str)}</span>'
        "</div></header>"
    )


def _render_teams(data: dict[str, Any]) -> str:
    rows = []
    for i, t in enumerate(data["teams"]):
        color = TEAM_COLORS[i % len(TEAM_COLORS)]
        agents = ", ".join(f"{_esc(a['id'])} ({_esc(a['role'])})" for a in t["agents"])
        rows.append(
            f'<div class="cteam"><span class="cswatch" style="background:{color}"></span>'
            f'<span class="cteam-name">{_esc(t["name"])}</span>'
            f'<span class="cteam-roster">{agents}</span></div>'
        )
    return f'<section class="ccard"><h2>Teams</h2>{"".join(rows)}</section>'


def _render_scorecard(data: dict[str, Any]) -> str:
    """Per-unit grades in the face's minimal idiom (plan C8-t8, spec c6/h6):
    one static server-rendered table plus one plain-text paragraph — no tabs,
    no client JS, no grid deck chrome (frame v4 stays pinned minimal). Units
    are ranked by grade descending with the canonical ``(team_id, unit_id)``
    tie-break (the payload's ``grades.units`` list keeps cgrade_units' own
    canonical team order — this re-sort is display only); MVP/LVP are marked
    in their rows AND named in a verdict line; the bold cell in each row is
    the unit's own role's purpose (full credit), everything else is off-role
    (half credit). Every number in the paragraph is interpolated from
    ``league.engine.continuous.grades``' pinned constants, so the explanation
    can never drift from the formula it explains."""
    grades = data["grades"]
    if not grades:
        return ""
    team_ids = [t["id"] for t in data["teams"]]
    mvp, lvp = grades["mvp"], grades["lvp"]
    ranked = sorted(grades["units"], key=lambda u: (-u["grade"], u["team_id"], u["unit_id"]))

    head = (
        "<tr><th>unit</th><th>role</th><th>grade</th>"
        + "".join(f"<th>{_esc(p)}</th>" for p in GRADE_PURPOSES)
        + "</tr>"
    )
    rows = []
    for u in ranked:
        color = _team_color(team_ids, u["team_id"])
        tags = ""
        if u["unit_id"] == mvp["unit_id"]:
            tags += ' <span class="cgrade-mvp">MVP</span>'
        if u["unit_id"] == lvp["unit_id"]:
            tags += ' <span class="cgrade-lvp">LVP</span>'
        cells = []
        for p in GRADE_PURPOSES:
            entry = u["purposes"][p]
            cls = "cgrade-num cgrade-home" if entry["on_role"] else "cgrade-num"
            cells.append(f'<td class="{cls}">{entry["points"]}</td>')
        rows.append(
            '<tr class="cgrade-row">'
            f'<td>{_esc(u["unit_id"])}'
            f' <span class="cswatch" style="background:{color}"></span>{tags}</td>'
            f'<td>{_esc(u["role"])}</td>'
            f'<td class="cgrade-num cgrade-total">{u["grade"]}</td>'
            f'{"".join(cells)}</tr>'
        )

    verdict = (
        f"MVP: {_esc(mvp['unit_id'])} ({_esc(mvp['team_id'])}, grade {mvp['grade']}) · "
        f"LVP: {_esc(lvp['unit_id'])} ({_esc(lvp['team_id'])}, grade {lvp['grade']})"
    )
    why = (
        f"How the grade is computed: each unit's grade sums three purposes — race_hold "
        f"(winning a take_post race earns {POST_TAKEN_POINTS} points; a banked hold mission "
        f"credits its reward ×{GRADE_UNIT} to the holder), economy (each resource gathered "
        f"or delivered earns its amount ×{GRADE_UNIT}; a banked deliver mission credits its "
        f"reward ×{GRADE_UNIT} to the delivering unit), and eyes "
        f"({MOVE_POINTS_PER_BOARD_UNIT} points per whole board-unit moved). The bold cell "
        f"is the unit's own role's purpose and earns full credit; off-role work earns "
        f"{OFF_ROLE_NUM}/{OFF_ROLE_DEN} credit — more than zero, never full. MVP is the "
        f"highest grade, LVP the lowest; ties break by (team_id, unit_id)."
    )
    return (
        '<section class="ccard cgrades-card"><h2>Scorecard — per-unit grades</h2>'
        f'<p class="cgrade-verdict">{verdict}</p>'
        f'<table class="cgrades">{head}{"".join(rows)}</table>'
        f'<p class="cgrade-why">{_esc(why)}</p></section>'
    )


def _render_events(data: dict[str, Any]) -> str:
    """Every row carries ``data-t`` (its own game time): the page's transport
    turns each row into a seek target — click an event, watch that instant."""
    rows = []
    for entry in data["events"]:
        classes = ["cevt", f"cevt-{entry['kind']}", f"cevt-{entry['class']}"]
        if entry["kind"] == "post_taken":
            classes.append("race-win")
        elif entry["kind"] == "action_failed":
            classes.append("race-fail")
        text = _describe_event(entry)
        rows.append(
            f'<li class="{" ".join(classes)}" data-t="{entry["game_time"]}">'
            f'<span class="cevt-t">t={entry["game_time"]}</span>'
            f'<span class="cevt-k">{_esc(entry["kind"])}</span>'
            f'<span class="cevt-d">{_esc(text)}</span></li>'
        )
    return (
        '<section class="ccard"><h2>Event timeline</h2>'
        f'<ol class="cfeed">{"".join(rows)}</ol></section>'
    )


def _render_play(data: dict[str, Any]) -> str:
    """The playable board (frame v5): a transport row plus one board host.

    The host is server-rendered with the pre-match starting frame so the
    document degrades to an honest static board without JavaScript (the
    <noscript> note says so out loud); with JavaScript the page's own
    renderer redraws the same SVG — same injected geometry constants — along
    the playback clock. The step buttons land on the distinct game-time
    steps, i.e. exactly the moments frame v4 used to print as its static
    sequence."""
    team_ids = [t["id"] for t in data["teams"]]
    final_clock = data["frames"][-1]["clock"]
    initial_svg = _render_board_svg(data["frames"][0], data["board"], team_ids)
    return (
        '<section class="ccard cboard-card"><h2>Board — full replay</h2>'
        '<div class="ctransport" role="group" aria-label="playback transport">'
        '<button id="cbtn-first" title="jump to start" aria-label="jump to start">'
        "&#171;</button>"
        '<button id="cbtn-prev" title="previous moment" aria-label="previous moment">'
        "&#8249;</button>"
        '<button id="cbtn-play" title="play/pause" aria-label="play">&#9654;</button>'
        '<button id="cbtn-next" title="next moment" aria-label="next moment">&#8250;</button>'
        '<button id="cbtn-last" title="jump to end" aria-label="jump to end">&#187;</button>'
        f'<input type="range" id="cclock" min="0" max="{final_clock}" step="any" value="0" '
        'aria-label="game time">'
        f'<span id="cclock-label" class="cclock-label">t=0.0 / {final_clock}</span>'
        '<span class="cspeed" role="group" aria-label="playback speed">'
        '<button data-cspeed="0.5" title="half speed">0.5&#215;</button>'
        '<button data-cspeed="1" class="on" title="normal speed">1&#215;</button>'
        '<button data-cspeed="2" title="double speed">2&#215;</button>'
        '<button data-cspeed="4" title="quadruple speed">4&#215;</button>'
        "</span>"
        '<button id="cbtn-audio" type="button" title="score + event sounds (off)" '
        'aria-pressed="false" aria-label="score + event sounds (off)">&#9834;</button>'
        "</div>"
        f'<div id="cboard-host">{initial_svg}</div>'
        "<noscript><p>Interactive playback needs JavaScript; this static board shows the "
        "starting positions. The event timeline beside it still lists every moment.</p>"
        "</noscript></section>"
    )


def _render_body(data: dict[str, Any]) -> str:
    return (
        _render_header(data)
        + '<div class="clayout">'
        + _render_play(data)
        + '<div class="cside">'
        + _render_teams(data)
        + _render_events(data)
        + _render_scorecard(data)
        + "</div></div>"
    )


_RAW_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>League of Agents — continuous replay</title>
<style>
:root { color-scheme: light dark; }
* { box-sizing: border-box; margin: 0; }
body {
  font: 14px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  background: #f7f6f2; color: #101010; padding: 20px;
}
@media (prefers-color-scheme: dark) {
  body { background: #14140f; color: #f2f1ec; }
  .ccard { background: #1f1f1b !important; border-color: #35342f !important; }
  .cboard-bg { fill: #201f1e; }
}
h1 { font-size: 18px; margin-bottom: 10px; }
h2 { font-size: 11px; text-transform: uppercase; letter-spacing: .08em; opacity: .7;
  margin-bottom: 8px; }
.chdr { margin-bottom: 16px; }
.cchips { display: flex; flex-wrap: wrap; gap: 6px; }
.cchip {
  background: rgba(127,127,127,.14); border-radius: 999px; padding: 3px 10px;
  font-size: 12px;
}
.cchip-winner { font-weight: 700; }
.clayout { display: flex; gap: 18px; align-items: flex-start; flex-wrap: wrap; }
.ccard {
  background: #fff; border: 1px solid rgba(127,127,127,.25); border-radius: 12px;
  padding: 14px; min-width: 260px;
}
.cboard-card { flex: 1 1 480px; }
.cside { display: flex; flex-direction: column; gap: 14px; flex: 1 1 320px; max-width: 420px; }
.cboard { width: 100%; height: auto; display: block; }
.ctransport { display: flex; align-items: center; gap: 6px; flex-wrap: wrap;
  margin-bottom: 10px; }
.ctransport button {
  min-width: 30px; min-height: 30px; padding: 2px 8px; font-size: 13px;
  background: transparent; color: inherit; cursor: pointer;
  border: 1px solid rgba(127,127,127,.45); border-radius: 8px;
}
.ctransport button.on { border-color: currentColor; font-weight: 700; }
#cclock { flex: 1 1 120px; min-width: 120px; accent-color: currentColor; }
.cclock-label { font-variant-numeric: tabular-nums; font-size: 12px; opacity: .8; }
.cspeed { display: inline-flex; gap: 4px; }
.cspeed button { min-width: 38px; font-variant-numeric: tabular-nums; }
.cboard-bg { fill: #eeece4; }
.ccp-id { font-size: 9px; fill: currentColor; opacity: .7; }
.cmission { fill: none; stroke: #8f8d87; stroke-width: 1.6; stroke-dasharray: 5 3; }
.cmission-done { opacity: .45; }
.cms-id { font-size: 9px; fill: currentColor; opacity: .7; }
.cnode-num { font-size: 8px; fill: #fff; font-weight: 700; text-anchor: middle; }
.cunit-glyph { font-size: 10px; fill: #fff; font-weight: 700; }
.ctaker { stroke-width: 2; stroke-dasharray: 4 3; }
.cunit-busy { stroke-width: 1.6; stroke-dasharray: 2 2; }
.cteam { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; font-size: 13px; }
.cswatch { width: 10px; height: 10px; border-radius: 3px; flex: 0 0 auto; }
.cteam-name { font-weight: 650; }
.cteam-roster { opacity: .75; }
.cfeed { list-style: none; display: flex; flex-direction: column; gap: 5px; max-height: 520px;
  overflow-y: auto; }
.cevt { display: flex; gap: 8px; font-size: 12.5px; padding: 2px 0; }
.cevt-t { font-variant-numeric: tabular-nums; opacity: .6; min-width: 42px; }
.cevt-k { opacity: .55; min-width: 108px; }
.cevt-observation { opacity: .55; }
.cevt.race-win { color: __STATUS_GOOD__; font-weight: 700; }
.cevt.race-fail { color: __STATUS_CRITICAL__; font-weight: 700; }
.cfeed li[data-t] { cursor: pointer; }
.cfeed li[data-t]:focus-visible { outline: 2px solid currentColor; border-radius: 6px; }
.cevt-future { opacity: .35; }
.cevt-now { background: rgba(127,127,127,.14); border-radius: 6px; }
.cgrades { width: 100%; border-collapse: collapse; font-size: 12px; }
.cgrades th, .cgrades td { text-align: left; padding: 3px 6px;
  border-bottom: 1px solid rgba(127,127,127,.2); }
.cgrades th { font-size: 10px; text-transform: uppercase; letter-spacing: .06em; opacity: .6; }
.cgrades .cgrade-num { font-variant-numeric: tabular-nums; text-align: right; }
.cgrades .cgrade-total { font-weight: 700; }
.cgrades .cgrade-home { font-weight: 700; }
.cgrades .cswatch { display: inline-block; vertical-align: baseline; }
.cgrade-mvp { color: __STATUS_GOOD__; font-weight: 700; font-size: 10.5px; }
.cgrade-lvp { color: __STATUS_CRITICAL__; font-weight: 700; font-size: 10.5px; }
.cgrade-verdict { font-size: 12.5px; margin-bottom: 8px; }
.cgrade-why { margin-top: 8px; font-size: 11.5px; opacity: .75; }
footer { margin-top: 16px; font-size: 11.5px; opacity: .6; }
</style>
</head>
<body>
<div class="wrap">
__CMATCH_BODY__
<footer>Continuous replay — frame v5 (the full replay, cycle-8 human review):
press play and the match runs on its own clock — every move glides along the
engine's own action record — with an optional score + event-sound layer
(&#9834;, off by default). Every fact rendered straight from the match log.</footer>
</div>
<script id="cmatch-data" type="application/json">__CMATCH_DATA__</script>
<script>
"use strict";
// Frame v5 playback: everything below is presentation. The clock, the
// interpolation and the audio are computed from the embedded log payload;
// no game logic is recomputed. A move's path is the straight line the
// engine's own action record names (pos -> target_pos over
// start_time..completion_time) — linear interpolation of that record and
// nothing else. Playback wall-clock (requestAnimationFrame timestamps,
// AudioContext time) is runtime-only and never reaches the document.
const M = JSON.parse(document.getElementById('cmatch-data').textContent);
const EVENT_SOUND = __CEVENT_SOUND__;
const EVENT_SOUND_ALIAS = __CEVENT_ALIAS__;
const GEO = __CGEO__;
const ROLE_GLYPH = __CROLE_GLYPH__;
const TEAM_COLORS = __CTEAM_COLORS__;
const NEUTRAL = '#8f8d87';
const $ = id => document.getElementById(id);
const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
function esc(s) {
  return String(s).replace(/[&<>"']/g, c =>
    ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
}
const teamIds = M.teams.map(t => t.id);
const teamIndex = {};
teamIds.forEach((id, i) => { teamIndex[id] = i; });
function teamColor(tid) {
  const i = teamIndex[tid];
  return i == null ? NEUTRAL : TEAM_COLORS[i % TEAM_COLORS.length];
}
const unitTeam = {};
M.frames[0].units.forEach(u => { unitTeam[u.id] = u.team_id; });
const FINAL_CLOCK = M.frames[M.frames.length - 1].clock;
const STEPS = M.frames.map(f => f.clock).filter((c, i, a) => i === 0 || c !== a[i - 1]);

// The governing snapshot for a clock value: the last folded frame at or
// before it (several frames can share clock 0 — the later fold governs).
function frameAt(tau) {
  let f = M.frames[0];
  for (const g of M.frames) { if (g.clock <= tau) f = g; else break; }
  return f;
}
// Where a unit IS at clock tau: mid-move, the linear interpolation of its
// own action record; otherwise exactly the folded position. Reduced motion
// collapses the glide to per-moment snaps.
function unitPosAt(u, tau) {
  const a = u.action;
  if (!reduce && a && a.kind === 'move' && a.target_pos &&
      a.completion_time > a.start_time) {
    const k = Math.max(0, Math.min(1,
      (tau - a.start_time) / (a.completion_time - a.start_time)));
    return { x: u.pos.x + (a.target_pos.x - u.pos.x) * k,
             y: u.pos.y + (a.target_pos.y - u.pos.y) * k };
  }
  return u.pos;
}

// ---- board renderer: the same geometry the server used for the static
// starting frame (GEO and the colors are injected from those exact
// constants — one geometry, two drawers, no drift).
const SCALE = GEO.max_px / Math.max(M.board.width, M.board.height, 1);
const px = mu => GEO.pad_px + mu * SCALE;
const f1 = n => n.toFixed(1);
function nodeSvg(node) {
  const cx = px(node.pos.x), cy = px(node.pos.y), r = GEO.node_r;
  const pts = f1(cx) + ',' + f1(cy - r) + ' ' + f1(cx + r) + ',' + f1(cy) + ' ' +
    f1(cx) + ',' + f1(cy + r) + ' ' + f1(cx - r) + ',' + f1(cy);
  return '<polygon points="' + pts + '" class="cnode" fill="__RESOURCE_COLOR__">' +
    '<title>' + esc(node.id) + ': ' + node.remaining + ' remaining</title></polygon>' +
    '<text x="' + f1(cx) + '" y="' + f1(cy + 3) + '" text-anchor="middle" ' +
    'class="cnode-num">' + node.remaining + '</text>';
}
function missionSvg(ms, cpSquares) {
  const cx = px(ms.pos.x), cy = px(ms.pos.y), r = GEO.ms_r;
  const done = ms.status !== 'open';
  const status = ms.status + (done ? ' — ' + ms.completed_by.join(', ') : '');
  // Same label rule as the server drawer: above when co-located with a
  // control point (whose own id renders below), otherwise below.
  const above = cpSquares[ms.pos.x + ',' + ms.pos.y];
  const ly = above ? cy - r - 5 : cy + r + 11;
  return '<rect x="' + f1(cx - r) + '" y="' + f1(cy - r) + '" width="' + (r * 2) +
    '" height="' + (r * 2) + '" rx="3" class="cmission' +
    (done ? ' cmission-done' : '') + '"><title>' + esc(ms.id) + ' (' + esc(ms.kind) +
    ' ' + ms.amount + ' for ' + ms.reward + ') — ' + esc(status) + '</title></rect>' +
    '<text x="' + f1(cx) + '" y="' + f1(ly) + '" text-anchor="middle" ' +
    'class="cms-id">' + esc(ms.id) + '</text>';
}
function cpSvg(cp) {
  const cx = px(cp.pos.x), cy = px(cp.pos.y);
  const oc = cp.owner ? teamColor(cp.owner) : NEUTRAL;
  const ownedBy = cp.owner ? ' — owned by ' + esc(cp.owner) : ' — unowned';
  let out = '<circle cx="' + f1(cx) + '" cy="' + f1(cy) + '" r="' + GEO.cp_r + '" ' +
    'class="ccp" fill="' + (cp.owner ? oc : 'none') + '" fill-opacity="' +
    (cp.owner ? '0.28' : '1') + '" stroke="' + oc + '">' +
    '<title>' + esc(cp.id) + ownedBy + '</title></circle>' +
    '<text x="' + f1(cx) + '" y="' + f1(cy + GEO.cp_r + 11) + '" text-anchor="middle" ' +
    'class="ccp-id">' + esc(cp.id) + '</text>';
  cp.takers.forEach((tk, i) => {
    out += '<circle cx="' + f1(cx) + '" cy="' + f1(cy) + '" r="' +
      (GEO.cp_r + 6 + i * 6) + '" class="ctaker" stroke="' + teamColor(tk.team_id) +
      '" fill="none"><title>' + esc(tk.unit_id) + ' taking — completes t=' +
      tk.completion_time + '</title></circle>';
  });
  return out;
}
function unitSvg(u, tau) {
  const pos = unitPosAt(u, tau);
  const cx = px(pos.x), cy = px(pos.y);
  const color = teamColor(u.team_id);
  const glyph = ROLE_GLYPH[u.role] || u.role.slice(0, 1).toUpperCase();
  const a = u.action;
  const title = u.id + ' — ' +
    (a ? a.kind + ', completes t=' + a.completion_time : 'idle') +
    (u.carrying ? ', carrying ' + u.carrying : '');
  let out = '<g class="cunit"><title>' + esc(title) + '</title>';
  if (a) out += '<circle cx="' + f1(cx) + '" cy="' + f1(cy) + '" r="' +
    (GEO.unit_r + 5) + '" class="cunit-busy" stroke="' + color + '" fill="none"/>';
  out += '<circle cx="' + f1(cx) + '" cy="' + f1(cy) + '" r="' + GEO.unit_r +
    '" fill="' + color + '" class="cunit-body"/>' +
    '<text x="' + f1(cx) + '" y="' + f1(cy + 4) + '" text-anchor="middle" ' +
    'class="cunit-glyph">' + esc(glyph) + '</text></g>';
  return out;
}
function drawBoard(tau) {
  const f = frameAt(tau);
  const w = GEO.pad_px * 2 + M.board.width * SCALE;
  const h = GEO.pad_px * 2 + M.board.height * SCALE;
  const p = ['<svg viewBox="0 0 ' + f1(w) + ' ' + f1(h) + '" class="cboard" role="img" ' +
    'aria-label="board at t=' + tau.toFixed(1) + '">',
    '<rect x="0" y="0" width="' + f1(w) + '" height="' + f1(h) + '" class="cboard-bg"/>'];
  const cpSquares = {};
  f.control_points.forEach(c => { cpSquares[c.pos.x + ',' + c.pos.y] = true; });
  for (const node of f.resource_nodes) p.push(nodeSvg(node));
  for (const ms of f.missions) p.push(missionSvg(ms, cpSquares));
  for (const cp of f.control_points) p.push(cpSvg(cp));
  for (const u of f.units) { if (u.alive) p.push(unitSvg(u, tau)); }
  p.push('</svg>');
  $('cboard-host').innerHTML = p.join('');
}

// ---- the transport: one continuous clock over [0, FINAL_CLOCK]. Playback
// advances it by requestAnimationFrame deltas; 1x plays one game-time unit
// per wall second.
let clock = 0, speed = 1, rafId = null, lastTs = null, playing = false;
let evtPtr = 0;        // M.events[0..evtPtr) are at or before the clock
let feedApplied = -1;
const feedRows = Array.from(document.querySelectorAll('.cfeed > li'));
function evtCount(tau) {
  let n = 0;
  while (n < M.events.length && M.events[n].game_time <= tau) n++;
  return n;
}
function syncFeed() {
  if (evtPtr === feedApplied) return;
  feedApplied = evtPtr;
  const nowT = evtPtr > 0 ? M.events[evtPtr - 1].game_time : null;
  feedRows.forEach((row, i) => {
    row.classList.toggle('cevt-future', i >= evtPtr);
    row.classList.toggle('cevt-now', i < evtPtr && M.events[i].game_time === nowT);
  });
  if (playing && evtPtr > 0) {
    const row = feedRows[evtPtr - 1], feed = row.parentElement;
    feed.scrollTop += row.getBoundingClientRect().top -
      feed.getBoundingClientRect().top - feed.clientHeight * 0.5;
  }
}
function renderAll() {
  drawBoard(clock);
  $('cclock').value = String(clock);
  $('cclock-label').textContent = 't=' + clock.toFixed(1) + ' / ' + FINAL_CLOCK;
  syncFeed();
}
function seek(tau) {   // navigation, not time passing: no motifs fire
  clock = Math.max(0, Math.min(FINAL_CLOCK, tau));
  evtPtr = evtCount(clock);
  renderAll();
}
// Consume every event the advancing clock just crossed; the k-th of an
// instant's sounding events staggers 70 ms so simultaneity stays legible
// (deterministic — canonical event order, never wall-clock jitter).
function fireCrossed(cur) {
  let batchT = null, k = 0;
  while (evtPtr < M.events.length && M.events[evtPtr].game_time <= cur) {
    const e = M.events[evtPtr++];
    if (!AUDIO.on || !AUDIO.graph || !AUDIO.rootHz) continue;
    const kind = EVENT_SOUND.motifs[e.kind] ? e.kind : EVENT_SOUND_ALIAS[e.kind];
    if (!kind) continue;
    if (e.game_time !== batchT) { batchT = e.game_time; k = 0; }
    playMotif(kind, e.data, AUDIO.graph.ctx.currentTime + 0.02 + 0.07 * k);
    k += 1;
  }
}
function tickPlay(ts) {
  if (lastTs == null) lastTs = ts;
  clock = Math.min(FINAL_CLOCK, clock + ((ts - lastTs) / 1000) * speed);
  lastTs = ts;
  fireCrossed(clock);
  renderAll();
  if (clock >= FINAL_CLOCK) { stop(); return; }
  rafId = requestAnimationFrame(tickPlay);
}
function stop() {
  if (!playing) return;
  playing = false;
  if (rafId != null) cancelAnimationFrame(rafId);
  rafId = null; lastTs = null;
  const b = $('cbtn-play');
  b.classList.remove('on'); b.innerHTML = '&#9654;';
  b.setAttribute('aria-label', 'play');
}
function play() {
  if (playing) return;
  if (clock >= FINAL_CLOCK) seek(0);   // replay from the top
  playing = true; lastTs = null;
  const b = $('cbtn-play');
  b.classList.add('on'); b.innerHTML = '&#10073;&#10073;';
  b.setAttribute('aria-label', 'pause');
  rafId = requestAnimationFrame(tickPlay);
}
function toggle() { playing ? stop() : play(); }
// The step buttons land on the distinct game-time steps — exactly the
// moments frame v4 printed as its static key-moment sequence.
function stepPrev() {
  stop();
  let target = 0;
  for (const t of STEPS) { if (t < clock) target = t; else break; }
  seek(target);
}
function stepNext() {
  stop();
  const next = STEPS.find(t => t > clock);
  seek(next == null ? FINAL_CLOCK : next);
}
$('cclock').addEventListener('input', e => { stop(); seek(parseFloat(e.target.value)); });
$('cbtn-first').onclick = () => { stop(); seek(0); };
$('cbtn-prev').onclick = stepPrev;
$('cbtn-next').onclick = stepNext;
$('cbtn-last').onclick = () => { stop(); seek(FINAL_CLOCK); };
$('cbtn-play').onclick = toggle;
document.querySelectorAll('.cspeed button').forEach(b => {
  b.onclick = () => {
    speed = parseFloat(b.dataset.cspeed);
    document.querySelectorAll('.cspeed button').forEach(x =>
      x.classList.toggle('on', x === b));
  };
});
feedRows.forEach(row => {
  const t = row.dataset.t;
  if (t == null) return;
  row.tabIndex = 0;
  const go = () => { stop(); seek(parseFloat(t)); };
  row.addEventListener('click', go);
  row.addEventListener('keydown', e => { if (e.key === 'Enter') go(); });
});
document.addEventListener('keydown', e => {
  if (e.target.tagName === 'INPUT') return;
  if (e.key === 'ArrowLeft') stepPrev();
  else if (e.key === 'ArrowRight') stepNext();
  else if (e.key === ' ') { e.preventDefault(); toggle(); }
});

// ---- ambient score + event motifs (inherited from the grid face the
// moment this face grew a transport — cycle-8 c17 + the audio-events
// amendment). The seed derives from data already embedded in this page
// (match id + seed) with the SAME formula the grid face uses, so one match
// sounds the same on every face; OFF by default — the AudioContext is
// created lazily on the user's own gesture. EVENT_SOUND / EVENT_SOUND_ALIAS
// above are injected verbatim from league/replay/audio.py: ONE canonical
// table, three renderers (grid page, this page, the MP4 soundtrack), zero
// drift by construction. Kinds absent from table+alias are silent by
// design; motifs fire only when the advancing clock crosses an event —
// scrubbing or jumping is navigation, not time passing, so skipped events
// never sound.
function mulberry32(a) {
  return function () {
    a |= 0; a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
function fnv1a(s) {
  let h = 2166136261 >>> 0;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i); h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}
function audioSeed() {
  return fnv1a(M.match_id + '|' + M.seed);  // same formula as the grid face
}
const MASTER_LEVEL = 0.3;
const ROOT_MIDI = [41, 43, 45, 48];
const PAD_CHORDS = [
  [0, 7, 14, 16], [0, 7, 16, 21], [2, 9, 14, 18], [0, 7, 19, 23],
];
const BELL_STEPS = [0, 2, 4, 7, 9, 11, 14, 16];
const midiHz = m => 440 * Math.pow(2, (m - 69) / 12);
const AUDIO = { graph: null, timer: null, on: false, rootHz: null };
function makeImpulse(ctx, rnd) {
  const len = Math.floor(3.2 * ctx.sampleRate);
  const buf = ctx.createBuffer(2, len, ctx.sampleRate);
  for (let ch = 0; ch < 2; ch++) {
    const d = buf.getChannelData(ch);
    for (let i = 0; i < len; i++) d[i] = (rnd() * 2 - 1) * Math.pow(1 - i / len, 2.9);
  }
  return buf;
}
function buildAudio(seed) {
  const ctx = new (window.AudioContext || window.webkitAudioContext)();
  const master = ctx.createGain(); master.gain.value = 0;
  const safety = ctx.createDynamicsCompressor();
  safety.threshold.value = -22; safety.knee.value = 18; safety.ratio.value = 4;
  safety.attack.value = 0.012; safety.release.value = 0.3;
  master.connect(safety); safety.connect(ctx.destination);
  const rev = ctx.createConvolver();
  rev.buffer = makeImpulse(ctx, mulberry32(seed ^ 0x1F123BB5));
  const wet = ctx.createGain(); wet.gain.value = 0.5;
  rev.connect(wet); wet.connect(master);
  const padLp = ctx.createBiquadFilter();
  padLp.type = 'lowpass'; padLp.frequency.value = 950; padLp.Q.value = 0.4;
  const padBus = ctx.createGain(); padBus.gain.value = 0.9;
  padBus.connect(padLp); padLp.connect(master);
  const padSend = ctx.createGain(); padSend.gain.value = 0.3;
  padLp.connect(padSend); padSend.connect(rev);
  const lfo = ctx.createOscillator(); lfo.frequency.value = 0.045;
  const lfoAmt = ctx.createGain(); lfoAmt.gain.value = 240;
  lfo.connect(lfoAmt); lfoAmt.connect(padLp.frequency); lfo.start();
  const bellBus = ctx.createGain(); bellBus.gain.value = 0.75; bellBus.connect(master);
  const bellSend = ctx.createGain(); bellSend.gain.value = 0.9;
  bellBus.connect(bellSend); bellSend.connect(rev);
  const eventBus = ctx.createGain(); eventBus.gain.value = EVENT_SOUND.level;
  eventBus.connect(master);
  return { ctx, master, padBus, bellBus, eventBus };
}
function padChord(A, rootHz, steps, t, dur) {
  const env = g => {
    g.gain.setValueAtTime(0, t);
    g.gain.linearRampToValueAtTime(0.05, t + 6);
    g.gain.setValueAtTime(0.05, t + dur - 7);
    g.gain.linearRampToValueAtTime(0, t + dur);
  };
  for (const st of steps) {
    const f = rootHz * Math.pow(2, st / 12);
    for (const det of [-2.5, 2.5]) {
      const o = A.ctx.createOscillator();
      o.type = 'sine'; o.frequency.value = f; o.detune.value = det;
      const g = A.ctx.createGain(); env(g);
      o.connect(g); g.connect(A.padBus); o.start(t); o.stop(t + dur + 0.2);
    }
  }
  const sub = A.ctx.createOscillator();
  sub.type = 'triangle';
  sub.frequency.value = rootHz * Math.pow(2, steps[0] / 12) / 2;
  const sg = A.ctx.createGain(); env(sg);
  sub.connect(sg); sg.connect(A.padBus); sub.start(t); sub.stop(t + dur + 0.2);
}
function bellNote(A, f, t, vel) {
  for (const [ratio, amp] of [[1, 1], [2.01, 0.38], [3.02, 0.13]]) {
    const o = A.ctx.createOscillator(); o.type = 'sine'; o.frequency.value = f * ratio;
    const g = A.ctx.createGain();
    g.gain.setValueAtTime(0, t);
    g.gain.linearRampToValueAtTime(0.16 * vel * amp, t + 0.012);
    g.gain.exponentialRampToValueAtTime(0.0001, t + 5 / ratio);
    o.connect(g); g.connect(A.bellBus); o.start(t); o.stop(t + 5 / ratio + 0.1);
  }
}
function startScore() {
  const seed = audioSeed();
  const A = AUDIO.graph = buildAudio(seed);
  const padRnd = mulberry32(seed ^ 0x51AB3C02);
  const bellRnd = mulberry32(seed ^ 0x9E3779B9);
  const rootHz = midiHz(ROOT_MIDI[Math.floor(mulberry32(seed)() * ROOT_MIDI.length)]);
  AUDIO.rootHz = rootHz;  // the event-motif layer plays in the bed's own key
  const t0 = A.ctx.currentTime + 0.08;
  let padT = 0, chord = 0, bellT = 2 + bellRnd() * 3;
  function ahead() {
    const now = A.ctx.currentTime - t0;
    while (padT < now + 1.5) {
      const dur = 18 + padRnd() * 8;
      padChord(A, rootHz, PAD_CHORDS[chord], t0 + padT, dur + 8);
      chord = (chord + 1 + Math.floor(padRnd() * (PAD_CHORDS.length - 1))) %
        PAD_CHORDS.length;
      padT += dur;
    }
    while (bellT < now + 1.5) {
      const curious = bellRnd() < 0.11;
      const step = curious ? 6 : BELL_STEPS[Math.floor(bellRnd() * BELL_STEPS.length)];
      const f = rootHz * Math.pow(2, (24 + step + (bellRnd() < 0.3 ? 12 : 0)) / 12);
      const vel = 0.5 + bellRnd() * 0.5;
      bellNote(A, f, t0 + bellT, vel);
      if (bellRnd() < 0.22)
        bellNote(A, f * Math.pow(2, (bellRnd() < 0.5 ? 7 : 4) / 12),
          t0 + bellT + 0.7 + bellRnd() * 0.8, vel * 0.55);
      bellT += 3.5 + bellRnd() * 5.5;
    }
  }
  ahead();
  AUDIO.timer = setInterval(ahead, 240);
  A.master.gain.setValueAtTime(0, A.ctx.currentTime);
  A.master.gain.linearRampToValueAtTime(MASTER_LEVEL, A.ctx.currentTime + 2);
}
function setAudioButton(on) {
  const b = $('cbtn-audio');
  b.classList.toggle('on', on);
  b.setAttribute('aria-pressed', String(on));
  const label = on ? 'score + event sounds (on)' : 'score + event sounds (off)';
  b.setAttribute('aria-label', label); b.title = label;
}
function audioToggle() {
  if (AUDIO.on) {
    AUDIO.on = false;
    clearInterval(AUDIO.timer); AUDIO.timer = null;
    const A = AUDIO.graph; AUDIO.graph = null; AUDIO.rootHz = null;
    if (A) {
      A.master.gain.cancelScheduledValues(A.ctx.currentTime);
      A.master.gain.setValueAtTime(A.master.gain.value, A.ctx.currentTime);
      A.master.gain.linearRampToValueAtTime(0, A.ctx.currentTime + 0.5);
      setTimeout(() => A.ctx.close(), 650);   // runtime teardown only
    }
    setAudioButton(false);
  } else {
    AUDIO.on = true;
    startScore();              // the ctx is born here, on the user's gesture
    setAudioButton(true);
  }
}
$('cbtn-audio').onclick = audioToggle;
function motifRegister(m, d) {
  let tid = m.team_field ? d[m.team_field]
    : m.unit_field ? unitTeam[d[m.unit_field]] : null;
  // Continuous events that name only a unit (action_failed) resolve their
  // team through the roster — same register rule, no new convention.
  if (tid == null && d.unit_id != null) tid = unitTeam[d.unit_id];
  const idx = teamIndex[tid];
  return idx == null ? 0 : (idx % 2) * EVENT_SOUND.register_semitones;
}
function motifVariant(m, d) {
  if (!m.variant_steps) return 0;
  return fnv1a(m.variant_key.map(k => String(d[k] == null ? '' : d[k])).join('|'))
    % m.variant_steps.length;
}
function motifPlan(kind, reg, variant, rootHz) {
  const m = EVENT_SOUND.motifs[kind];
  const steps = m.variant_steps ? [m.variant_steps[variant]] : m.steps;
  return steps.map((st, i) => [i * m.gap,
    rootHz * Math.pow(2, (m.octave * 12 + st + reg) / 12),
    m.vel * m.vels[i], m.dur, m.voice]);
}
function motifNote(A, voice, f, t, vel, dur) {
  for (const [ratio, amp] of voice.partials) {
    const o = A.ctx.createOscillator(); o.type = 'sine'; o.frequency.value = f * ratio;
    const g = A.ctx.createGain();
    g.gain.setValueAtTime(0, t);
    g.gain.linearRampToValueAtTime(EVENT_SOUND.peak * vel * amp, t + voice.attack);
    g.gain.exponentialRampToValueAtTime(EVENT_SOUND.floor, t + dur / ratio);
    o.connect(g); g.connect(A.eventBus); o.start(t); o.stop(t + dur / ratio + 0.05);
  }
}
function playMotif(kind, d, t) {
  const m = EVENT_SOUND.motifs[kind];
  for (const [dt, f, vel, dur, voice] of
       motifPlan(kind, motifRegister(m, d), motifVariant(m, d), AUDIO.rootHz))
    motifNote(AUDIO.graph, EVENT_SOUND.voices[voice], f, t + dt, vel, dur);
}

seek(0);   // boot: the client renderer takes over the server-drawn board
</script>
</body>
</html>
"""

# Constant substitution happens once at import time — the validated palette
# colors, the board geometry, the role-glyph convention, the team palette,
# and the canonical event-sound table + continuous alias (all fixed module
# constants; the JSON dumps are key-sorted, so the template stays a
# deterministic constant) — leaving ``render_chtml`` to substitute only
# per-log content into an already-finished template.
_TEMPLATE = (
    _RAW_TEMPLATE.replace("__STATUS_GOOD__", STATUS_GOOD)
    .replace("__STATUS_CRITICAL__", STATUS_CRITICAL)
    .replace("__RESOURCE_COLOR__", RESOURCE_COLOR)
    .replace("__CEVENT_SOUND__", json.dumps(EVENT_SOUND, sort_keys=True, separators=(",", ":")))
    .replace(
        "__CEVENT_ALIAS__",
        json.dumps(CONTINUOUS_EVENT_SOUND_ALIAS, sort_keys=True, separators=(",", ":")),
    )
    .replace("__CGEO__", json.dumps(_GEO, sort_keys=True, separators=(",", ":")))
    .replace("__CROLE_GLYPH__", json.dumps(_ROLE_GLYPH, sort_keys=True, separators=(",", ":")))
    .replace("__CTEAM_COLORS__", json.dumps(list(TEAM_COLORS), separators=(",", ":")))
)


def render_chtml(log: CMatchLog) -> str:
    """The continuous lane's single-file human view. No external requests,
    ever; the same log renders byte-identical HTML, every time."""
    data = build_continuous_replay_data(log)
    payload = json.dumps(data, sort_keys=True, ensure_ascii=False)
    payload = payload.replace("</", "<\\/")  # keep </script> out of the data block
    html = _TEMPLATE.replace("__CMATCH_BODY__", _render_body(data))
    return html.replace("__CMATCH_DATA__", payload)
