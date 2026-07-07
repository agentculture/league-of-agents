"""Render a match log as a self-contained, beautiful HTML replay.

Design notes (dataviz method):

* Team colors are the validated diverging pair — blue vs red — which reads as
  opposition and passes CVD/contrast checks on both surfaces (light
  ``#2a78d6``/``#e34948``, dark ``#3987e5``/``#e66767``; worst adjacent
  ΔE ≥ 66). Identity is never color-alone: every unit carries its role glyph
  and every panel labels teams by name.
* Both themes ship: ``prefers-color-scheme`` picks the default and a toggle
  stamps ``data-theme`` on the root, which wins in both directions.
* The page embeds the replay data as one ``<script type="application/json">``
  block derived from the log — the HTML and ``--json`` projections cannot
  diverge because they are the same fold.
"""

from __future__ import annotations

import json
from typing import Any

from league.engine.events import MatchLog, fold_events
from league.engine.scoring import score_match
from league.engine.state import MatchState


def _snapshot(state: MatchState) -> dict[str, Any]:
    return {
        "turn": state.turn,
        "status": state.status,
        "winner": state.winner,
        "teams": [{"id": t.id, "resources": t.resources} for t in state.teams],
        "units": [
            {
                "id": u.id,
                "team": u.team_id,
                "agent": u.agent_id,
                "role": u.role,
                "pos": list(u.pos),
                "carrying": u.carrying,
                "alive": u.alive,
            }
            for u in state.units
        ],
        "control_points": [
            {"id": c.id, "pos": list(c.pos), "owner": c.owner, "hold": [list(h) for h in c.hold]}
            for c in state.control_points
        ],
        "missions": [
            {
                "id": m.id,
                "kind": m.kind,
                "pos": list(m.pos),
                "amount": m.amount,
                "reward": m.reward,
                "status": m.status,
                "completed_by": m.completed_by,
            }
            for m in state.missions
        ],
        "resource_nodes": [
            {"id": r.id, "pos": list(r.pos), "remaining": r.remaining} for r in state.resource_nodes
        ],
    }


def build_replay_data(log: MatchLog) -> dict[str, Any]:
    """Everything the replay shows, derived from the log and nothing else."""
    initial = log.initial_state
    grouped: dict[int, list] = {}
    for event in log.events:  # one pass; (turn, seq) order is the log order
        grouped.setdefault(event.turn, []).append(event)
    frames = [_snapshot(initial)]
    events_by_turn: dict[int, list[dict[str, Any]]] = {}
    state = initial
    for turn in sorted(grouped):
        batch = tuple(grouped[turn])
        state = fold_events(state, batch)
        frames.append(_snapshot(state))
        events_by_turn[turn] = [{"kind": e.kind, "data": e.data} for e in batch]

    return {
        "match_id": initial.match_id,
        "scenario_id": initial.scenario_id,
        "seed": initial.seed,
        "mode": initial.mode,
        "grid": {"width": initial.grid_width, "height": initial.grid_height},
        "turn_limit": initial.turn_limit,
        "teams": [
            {
                "id": t.id,
                "name": t.name,
                "agents": [{"id": a.id, "model": a.model, "role": a.role} for a in t.agents],
            }
            for t in initial.teams
        ],
        "frames": frames,
        "events_by_turn": {str(k): v for k, v in events_by_turn.items()},
        "scores": score_match(log),
    }


def render_html(log: MatchLog) -> str:
    """The single-file human view. No external requests, ever."""
    payload = json.dumps(build_replay_data(log), sort_keys=True, ensure_ascii=False)
    payload = payload.replace("</", "<\\/")  # keep </script> out of the data block
    return _TEMPLATE.replace("__MATCH_DATA__", payload)


