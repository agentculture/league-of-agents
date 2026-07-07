"""Render a match log as a shareable, offline animated GIF (plan task t6, spec c7/h7).

**Toolchain decision (parked risk r1, pinned here):** the primary path is a
pure-stdlib animated GIF89a writer — palette-indexed raster frames plus a
hand-rolled LZW encoder (~a few hundred lines, no dependency). The board is
flat-color geometry (discs, rings, diamonds, a tiny bitmap font), so a small
global palette (25 colors — the SAME validated hues :mod:`league.replay.html`
uses plus that face's own neutral steps, selected per ``--theme``: light
Anthropic cream / dark Culture black-green) compresses well and always works,
on any machine, with nothing to install. This keeps the runtime dependency-free
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
plus caller-supplied, non-random parameters (cell size, frame delay, theme,
tween count). No ``time``/``random``/``datetime`` anywhere: the same log, at the
same ``--scale``/``--fps``/``--theme``/``--tween``, renders byte-identical GIF
bytes — the merge gate's reproducibility proof. Interpolation rounds to whole
pixels, and ``--theme`` changes only the color table (the frame indices are
theme-independent), so both stay reproducible.

**Frame layout.** The GIF speaks the same design system as the HTML face
(:mod:`league.replay.html`; rationale in ``docs/replay-design.md``): every
frame sits on the theme's page matte, composed with generous margins, and only
the color table differs between themes. One opening **title card** — a centered
lockup (the title over a thin accent rule, the match id, a scenario/mode/seed
metadata line, then one swatch-chipped row per team with its roster), framed by
hairline corner marks. One frame per **turn** actually played (skips the
pre-turn-0 snapshot the title card covers), where the board is the hero: a
hairline grid on a subtly distinct board panel, shape-coded furniture (diamond
resource nodes, mission rings, control-point discs with owner tint + ring),
team-colored unit discs wearing a surface-colored ring (the raster cousin of
the HTML face's 2px surface stroke) and a role glyph, fanned out
deterministically when several share a cell — the same "never occluded" rule
:mod:`league.replay.html` follows — under a muted caption and over a footer
strip carrying the turn counter and per-team scores in aligned, swatch-labelled
columns. ``tween`` linearly interpolated frames between each adjacent pair of
turns keep movement flowing instead of teleporting; a tween frame holds the
starting turn's board furniture and glides only the units. One **closing
card** — big score numerals per team over swatch-labelled rows, the winner
named beneath — closes the loop. Frame count: ``turns + (turns - 1) * tween +
2``.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from league.engine.events import MatchLog
from league.replay.html import THEMES, build_replay_data

# Parity with league/replay/html.py's JS GLYPH map and tui.py's _ROLE_GLYPH —
# the same role reads as the same letter on every face.
_ROLE_GLYPH = {"scout": "S", "harvester": "H", "defender": "D", "striker": "K", "support": "U"}

DEFAULT_SCALE = 24
DEFAULT_FPS = 2
MIN_SCALE, MAX_SCALE = 8, 64
MIN_FPS, MAX_FPS = 1, 10
# Interpolated tween frames inserted between each pair of turns (linear, fixed
# count, deterministic) so movement flows instead of teleporting. 0 disables.
DEFAULT_TWEEN = 4
MIN_TWEEN, MAX_TWEEN = 0, 12
DEFAULT_THEME = "light"

# --- composition constants (the raster face's spacing scale) ----------------

_MARGIN = 20  # generous outer margin around every composition
_GAP = 4  # small intra-line gap (swatch <-> text)
_DIM_GAP = 10  # gap between a line's primary text and its muted segment
_PANEL_PAD = 10  # board-panel padding around the grid
_FOOTER_PAD = 8  # footer-strip inner padding
_ROW_LEADING = 5  # vertical gap between footer team rows
_CARD_INSET = 10  # corner-mark inset on the title/closing cards
_MARK_LEN = 12  # corner-mark arm length
_RULE_W = 36  # accent rule width
_RULE_H = 2  # accent rule height
_CAPTION_TRACK = 1  # extra letter-spacing (px per glyph) for small-caps captions

# Typographic hierarchy — integer scales of the 5x7 glyph grid.
_TEXT_SCALE = 2  # section text (match id, turn counter, winner)
_TITLE_SCALE = 3  # the title lockup
_SCORE_SCALE = 5  # the closing card's big score numerals

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
    "·": (".....", ".....", ".....", "..#..", ".....", ".....", "....."),
}

_MDOT = "·"  # the middle-dot metadata separator (kept escaped for tooling)


def _text_width(s: str, scale: int, tracking: int = 0) -> int:
    if not s:
        return 0
    advance = (_FONT_COLS + 1) * scale + tracking
    return len(s) * advance - scale - tracking


def _text_height(scale: int) -> int:
    return _FONT_ROWS * scale


# --- palette (per-theme, match-independent — the same 25 index SLOTS every
# render; only the RGB behind them changes with the theme, so frame INDICES are
# theme-independent and it is the GIF's global color table that carries the
# theme) ------------------------------------------------------------------


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def _blend_hex(bg_hex: str, fg_hex: str, alpha: float) -> str:
    bg = _hex_to_rgb(bg_hex)
    fg = _hex_to_rgb(fg_hex)
    r, g, b = (round(bg[i] * (1 - alpha) + fg[i] * alpha) for i in range(3))
    return f"#{r:02x}{g:02x}{b:02x}"


_OWNED_TINT_ALPHA = 0.28

# Neutral/chrome steps beyond the tokens ``THEMES`` exports — lifted VERBATIM
# from the HTML face's CSS custom properties (the ``:root`` blocks in
# ``league/replay/html.py``'s template), so the raster face composes with the
# identical, already-designed surface system: the page matte the cards sit on
# (``--plane``), the card surface (``--surface`` — also the unit-marker ring,
# the raster cousin of ``.u-body { stroke: var(--surface) }``), the hairline
# grid (``--grid``), secondary ink (``--ink-2``), and the chrome accent
# (``--accent`` — chrome only, never a team, per docs/replay-design.md).
_THEME_EXTRAS: dict[str, dict[str, str]] = {
    "light": {
        "matte": "#f0eee5",
        "surface": "#faf8f1",
        "grid": "#ded9c9",
        "ink2": "#5a5546",
        "accent": "#1e7a4d",
    },
    "dark": {
        "matte": "#0c1210",
        "surface": "#111a16",
        "grid": "#1e2a24",
        "ink2": "#aebcb2",
        "accent": "#46c79e",
    },
}


def _theme_palette_hex(name: str, theme: Mapping[str, Any]) -> tuple[str, ...]:
    """The 25 palette hexes for a theme, in slot order — the SAME validated hues
    :mod:`league.replay.html` uses for that theme (board plane/line/ink/muted,
    status good/critical, resource, glyph ink, the team hues and their
    ownership tints), then the HTML face's own neutral steps (page matte, card
    surface, hairline grid, secondary ink, chrome accent)."""
    teams = tuple(theme["teams"])
    extras = _THEME_EXTRAS[name]
    return (
        (
            theme["plane"],
            theme["line"],
            theme["ink"],
            theme["muted"],
            theme["good"],
            theme["critical"],
            theme["resource"],
            theme["glyph_ink"],
        )
        + teams
        + tuple(_blend_hex(theme["plane"], c, _OWNED_TINT_ALPHA) for c in teams)
        + (extras["matte"], extras["surface"], extras["grid"], extras["ink2"], extras["accent"])
    )


def build_palette(theme: str = DEFAULT_THEME) -> tuple[tuple[int, int, int], ...]:
    """The RGB color table for a theme (``"light"`` = Anthropic cream, ``"dark"``
    = Culture black-green) — shared verbatim with the HTML replay's tokens."""
    try:
        tokens = THEMES[theme]
    except KeyError as err:
        raise ValueError(f"unknown theme {theme!r}; expected one of: {', '.join(THEMES)}") from err
    return tuple(_hex_to_rgb(h) for h in _theme_palette_hex(theme, tokens))


