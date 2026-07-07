"""Render a match log as a self-contained, mesmerizing HTML replay.

Design notes (dataviz method — see ``docs/replay-design.md`` for the full
rationale, palette values, and the ``validate_palette.js`` results):

* **Color by job.** Team identity is the validated *categorical* pair — blue
  (slot 1) vs red (slot 6) — stepped per surface (light ``#2a78d6``/``#e34948``,
  dark ``#3987e5``/``#e66767``); both modes pass all six checks, worst adjacent
  CVD ΔE 74.6 light / 66.4 dark. Control-point ownership is the owner's hue as a
  low-opacity tint. Resources are a fixed element hue (aqua) carried on a
  distinct diamond mark with a numeric label (the secondary encoding that keeps
  it legal beside the reds). **Status colors** (good ``#0ca30c``, critical
  ``#d03b3b``) are reserved for event moments — delivery/mission/defeat — always
  paired with an icon+label, and never worn by a team. Text always wears text
  tokens; identity rides a colored chip/swatch beside the name, never the text.
* **Both themes are deliberately designed** — each carries its own surface, ink,
  and elevation tokens (not an auto-flip). ``prefers-color-scheme`` picks the
  default; a manual toggle stamps ``data-theme`` on the root and wins in both
  directions.
* **Purposeful motion, all gated by ``prefers-reduced-motion``.** Units glide
  between turns via a transform transition; a soft ring pulses on a fresh
  capture, a flash celebrates deliveries and mission completions, a red ring
  marks a defeat. Play/pause with an adjustable speed. Timing is CSS-only, so
  generation stays byte-deterministic — the same log renders identical HTML.
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

# Palette constants — the SAME validated hex values behind the CSS custom
# properties in ``_TEMPLATE`` below (light theme). Exported so other
# renderers built on the same replay fold (e.g. ``league.replay.video``'s
# raster frames, plan task t6) draw with the identical, already-validated
# hues instead of re-deriving their own (dataviz palette.md).
TEAM_COLORS: tuple[str, ...] = (
    "#2a78d6",
    "#e34948",
    "#eb6834",
    "#4a3aa7",
    "#e87ba4",
    "#eda100",
)
RESOURCE_COLOR = "#1baf7a"
STATUS_GOOD = "#0ca30c"
STATUS_CRITICAL = "#d03b3b"
BOARD_PLANE = "#f2f1ec"
BOARD_LINE = "#c3c2b7"
BOARD_INK = "#0b0b0b"
BOARD_MUTED = "#898781"
GLYPH_INK = "#ffffff"


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
                "completed_by": list(m.completed_by),
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
  color-scheme: light;
  --font: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  --s1: 4px; --s2: 8px; --s3: 12px; --s4: 16px; --s5: 20px; --s6: 28px;
  --r-sm: 8px; --r-md: 12px; --r-lg: 18px;
  --move: 0.55s;
  /* status scale — fixed, never themed (dataviz palette.md) */
  --good: #0ca30c; --warning: #fab219; --serious: #ec835a; --critical: #d03b3b;
  /* light surfaces + ink */
  --plane: #f2f1ec; --surface: #fcfcfb; --surface-2: #ffffff;
  --ink: #0b0b0b; --ink-2: #52514e; --muted: #898781;
  --grid: #e6e5de; --line: #c3c2b7; --ring: rgba(11, 11, 11, .10);
  --chip: #f0efec; --track: #e9e8e2; --board-top: #ffffff; --board-bot: #f5f4f0;
  /* team identity = validated categorical hues, fixed order */
  --team-0: #2a78d6; --team-1: #e34948; --team-2: #eb6834;
  --team-3: #4a3aa7; --team-4: #e87ba4; --team-5: #eda100;
  --resource: #1baf7a; --glyph-ink: #ffffff;
  --shadow: 0 1px 2px rgba(11, 11, 11, .05), 0 10px 30px -16px rgba(11, 11, 11, .22);
  --shadow-hero: 0 2px 6px rgba(11, 11, 11, .06), 0 26px 52px -28px rgba(11, 11, 11, .30);
}
@media (prefers-color-scheme: dark) { :root {
  color-scheme: dark;
  --plane: #0d0d0d; --surface: #1a1a19; --surface-2: #232221;
  --ink: #ffffff; --ink-2: #c3c2b7; --muted: #8f8d87;
  --grid: #2a2a28; --line: #3a3a37; --ring: rgba(255, 255, 255, .10);
  --chip: #262624; --track: #2b2b28; --board-top: #201f1e; --board-bot: #161615;
  --team-0: #3987e5; --team-1: #e66767; --team-2: #d95926;
  --team-3: #9085e9; --team-4: #d55181; --team-5: #c98500;
  --resource: #199e70; --glyph-ink: #ffffff;
  --shadow: 0 1px 0 rgba(255, 255, 255, .04) inset, 0 14px 34px -18px rgba(0, 0, 0, .75);
  --shadow-hero: 0 1px 0 rgba(255, 255, 255, .05) inset, 0 30px 60px -30px rgba(0, 0, 0, .85);
}}
:root[data-theme="light"] {
  color-scheme: light;
  --plane: #f2f1ec; --surface: #fcfcfb; --surface-2: #ffffff;
  --ink: #0b0b0b; --ink-2: #52514e; --muted: #898781;
  --grid: #e6e5de; --line: #c3c2b7; --ring: rgba(11, 11, 11, .10);
  --chip: #f0efec; --track: #e9e8e2; --board-top: #ffffff; --board-bot: #f5f4f0;
  --team-0: #2a78d6; --team-1: #e34948; --team-2: #eb6834;
  --team-3: #4a3aa7; --team-4: #e87ba4; --team-5: #eda100;
  --resource: #1baf7a; --glyph-ink: #ffffff;
  --shadow: 0 1px 2px rgba(11, 11, 11, .05), 0 10px 30px -16px rgba(11, 11, 11, .22);
  --shadow-hero: 0 2px 6px rgba(11, 11, 11, .06), 0 26px 52px -28px rgba(11, 11, 11, .30);
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --plane: #0d0d0d; --surface: #1a1a19; --surface-2: #232221;
  --ink: #ffffff; --ink-2: #c3c2b7; --muted: #8f8d87;
  --grid: #2a2a28; --line: #3a3a37; --ring: rgba(255, 255, 255, .10);
  --chip: #262624; --track: #2b2b28; --board-top: #201f1e; --board-bot: #161615;
  --team-0: #3987e5; --team-1: #e66767; --team-2: #d95926;
  --team-3: #9085e9; --team-4: #d55181; --team-5: #c98500;
  --resource: #199e70; --glyph-ink: #ffffff;
  --shadow: 0 1px 0 rgba(255, 255, 255, .04) inset, 0 14px 34px -18px rgba(0, 0, 0, .75);
  --shadow-hero: 0 1px 0 rgba(255, 255, 255, .05) inset, 0 30px 60px -30px rgba(0, 0, 0, .85);
}
* { box-sizing: border-box; margin: 0; }
body {
  font: 14px/1.55 var(--font); background: var(--plane); color: var(--ink);
  padding: 24px 20px; -webkit-font-smoothing: antialiased;
  transition: background .3s ease, color .3s ease;
}
.wrap { max-width: 1200px; margin: 0 auto; }
header { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin-bottom: 20px; }
.brand { display: flex; align-items: center; gap: 11px; }
.brand .mark {
  width: 22px; height: 22px; border-radius: 7px;
  background: linear-gradient(135deg, var(--team-0), var(--team-1));
  box-shadow: var(--shadow); flex: 0 0 auto;
}
header h1 { font-size: 20px; font-weight: 640; letter-spacing: -.02em; }
.meta { display: flex; flex-wrap: wrap; gap: 8px; }
.chip {
  background: var(--chip); color: var(--ink-2); border: 1px solid var(--ring);
  border-radius: 999px; padding: 3px 11px; font-size: 12px; white-space: nowrap;
}
.winner-chip { color: var(--good); font-weight: 600; border-color: var(--good); }
#theme-toggle {
  margin-left: auto; display: inline-flex; align-items: center; gap: 8px;
  background: var(--surface-2); color: var(--ink-2); border: 1px solid var(--ring);
  border-radius: 999px; padding: 6px 13px; cursor: pointer; font: inherit; font-size: 12px;
  box-shadow: var(--shadow); transition: color .15s, border-color .15s;
}
#theme-toggle:hover { color: var(--ink); border-color: var(--muted); }
#theme-toggle .tt-ico {
  width: 12px; height: 12px; border-radius: 50%;
  background: linear-gradient(135deg, var(--ink-2), var(--muted));
}
.layout {
  display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 18px; align-items: start;
}
@media (max-width: 920px) { .layout { grid-template-columns: 1fr; } }
.card {
  background: var(--surface); border: 1px solid var(--ring); border-radius: var(--r-lg);
  padding: 16px; box-shadow: var(--shadow);
}
.card h2 {
  font-size: 10.5px; font-weight: 700; text-transform: uppercase; letter-spacing: .12em;
  color: var(--muted); margin-bottom: 12px;
}
.board-card { padding: 14px; box-shadow: var(--shadow-hero); }
#board-box { display: flex; flex-direction: column; gap: 14px; }
.board-frame {
  border-radius: var(--r-md); padding: 8px; border: 1px solid var(--ring);
  background: linear-gradient(180deg, var(--board-top), var(--board-bot));
}
#board { width: 100%; height: auto; display: block; }
.gl { stroke: var(--grid); stroke-width: 1; }
#unit-layer g {
  transition: transform var(--move) cubic-bezier(.34, .03, .24, 1), opacity .35s ease;
}
body.booting #unit-layer g { transition: none; }
.u-body { stroke: var(--surface); stroke-width: 2.4; }
.u-glyph { fill: var(--glyph-ink); font-weight: 700; }
.u-carry-dot { stroke: var(--surface); stroke-width: 1.5; }
.u-carry-num { fill: var(--glyph-ink); font-size: 8px; font-weight: 700; }
.cp-disc {
  fill: var(--surface); stroke: var(--line); stroke-width: 2.4;
  transform-box: fill-box; transform-origin: center;
}
.cp-disc.owned { fill-opacity: .24; }
.cp-disc.flood { animation: cp-flood .7s ease-out both; }
.cp-id { fill: var(--muted); font-size: 9px; letter-spacing: .05em; }
.cp-hold { fill: var(--ink-2); font-size: 10px; font-weight: 700; }
.node-num { fill: var(--glyph-ink); font-size: 11px; font-weight: 700; }
.m-ring { fill: none; stroke-width: 1.5; opacity: .5; }
.m-ring.done { stroke-width: 2.4; opacity: 1; }
.m-label { fill: var(--ink-2); font-size: 9.5px; }
.fx {
  fill: none; stroke-width: 2.6; pointer-events: none;
  transform-box: fill-box; transform-origin: center;
}
.fx.ring { animation: fx-ring .9s ease-out forwards; }
.fx.big { animation-duration: 1.15s; }
.fx.flash { stroke: none; animation: fx-flash 1s ease-out forwards; }
@keyframes fx-ring { from { opacity: .85; transform: scale(.3); }
  to { opacity: 0; transform: scale(2.7); } }
@keyframes fx-flash { 0% { opacity: 0; transform: scale(.35); } 30% { opacity: .85; }
  100% { opacity: 0; transform: scale(2.1); } }
@keyframes cp-flood { from { transform: scale(.4); } to { transform: scale(1); } }
@keyframes row-in { from { opacity: 0; transform: translateY(3px); } to { opacity: 1;
  transform: none; } }
.controls { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.transport { display: inline-flex; gap: 4px; }
.controls button {
  background: var(--chip); color: var(--ink); border: 1px solid var(--ring);
  border-radius: 9px; min-width: 34px; height: 32px; cursor: pointer; font-size: 13px;
  font-family: var(--font); display: inline-flex; align-items: center; justify-content: center;
  transition: border-color .15s, background .15s, color .15s;
}
.controls button:hover { border-color: var(--muted); }
#btn-play.on { background: var(--team-0); color: #fff; border-color: var(--team-0); }
#turn-slider { flex: 1; min-width: 120px; accent-color: var(--team-0); }
#turn-label {
  font-variant-numeric: tabular-nums; color: var(--ink-2); min-width: 92px;
  text-align: right; font-size: 13px;
}
.speed { display: inline-flex; gap: 4px; }
.speed button { min-width: 40px; font-size: 11px; font-variant-numeric: tabular-nums; }
.speed button.on { border-color: var(--team-0); color: var(--team-0); }
.right { display: flex; flex-direction: column; gap: 18px; }
.team { display: flex; flex-direction: column; gap: 7px; padding: 11px 0; }
.team + .team { border-top: 1px solid var(--grid); }
.team-head { display: flex; align-items: center; gap: 9px; }
.swatch { width: 12px; height: 12px; border-radius: 4px; box-shadow: 0 0 0 1px var(--ring) inset; }
.team-name { font-weight: 640; letter-spacing: -.01em; }
.team-stats {
  display: flex; gap: 16px; color: var(--ink-2); font-variant-numeric: tabular-nums;
  font-size: 13px;
}
.team-stats b { color: var(--ink); font-weight: 650; }
.agents { display: flex; flex-wrap: wrap; gap: 6px; }
.agents .chip {
  font-size: 11px; padding: 2px 9px; display: inline-flex; align-items: center; gap: 5px;
}
.agents .chip .dot { width: 7px; height: 7px; border-radius: 50%; flex: 0 0 auto; }
#feed {
  display: flex; flex-direction: column; gap: 8px; max-height: 320px; overflow-y: auto;
  padding-right: 2px;
}
.evt {
  display: flex; gap: 9px; font-size: 13px; color: var(--ink-2); line-height: 1.4;
  animation: row-in .3s ease both;
}
.evt .glyph { flex: 0 0 18px; text-align: center; color: var(--muted); }
.evt .txt { min-width: 0; }
.evt.msg { color: var(--ink); }
.evt.msg .body {
  background: var(--chip); border-radius: 10px; padding: 3px 10px; border: 1px solid var(--ring);
  display: inline-block;
}
.evt .who { font-weight: 640; color: var(--ink); }
.evt.big { color: var(--ink); font-weight: 600; }
.evt.good .glyph { color: var(--good); }
.evt.reject { color: var(--critical); }
.evt.reject .glyph { color: var(--critical); }
.empty { color: var(--muted); font-style: italic; }
.score-grid {
  display: grid; grid-template-columns: auto repeat(2, 1fr); gap: 7px 14px;
  font-variant-numeric: tabular-nums; align-items: center;
}
.score-grid .h { color: var(--muted); font-size: 12px; }
.score-grid .team-col {
  color: var(--ink); font-weight: 640; display: inline-flex; align-items: center; gap: 6px;
  justify-content: flex-end;
}
.score-grid .team-col .dot { width: 9px; height: 9px; border-radius: 3px; flex: 0 0 auto; }
.score-grid .num { text-align: right; }
.score-grid .total {
  font-weight: 700; border-top: 1px solid var(--grid); padding-top: 7px; margin-top: 1px;
}
.sig { margin-top: 10px; }
.sig-row {
  display: grid; grid-template-columns: 132px 1fr 40px; gap: 9px; align-items: center;
  margin-bottom: 7px;
}
.sig-row .lbl { color: var(--ink-2); font-size: 11.5px; }
.sig-row .val {
  text-align: right; font-variant-numeric: tabular-nums; color: var(--ink-2); font-size: 11.5px;
}
.bar {
  height: 8px; border-radius: 5px; background: var(--track); position: relative; overflow: hidden;
}
.bar > i { position: absolute; inset: 0 auto 0 0; border-radius: 5px; display: block; }
footer { margin-top: 20px; color: var(--muted); font-size: 12px; line-height: 1.6; }
footer kbd {
  font-family: var(--font); background: var(--chip); border: 1px solid var(--ring);
  border-radius: 5px; padding: 1px 6px; font-size: 11px; color: var(--ink-2);
}
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    transition-duration: 1ms !important; animation-duration: 1ms !important;
    animation-iteration-count: 1 !important;
  }
}
</style>
</head>
<body class="booting">
<div class="wrap">
  <header>
    <div class="brand"><span class="mark" aria-hidden="true"></span><h1>League of Agents</h1></div>
    <div class="meta">
      <span class="chip" id="meta-match"></span>
      <span class="chip" id="meta-mode"></span>
      <span class="chip" id="meta-seed"></span>
      <span class="chip winner-chip" id="meta-winner" hidden></span>
    </div>
    <button id="theme-toggle" type="button" aria-pressed="false">
      <span class="tt-ico" aria-hidden="true"></span><span class="tt-label">Dark</span>
    </button>
  </header>
  <div class="layout">
    <div class="card board-card" id="board-box">
      <div class="board-frame"><svg id="board" role="img" aria-label="match board"></svg></div>
      <div class="controls">
        <div class="transport" role="group" aria-label="transport">
          <button id="btn-first" title="first turn">&#171;</button>
          <button id="btn-prev" title="previous turn">&#8249;</button>
          <button id="btn-play" title="play/pause" aria-label="play">&#9654;</button>
          <button id="btn-next" title="next turn">&#8250;</button>
          <button id="btn-last" title="last turn">&#187;</button>
        </div>
        <input type="range" id="turn-slider" min="0" value="0" aria-label="turn">
        <span id="turn-label"></span>
        <div class="speed" role="group" aria-label="playback speed">
          <button data-speed="0.5" title="half speed">0.5&#215;</button>
          <button data-speed="1" class="on" title="normal speed">1&#215;</button>
          <button data-speed="2" title="double speed">2&#215;</button>
        </div>
      </div>
    </div>
    <div class="right">
      <div class="card"><h2>Teams</h2><div id="teams"></div></div>
      <div class="card"><h2>Turn feed</h2><div id="feed"></div></div>
      <div class="card"><h2>Final score</h2><div id="scores"></div></div>
    </div>
  </div>
  <footer>Replay rendered from the match log &mdash; the same record agents read as JSON.
    <kbd>&larr;</kbd> <kbd>&rarr;</kbd> step turns, <kbd>space</kbd> plays.</footer>
</div>
<script id="match-data" type="application/json">__MATCH_DATA__</script>
<script>
const M = JSON.parse(document.getElementById('match-data').textContent);
const CELL = 46, PAD = 14;
const SVGNS = 'http://www.w3.org/2000/svg';
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
const SPEEDS = { '0.5': 1400, '1': 800, '2': 400 };
const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
let frame = 0, playing = null, speed = 1;

const $ = id => document.getElementById(id);
const cx = x => PAD + x * CELL + CELL / 2;
const cy = y => PAD + y * CELL + CELL / 2;
function esc(s) {
  const d = document.createElement('i'); d.textContent = String(s); return d.innerHTML;
}
function svgEl(tag, attrs, text) {
  const el = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  if (text != null) el.textContent = text;
  return el;
}

$('meta-match').textContent = `${M.match_id} · ${M.scenario_id}`;
$('meta-mode').textContent = M.mode;
$('meta-seed').textContent = `seed ${M.seed}`;

// ---- static board scaffold (built once; only units + field + fx change per frame)
const W = M.grid.width * CELL + PAD * 2, H = M.grid.height * CELL + PAD * 2;
const svg = $('board');
svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
svg.innerHTML = '';
const gGrid = svgEl('g', { class: 'grid' });
for (let x = 0; x <= M.grid.width; x++)
  gGrid.appendChild(svgEl('line', { x1: PAD + x * CELL, y1: PAD, x2: PAD + x * CELL,
    y2: H - PAD, class: 'gl' }));
for (let y = 0; y <= M.grid.height; y++)
  gGrid.appendChild(svgEl('line', { x1: PAD, y1: PAD + y * CELL, x2: W - PAD,
    y2: PAD + y * CELL, class: 'gl' }));
const gField = svgEl('g', { class: 'field' });
const gUnits = svgEl('g', { id: 'unit-layer' });
const gFx = svgEl('g', { class: 'fx-layer' });
svg.appendChild(gGrid); svg.appendChild(gField); svg.appendChild(gUnits); svg.appendChild(gFx);

// Persistent unit nodes over the whole roster, so a move animates the SAME node
// from its old cell to its new one (a transform transition), never a redraw.
const roster = [], seen = new Set();
for (const f of M.frames) for (const u of f.units)
  if (!seen.has(u.id)) { seen.add(u.id); roster.push(u); }
const unitNodes = new Map();
for (const u of roster) {
  const g = svgEl('g', { class: 'unit', 'data-id': u.id });
  const body = svgEl('circle', { r: 12, class: 'u-body' }); body.style.fill = teamColor(u.team);
  const glyph = svgEl('text', { y: 4, 'text-anchor': 'middle', 'font-size': 11, class: 'u-glyph' },
    GLYPH[u.role] || u.role[0].toUpperCase());
  const carry = svgEl('g', { class: 'u-carry' }); carry.style.opacity = 0;
  const cdot = svgEl('circle', { r: 6, class: 'u-carry-dot' }); cdot.style.fill = 'var(--resource)';
  const cnum = svgEl('text', { y: 3, 'text-anchor': 'middle', class: 'u-carry-num' }, '');
  carry.appendChild(cdot); carry.appendChild(cnum);
  g.appendChild(body); g.appendChild(glyph); g.appendChild(carry);
  g.appendChild(svgEl('title', {}, `${u.id} — ${u.role} · ${u.agent}`));
  gUnits.appendChild(g);
  unitNodes.set(u.id, { g, body, glyph, carry, cnum });
}

// Per-frame placement, incl. the deterministic stack fan-out.
function placement(f) {
  const byCell = new Map();
  for (const u of f.units) {
    if (!u.alive) continue;
    const key = u.pos.join(',');
    if (!byCell.has(key)) byCell.set(key, []);
    byCell.get(key).push(u);
  }
  const out = {};
  for (const stack of byCell.values()) {
    stack.sort((a, b) => a.id < b.id ? -1 : a.id > b.id ? 1 : 0);
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
      // Solitary units keep the full 12px radius; stacked ones shrink, never hide.
      const r = stack.length > 1 ? 9 : 12;
      out[u.id] = { x: cx(u.pos[0]) + dx, y: cy(u.pos[1]) + dy, r, carry: u.carrying };
    });
  }
  return out;
}

function renderUnits(f) {
  const p = placement(f);
  for (const [id, n] of unitNodes) {
    const s = p[id];
    if (!s) { n.g.style.opacity = 0; continue; }
    n.g.style.opacity = 1;
    n.g.style.transform = `translate(${s.x}px, ${s.y}px)`;
    n.body.setAttribute('r', s.r);
    n.glyph.setAttribute('font-size', s.r > 9 ? 11 : 9);
    n.glyph.setAttribute('y', s.r > 9 ? 4 : 3);
    if (s.carry > 0) {
      n.carry.style.opacity = 1;
      n.carry.setAttribute('transform', `translate(${s.r - 2}, ${2 - s.r})`);
      n.cnum.textContent = s.carry;
    } else n.carry.style.opacity = 0;
  }
}

function capturesOf(fi) {
  const s = new Set();
  const turn = M.frames[fi].turn;
  for (const e of (M.events_by_turn[String(turn)] || []))
    if (e.kind === 'control_point_captured') s.add(e.data.cp_id);
  return s;
}

function renderField(f, flooded) {
  gField.textContent = '';
  for (const n of f.resource_nodes) {
    const g = svgEl('g',
      { transform: `translate(${cx(n.pos[0])},${cy(n.pos[1])})`, class: 'node' });
    const d = svgEl('rect', { x: -11, y: -11, width: 22, height: 22, rx: 5,
      transform: 'rotate(45)' });
    d.style.fill = 'var(--resource)'; d.style.fillOpacity = n.remaining ? 0.95 : 0.28;
    g.appendChild(d);
    g.appendChild(svgEl('text', { y: 4, 'text-anchor': 'middle', class: 'node-num' }, n.remaining));
    gField.appendChild(g);
  }
  for (const m of f.missions) {
    const done = m.status === 'completed' && m.completed_by.length > 0;
    const single = done && m.completed_by.length === 1;
    const g = svgEl('g',
      { transform: `translate(${cx(m.pos[0])},${cy(m.pos[1])})`, class: 'mission' });
    if (m.kind === 'deliver') {
      // The ring is a MARK and carries team identity; a shared win wears the
      // neutral ink so neither team's color claims it (spec c15).
      const ring = svgEl('circle', { r: 18, class: 'm-ring' + (done ? ' done' : '') });
      ring.style.stroke = single ? teamColor(m.completed_by[0])
        : done ? 'var(--ink-2)' : 'var(--muted)';
      g.appendChild(ring);
    }
    // The label is TEXT — it wears a text token, never the team color.
    g.appendChild(svgEl('text', { y: 30, 'text-anchor': 'middle', class: 'm-label' },
      done ? `${m.id} → ${m.completed_by.join(' + ')}` : `${m.id}: ${m.kind} ${m.amount}`));
    gField.appendChild(g);
  }
  for (const c of f.control_points) {
    const owned = c.owner != null;
    const g = svgEl('g', { transform: `translate(${cx(c.pos[0])},${cy(c.pos[1])})`, class: 'cp' });
    const cls = 'cp-disc' + (owned ? ' owned' : '') + (flooded.has(c.id) ? ' flood' : '');
    const disc = svgEl('circle', { r: 15, class: cls });
    if (owned) { disc.style.fill = teamColor(c.owner); disc.style.stroke = teamColor(c.owner); }
    g.appendChild(disc);
    g.appendChild(svgEl('text', { y: -20, 'text-anchor': 'middle', class: 'cp-id' }, c.id));
    if (c.hold.length) g.appendChild(svgEl('text', { y: 5, 'text-anchor': 'middle',
      class: 'cp-hold' }, c.hold[0][1]));
    gField.appendChild(g);
  }
}

// Restrained, deterministic celebration — only on a forward step, never on a
// scrub or reverse, and never at all under prefers-reduced-motion.
function fxRing(x, y, color, r, big) {
  const c = svgEl('circle', { cx: x, cy: y, r, class: 'fx ring' + (big ? ' big' : '') });
  c.style.stroke = color; gFx.appendChild(c);
  c.addEventListener('animationend', () => c.remove(), { once: true });
}
function fxFlash(x, y, color, r) {
  const c = svgEl('circle', { cx: x, cy: y, r, class: 'fx flash' });
  c.style.fill = color; gFx.appendChild(c);
  c.addEventListener('animationend', () => c.remove(), { once: true });
}
function spawnFx(fi) {
  if (reduce) return;
  const f = M.frames[fi];
  for (const e of (M.events_by_turn[String(f.turn)] || [])) {
    if (e.kind === 'control_point_captured') {
      const cp = f.control_points.find(c => c.id === e.data.cp_id);
      if (cp) fxRing(cx(cp.pos[0]), cy(cp.pos[1]), teamColor(e.data.team_id), 15, true);
    } else if (e.kind === 'resource_delivered') {
      const u = f.units.find(x => x.id === e.data.unit_id);
      if (u) fxFlash(cx(u.pos[0]), cy(u.pos[1]), 'var(--good)', 13);
    } else if (e.kind === 'mission_completed') {
      const m = f.missions.find(x => x.id === e.data.mission_id);
      if (m) { fxRing(cx(m.pos[0]), cy(m.pos[1]), 'var(--good)', 16, true);
        fxFlash(cx(m.pos[0]), cy(m.pos[1]), 'var(--good)', 10); }
    } else if (e.kind === 'unit_defeated') {
      const u = f.units.find(x => x.id === e.data.unit_id);
      if (u) fxRing(cx(u.pos[0]), cy(u.pos[1]), 'var(--critical)', 12, false);
    }
  }
}

function drawTeams(f) {
  $('teams').innerHTML = M.teams.map(t => {
    const res = f.teams.find(x => x.id === t.id).resources;
    const done = f.missions.filter(m => m.completed_by.includes(t.id)).length;
    return `<div class="team">
      <div class="team-head"><span class="swatch" style="background:${teamColor(t.id)}"></span>
        <span class="team-name">${esc(t.name)}</span></div>
      <div class="team-stats"><span>resources <b>${esc(res)}</b></span>
        <span>missions <b>${esc(done)}</b></span></div>
      <div class="agents">${t.agents.map(a =>
        `<span class="chip"><span class="dot" style="background:${teamColor(t.id)}"></span>${
          esc(GLYPH[a.role] || '?')} ${esc(a.id)} · ${esc(a.model)}</span>`).join('')}</div>
    </div>`;
  }).join('');
}

const FEED = {
  match_started: () => ['&#9873;', 'big', 'match started'],
  plan_declared: d => ['&#9776;', 'msg', `<span class="who">${esc(d.team_id)}</span>
    <span class="body">plan · ${esc(d.text)}</span>`],
  message_sent: d => ['&#128172;', 'msg', `<span class="who">${esc(d.from)}</span>
    <span class="body">${esc(d.text)}</span>`],
  action_declared: d => ['&#8227;', '', `${esc(d.unit_id)} declares ${esc(d.action)}${d.to ?
    ' → ' + esc(d.to.join(',')) : ''}`],
  action_rejected: d => ['&#10007;', 'reject',
    `${esc(d.unit_id ?? '?')} rejected — ${esc(d.reason)}`],
  unit_moved: d => ['&#8599;', '', `${esc(d.unit_id)} moves to ${esc(d.to.join(','))}`],
  resource_gathered: d => ['&#9670;', '',
    `${esc(d.unit_id)} gathers ${esc(d.amount)} from ${esc(d.node_id)}`],
  resource_delivered: d => ['&#9679;', 'good', `${esc(d.unit_id)} delivers ${esc(d.amount)}`],
  control_point_captured: d => ['&#9873;', 'big', `${esc(d.team_id)} captures ${esc(d.cp_id)}`],
  control_point_held: d => d.turns ? ['&#9203;', '', `${esc(d.team_id)} holds ${esc(d.cp_id)}
    (${esc(d.turns)})`] : null,
  unit_defeated: d => ['&#9760;', 'reject', `${esc(d.unit_id)} is down`],
  mission_completed: d => ['&#9733;', 'good big',
    `${esc(d.team_id)} completes ${esc(d.mission_id)}`],
  match_finished: d => ['&#9873;', 'big', d.winner ? `match over — ${esc(d.winner)} wins`
    : 'match over'],
  turn_advanced: () => null, turn_resolved: () => null,
};

function drawFeed() {
  const f = M.frames[frame];
  const evts = frame === 0 ? [] : (M.events_by_turn[String(f.turn)] || []);
  const rows = evts.map(e => FEED[e.kind] ? FEED[e.kind](e.data) : null).filter(Boolean)
    .map(([g, cls, html]) => `<div class="evt ${cls}"><span class="glyph">${g}</span>
      <span class="txt">${html}</span></div>`);
  $('feed').innerHTML = rows.length ? rows.join('')
    : '<div class="empty">nothing happened this turn</div>';
}

function drawScores() {
  const S = M.scores, box = $('scores');
  // Team columns name teams in INK with a swatch — never coloured text.
  const head = `<div class="score-grid"><span class="h"></span>` + M.teams.map(t =>
    `<span class="h num team-col"><span class="dot" style="background:${teamColor(t.id)}"></span>${
      esc(t.name)}</span>`).join('') + rows() + `</div>` + sigs();
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

function updateWinner() {
  const last = M.frames[M.frames.length - 1];
  if (last.status === 'finished') {
    const w = $('meta-winner');
    w.hidden = false;
    w.textContent = last.winner ? (last.winner === 'draw' ? 'draw' : `${last.winner} wins`)
      : 'unresolved';
  }
}

function render(forward) {
  const f = M.frames[frame];
  const flooded = (forward && !reduce) ? capturesOf(frame) : new Set();
  renderField(f, flooded);
  renderUnits(f);
  drawTeams(f);
  drawFeed();
  $('turn-slider').value = frame;
  $('turn-label').textContent = `turn ${f.turn} / ${M.turn_limit}`;
  updateWinner();
  if (forward && !reduce) spawnFx(frame);
}

function go(i) {
  i = Math.max(0, Math.min(M.frames.length - 1, i));
  const forward = i === frame + 1;
  frame = i;
  render(forward);
}
function stop() {
  if (!playing) return;
  clearInterval(playing); playing = null;
  const b = $('btn-play'); b.classList.remove('on'); b.innerHTML = '&#9654;';
  b.setAttribute('aria-label', 'play');
}
function play() {
  const b = $('btn-play'); b.classList.add('on'); b.innerHTML = '&#10073;&#10073;';
  b.setAttribute('aria-label', 'pause');
  playing = setInterval(() => {
    if (frame >= M.frames.length - 1) stop(); else go(frame + 1);
  }, SPEEDS[String(speed)]);
}
function toggle() { playing ? stop() : play(); }
function setSpeed(s) {
  speed = s;
  document.querySelectorAll('.speed button').forEach(b =>
    b.classList.toggle('on', b.dataset.speed === String(s)));
  document.documentElement.style.setProperty('--move', Math.round(SPEEDS[String(s)] * 0.72) + 'ms');
  if (playing) { stop(); play(); }
}

$('turn-slider').max = M.frames.length - 1;
$('turn-slider').addEventListener('input', e => { stop(); go(+e.target.value); });
$('btn-first').onclick = () => { stop(); go(0); };
$('btn-prev').onclick = () => { stop(); go(frame - 1); };
$('btn-next').onclick = () => go(frame + 1);
$('btn-last').onclick = () => { stop(); go(M.frames.length - 1); };
$('btn-play').onclick = toggle;
document.querySelectorAll('.speed button').forEach(b =>
  b.onclick = () => setSpeed(parseFloat(b.dataset.speed)));
document.addEventListener('keydown', e => {
  if (e.key === 'ArrowLeft') { stop(); go(frame - 1); }
  else if (e.key === 'ArrowRight') go(frame + 1);
  else if (e.key === ' ') { e.preventDefault(); toggle(); }
});
$('theme-toggle').onclick = () => {
  const root = document.documentElement;
  const dark = window.matchMedia('(prefers-color-scheme: dark)').matches;
  const cur = root.dataset.theme || (dark ? 'dark' : 'light');
  const next = cur === 'dark' ? 'light' : 'dark';
  root.dataset.theme = next;
  const tt = $('theme-toggle');
  tt.setAttribute('aria-pressed', String(next === 'dark'));
  tt.querySelector('.tt-label').textContent = next === 'dark' ? 'Light' : 'Dark';
};
(function initToggleLabel() {
  const dark = window.matchMedia('(prefers-color-scheme: dark)').matches;
  const cur = document.documentElement.dataset.theme || (dark ? 'dark' : 'light');
  $('theme-toggle').querySelector('.tt-label').textContent = cur === 'dark' ? 'Light' : 'Dark';
})();

setSpeed(1);
// Deep link: replay.html#t7 opens on turn 7, so reviewers can point at a frame.
const hashTurn = (location.hash.match(/^#t(\\d+)$/) || [])[1];
if (hashTurn != null) {
  const idx = M.frames.findIndex(f => f.turn === +hashTurn);
  if (idx >= 0) frame = idx;
}
drawScores();
render(false);
// Let the first paint land at rest, then arm the movement transitions.
requestAnimationFrame(() => document.body.classList.remove('booting'));
</script>
</body>
</html>
"""