_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>League of Agents — match replay</title>
<style>
:root {
  --surface: #fcfcfb; --plane: #f9f9f7; --ink: #0b0b0b; --ink-2: #52514e;
  --muted: #898781; --grid: #e1e0d9; --line: #c3c2b7; --ring: rgba(11,11,11,.10);
  --team-0: #2a78d6; --team-1: #e34948; --node: #1baf7a; --good: #0ca30c;
  --bad: #d03b3b; --chip: #f0efec;
}
@media (prefers-color-scheme: dark) { :root {
  --surface: #1a1a19; --plane: #0d0d0d; --ink: #ffffff; --ink-2: #c3c2b7;
  --muted: #898781; --grid: #2c2c2a; --line: #383835; --ring: rgba(255,255,255,.10);
  --team-0: #3987e5; --team-1: #e66767; --node: #199e70; --good: #0ca30c;
  --bad: #d03b3b; --chip: #262624;
}}
:root[data-theme="light"] {
  --surface: #fcfcfb; --plane: #f9f9f7; --ink: #0b0b0b; --ink-2: #52514e;
  --muted: #898781; --grid: #e1e0d9; --line: #c3c2b7; --ring: rgba(11,11,11,.10);
  --team-0: #2a78d6; --team-1: #e34948; --node: #1baf7a; --chip: #f0efec;
}
:root[data-theme="dark"] {
  --surface: #1a1a19; --plane: #0d0d0d; --ink: #ffffff; --ink-2: #c3c2b7;
  --muted: #898781; --grid: #2c2c2a; --line: #383835; --ring: rgba(255,255,255,.10);
  --team-0: #3987e5; --team-1: #e66767; --node: #199e70; --chip: #262624;
}
* { box-sizing: border-box; margin: 0; }
body {
  font: 14px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif;
  background: var(--plane); color: var(--ink); padding: 20px;
}
.wrap { max-width: 1180px; margin: 0 auto; }
header { display: flex; flex-wrap: wrap; align-items: baseline; gap: 10px; margin-bottom: 16px; }
header h1 { font-size: 19px; font-weight: 650; letter-spacing: -0.01em; }
.chip {
  background: var(--chip); color: var(--ink-2); border: 1px solid var(--ring);
  border-radius: 999px; padding: 2px 10px; font-size: 12px; white-space: nowrap;
}
.winner-chip { color: var(--good); font-weight: 600; border-color: var(--good); }
#theme-toggle {
  margin-left: auto; background: var(--surface); color: var(--ink-2);
  border: 1px solid var(--ring); border-radius: 999px; padding: 4px 12px; cursor: pointer;
}
.layout { display: grid; grid-template-columns: minmax(0, 1fr) 340px; gap: 16px; }
@media (max-width: 900px) { .layout { grid-template-columns: 1fr; } }
.card {
  background: var(--surface); border: 1px solid var(--ring); border-radius: 14px;
  padding: 14px; overflow: hidden;
}
.card h2 {
  font-size: 11px; font-weight: 650; text-transform: uppercase; letter-spacing: .08em;
  color: var(--muted); margin-bottom: 10px;
}
#board-box { display: flex; flex-direction: column; gap: 12px; }
#board { width: 100%; height: auto; display: block; }
.controls { display: flex; align-items: center; gap: 8px; }
.controls button {
  background: var(--chip); color: var(--ink); border: 1px solid var(--ring);
  border-radius: 8px; min-width: 34px; height: 30px; cursor: pointer; font-size: 13px;
}
.controls button:hover { border-color: var(--muted); }
#turn-slider { flex: 1; accent-color: var(--team-0); }
#turn-label { font-variant-numeric: tabular-nums; color: var(--ink-2); min-width: 86px;
  text-align: right; }
.right { display: flex; flex-direction: column; gap: 16px; }
.team { display: flex; flex-direction: column; gap: 6px; padding: 10px 0; }
.team + .team { border-top: 1px solid var(--grid); }
.team-head { display: flex; align-items: center; gap: 8px; }
.swatch { width: 12px; height: 12px; border-radius: 4px; }
.team-name { font-weight: 650; }
.team-stats { display: flex; gap: 14px; color: var(--ink-2); font-variant-numeric: tabular-nums; }
.team-stats b { color: var(--ink); font-weight: 650; }
.agents { display: flex; flex-wrap: wrap; gap: 6px; }
.agents .chip { font-size: 11px; padding: 1px 8px; }
#feed { display: flex; flex-direction: column; gap: 6px; max-height: 300px; overflow-y: auto; }
.evt { display: flex; gap: 8px; font-size: 13px; color: var(--ink-2); }
.evt .glyph { flex: 0 0 18px; text-align: center; }
.evt.msg { color: var(--ink); }
.evt.msg .body {
  background: var(--chip); border-radius: 10px; padding: 4px 10px; border: 1px solid var(--ring);
}
.evt.reject { color: var(--bad); }
.evt.big { color: var(--ink); font-weight: 600; }
.evt .who { font-weight: 600; }
.empty { color: var(--muted); font-style: italic; }
.score-grid { display: grid; grid-template-columns: auto repeat(2, 1fr); gap: 6px 12px;
  font-variant-numeric: tabular-nums; }