# Default (light) palette — kept as a module constant for back-compat with
# importers/tests that predate the theme flag; every render selects explicitly.
PALETTE: tuple[tuple[int, int, int], ...] = build_palette(DEFAULT_THEME)

_N_TEAM_SLOTS = len(THEMES[DEFAULT_THEME]["teams"])
_BG, _LINE, _INK, _MUTED, _GOOD, _CRITICAL, _RESOURCE, _GLYPH = range(8)
_TEAM0 = 8
_TINT0 = _TEAM0 + _N_TEAM_SLOTS
# The HTML face's neutral steps (slots 20..24): page matte, card surface,
# hairline grid, secondary ink, chrome accent. Slot 0 (_BG) stays the *board*
# plane — the tone the panel wears; the canvas itself sits on _MATTE.
_MATTE = _TINT0 + _N_TEAM_SLOTS
_SURFACE = _MATTE + 1
_GRID = _MATTE + 2
_INK2 = _MATTE + 3
_ACCENT = _MATTE + 4

# _GOOD/_CRITICAL are reserved status slots (parity with the HTML replay's
# fixed status scale) — this raster face doesn't animate event flashes, but
# keeping the slots reserved means a future frame kind can use them without
# renumbering the whole palette.
_ = (_GOOD, _CRITICAL)


def _team_color(index: int) -> int:
    return _TEAM0 + (index % _N_TEAM_SLOTS)


def _team_tint(index: int) -> int:
    return _TINT0 + (index % _N_TEAM_SLOTS)


def indices_to_rgb(indices: bytes, palette: Sequence[tuple[int, int, int]] = PALETTE) -> bytes:
    """Expand palette indices to interleaved RGB24 bytes (for an ffmpeg rawvideo pipe).

    Pure and stdlib-only (``bytes.translate`` is a C-level lookup, not a
    subprocess) — safe to call from the CLI layer's optional MP4 path without
    pulling any subprocess concern into this module. Pass the theme's palette
    (``VideoFrames.palette``) so the MP4 inherits the same theme as the GIF.
    """
    pad = bytes(256 - len(palette))
    r_lut = bytes(c[0] for c in palette) + pad
    g_lut = bytes(c[1] for c in palette) + pad
    b_lut = bytes(c[2] for c in palette) + pad
    out = bytearray(len(indices) * 3)
    out[0::3] = indices.translate(r_lut)
    out[1::3] = indices.translate(g_lut)
    out[2::3] = indices.translate(b_lut)
    return bytes(out)


