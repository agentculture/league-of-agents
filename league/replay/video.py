"""Render a match log as a shareable, offline animated GIF (plan task t6, spec c7/h7).

**Toolchain decision (parked risk r1, pinned here):** the primary path is a
pure-stdlib animated GIF89a writer — palette-indexed raster frames plus a
hand-rolled LZW encoder (~a few hundred lines, no dependency). The board is
flat-color geometry (discs, rings, diamonds, a tiny bitmap font), so a small
fixed global palette (~20 colors — the SAME validated hues
:mod:`league.replay.html` uses) compresses well and always works, on any
machine, with nothing to install. This keeps the runtime dependency-free
(``dependencies = []`` in ``pyproject.toml`` is untouched) while resolving the
"how do we ship a video, offline, from the log alone" toolchain question the
cycle-5 plan parked as risk r1.

An **optional** enhancement — piping the same raw frames through ``ffmpeg``
for an MP4 — is offered by the CLI (``league match record --format mp4``),
gated on ``ffmpeg`` being found on ``PATH``; absent it, that flag fails with a
clear, remediated error naming the GIF fallback. That subprocess call lives
in the CLI layer (``league/cli/_commands/match.py``), never here — this
module never shells out, so it stays trivially testable and bandit-quiet.

**Determinism.** Every function here is a pure fold of
:func:`league.replay.html.build_replay_data`'s output (frames, teams, scores)
plus caller-supplied, non-random parameters (cell size, frame delay). No
``time``/``random``/``datetime`` anywhere: the same log, at the same
``--scale``/``--fps``, renders byte-identical GIF bytes — the merge gate's
reproducibility proof.

**Frame layout.** One opening title card (match id, scenario, teams with
color swatches + rosters), one frame per turn actually played (skips the
pre-turn-0 snapshot the title card already covers — so frame count is
``turns + 2``, matching the acceptance criterion), and one closing frame
(final score by axis). Board frames draw the grid, resource nodes (diamonds),
missions (rings, colored by whoever completed them), control points (a tint
disc + owner-colored ring), and units (team-colored discs with a role glyph,
fanned out deterministically when several units share a cell — the same
"never occluded" rule :mod:`league.replay.html` follows). Polish belongs to
the HTML replay; this is a clean, legible, correct board, not a second design
system.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from league.engine.events import MatchLog
from league.replay.html import (
    BOARD_INK,
    BOARD_LINE,
    BOARD_MUTED,
    BOARD_PLANE,
    GLYPH_INK,
    RESOURCE_COLOR,
    STATUS_CRITICAL,
    STATUS_GOOD,
    TEAM_COLORS,
    build_replay_data,
)

# Parity with league/replay/html.py's JS GLYPH map and tui.py's _ROLE_GLYPH —
# the same role reads as the same letter on every face.
_ROLE_GLYPH = {"scout": "S", "harvester": "H", "defender": "D", "striker": "K", "support": "U"}

DEFAULT_SCALE = 24
DEFAULT_FPS = 2
MIN_SCALE, MAX_SCALE = 8, 64
MIN_FPS, MAX_FPS = 1, 10

_MARGIN = 12
_GAP = 4
_TEXT_SCALE = 2
_TITLE_SCALE = 3

_FONT_COLS = 5
_FONT_ROWS = 7

# A tiny hand-authored 5x7 bitmap font — just enough of ASCII to render match
# ids, scenario ids, team/agent names, and numbers (all rendered upper-case;
# any character outside this table falls back to a blank space rather than
# raising, so an unusual id never crashes the renderer).
_FONT: dict[str, tuple[str, ...]] = {
    " ": (".....",) * 7,
    "0": ("#####", "#...#", "#...#", "#...#", "#...#", "#...#", "#####"),
    "1": ("..#..", ".##..", "..#..", "..#..", "..#..", "..#..", "#####"),
    "2": ("#####", "....#", "....#", "#####", "#....", "#....", "#####"),
    "3": ("#####", "....#", "....#", "#####", "....#", "....#", "#####"),
    "4": ("#...#", "#...#", "#...#", "#####", "....#", "....#", "....#"),
    "5": ("#####", "#....", "#....", "#####", "....#", "....#", "#####"),
    "6": ("#####", "#....", "#....", "#####", "#...#", "#...#", "#####"),
    "7": ("#####", "....#", "...#.", "..#..", ".#...", ".#...", ".#..."),
    "8": ("#####", "#...#", "#...#", "#####", "#...#", "#...#", "#####"),
    "9": ("#####", "#...#", "#...#", "#####", "....#", "....#", "#####"),
    "A": ("..#..", ".#.#.", "#...#", "#...#", "#####", "#...#", "#...#"),
    "B": ("####.", "#...#", "#...#", "####.", "#...#", "#...#", "####."),
    "C": (".####", "#....", "#....", "#....", "#....", "#....", ".####"),
    "D": ("####.", "#...#", "#...#", "#...#", "#...#", "#...#", "####."),
    "E": ("#####", "#....", "#....", "####.", "#....", "#....", "#####"),
    "F": ("#####", "#....", "#....", "####.", "#....", "#....", "#...."),
    "G": (".####", "#....", "#....", "#.###", "#...#", "#...#", ".####"),
    "H": ("#...#", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"),
    "I": ("#####", "..#..", "..#..", "..#..", "..#..", "..#..", "#####"),
    "J": ("..###", "...#.", "...#.", "...#.", "#..#.", "#..#.", ".##.."),
    "K": ("#...#", "#..#.", "#.#..", "##...", "#.#..", "#..#.", "#...#"),
    "L": ("#....", "#....", "#....", "#....", "#....", "#....", "#####"),
    "M": ("#...#", "##.##", "#.#.#", "#...#", "#...#", "#...#", "#...#"),
    "N": ("#...#", "##..#", "#.#.#", "#..##", "#...#", "#...#", "#...#"),
    "O": (".###.", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."),
    "P": ("####.", "#...#", "#...#", "####.", "#....", "#....", "#...."),
    "Q": (".###.", "#...#", "#...#", "#...#", "#.#.#", "#..#.", ".##.#"),
    "R": ("####.", "#...#", "#...#", "####.", "#.#..", "#..#.", "#...#"),
    "S": (".####", "#....", "#....", ".###.", "....#", "....#", "####."),
    "T": ("#####", "..#..", "..#..", "..#..", "..#..", "..#..", "..#.."),
    "U": ("#...#", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."),
    "V": ("#...#", "#...#", "#...#", "#...#", "#...#", ".#.#.", "..#.."),
    "W": ("#...#", "#...#", "#...#", "#.#.#", "#.#.#", "#.#.#", ".#.#."),
    "X": ("#...#", "#...#", ".#.#.", "..#..", ".#.#.", "#...#", "#...#"),
    "Y": ("#...#", "#...#", ".#.#.", "..#..", "..#..", "..#..", "..#.."),
    "Z": ("#####", "....#", "...#.", "..#..", ".#...", "#....", "#####"),
    "-": (".....", ".....", ".....", "#####", ".....", ".....", "....."),
    ":": (".....", "..#..", ".....", ".....", "..#..", ".....", "....."),
    ".": (".....", ".....", ".....", ".....", ".....", "..#..", "....."),
    ",": (".....", ".....", ".....", ".....", ".....", "..#..", ".#..."),
    "_": (".....", ".....", ".....", ".....", ".....", ".....", "#####"),
    "/": ("....#", "...#.", "..#..", ".#...", "#....", ".....", "....."),
    "(": ("...#.", "..#..", ".#...", ".#...", ".#...", "..#..", "...#."),
    ")": (".#...", "..#..", "...#.", "...#.", "...#.", "..#..", ".#..."),
    "+": (".....", "..#..", "..#..", "#####", "..#..", "..#..", "....."),
    "%": ("#...#", "....#", "...#.", "..#..", ".#...", "#....", "#...#"),
    "'": (".#...", ".#...", ".....", ".....", ".....", ".....", "....."),
}


def _text_width(s: str, scale: int) -> int:
    if not s:
        return 0
    return len(s) * (_FONT_COLS + 1) * scale - scale


def _text_height(scale: int) -> int:
    return _FONT_ROWS * scale


# --- palette (fixed, match-independent — the same 20 colors every render) --


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def _blend_hex(bg_hex: str, fg_hex: str, alpha: float) -> str:
    bg = _hex_to_rgb(bg_hex)
    fg = _hex_to_rgb(fg_hex)
    r, g, b = (round(bg[i] * (1 - alpha) + fg[i] * alpha) for i in range(3))
    return f"#{r:02x}{g:02x}{b:02x}"


_OWNED_TINT_ALPHA = 0.28

_PALETTE_HEX: tuple[str, ...] = (
    (
        BOARD_PLANE,
        BOARD_LINE,
        BOARD_INK,
        BOARD_MUTED,
        STATUS_GOOD,
        STATUS_CRITICAL,
        RESOURCE_COLOR,
        GLYPH_INK,
    )
    + TEAM_COLORS
    + tuple(_blend_hex(BOARD_PLANE, c, _OWNED_TINT_ALPHA) for c in TEAM_COLORS)
)

PALETTE: tuple[tuple[int, int, int], ...] = tuple(_hex_to_rgb(h) for h in _PALETTE_HEX)

_BG, _LINE, _INK, _MUTED, _GOOD, _CRITICAL, _RESOURCE, _GLYPH = range(8)
_TEAM0 = 8
_TINT0 = _TEAM0 + len(TEAM_COLORS)
_N_TEAM_SLOTS = len(TEAM_COLORS)

# _GOOD/_CRITICAL are reserved status slots (parity with the HTML replay's
# fixed status scale) — this raster face doesn't animate event flashes, but
# keeping the slots reserved means a future frame kind can use them without
# renumbering the whole palette.
_ = (_GOOD, _CRITICAL)


def _team_color(index: int) -> int:
    return _TEAM0 + (index % _N_TEAM_SLOTS)


def _team_tint(index: int) -> int:
    return _TINT0 + (index % _N_TEAM_SLOTS)


def indices_to_rgb(indices: bytes) -> bytes:
    """Expand palette indices to interleaved RGB24 bytes (for an ffmpeg rawvideo pipe).

    Pure and stdlib-only (``bytes.translate`` is a C-level lookup, not a
    subprocess) — safe to call from the CLI layer's optional MP4 path without
    pulling any subprocess concern into this module.
    """
    pad = bytes(256 - len(PALETTE))
    r_lut = bytes(c[0] for c in PALETTE) + pad
    g_lut = bytes(c[1] for c in PALETTE) + pad
    b_lut = bytes(c[2] for c in PALETTE) + pad
    out = bytearray(len(indices) * 3)
    out[0::3] = indices.translate(r_lut)
    out[1::3] = indices.translate(g_lut)
    out[2::3] = indices.translate(b_lut)
    return bytes(out)


# --- raster canvas (palette-index pixel buffer) -----------------------------


class _Canvas:
    __slots__ = ("width", "height", "buf")

    def __init__(self, width: int, height: int, bg: int = _BG) -> None:
        self.width = width
        self.height = height
        self.buf = bytearray([bg]) * (width * height)

    def fill_rect(self, x0: int, y0: int, w: int, h: int, color: int) -> None:
        x1, y1 = max(0, x0), max(0, y0)
        x2, y2 = min(self.width, x0 + w), min(self.height, y0 + h)
        if x2 <= x1 or y2 <= y1:
            return
        row = bytes([color]) * (x2 - x1)
        for y in range(y1, y2):
            start = y * self.width + x1
            self.buf[start : start + (x2 - x1)] = row

    def hline(self, x0: int, y: int, length: int, color: int) -> None:
        self.fill_rect(x0, y, length, 1, color)

    def vline(self, x: int, y0: int, length: int, color: int) -> None:
        self.fill_rect(x, y0, 1, length, color)

    def disc(self, cx: int, cy: int, r: int, color: int) -> None:
        r2 = r * r
        for y in range(max(0, cy - r), min(self.height, cy + r + 1)):
            dy2 = (y - cy) ** 2
            row_start = y * self.width
            for x in range(max(0, cx - r), min(self.width, cx + r + 1)):
                if (x - cx) ** 2 + dy2 <= r2:
                    self.buf[row_start + x] = color

    def ring(self, cx: int, cy: int, r: int, thickness: int, color: int) -> None:
        outer2 = r * r
        inner = max(0, r - thickness)
        inner2 = inner * inner
        for y in range(max(0, cy - r), min(self.height, cy + r + 1)):
            dy2 = (y - cy) ** 2
            row_start = y * self.width
            for x in range(max(0, cx - r), min(self.width, cx + r + 1)):
                d2 = (x - cx) ** 2 + dy2
                if inner2 <= d2 <= outer2:
                    self.buf[row_start + x] = color

    def diamond(self, cx: int, cy: int, r: int, color: int) -> None:
        for y in range(max(0, cy - r), min(self.height, cy + r + 1)):
            dy = abs(y - cy)
            span = r - dy
            if span < 0:
                continue
            self.fill_rect(cx - span, y, 2 * span + 1, 1, color)

    def text(self, x: int, y: int, s: str, color: int, scale: int = 1) -> int:
        cursor = x
        for ch in s.upper():
            rows = _FONT.get(ch, _FONT[" "])
            for row_i, row in enumerate(rows):
                for col_i, mark in enumerate(row):
                    if mark == "#":
                        self.fill_rect(
                            cursor + col_i * scale, y + row_i * scale, scale, scale, color
                        )
            cursor += (_FONT_COLS + 1) * scale
        return cursor

    def to_bytes(self) -> bytes:
        return bytes(self.buf)


# --- content lines (shared by measuring and drawing, so they cannot drift) -


@dataclass(frozen=True)
class _Line:
    text: str
    scale: int
    swatch_team: str | None = None


def _swatch_side(scale: int) -> int:
    return _text_height(scale)


def _line_width(line: _Line) -> int:
    w = _text_width(line.text, line.scale)
    if line.swatch_team is not None:
        w += _swatch_side(line.scale) + _GAP
    return w


def _line_height(line: _Line) -> int:
    return _text_height(line.scale)


def _block_height(lines: Sequence[_Line]) -> int:
    if not lines:
        return 0
    return sum(_line_height(line) + _GAP for line in lines) - _GAP


def _draw_lines(canvas: _Canvas, x: int, y: int, lines: Sequence[_Line], team_index: dict) -> int:
    for line in lines:
        cur_x = x
        if line.swatch_team is not None:
            side = _swatch_side(line.scale)
            canvas.fill_rect(cur_x, y, side, side, _team_color(team_index[line.swatch_team]))
            cur_x += side + _GAP
        canvas.text(cur_x, y, line.text, _INK, line.scale)
        y += _line_height(line) + _GAP
    return y


def _title_content(data: Mapping[str, Any]) -> list[_Line]:
    lines = [
        _Line("LEAGUE OF AGENTS", _TITLE_SCALE),
        _Line(f"MATCH {data['match_id']}", _TEXT_SCALE),
        _Line(
            f"SCENARIO {data['scenario_id']}  MODE {data['mode']}  SEED {data['seed']}",
            _TEXT_SCALE,
        ),
    ]
    for t in data["teams"]:
        agents = ", ".join(f"{a['id']}:{a['role']}" for a in t["agents"])
        lines.append(_Line(f"{t['name']} ({t['id']}): {agents}", _TEXT_SCALE, swatch_team=t["id"]))
    return lines


def _closing_content(data: Mapping[str, Any]) -> list[_Line]:
    scores = data["scores"]
    lines = [_Line("FINAL SCORE", _TITLE_SCALE)]
    for t in data["teams"]:
        outcome = scores["outcome"][t["id"]]
        coop = scores["cooperation"][t["id"]]
        lines.append(
            _Line(
                f"{t['name']}: OUTCOME {outcome['total']} (M{outcome['missions']} "
                f"C{outcome['control']} R{outcome['resources']})  COOP {coop['score']}",
                _TEXT_SCALE,
                swatch_team=t["id"],
            )
        )
    winner = scores.get("winner")
    lines.append(_Line(f"WINNER {winner}" if winner else "WINNER NONE (DRAW)", _TEXT_SCALE))
    return lines


def _footer_content(data: Mapping[str, Any], frame: Mapping[str, Any]) -> list[_Line]:
    resources = {t["id"]: t["resources"] for t in frame["teams"]}
    lines = []
    for t in data["teams"]:
        done = sum(1 for m in frame["missions"] if t["id"] in m["completed_by"])
        lines.append(
            _Line(
                f"{t['name']}  RES {resources.get(t['id'], 0)}  MISSIONS {done}",
                _TEXT_SCALE,
                swatch_team=t["id"],
            )
        )
    return lines


def _header_content(data: Mapping[str, Any], frame: Mapping[str, Any]) -> _Line:
    return _Line(
        f"{data['match_id']}  {data['scenario_id']}  TURN {frame['turn']}/{data['turn_limit']}",
        _TEXT_SCALE,
    )


# --- board drawing -----------------------------------------------------------


def _cell_center(x0: int, y0: int, cell_px: int, pos: Sequence[int]) -> tuple[int, int]:
    return x0 + pos[0] * cell_px + cell_px // 2, y0 + pos[1] * cell_px + cell_px // 2


def _stack_offset(i: int, n: int, spread: int) -> tuple[int, int]:
    """Deterministic fan-out for units sharing a cell (parity with html.py's
    STACK_OFFSETS/circle fallback) — nothing is ever occluded."""
    if n <= 1:
        return 0, 0
    angle = (2 * math.pi * i) / n - math.pi / 2
    return round(spread * math.cos(angle)), round(spread * math.sin(angle))


def _draw_grid(canvas: _Canvas, x0: int, y0: int, grid_w: int, grid_h: int, cell_px: int) -> None:
    for gx in range(grid_w + 1):
        canvas.vline(x0 + gx * cell_px, y0, grid_h * cell_px, _LINE)
    for gy in range(grid_h + 1):
        canvas.hline(x0, y0 + gy * cell_px, grid_w * cell_px, _LINE)


def _draw_resource_nodes(canvas: _Canvas, x0: int, y0: int, cell_px: int, nodes) -> None:
    for n in nodes:
        cx, cy = _cell_center(x0, y0, cell_px, n["pos"])
        r = max(3, cell_px // 3)
        canvas.diamond(cx, cy, r, _RESOURCE if n["remaining"] else _MUTED)


def _draw_missions(canvas: _Canvas, x0: int, y0: int, cell_px: int, missions, team_index) -> None:
    for m in missions:
        cx, cy = _cell_center(x0, y0, cell_px, m["pos"])
        r = max(4, cell_px // 2 - 2)
        completed = m["status"] == "completed" and m["completed_by"]
        if completed:
            color = (
                _team_color(team_index[m["completed_by"][0]])
                if len(m["completed_by"]) == 1
                else _INK
            )
        else:
            color = _MUTED
        canvas.ring(cx, cy, r, 2, color)


def _draw_control_points(
    canvas: _Canvas, x0: int, y0: int, cell_px: int, control_points, team_index
) -> None:
    for c in control_points:
        cx, cy = _cell_center(x0, y0, cell_px, c["pos"])
        r = max(4, cell_px // 2 - 3)
        if c["owner"] is not None:
            idx = team_index[c["owner"]]
            canvas.disc(cx, cy, r, _team_tint(idx))
            canvas.ring(cx, cy, r, 2, _team_color(idx))
        else:
            canvas.ring(cx, cy, r, 2, _LINE)


def _draw_units(canvas: _Canvas, x0: int, y0: int, cell_px: int, units, team_index) -> None:
    by_cell: dict[tuple[int, int], list[dict]] = {}
    for u in units:
        if not u["alive"]:
            continue
        by_cell.setdefault(tuple(u["pos"]), []).append(u)
    for pos, stack in by_cell.items():
        stack.sort(key=lambda u: u["id"])  # canonical order — never submission order
        n = len(stack)
        spread = max(2, cell_px // 4)
        base_r = max(3, cell_px // 2 - (3 if n > 1 else 1))
        cx, cy = _cell_center(x0, y0, cell_px, pos)
        for i, u in enumerate(stack):
            dx, dy = _stack_offset(i, n, spread)
            ux, uy = cx + dx, cy + dy
            canvas.disc(ux, uy, base_r, _team_color(team_index[u["team"]]))
            glyph = _ROLE_GLYPH.get(u["role"], (u["role"][:1] or "?").upper())
            gw = _text_width(glyph, 1)
            canvas.text(ux - gw // 2, uy - _FONT_ROWS // 2, glyph, _GLYPH, 1)
            if u["carrying"]:
                canvas.disc(ux + base_r - 2, uy - base_r + 2, max(2, base_r // 3), _RESOURCE)


def _layout(data: Mapping[str, Any], cell_px: int) -> tuple[int, int, int, int, int]:
    grid_w = data["grid"]["width"]
    grid_h = data["grid"]["height"]
    board_w = grid_w * cell_px
    board_h = grid_h * cell_px
    board_frames = data["frames"][1:]

    widths = [board_w]
    for f in board_frames:
        widths.append(_line_width(_header_content(data, f)))
        widths.extend(_line_width(line) for line in _footer_content(data, f))
    widths.extend(_line_width(line) for line in _title_content(data))
    widths.extend(_line_width(line) for line in _closing_content(data))
    content_w = max(widths)

    header_h = _text_height(_TEXT_SCALE)
    footer_h = _block_height(_footer_content(data, board_frames[0])) if board_frames else 0
    turn_h = _MARGIN + header_h + _GAP + board_h + _GAP + footer_h + _MARGIN
    title_h = _MARGIN + _block_height(_title_content(data)) + _MARGIN
    closing_h = _MARGIN + _block_height(_closing_content(data)) + _MARGIN

    width = content_w + 2 * _MARGIN
    height = max(turn_h, title_h, closing_h)
    board_x = (width - board_w) // 2
    board_y = _MARGIN + header_h + _GAP
    footer_y = board_y + board_h + _GAP
    return width, height, board_x, board_y, footer_y


def _draw_turn_frame(
    canvas: _Canvas,
    data: Mapping[str, Any],
    frame: Mapping[str, Any],
    team_index: dict,
    cell_px: int,
    board_x: int,
    board_y: int,
    footer_y: int,
) -> None:
    canvas.fill_rect(0, 0, canvas.width, canvas.height, _BG)
    header = _header_content(data, frame)
    canvas.text(_MARGIN, _MARGIN, header.text, _INK, header.scale)
    grid_w, grid_h = data["grid"]["width"], data["grid"]["height"]
    _draw_grid(canvas, board_x, board_y, grid_w, grid_h, cell_px)
    _draw_resource_nodes(canvas, board_x, board_y, cell_px, frame["resource_nodes"])
    _draw_missions(canvas, board_x, board_y, cell_px, frame["missions"], team_index)
    _draw_control_points(canvas, board_x, board_y, cell_px, frame["control_points"], team_index)
    _draw_units(canvas, board_x, board_y, cell_px, frame["units"], team_index)
    _draw_lines(canvas, _MARGIN, footer_y, _footer_content(data, frame), team_index)


def _draw_title_frame(canvas: _Canvas, data: Mapping[str, Any], team_index: dict) -> None:
    canvas.fill_rect(0, 0, canvas.width, canvas.height, _BG)
    _draw_lines(canvas, _MARGIN, _MARGIN, _title_content(data), team_index)


def _draw_closing_frame(canvas: _Canvas, data: Mapping[str, Any], team_index: dict) -> None:
    canvas.fill_rect(0, 0, canvas.width, canvas.height, _BG)
    _draw_lines(canvas, _MARGIN, _MARGIN, _closing_content(data), team_index)


# --- frames -------------------------------------------------------------


@dataclass(frozen=True)
class Frame:
    """One raster frame: palette-index pixels plus its GIF-style hold time."""

    indices: bytes
    delay_cs: int


@dataclass(frozen=True)
class VideoFrames:
    width: int
    height: int
    frames: tuple[Frame, ...]


def _delay_cs(fps: int) -> int:
    return max(2, round(100 / fps))


def build_frames(
    replay_data: Mapping[str, Any],
    *,
    cell_px: int = DEFAULT_SCALE,
    turn_delay_cs: int = 50,
) -> VideoFrames:
    """Deterministic raster frames from a replay fold: title, one per turn played, closing.

    ``replay_data`` is exactly :func:`league.replay.html.build_replay_data`'s
    output — the same fold every other face (HTML, TUI, ``--json``) reads, so
    this can never disagree with them on the facts. Frame count is
    ``len(replay_data["frames"]) - 1 + 2`` (turns played, plus the opening
    title and closing score card) — the pre-turn-0 snapshot is folded into the
    title card rather than drawn as its own near-duplicate board frame.
    """
    if cell_px < 4:
        raise ValueError("cell_px must be >= 4")
    if turn_delay_cs < 1:
        raise ValueError("turn_delay_cs must be >= 1")

    team_index = {t["id"]: i for i, t in enumerate(replay_data["teams"])}
    board_frames = replay_data["frames"][1:]
    width, height, board_x, board_y, footer_y = _layout(replay_data, cell_px)

    frames: list[Frame] = []

    title_canvas = _Canvas(width, height)
    _draw_title_frame(title_canvas, replay_data, team_index)
    frames.append(Frame(title_canvas.to_bytes(), max(turn_delay_cs * 4, 200)))

    for f in board_frames:
        canvas = _Canvas(width, height)
        _draw_turn_frame(canvas, replay_data, f, team_index, cell_px, board_x, board_y, footer_y)
        frames.append(Frame(canvas.to_bytes(), turn_delay_cs))

    closing_canvas = _Canvas(width, height)
    _draw_closing_frame(closing_canvas, replay_data, team_index)
    frames.append(Frame(closing_canvas.to_bytes(), max(turn_delay_cs * 6, 300)))

    return VideoFrames(width=width, height=height, frames=tuple(frames))


# --- GIF89a encoding (stdlib-only: header, LZW, sub-blocks, trailer) --------

_GIF_HEADER = b"GIF89a"


def _color_table_size_field(n_colors: int) -> tuple[int, int]:
    """Return (size field 0..7, padded table length) for ``n_colors`` entries."""
    bits = max(2, (max(1, n_colors) - 1).bit_length())
    bits = min(bits, 8)
    return bits - 1, 1 << bits


def _pack_sub_blocks(data: bytes) -> bytes:
    out = bytearray()
    for i in range(0, len(data), 255):
        chunk = data[i : i + 255]
        out.append(len(chunk))
        out += chunk
    out.append(0)
    return bytes(out)


def _lzw_encode(indices: bytes, min_code_size: int) -> bytes:
    """GIF-flavoured variable-width LZW: bump the code width once the *next*
    dictionary code would no longer fit, then freeze the dictionary (stop
    growing it, keep encoding with what's there) once codes reach the 12-bit
    ceiling rather than emitting a fresh CLEAR — simpler, still spec-legal.

    The ``+ 1`` in the bump check is the well-known real-world GIF LZW
    convention (distinct from "textbook"/TIFF-style LZW's boundary): every
    mainstream decoder — verified here by round-tripping Pillow/giflib's own
    encoder output byte-for-byte through this exact formula — increments the
    code width one dictionary slot later than the naive
    ``next_code == 1 << code_size`` boundary would suggest. Without it, the
    two agree everywhere except right at each width transition, which is
    silent corruption, not a crash — hence the byte-exact cross-check against
    a real encoder in ``tests/test_replay_video.py`` rather than trusting a
    from-scratch derivation."""
    clear_code = 1 << min_code_size
    end_code = clear_code + 1
    code_size = min_code_size + 1
    next_code = end_code + 1
    table: dict[bytes, int] = {bytes([i]): i for i in range(clear_code)}

    buf = 0
    nbits = 0
    out = bytearray()

    def emit(code: int) -> None:
        nonlocal buf, nbits
        buf |= code << nbits
        nbits += code_size
        while nbits >= 8:
            out.append(buf & 0xFF)
            buf >>= 8
            nbits -= 8

    emit(clear_code)
    if not indices:
        emit(end_code)
        if nbits:
            out.append(buf & 0xFF)
        return bytes(out)

    w = bytes([indices[0]])
    for byte in indices[1:]:
        k = bytes([byte])
        wk = w + k
        if wk in table:
            w = wk
            continue
        emit(table[w])
        if next_code < 4096:
            table[wk] = next_code
            next_code += 1
            if next_code == (1 << code_size) + 1 and code_size < 12:
                code_size += 1
        w = k
    emit(table[w])
    emit(end_code)
    if nbits:
        out.append(buf & 0xFF)
    return bytes(out)


def _graphic_control_extension(delay_cs: int, *, disposal: int = 1) -> bytes:
    packed = (disposal & 0x07) << 2
    body = bytes([packed]) + struct.pack("<H", max(0, min(65535, delay_cs))) + b"\x00"
    return b"\x21\xf9" + bytes([len(body)]) + body + b"\x00"


def _image_descriptor(width: int, height: int) -> bytes:
    return b"\x2c" + struct.pack("<HHHH", 0, 0, width, height) + b"\x00"


def _image_data(indices: bytes, min_code_size: int) -> bytes:
    compressed = _lzw_encode(indices, min_code_size)
    return bytes([min_code_size]) + _pack_sub_blocks(compressed)


def _loop_extension(loop_count: int = 0) -> bytes:
    return b"\x21\xff\x0bNETSCAPE2.0" + bytes([3, 1]) + struct.pack("<H", loop_count) + b"\x00"


def _comment_extension(text: str) -> bytes:
    if not text:
        return b""
    payload = text.encode("ascii", errors="replace")
    return b"\x21\xfe" + _pack_sub_blocks(payload)


def _encode_gif(video: VideoFrames, *, comment: str = "") -> bytes:
    n_colors = len(PALETTE)
    size_field, padded_len = _color_table_size_field(n_colors)
    min_code_size = size_field + 1
    packed_lsd = 0x80 | (size_field << 4) | size_field

    color_table = bytearray()
    for i in range(padded_len):
        rgb = PALETTE[i] if i < n_colors else (0, 0, 0)
        color_table += bytes(rgb)

    out = bytearray()
    out += _GIF_HEADER
    out += struct.pack("<HH", video.width, video.height)
    out += bytes([packed_lsd, 0, 0])  # background color index 0, no pixel-aspect info
    out += color_table
    out += _loop_extension()
    out += _comment_extension(comment)
    for frame in video.frames:
        out += _graphic_control_extension(frame.delay_cs)
        out += _image_descriptor(video.width, video.height)
        out += _image_data(frame.indices, min_code_size)
    out += b"\x3b"
    return bytes(out)


def render_gif(
    log: MatchLog,
    *,
    scale: int = DEFAULT_SCALE,
    fps: int = DEFAULT_FPS,
    provenance: str = "",
) -> bytes:
    """The one function most callers want: a match log straight to GIF bytes.

    Deterministic end to end — the same log at the same ``scale``/``fps``
    (and the same ``provenance`` string, since it's embedded verbatim as a
    GIF Comment Extension) renders byte-identical output.
    """
    data = build_replay_data(log)
    video = build_frames(data, cell_px=scale, turn_delay_cs=_delay_cs(fps))
    return _encode_gif(video, comment=provenance)