.score-grid .h { color: var(--muted); font-size: 12px; }
.score-grid .num { text-align: right; }
.score-grid .total { font-weight: 700; border-top: 1px solid var(--grid); padding-top: 6px; }
.sig { margin-top: 4px; }
.sig-row { display: grid; grid-template-columns: 130px 1fr 40px; gap: 8px; align-items: center;
  margin-bottom: 6px; }
.sig-row .lbl { color: var(--ink-2); font-size: 12px; }
.sig-row .val { text-align: right; font-variant-numeric: tabular-nums; color: var(--ink-2);
  font-size: 12px; }
.bar { height: 8px; border-radius: 4px; background: var(--chip); position: relative; }
.bar > i { position: absolute; inset: 0 auto 0 0; border-radius: 4px; display: block; }
footer { margin-top: 16px; color: var(--muted); font-size: 12px; }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>League of Agents</h1>
    <span class="chip" id="meta-match"></span>
    <span class="chip" id="meta-mode"></span>
    <span class="chip" id="meta-seed"></span>
    <span class="chip winner-chip" id="meta-winner" hidden></span>
    <button id="theme-toggle" type="button">theme</button>
  </header>
  <div class="layout">
    <div class="card" id="board-box">
      <svg id="board" role="img" aria-label="match board"></svg>
      <div class="controls">
        <button id="btn-first" title="first turn">&#171;</button>
        <button id="btn-prev" title="previous turn">&#8249;</button>
        <button id="btn-play" title="play/pause">&#9654;</button>
        <button id="btn-next" title="next turn">&#8250;</button>
        <button id="btn-last" title="last turn">&#187;</button>
        <input type="range" id="turn-slider" min="0" value="0">
        <span id="turn-label"></span>
      </div>
    </div>
    <div class="right">
      <div class="card"><h2>Teams</h2><div id="teams"></div></div>
      <div class="card"><h2>Turn feed</h2><div id="feed"></div></div>
      <div class="card"><h2>Final score</h2><div id="scores"></div></div>
    </div>
  </div>
  <footer>Replay rendered from the match log — the same record agents read as JSON.
    Arrow keys step turns; space plays.</footer>
</div>
<script id="match-data" type="application/json">__MATCH_DATA__</script>
<script>
const M = JSON.parse(document.getElementById('match-data').textContent);
const CELL = 44, PAD = 10;
const teamIndex = {}; M.teams.forEach((t, i) => teamIndex[t.id] = i);
const teamColor = id => `var(--team-${teamIndex[id] ?? 0})`;
const GLYPH = { scout: 'S', harvester: 'H', defender: 'D', striker: 'K', support: 'U' };
// Deterministic fan-out for units sharing a cell — nothing may ever be occluded.
const STACK_OFFSETS = [
  [[0, 0]],
  [[-9, 0], [9, 0]],
  [[0, -9], [-9, 8], [9, 8]],
  [[-9, -9], [9, -9], [-9, 9], [9, 9]],
];
let frame = 0, playing = null;

const $ = id => document.getElementById(id);
$('meta-match').textContent = `${M.match_id} · ${M.scenario_id}`;
$('meta-mode').textContent = M.mode;
$('meta-seed').textContent = `seed ${M.seed}`;

function svgEl(tag, attrs, text) {
  const el = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  if (text != null) el.textContent = text;
  return el;
}
const cx = x => PAD + x * CELL + CELL / 2;
const cy = y => PAD + y * CELL + CELL / 2;