# --- raster canvas (palette-index pixel buffer) -----------------------------


class _Canvas:
    __slots__ = ("width", "height", "buf")

    def __init__(self, width: int, height: int, bg: int = _MATTE) -> None:
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

    def outline_rect(self, x: int, y: int, w: int, h: int, color: int) -> None:
        self.hline(x, y, w, color)
        self.hline(x, y + h - 1, w, color)
        self.vline(x, y, h, color)
        self.vline(x + w - 1, y, h, color)

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

    def text(self, x: int, y: int, s: str, color: int, scale: int = 1, tracking: int = 0) -> int:
        cursor = x
        for ch in s.upper():
            rows = _FONT.get(ch, _FONT[" "])
            for row_i, row in enumerate(rows):
                for col_i, mark in enumerate(row):
                    if mark == "#":
                        self.fill_rect(
                            cursor + col_i * scale, y + row_i * scale, scale, scale, color
                        )
            cursor += (_FONT_COLS + 1) * scale + tracking
        return cursor

    def to_bytes(self) -> bytes:
        return bytes(self.buf)


# --- content lines (shared by measuring and drawing, so they cannot drift) -


@dataclass(frozen=True)
class _Line:
    """One centered row of a card: text (optionally swatch-chipped and/or
    followed by a muted segment), or a thin accent rule. ``pad_before`` is the
    vertical space above the row — the card's typographic leading lives in the
    content builders, so measuring and drawing can never disagree."""

    text: str = ""
    scale: int = 1
    color: int = _INK
    dim: str = ""  # secondary segment, drawn scale-1 in dim_color after the text
    dim_color: int = _INK2
    swatch_team: str | None = None
    tracking: int = 0
    pad_before: int = 0
    rule: bool = False


def _swatch_side(scale: int) -> int:
    return _text_height(scale)


def _line_width(line: _Line) -> int:
    if line.rule:
        return _RULE_W
    w = _text_width(line.text, line.scale, line.tracking)
    if line.swatch_team is not None:
        w += _swatch_side(line.scale) + _GAP + 2
    if line.dim:
        w += _DIM_GAP + _text_width(line.dim, 1)
    return w


def _line_height(line: _Line) -> int:
    return _RULE_H if line.rule else _text_height(line.scale)


def _block_height(lines: Sequence[_Line]) -> int:
    return sum(line.pad_before + _line_height(line) for line in lines)


def _draw_lines_centered(
    canvas: _Canvas, cx: int, y: int, lines: Sequence[_Line], team_index: dict
) -> int:
    for line in lines:
        y += line.pad_before
        w = _line_width(line)
        x = cx - w // 2
        if line.rule:
            canvas.fill_rect(x, y, _RULE_W, _RULE_H, _ACCENT)
        else:
            if line.swatch_team is not None:
                side = _swatch_side(line.scale)
                canvas.fill_rect(x, y, side, side, _team_color(team_index[line.swatch_team]))
                x += side + _GAP + 2
            cursor = canvas.text(x, y, line.text, line.color, line.scale, line.tracking)
            if line.dim:
                dim_x = cursor - line.scale - line.tracking + _DIM_GAP
                dim_y = y + (_text_height(line.scale) - _text_height(1))
                canvas.text(dim_x, dim_y, line.dim, line.dim_color, 1)
        y += _line_height(line)
    return y


def _title_content(data: Mapping[str, Any]) -> list[_Line]:
    """The opening lockup: title over an accent rule, match id, a metadata
    line, then one swatch-chipped row per team with its roster."""
    meta = f"{data['scenario_id']} {_MDOT} {data['mode']} {_MDOT} seed {data['seed']}"
    lines = [
        _Line("LEAGUE OF AGENTS", _TITLE_SCALE, tracking=1),
        _Line(rule=True, pad_before=12),
        _Line(f"MATCH {data['match_id']}", _TEXT_SCALE, color=_INK2, pad_before=14),
        _Line(meta, 1, color=_MUTED, tracking=_CAPTION_TRACK, pad_before=8),
    ]
    pad = 22
    for t in data["teams"]:
        roster = "  ".join(f"{a['id']}:{a['role']}" for a in t["agents"])
        lines.append(_Line(t["name"], 1, swatch_team=t["id"], dim=roster, pad_before=pad))
        pad = 8
    return lines


# --- the closing card (big numerals, per-team columns, the winner) ----------


def _closing_head() -> list[_Line]:
    return [
        _Line("FINAL SCORE", 1, color=_MUTED, tracking=2),
        _Line(rule=True, pad_before=10),
    ]


def _closing_tail(data: Mapping[str, Any]) -> list[_Line]:
    # ``winner`` is a team id, the literal "draw", or None (see tick.py's
    # _pick_winner) — only a real team gets the swatch-chipped name row.
    winner = data["scores"].get("winner")
    names = {t["id"]: t["name"] for t in data["teams"]}
    if winner in names:
        return [
            _Line("WINNER", 1, color=_MUTED, tracking=2, pad_before=24),
            _Line(names[winner], _TEXT_SCALE, swatch_team=winner, pad_before=6),
        ]
    label = "DRAW" if winner == "draw" else "NO WINNER"
    return [_Line(label, _TEXT_SCALE, color=_MUTED, tracking=1, pad_before=24)]


