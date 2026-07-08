"""Render a continuous match log as a self-contained HTML replay — the race
made visible (plan C7-t9, spec c12/c2).

Frame v4 is PINNED here as *minimal-but-real this cycle*: the mesmerizing/
video generalization (tweened motion, a play/pause transport, the dual-theme
token system, GIF/video export) is deliberately parked for a later cycle —
this module reads ``league/replay/html.py`` beside it for the validated
palette constants only, and never ports (or modifies) its tween/GIF/theme
machinery. Two lanes, both honest (spec c11/h11): grid logs still render
through the untouched grid face; this is the continuous lane's own face.

What ships is the honest minimum the acceptance criteria demand:

* a **header** — match id, scenario, seed, mode, time limit, and the final
  status/winner/outcome points;
* an **event timeline** — every event in the log, in canonical ``(game_time,
  seq)`` order, each row timestamped with its integer game time. This is
  where the race must read clearly: a ``post_taken`` row always carries the
  ``race-win`` marker class and a distinct color, an ``action_failed`` row
  always carries the ``race-fail`` marker class and a distinct color — so the
  winning take and the losing attempt are two unmistakably distinct,
  differently-styled moments in the same feed, never merged into one
  ambiguous line;
* a **board snapshot per distinct game-time step** — a plain inline SVG,
  positions drawn to scale from the fixed-point milliunits (never
  interpolated/tweened — a static sequence of key moments, which the spec
  explicitly allows in place of a scrubber). A contested control point draws
  one dashed ring per concurrent taker, in the taker's own team color, so the
  instant both racers are mid-take is visible in the BOARD too, not just the
  feed — because the engine represents it that way in state
  (``CControlPoint.takers``; see ``league/engine/continuous/state.py``);
* a **scorecard** (cycle-8 t8, spec c6/h6) — the per-unit grades from
  :func:`league.engine.continuous.grades.cgrade_units`, listed in this face's
  own minimal idiom: one static table (units ranked by grade, MVP/LVP marked,
  the on-role cell bolded) and one plain-text paragraph explaining exactly
  what the grade weighs. No tabs, no client JS — the grid deck's chrome stays
  un-ported.

Determinism and self-containedness (matching the repo's replay conventions,
``docs/replay-design.md``): every byte here comes from the log via
``fold_events``/``apply_event`` — the event log is the single source of
truth, and this module never recomputes game logic, only formats it. No
``Date.now``/``Math.random``, no external request of any kind (no
``http(s)://``, ``fetch``, ``@import``, remote font/CDN) — a single
self-contained file, byte-identical for the same log, every time.
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


def _render_board_svg(frame: dict[str, Any], board: dict[str, int], team_ids: list[str]) -> str:
    scale = _scale(board["width"], board["height"])
    w = _BOARD_PAD_PX * 2 + board["width"] * scale
    h = _BOARD_PAD_PX * 2 + board["height"] * scale
    parts: list[str] = [
        f'<svg viewBox="0 0 {w:.1f} {h:.1f}" class="cboard" role="img" '
        f'aria-label="board at t={frame["clock"]}">',
        f'<rect x="0" y="0" width="{w:.1f}" height="{h:.1f}" class="cboard-bg"/>',
    ]

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
    rows = []
    for entry in data["events"]:
        classes = ["cevt", f"cevt-{entry['kind']}", f"cevt-{entry['class']}"]
        if entry["kind"] == "post_taken":
            classes.append("race-win")
        elif entry["kind"] == "action_failed":
            classes.append("race-fail")
        text = _describe_event(entry)
        rows.append(
            f'<li class="{" ".join(classes)}">'
            f'<span class="cevt-t">t={entry["game_time"]}</span>'
            f'<span class="cevt-k">{_esc(entry["kind"])}</span>'
            f'<span class="cevt-d">{_esc(text)}</span></li>'
        )
    return (
        '<section class="ccard"><h2>Event timeline</h2>'
        f'<ol class="cfeed">{"".join(rows)}</ol></section>'
    )


def _render_boards(data: dict[str, Any]) -> str:
    """A static sequence of board snapshots — one per distinct game time PLUS
    the pre-match initial snapshot. Several moments can share a ``clock``
    value (e.g. the match-started transition and every unit's opening
    ``action_started`` all happen AT game_time 0, before the clock first
    advances), so each card is numbered as well as timestamped — two visibly
    different boards can legitimately both read ``t=0``."""
    team_ids = [t["id"] for t in data["teams"]]
    parts = ['<section class="ccard cboard-card"><h2>Board — key moments</h2>']
    for i, frame in enumerate(data["frames"]):
        parts.append(
            f'<div class="cframe"><div class="cframe-t">moment {i + 1} · t={frame["clock"]}'
            f"</div>"
            f'{_render_board_svg(frame, data["board"], team_ids)}</div>'
        )
    parts.append("</section>")
    return "".join(parts)


def _render_body(data: dict[str, Any]) -> str:
    return (
        _render_header(data)
        + '<div class="clayout">'
        + _render_boards(data)
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
  .ccard, .cframe { background: #1f1f1b !important; border-color: #35342f !important; }
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
.cframe { border: 1px solid rgba(127,127,127,.2); border-radius: 10px; padding: 8px;
  margin-bottom: 10px; }
.cframe-t { font-variant-numeric: tabular-nums; font-size: 12px; opacity: .7;
  margin-bottom: 4px; }
.cboard { width: 100%; height: auto; display: block; }
.cboard-bg { fill: #eeece4; }
.ccp-id { font-size: 9px; fill: currentColor; opacity: .7; }
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
<footer>Continuous replay — frame v4 (minimal-but-real, cycle 7): a static
sequence of board snapshots plus the full event timeline, rendered straight
from the match log.</footer>
</div>
<script id="cmatch-data" type="application/json">__CMATCH_DATA__</script>
</body>
</html>
"""

# Color substitution happens once at import time (fixed, validated palette
# constants — see ``docs/replay-design.md``), so ``render_chtml`` only ever
# substitutes per-log content into an already-finished template.
_TEMPLATE = _RAW_TEMPLATE.replace("__STATUS_GOOD__", STATUS_GOOD).replace(
    "__STATUS_CRITICAL__", STATUS_CRITICAL
)


def render_chtml(log: CMatchLog) -> str:
    """The continuous lane's single-file human view. No external requests,
    ever; the same log renders byte-identical HTML, every time."""
    data = build_continuous_replay_data(log)
    payload = json.dumps(data, sort_keys=True, ensure_ascii=False)
    payload = payload.replace("</", "<\\/")  # keep </script> out of the data block
    html = _TEMPLATE.replace("__CMATCH_BODY__", _render_body(data))
    return html.replace("__CMATCH_DATA__", payload)