function drawBoard() {
  const svg = $('board');
  const w = M.grid.width * CELL + PAD * 2, h = M.grid.height * CELL + PAD * 2;
  svg.setAttribute('viewBox', `0 0 ${w} ${h}`);
  svg.innerHTML = '';
  const f = M.frames[frame];
  for (let x = 0; x <= M.grid.width; x++)
    svg.appendChild(svgEl('line', { x1: PAD + x * CELL, y1: PAD, x2: PAD + x * CELL,
      y2: h - PAD, stroke: 'var(--grid)', 'stroke-width': 1 }));
  for (let y = 0; y <= M.grid.height; y++)
    svg.appendChild(svgEl('line', { x1: PAD, y1: PAD + y * CELL, x2: w - PAD,
      y2: PAD + y * CELL, stroke: 'var(--grid)', 'stroke-width': 1 }));
  for (const n of f.resource_nodes) {
    const g = svgEl('g', { transform: `translate(${cx(n.pos[0])},${cy(n.pos[1])})` });
    g.appendChild(svgEl('rect', { x: -11, y: -11, width: 22, height: 22, rx: 6,
      transform: 'rotate(45)', fill: 'var(--node)', opacity: n.remaining ? 0.92 : 0.25 }));
    g.appendChild(svgEl('text', { y: 4, 'text-anchor': 'middle', 'font-size': 11,
      'font-weight': 700, fill: '#fff' }, n.remaining));
    svg.appendChild(g);
  }
  for (const m of f.missions) {
    const done = m.status === 'completed' && m.completed_by != null;
    if (m.kind === 'deliver') {
      svg.appendChild(svgEl('circle', { cx: cx(m.pos[0]), cy: cy(m.pos[1]), r: 17,
        fill: 'none', stroke: done ? teamColor(m.completed_by) : 'var(--muted)',
        'stroke-dasharray': '3 3', 'stroke-width': done ? 2 : 1 }));
    }
    svg.appendChild(svgEl('text', { x: cx(m.pos[0]), y: cy(m.pos[1]) + 28,
      'text-anchor': 'middle', 'font-size': 9,
      fill: done ? teamColor(m.completed_by) : 'var(--muted)' },
      done ? `${m.id} → ${m.completed_by}` : `${m.id}: ${m.kind} ${m.amount}`));
  }
  for (const c of f.control_points) {
    const owned = c.owner != null;
    svg.appendChild(svgEl('circle', { cx: cx(c.pos[0]), cy: cy(c.pos[1]), r: 14,
      fill: owned ? teamColor(c.owner) : 'var(--surface)',
      'fill-opacity': owned ? 0.25 : 1,
      stroke: owned ? teamColor(c.owner) : 'var(--line)', 'stroke-width': 2.5 }));
    svg.appendChild(svgEl('text', { x: cx(c.pos[0]), y: cy(c.pos[1]) - 18,
      'text-anchor': 'middle', 'font-size': 9, fill: 'var(--muted)' }, c.id));
    if (c.hold.length) svg.appendChild(svgEl('text', { x: cx(c.pos[0]),
      y: cy(c.pos[1]) + 4, 'text-anchor': 'middle', 'font-size': 10, 'font-weight': 700,
      fill: 'var(--ink-2)' }, c.hold[0][1]));
  }
  const byCell = new Map();
  for (const u of f.units) {
    if (!u.alive) continue;
    const key = u.pos.join(',');
    if (!byCell.has(key)) byCell.set(key, []);
    byCell.get(key).push(u);
  }
  for (const stack of byCell.values()) {
    const n = stack.length;
    // Predefined aesthetic patterns cover 1-4; beyond that, place units evenly
    // on a circle so no two ever land on the same offset (nothing is occluded
    // no matter how many units share a cell — e.g. the deliver square doubling
    // as a control point can stack a full 6-unit match there).
    const offs = n <= STACK_OFFSETS.length ? STACK_OFFSETS[n - 1] : Array.from(
      { length: n },
      (_, i) => {
        const angle = (2 * Math.PI * i) / n - Math.PI / 2;
        return [Math.round(13 * Math.cos(angle)), Math.round(13 * Math.sin(angle))];
      },
    );
    stack.forEach((u, i) => {
      const [dx, dy] = offs[i];
      const r = stack.length > 1 ? 9 : 12;
      const g = svgEl('g',
        { transform: `translate(${cx(u.pos[0]) + dx},${cy(u.pos[1]) + dy})` });
      g.appendChild(svgEl('circle', { r, fill: teamColor(u.team),
        stroke: 'var(--surface)', 'stroke-width': 2 }));
      g.appendChild(svgEl('text', { y: r > 9 ? 4 : 3, 'text-anchor': 'middle',
        'font-size': r > 9 ? 11 : 9, 'font-weight': 700, fill: '#fff' },
        GLYPH[u.role] || u.role[0].toUpperCase()));
      if (u.carrying > 0) {
        const bx = r - 2, by = 2 - r;
        g.appendChild(svgEl('circle', { cx: bx, cy: by, r: 6, fill: 'var(--node)',
          stroke: 'var(--surface)', 'stroke-width': 1.5 }));
        g.appendChild(svgEl('text', { x: bx, y: by + 3, 'text-anchor': 'middle',
          'font-size': 8, 'font-weight': 700, fill: '#fff' }, u.carrying));
      }
      g.appendChild(svgEl('title', {}, `${u.id} (${u.role}, ${u.agent})`));
      svg.appendChild(g);
    });
  }
}