def _closing_columns(data: Mapping[str, Any]) -> list[dict[str, str]]:
    scores = data["scores"]
    cols = []
    for t in data["teams"]:
        outcome = scores["outcome"][t["id"]]
        coop = scores["cooperation"][t["id"]]
        detail = (
            f"M {outcome['missions']} {_MDOT} C {outcome['control']} {_MDOT} "
            f"R {outcome['resources']} {_MDOT} COOP {coop['score']}"
        )
        cols.append(
            {"team": t["id"], "name": t["name"], "total": str(outcome["total"]), "detail": detail}
        )
    return cols


def _closing_col_width(col: Mapping[str, str]) -> int:
    return max(
        _text_width(col["total"], _SCORE_SCALE),
        _swatch_side(1) + _GAP + 2 + _text_width(col["name"], 1),
        _text_width(col["detail"], 1),
    )


_COL_GAP = 32
_COLS_PAD = 20  # space between the closing head and the score columns


def _closing_cols_height() -> int:
    return _text_height(_SCORE_SCALE) + 8 + _text_height(1) + 5 + _text_height(1)


def _closing_block_height(data: Mapping[str, Any]) -> int:
    return (
        _block_height(_closing_head())
        + _COLS_PAD
        + _closing_cols_height()
        + _block_height(_closing_tail(data))
    )


def _closing_width(data: Mapping[str, Any]) -> int:
    cols = _closing_columns(data)
    cols_w = sum(_closing_col_width(c) for c in cols) + _COL_GAP * (len(cols) - 1)
    head_w = max(_line_width(line) for line in _closing_head())
    tail_w = max(_line_width(line) for line in _closing_tail(data))
    return max(cols_w, head_w, tail_w)


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
    # Hairline, low-contrast grid — the raster cousin of the HTML face's
    # ``.gl { stroke: var(--grid) }`` on the board gradient.
    for gx in range(grid_w + 1):
        canvas.vline(x0 + gx * cell_px, y0, grid_h * cell_px + 1, _GRID)
    for gy in range(grid_h + 1):
        canvas.hline(x0, y0 + gy * cell_px, grid_w * cell_px + 1, _GRID)