function drawTeams() {
  const f = M.frames[frame];
  $('teams').innerHTML = M.teams.map(t => {
    const res = f.teams.find(x => x.id === t.id).resources;
    const done = f.missions.filter(m => m.completed_by === t.id).length;
    return `<div class="team">
      <div class="team-head"><span class="swatch" style="background:${teamColor(t.id)}"></span>
        <span class="team-name">${esc(t.name)}</span></div>
      <div class="team-stats"><span>resources <b>${esc(res)}</b></span>
        <span>missions <b>${esc(done)}</b></span></div>
      <div class="agents">${t.agents.map(a =>
        `<span class="chip">${GLYPH[a.role] || '?'} ${esc(a.id)} · ${esc(a.model)}</span>`)
        .join('')}</div>
    </div>`;
  }).join('');
}

const FEED = {
  match_started: () => ['&#9873;', 'big', 'match started'],
  plan_declared: d => ['&#128220;', 'msg', `<span class="who">${esc(d.team_id)}</span>
    <span class="body">plan: ${esc(d.text)}</span>`],
  message_sent: d => ['&#128172;', 'msg', `<span class="who">${esc(d.from)}</span>
    <span class="body">${esc(d.text)}</span>`],
  action_declared: d => ['&#9998;', '', `${esc(d.unit_id)} declares ${esc(d.action)}${d.to ?
    ' to ' + esc(d.to.join(',')) : ''}`],
  action_rejected: d => ['&#10060;', 'reject',
    `${esc(d.unit_id ?? '?')} rejected — ${esc(d.reason)}`],
  unit_moved: d => ['&#8599;', '', `${esc(d.unit_id)} moves to ${esc(d.to.join(','))}`],
  resource_gathered: d => ['&#9935;', '',
    `${esc(d.unit_id)} gathers ${esc(d.amount)} from ${esc(d.node_id)}`],
  resource_delivered: d => ['&#128230;', '', `${esc(d.unit_id)} delivers ${esc(d.amount)}`],
  control_point_captured: d => ['&#127988;', 'big', `${esc(d.team_id)} captures ${esc(d.cp_id)}`],
  control_point_held: d => d.turns ? ['&#9200;', '', `${esc(d.team_id)} holds ${esc(d.cp_id)}
    (${esc(d.turns)})`] : null,
  unit_defeated: d => ['&#128128;', 'big', `${esc(d.unit_id)} is down`],
  mission_completed: d => ['&#127942;', 'big',
    `${esc(d.team_id)} completes ${esc(d.mission_id)}`],
  match_finished: d => ['&#127937;', 'big', d.winner ? `match over — ${esc(d.winner)} wins`
    : 'match over'],
  turn_advanced: () => null, turn_resolved: () => null,
};
function esc(s) { const d = document.createElement('i'); d.textContent = String(s);
  return d.innerHTML; }

function drawFeed() {
  const f = M.frames[frame];
  const evts = frame === 0 ? [] : (M.events_by_turn[String(f.turn)] || []);
  const rows = evts.map(e => FEED[e.kind] ? FEED[e.kind](e.data) : null).filter(Boolean)
    .map(([g, cls, html]) => `<div class="evt ${cls}"><span class="glyph">${g}</span>
      <span>${html}</span></div>`);
  $('feed').innerHTML = rows.length ? rows.join('')
    : '<div class="empty">nothing happened this turn</div>';
}

function drawScores() {
  const S = M.scores, box = $('scores');
  const head = `<div class="score-grid"><span class="h"></span>` + M.teams.map(t =>
    `<span class="h num" style="color:${teamColor(t.id)};font-weight:700">${esc(t.name)}</span>`)
    .join('') + rows() + `</div>` + sigs();
  function rows() {
    const parts = ['missions', 'control', 'resources'];
    let out = parts.map(p => `<span class="h">${p}</span>` + M.teams.map(t =>
      `<span class="num">${S.outcome[t.id][p]}</span>`).join('')).join('');
    out += `<span class="total">outcome</span>` + M.teams.map(t =>
      `<span class="num total">${S.outcome[t.id].total}</span>`).join('');
    out += `<span class="total">cooperation</span>` + M.teams.map(t =>
      `<span class="num total">${S.cooperation[t.id].score}</span>`).join('');
    return out;
  }
  function sigs() {
    return `<div class="sig">` + M.teams.map(t => {
      const sig = S.cooperation[t.id].signals;
      return Object.entries(sig).map(([k, v]) => `<div class="sig-row">
        <span class="lbl">${esc(t.id)} · ${esc(k.replace(/_/g, ' '))}</span>
        <span class="bar"><i style="width:${Math.round(v * 100)}%;
          background:${teamColor(t.id)}"></i></span>
        <span class="val">${v.toFixed(2)}</span></div>`).join('');
    }).join('') + `</div>`;
  }
  box.innerHTML = head;
}

function render() {
  const f = M.frames[frame];
  drawBoard(); drawTeams(); drawFeed();
  $('turn-slider').value = frame;
  $('turn-label').textContent = `turn ${f.turn} / ${M.turn_limit}`;
  const last = M.frames[M.frames.length - 1];
  if (last.status === 'finished') {
    const w = $('meta-winner');
    w.hidden = false;
    w.textContent = last.winner ? (last.winner === 'draw' ? 'draw' : `${last.winner} wins`)
      : 'unresolved';
  }
}
function go(i) { frame = Math.max(0, Math.min(M.frames.length - 1, i)); render(); }
function toggle() {
  if (playing) { clearInterval(playing); playing = null; $('btn-play').innerHTML = '&#9654;'; }
  else {
    $('btn-play').innerHTML = '&#10073;&#10073;';
    playing = setInterval(() => {
      if (frame >= M.frames.length - 1) toggle(); else go(frame + 1);
    }, 550);
  }
}
$('turn-slider').max = M.frames.length - 1;
$('turn-slider').addEventListener('input', e => go(+e.target.value));
$('btn-first').onclick = () => go(0);
$('btn-prev').onclick = () => go(frame - 1);
$('btn-next').onclick = () => go(frame + 1);
$('btn-last').onclick = () => go(M.frames.length - 1);
$('btn-play').onclick = toggle;
document.addEventListener('keydown', e => {
  if (e.key === 'ArrowLeft') go(frame - 1);
  else if (e.key === 'ArrowRight') go(frame + 1);
  else if (e.key === ' ') { e.preventDefault(); toggle(); }
});
$('theme-toggle').onclick = () => {
  const root = document.documentElement;
  const dark = window.matchMedia('(prefers-color-scheme: dark)').matches;
  const cur = root.dataset.theme || (dark ? 'dark' : 'light');
  root.dataset.theme = cur === 'dark' ? 'light' : 'dark';
};
// Deep link: replay.html#t7 opens on turn 7, so reviewers can point at a frame.
const hashTurn = (location.hash.match(/^#t(\\d+)$/) || [])[1];
if (hashTurn != null) {
  const idx = M.frames.findIndex(f => f.turn === +hashTurn);
  if (idx >= 0) frame = idx;
}
drawScores(); render();
</script>
</body>
</html>
"""