def _draw_resource_nodes(canvas: _Canvas, x0: int, y0: int, cell_px: int, nodes) -> None:
    # Diamonds — shape-coded, never a round mark, so a node can never be
    # mistaken for a unit or a control point even in grayscale.
    for n in nodes:
        cx, cy = _cell_center(x0, y0, cell_px, n["pos"])
        r = max(3, cell_px // 3)
        canvas.diamond(cx, cy, r, _RESOURCE if n["remaining"] else _LINE)


def _draw_missions(canvas: _Canvas, x0: int, y0: int, cell_px: int, missions, team_index) -> None:
    # Open missions: a thin muted ring; completed: a heavier ring in the
    # completing team's hue (ink when shared) — parity with ``.m-ring.done``.
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
            canvas.ring(cx, cy, r, 2, color)
        else:
            canvas.ring(cx, cy, r, 1, _MUTED)


def _draw_control_points(
    canvas: _Canvas, x0: int, y0: int, cell_px: int, control_points, team_index
) -> None:
    # Owned: the owner's tint disc under a team-colored ring. Unowned: a quiet
    # hairline ring with a center dot (the dot keeps it distinct from an open
    # mission ring by shape, not just weight).
    for c in control_points:
        cx, cy = _cell_center(x0, y0, cell_px, c["pos"])
        r = max(4, cell_px // 2 - 3)
        if c["owner"] is not None:
            idx = team_index[c["owner"]]
            canvas.disc(cx, cy, r, _team_tint(idx))
            canvas.ring(cx, cy, r, 2, _team_color(idx))
        else:
            canvas.ring(cx, cy, r, 1, _LINE)
            canvas.disc(cx, cy, max(1, r // 4), _LINE)


def _unit_positions(units, x0: int, y0: int, cell_px: int) -> dict[str, dict[str, Any]]:
    """Deterministic per-unit render positions (cell center + the same fan-out
    offsets a turn frame uses), keyed by unit id — shared by turn frames and the
    interpolated tween frames so a unit glides from exactly where it stood to
    exactly where it lands."""
    by_cell: dict[tuple[int, int], list[dict]] = {}
    for u in units:
        if not u["alive"]:
            continue
        by_cell.setdefault(tuple(u["pos"]), []).append(u)
    out: dict[str, dict[str, Any]] = {}
    for pos, stack in by_cell.items():
        stack.sort(key=lambda u: u["id"])  # canonical order — never submission order
        n = len(stack)
        spread = max(2, cell_px // 4)
        base_r = max(3, cell_px // 2 - (3 if n > 1 else 1))
        cx, cy = _cell_center(x0, y0, cell_px, pos)
        for i, u in enumerate(stack):
            dx, dy = _stack_offset(i, n, spread)
            out[u["id"]] = {
                "x": cx + dx,
                "y": cy + dy,
                "r": base_r,
                "team": u["team"],
                "role": u["role"],
                "carrying": u["carrying"],
            }
    return out


def _paint_unit(canvas: _Canvas, p: Mapping[str, Any], team_index) -> None:
    ux, uy, base_r = p["x"], p["y"], p["r"]
    # A surface-colored ring under the team disc — the raster cousin of the
    # HTML face's ``.u-body { stroke: var(--surface); stroke-width: 2.4 }`` —
    # separates units from furniture and from each other when stacked.
    ring_w = 1 if base_r <= 6 else 2
    canvas.disc(ux, uy, base_r + ring_w, _SURFACE)
    canvas.disc(ux, uy, base_r, _team_color(team_index[p["team"]]))
    glyph = _ROLE_GLYPH.get(p["role"], (p["role"][:1] or "?").upper())
    gw = _text_width(glyph, 1)
    canvas.text(ux - gw // 2, uy - _FONT_ROWS // 2, glyph, _GLYPH, 1)
    if p["carrying"]:
        dot_r = max(2, base_r // 3)
        canvas.disc(ux + base_r - 2, uy - base_r + 2, dot_r + 1, _SURFACE)
        canvas.disc(ux + base_r - 2, uy - base_r + 2, dot_r, _RESOURCE)


def _paint_units(canvas: _Canvas, positions: Mapping[str, dict[str, Any]], team_index) -> None:
    for uid in sorted(positions):  # id order — deterministic, stable stacking
        _paint_unit(canvas, positions[uid], team_index)


def _draw_units(canvas: _Canvas, x0: int, y0: int, cell_px: int, units, team_index) -> None:
    _paint_units(canvas, _unit_positions(units, x0, y0, cell_px), team_index)


def _tween_positions(
    pa: Mapping[str, dict[str, Any]], pb: Mapping[str, dict[str, Any]], frac: float
) -> dict[str, dict[str, Any]]:
    """Linear interpolation of each unit's render position from turn A to B at
    ``frac`` in (0, 1). A unit alive in both frames glides; one that leaves
    before B holds at its A position (it disappears on the B turn frame); one
    that only appears in B is omitted until then. Integer rounding keeps it
    byte-deterministic."""
    out: dict[str, dict[str, Any]] = {}
    for uid, a in pa.items():
        b = pb.get(uid)
        if b is None:
            out[uid] = a
            continue
        out[uid] = {
            "x": round(a["x"] + (b["x"] - a["x"]) * frac),
            "y": round(a["y"] + (b["y"] - a["y"]) * frac),
            "r": round(a["r"] + (b["r"] - a["r"]) * frac),
            "team": a["team"],
            "role": a["role"],
            "carrying": a["carrying"],  # carry state snaps on the turn frame
        }
    return out


# --- layout (computed once per render; every frame kind shares it) -----------


@dataclass(frozen=True)
class _FooterCols:
    """Fixed column widths for the footer strip, measured across ALL frames so
    the columns never shift as scores grow."""

    turn_w: int  # the turn-counter block (widest "limit/limit" at _TEXT_SCALE)
    name_w: int  # widest team name, scale 1
    res_w: int  # widest resource numeral, scale 1
    msn_w: int  # widest missions numeral, scale 1


@dataclass(frozen=True)
class _Layout:
    width: int
    height: int
    board_x: int
    board_y: int
    caption_y: int
    panel: tuple[int, int, int, int]  # x, y, w, h — the board's panel plate
    footer: tuple[int, int, int, int]  # x, y, w, h — the score strip
    footer_cols: _FooterCols


def _footer_metrics(data: Mapping[str, Any]) -> _FooterCols:
    board_frames = data["frames"][1:] or data["frames"]
    limit = data["turn_limit"]
    turn_w = max(
        _text_width(f"{limit}/{limit}", _TEXT_SCALE),
        _text_width("TURN", 1, _CAPTION_TRACK),
    )
    name_w = max((_text_width(t["name"], 1) for t in data["teams"]), default=0)
    max_res = max((t["resources"] for f in board_frames for t in f["teams"]), default=0)
    res_w = _text_width(str(max_res), 1)
    msn_w = _text_width(str(len(data["frames"][0]["missions"])), 1)
    return _FooterCols(turn_w=turn_w, name_w=name_w, res_w=res_w, msn_w=msn_w)


def _footer_size(data: Mapping[str, Any], cols: _FooterCols) -> tuple[int, int]:
    n_teams = len(data["teams"])
    rows_w = (
        _swatch_side(1)
        + _GAP
        + 2
        + cols.name_w
        + 16
        + _text_width("RES", 1)
        + 6
        + cols.res_w
        + 14
        + _text_width("MSN", 1)
        + 6
        + cols.msn_w
    )
    width = _FOOTER_PAD + cols.turn_w + 24 + rows_w + _FOOTER_PAD
    turn_block_h = _text_height(1) + 3 + _text_height(_TEXT_SCALE)
    rows_h = n_teams * _text_height(1) + max(0, n_teams - 1) * _ROW_LEADING
    height = max(turn_block_h, rows_h) + 2 * _FOOTER_PAD
    return width, height


def _caption_text(data: Mapping[str, Any]) -> str:
    return f"{data['match_id']} {_MDOT} {data['scenario_id']}"


def _compute_layout(data: Mapping[str, Any], cell_px: int) -> _Layout:
    grid_w = data["grid"]["width"]
    grid_h = data["grid"]["height"]
    board_w, board_h = grid_w * cell_px, grid_h * cell_px
    panel_w, panel_h = board_w + 2 * _PANEL_PAD, board_h + 2 * _PANEL_PAD

    cols = _footer_metrics(data)
    footer_min_w, footer_h = _footer_size(data, cols)
    caption_w = _text_width(_caption_text(data), 1, _CAPTION_TRACK)
    title_w = max(_line_width(line) for line in _title_content(data))

    content_w = max(panel_w, footer_min_w, caption_w, title_w, _closing_width(data))
    width = content_w + 2 * _MARGIN

    turn_block_h = _text_height(1) + 8 + panel_h + 10 + footer_h
    title_h = _block_height(_title_content(data))
    closing_h = _closing_block_height(data)
    height = max(turn_block_h, title_h, closing_h) + 2 * _MARGIN

    y0 = (height - turn_block_h) // 2  # the board composition is centered too
    caption_y = y0
    panel_y = y0 + _text_height(1) + 8
    board_x = (width - board_w) // 2
    board_y = panel_y + _PANEL_PAD
    footer_w = max(footer_min_w, panel_w)
    footer = ((width - footer_w) // 2, panel_y + panel_h + 10, footer_w, footer_h)
    panel = (board_x - _PANEL_PAD, panel_y, panel_w, panel_h)
    return _Layout(
        width=width,
        height=height,
        board_x=board_x,
        board_y=board_y,
        caption_y=caption_y,
        panel=panel,
        footer=footer,
        footer_cols=cols,
    )


# --- frame drawing -----------------------------------------------------------


def _draw_corner_marks(canvas: _Canvas) -> None:
    """Hairline corner marks framing the title/closing cards — quiet chrome in
    the line tone, symmetric on all four corners."""
    inset, arm = _CARD_INSET, _MARK_LEN
    w, h = canvas.width, canvas.height
    canvas.hline(inset, inset, arm, _LINE)
    canvas.vline(inset, inset, arm, _LINE)
    canvas.hline(w - inset - arm, inset, arm, _LINE)
    canvas.vline(w - inset - 1, inset, arm, _LINE)
    canvas.hline(inset, h - inset - 1, arm, _LINE)
    canvas.vline(inset, h - inset - arm, arm, _LINE)
    canvas.hline(w - inset - arm, h - inset - 1, arm, _LINE)
    canvas.vline(w - inset - 1, h - inset - arm, arm, _LINE)


def _draw_footer(
    canvas: _Canvas,
    layout: _Layout,
    data: Mapping[str, Any],
    frame: Mapping[str, Any],
    team_index: dict,
) -> None:
    """The score strip: a surface-toned card carrying the turn counter and one
    swatch-chipped row per team with RES/MSN numerals right-aligned in fixed
    columns (tabular by construction — the font is monospaced)."""
    fx, fy, fw, fh = layout.footer
    cols = layout.footer_cols
    canvas.fill_rect(fx, fy, fw, fh, _SURFACE)
    canvas.outline_rect(fx, fy, fw, fh, _GRID)

    turn_block_h = _text_height(1) + 3 + _text_height(_TEXT_SCALE)
    tx = fx + _FOOTER_PAD
    ty = fy + (fh - turn_block_h) // 2
    canvas.text(tx, ty, "TURN", _MUTED, 1, _CAPTION_TRACK)
    counter = f"{frame['turn']}/{data['turn_limit']}"
    canvas.text(tx, ty + _text_height(1) + 3, counter, _INK, _TEXT_SCALE)

    resources = {t["id"]: t["resources"] for t in frame["teams"]}
    n_teams = len(data["teams"])
    rows_h = n_teams * _text_height(1) + max(0, n_teams - 1) * _ROW_LEADING
    ry = fy + (fh - rows_h) // 2
    rx = fx + _FOOTER_PAD + cols.turn_w + 24
    side = _swatch_side(1)
    res_label_w = _text_width("RES", 1)
    msn_label_w = _text_width("MSN", 1)
    for t in data["teams"]:
        canvas.fill_rect(rx, ry, side, side, _team_color(team_index[t["id"]]))
        canvas.text(rx + side + _GAP + 2, ry, t["name"], _INK, 1)
        x = rx + side + _GAP + 2 + cols.name_w + 16
        canvas.text(x, ry, "RES", _MUTED, 1)
        x += res_label_w + 6
        res_val = str(resources.get(t["id"], 0))
        canvas.text(x + cols.res_w - _text_width(res_val, 1), ry, res_val, _INK, 1)
        x += cols.res_w + 14
        canvas.text(x, ry, "MSN", _MUTED, 1)
        x += msn_label_w + 6
        done = str(sum(1 for m in frame["missions"] if t["id"] in m["completed_by"]))
        canvas.text(x + cols.msn_w - _text_width(done, 1), ry, done, _INK, 1)
        ry += _text_height(1) + _ROW_LEADING


def _draw_board_chrome(
    canvas: _Canvas,
    layout: _Layout,
    data: Mapping[str, Any],
    frame: Mapping[str, Any],
    team_index: dict,
    cell_px: int,
) -> None:
    """Everything on a board frame except the units: the muted caption, the
    board panel with its hairline grid and furniture, and the footer strip.
    Turn frames and tween frames share this exactly, so their chrome can never
    drift apart."""
    caption = _caption_text(data)
    caption_w = _text_width(caption, 1, _CAPTION_TRACK)
    caption_x = (canvas.width - caption_w) // 2
    canvas.text(caption_x, layout.caption_y, caption, _MUTED, 1, _CAPTION_TRACK)
    px, py, pw, ph = layout.panel
    canvas.fill_rect(px, py, pw, ph, _BG)
    canvas.outline_rect(px, py, pw, ph, _LINE)
    grid_w, grid_h = data["grid"]["width"], data["grid"]["height"]
    _draw_grid(canvas, layout.board_x, layout.board_y, grid_w, grid_h, cell_px)
    _draw_resource_nodes(canvas, layout.board_x, layout.board_y, cell_px, frame["resource_nodes"])
    _draw_missions(canvas, layout.board_x, layout.board_y, cell_px, frame["missions"], team_index)
    _draw_control_points(
        canvas, layout.board_x, layout.board_y, cell_px, frame["control_points"], team_index
    )
    _draw_footer(canvas, layout, data, frame, team_index)


def _draw_turn_frame(
    canvas: _Canvas,
    layout: _Layout,
    data: Mapping[str, Any],
    frame: Mapping[str, Any],
    team_index: dict,
    cell_px: int,
) -> None:
    _draw_board_chrome(canvas, layout, data, frame, team_index, cell_px)
    _draw_units(canvas, layout.board_x, layout.board_y, cell_px, frame["units"], team_index)


def _draw_tween_frame(
    canvas: _Canvas,
    layout: _Layout,
    data: Mapping[str, Any],
    frame_a: Mapping[str, Any],
    frame_b: Mapping[str, Any],
    team_index: dict,
    cell_px: int,
    frac: float,
) -> None:
    """An in-between frame: the board furniture (grid, nodes, missions, control
    points, caption, footer) is the *starting* turn's discrete state; only the
    units move, linearly interpolated toward the next turn. So resource counts,
    captures and the turn number land crisply on turn frames while movement
    flows continuously between them."""
    _draw_board_chrome(canvas, layout, data, frame_a, team_index, cell_px)
    pa = _unit_positions(frame_a["units"], layout.board_x, layout.board_y, cell_px)
    pb = _unit_positions(frame_b["units"], layout.board_x, layout.board_y, cell_px)
    _paint_units(canvas, _tween_positions(pa, pb, frac), team_index)


def _draw_title_frame(canvas: _Canvas, data: Mapping[str, Any], team_index: dict) -> None:
    _draw_corner_marks(canvas)
    lines = _title_content(data)
    y = (canvas.height - _block_height(lines)) // 2
    _draw_lines_centered(canvas, canvas.width // 2, y, lines, team_index)


def _draw_closing_frame(canvas: _Canvas, data: Mapping[str, Any], team_index: dict) -> None:
    _draw_corner_marks(canvas)
    cx = canvas.width // 2
    y = (canvas.height - _closing_block_height(data)) // 2
    y = _draw_lines_centered(canvas, cx, y, _closing_head(), team_index)
    y += _COLS_PAD

    cols = _closing_columns(data)
    widths = [_closing_col_width(c) for c in cols]
    total_w = sum(widths) + _COL_GAP * (len(cols) - 1)
    x = cx - total_w // 2
    side = _swatch_side(1)
    for col, col_w in zip(cols, widths):
        col_cx = x + col_w // 2
        total_txt_w = _text_width(col["total"], _SCORE_SCALE)
        canvas.text(col_cx - total_txt_w // 2, y, col["total"], _INK, _SCORE_SCALE)
        name_y = y + _text_height(_SCORE_SCALE) + 8
        name_w = side + _GAP + 2 + _text_width(col["name"], 1)
        name_x = col_cx - name_w // 2
        canvas.fill_rect(name_x, name_y, side, side, _team_color(team_index[col["team"]]))
        canvas.text(name_x + side + _GAP + 2, name_y, col["name"], _INK, 1)
        detail_y = name_y + _text_height(1) + 5
        detail_w = _text_width(col["detail"], 1)
        canvas.text(col_cx - detail_w // 2, detail_y, col["detail"], _INK2, 1)
        x += col_w + _COL_GAP

    y += _closing_cols_height()
    _draw_lines_centered(canvas, cx, y, _closing_tail(data), team_index)


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
    # The theme's RGB color table (the GIF global color table); frame indices
    # are theme-independent, so only this changes between light and dark.
    palette: tuple[tuple[int, int, int], ...] = PALETTE


def _delay_cs(fps: int) -> int:
    return max(2, round(100 / fps))


def build_frames(
    replay_data: Mapping[str, Any],
    *,
    cell_px: int = DEFAULT_SCALE,
    turn_delay_cs: int = 50,
    theme: str = DEFAULT_THEME,
    tween: int = DEFAULT_TWEEN,
) -> VideoFrames:
    """Deterministic raster frames from a replay fold: title, the turns played
    (with ``tween`` interpolated frames between each pair), and a closing card.

    ``replay_data`` is exactly :func:`league.replay.html.build_replay_data`'s
    output — the same fold every other face (HTML, TUI, ``--json``) reads, so
    this can never disagree with them on the facts. With ``turns =
    len(replay_data["frames"]) - 1``, the frame count is ``turns + (turns - 1) *
    tween + 2``: the opening title card, one frame per turn actually played,
    ``tween`` linearly-interpolated frames between each adjacent pair of turns
    (so movement flows instead of teleporting), and the closing score card —
    the pre-turn-0 snapshot is folded into the title card rather than drawn as
    its own near-duplicate board frame. ``theme`` selects the shared HTML-replay
    palette (``"light"`` cream / ``"dark"`` black-green); it changes only the
    color table, so the indices — and thus the tween interpolation — stay
    byte-deterministic.

    The ``tween + 1`` sub-frame delays of every non-final turn sum *exactly* to
    ``turn_delay_cs``, so the requested pace is honored to the centisecond. GIF
    renderers ignore holds under 2cs, so a ``tween`` too high for the hold —
    ``turn_delay_cs < 2 * (tween + 1)`` — raises :class:`ValueError` instead of
    silently playing slower than asked.
    """
    if cell_px < 4:
        raise ValueError("cell_px must be >= 4")
    if turn_delay_cs < 1:
        raise ValueError("turn_delay_cs must be >= 1")
    if not MIN_TWEEN <= tween <= MAX_TWEEN:
        raise ValueError(f"tween must be in {MIN_TWEEN}..{MAX_TWEEN}")

    palette = build_palette(theme)  # also validates the theme name
    team_index = {t["id"]: i for i, t in enumerate(replay_data["teams"])}
    board_frames = replay_data["frames"][1:]
    layout = _compute_layout(replay_data, cell_px)
    width, height = layout.width, layout.height
    # Split a turn's screen time exactly across its (tween + 1) sub-frames —
    # integer division, remainder spread over the leading sub-frames — so the
    # delays sum to turn_delay_cs. Each sub-frame must clear the 2cs floor GIF
    # renderers enforce; refuse combinations that can't, rather than inflating.
    if turn_delay_cs < 2 * (tween + 1):
        raise ValueError(
            f"tween {tween} does not fit a {turn_delay_cs}cs turn hold: "
            f"{tween + 1} sub-frames need >= 2cs each"
        )
    base, extra = divmod(turn_delay_cs, tween + 1)
    sub_delays = tuple(base + 1 if k < extra else base for k in range(tween + 1))

    frames: list[Frame] = []

    title_canvas = _Canvas(width, height)
    _draw_title_frame(title_canvas, replay_data, team_index)
    frames.append(Frame(title_canvas.to_bytes(), max(turn_delay_cs * 4, 200)))

    last = len(board_frames) - 1
    for i, f in enumerate(board_frames):
        canvas = _Canvas(width, height)
        _draw_turn_frame(canvas, layout, replay_data, f, team_index, cell_px)
        # The final turn rests the full hold; earlier turns share time with the
        # tween frames that follow them.
        frames.append(Frame(canvas.to_bytes(), turn_delay_cs if i == last else sub_delays[0]))
        if i != last and tween:
            nxt = board_frames[i + 1]
            for k in range(1, tween + 1):
                frac = k / (tween + 1)
                tcanvas = _Canvas(width, height)
                _draw_tween_frame(
                    tcanvas,
                    layout,
                    replay_data,
                    f,
                    nxt,
                    team_index,
                    cell_px,
                    frac,
                )
                frames.append(Frame(tcanvas.to_bytes(), sub_delays[k]))

    closing_canvas = _Canvas(width, height)
    _draw_closing_frame(closing_canvas, replay_data, team_index)
    frames.append(Frame(closing_canvas.to_bytes(), max(turn_delay_cs * 6, 300)))

    return VideoFrames(width=width, height=height, frames=tuple(frames), palette=palette)


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
    palette = video.palette
    n_colors = len(palette)
    size_field, padded_len = _color_table_size_field(n_colors)
    min_code_size = size_field + 1
    packed_lsd = 0x80 | (size_field << 4) | size_field

    color_table = bytearray()
    for i in range(padded_len):
        rgb = palette[i] if i < n_colors else (0, 0, 0)
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
    theme: str = DEFAULT_THEME,
    tween: int = DEFAULT_TWEEN,
    provenance: str = "",
) -> bytes:
    """The one function most callers want: a match log straight to GIF bytes.

    Deterministic end to end — the same log at the same
    ``scale``/``fps``/``theme``/``tween`` (and the same ``provenance`` string,
    since it's embedded verbatim as a GIF Comment Extension) renders
    byte-identical output.
    """
    data = build_replay_data(log)
    video = build_frames(
        data, cell_px=scale, turn_delay_cs=_delay_cs(fps), theme=theme, tween=tween
    )
    return _encode_gif(video, comment=provenance)
