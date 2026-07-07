"""Render a match log as a shareable, offline animated GIF (plan task t6, spec c7/h7).

**Toolchain decision (parked risk r1, pinned here):** the primary path is a
pure-stdlib animated GIF89a writer — palette-indexed raster frames plus a
hand-rolled LZW encoder (~a few hundred lines, no dependency). The board is
flat-color geometry (discs, rings, diamonds, a tiny bitmap font), so a small
global palette (28 colors — the SAME validated hues :mod:`league.replay.html`
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
(:mod:`league.replay.html`; rationale in ``docs/replay-design.md``), and its
play frames mirror that page's **board card during playback**, raster-exact:
every geometry value is one of the HTML face's own CSS/SVG pixel numbers
scaled by ``cell_px / 46`` (46 is the HTML board's SVG cell — see ``_HTML_CELL``
and the metric constants below). One opening **title card** — a centered
lockup (the title over a thin accent rule, the match id, a scenario/mode/seed
metadata line, then one swatch-chipped row per team with its roster), framed by
hairline corner marks. One frame per **turn** actually played (skips the
pre-turn-0 snapshot the title card covers), drawn as the HTML replay's board
card on the page matte: a rounded card surface (``--r-lg`` 18px corners, a 1px
``--ring`` border, 14px padding), a header row inside the card — the brand
mark and title with the turn readout right-aligned (the HTML's
``turn N / limit``), then one pill chip per team (swatch · name · live RES/MSN
numerals) with the match id · scenario line right-aligned — and the board
frame (``--r-md`` 12px corners, 1px border, the board plane at the HTML
gradient's midpoint) carrying the hairline grid and the HTML board's exact
mark vocabulary: unit discs (r 12/46 of a cell, a 2.4/46 surface stroke, a
bold white role glyph; r 9/46 and the HTML's own fan-out offsets when
stacked), control-point discs (r 15/46 — surface fill + line ring unowned,
owner tint at ``fill-opacity`` .24 + team ring owned, the hold counter in
secondary ink), deliver-mission rings (r 18/46 — muted pending, the
completer's hue when done, secondary ink when shared), resource diamonds
(11√2/46 half-diagonal, the remaining count in glyph ink, the resource tint
when exhausted), and the carry badge at the unit's shoulder. Interactive-only
HTML chrome (transport buttons, slider, tab deck) is deliberately absent — the
GIF is the board card, not the page — and the board's fine-print id labels
(``cp-id``/``m-label``) are the one omission: they sit below the 5x7 bitmap
font's legibility floor. ``tween`` linearly interpolated frames between each
adjacent pair of turns keep movement flowing instead of teleporting; a tween
frame holds the starting turn's card chrome and glides only the units. One
**closing card** — big score numerals per team over swatch-labelled rows, the
winner named beneath — closes the loop. Frame count: ``turns + (turns - 1) *
tween + 2``.
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
_CARD_INSET = 10  # corner-mark inset on the title/closing cards
_MARK_LEN = 12  # corner-mark arm length
_RULE_W = 36  # accent rule width
_RULE_H = 2  # accent rule height
_CAPTION_TRACK = 1  # extra letter-spacing (px per glyph) for small-caps captions

# --- HTML board-card geometry (the raster mirrors the HTML play view) --------
#
# ``league/replay/html.py`` draws its board at ``CELL = 46`` SVG units per grid
# cell; every card/board metric below is one of that file's own CSS or SVG
# pixel values (named after its selector), scaled to this render's ``cell_px``
# through ``_hpx``/``_hoff``/``_hscale`` — so a GIF play frame is a raster crop
# of the HTML page's board card at any scale, not a lookalike.
_HTML_CELL = 46  # html.py: const CELL = 46

_U_R = 12  # .u-body solo radius (circle r=12)
_U_R_STACKED = 9  # stacked unit radius
_U_STROKE = 2.4  # .u-body { stroke-width: 2.4 } — the surface ring
_U_GLYPH_PX = 11  # .u-glyph font-size (solo)
_CARRY_R = 6  # .u-carry-dot radius
_CARRY_STROKE = 1.5  # .u-carry-dot { stroke-width: 1.5 }
_CARRY_NUDGE = 2  # carry badge offset: translate(r - 2, 2 - r)
_CP_R = 15  # .cp-disc radius
_CP_STROKE = 2.4  # .cp-disc { stroke-width: 2.4 }
_CP_HOLD_PX = 10  # .cp-hold font-size
_MISSION_R = 18  # .m-ring radius (deliver missions only)
_MISSION_STROKE = 1.5  # .m-ring { stroke-width: 1.5 } — pending
_MISSION_STROKE_DONE = 2.4  # .m-ring.done { stroke-width: 2.4 }
_NODE_R = 11 * 2**0.5  # the 22x22 node rect rotated 45° — its half-diagonal
_NODE_NUM_PX = 11  # .node-num font-size
_SVG_PAD = 14  # html.py: const PAD = 14 (inside the SVG viewBox)
_FRAME_PAD = 8  # .board-frame { padding: 8px }
_FRAME_RADIUS = 12  # .board-frame { border-radius: var(--r-md) } = 12px
_CARD_PAD = 14  # .board-card { padding: 14px } (and #board-box { gap: 14px })
_CARD_RADIUS = 18  # .card { border-radius: var(--r-lg) } = 18px
_MARK_SIDE = 22  # .brand .mark { width/height: 22px }
_MARK_RADIUS = 7  # .brand .mark { border-radius: 7px }
_BRAND_GAP = 11  # .brand { gap: 11px }
_H1_PX = 20  # header h1 { font-size: 20px }
_SMALL_PX = 13  # #turn-label / .team-stats font-size (the 12-14px family)
_HEADER_ROW_GAP = 10  # header { gap: 10px }
_HEAD_GAP = 9  # .team-head { gap: 9px } — swatch <-> team name
_STATS_GAP = 16  # .team-stats { gap: 16px }
_NUM_GAP = 6  # .agents { gap: 6px } — a stat label <-> its numeral
_SWATCH = 12  # .swatch { width/height: 12px }
_SWATCH_RADIUS = 4  # .swatch { border-radius: 4px }
_CHIP_PAD_X = 11  # .chip { padding: 3px 11px }
_CHIP_PAD_Y = 3
_CHIP_GAP = 8  # .meta { gap: 8px } — chip <-> chip

# html.py's STACK_OFFSETS (SVG px at CELL=46), plus its >4-units-per-cell
# circle-fallback radius — the deterministic "nothing is ever occluded" fan-out.
_STACK_OFFSETS: tuple[tuple[tuple[int, int], ...], ...] = (
    ((0, 0),),
    ((-9, 0), (9, 0)),
    ((0, -9), (-9, 8), (9, 8)),
    ((-9, -9), (9, -9), (-9, 9), (9, 9)),
)
_STACK_RING = 13

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


# --- HTML-pixel scaling (46 SVG units = one cell on the HTML board) ----------


def _hpx(v: float, cell_px: int) -> int:
    """One of the HTML face's pixel values scaled to ``cell_px`` — floored at
    1px so hairlines, strokes, and paddings survive small scales."""
    return max(1, round(v * cell_px / _HTML_CELL))


def _hoff(v: float, cell_px: int) -> int:
    """A signed/zero-preserving scaled offset (stack fan-outs, badge nudges)."""
    return round(v * cell_px / _HTML_CELL)


def _hscale(font_px: float, cell_px: int) -> int:
    """The integer 5x7-glyph scale nearest an HTML font size at this cell."""
    return max(1, round(font_px * cell_px / _HTML_CELL / _FONT_ROWS))


# --- palette (per-theme, match-independent — the same 28 index SLOTS every
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


# The HTML face's exact ownership tint: ``.cp-disc.owned { fill-opacity: .24 }``
# — the owner's hue at 24% over the board plane.
_OWNED_TINT_ALPHA = 0.24
# ``.node`` fill-opacity for an exhausted resource node (``d.style.fillOpacity
# = n.remaining ? 0.95 : 0.28``) — the resource hue at 28% over the plane.
_NODE_DEPLETED_ALPHA = 0.28
# ``--ring`` is rgba(ink, .10) in both themes — rasterized as ink blended over
# the card surface it actually borders.
_RING_ALPHA = 0.10

# Neutral/chrome steps beyond the tokens ``THEMES`` exports — lifted VERBATIM
# from the HTML face's CSS custom properties (the ``:root`` blocks in
# ``league/replay/html.py``'s template), so the raster face composes with the
# identical, already-designed surface system: the page matte the cards sit on
# (``--plane``), the card surface (``--surface`` — also the unit-marker ring,
# the raster cousin of ``.u-body { stroke: var(--surface) }``), the hairline
# grid (``--grid``), secondary ink (``--ink-2``), the chrome accent
# (``--accent`` — chrome only, never a team, per docs/replay-design.md), and
# the chip tone (``--chip`` — the pill background behind header chips).
_THEME_EXTRAS: dict[str, dict[str, str]] = {
    "light": {
        "matte": "#f0eee5",
        "surface": "#faf8f1",
        "grid": "#ded9c9",
        "ink2": "#5a5546",
        "accent": "#1e7a4d",
        "chip": "#ece8dd",
    },
    "dark": {
        "matte": "#0c1210",
        "surface": "#111a16",
        "grid": "#1e2a24",
        "ink2": "#aebcb2",
        "accent": "#46c79e",
        "chip": "#152019",
    },
}


def _theme_palette_hex(name: str, theme: Mapping[str, Any]) -> tuple[str, ...]:
    """The 28 palette hexes for a theme, in slot order — the SAME validated hues
    :mod:`league.replay.html` uses for that theme (board plane/line/ink/muted,
    status good/critical, resource, glyph ink, the team hues and their
    ownership tints), then the HTML face's own neutral steps (page matte, card
    surface, hairline grid, secondary ink, chrome accent, chip tone) and two
    derived steps that rasterize its alpha effects: the ``--ring`` hairline
    (ink at 10% over the surface) and the depleted-node tint (the resource hue
    at 28% over the plane). No new hues — every step is a token or an
    alpha-blend of two tokens, exactly as the HTML face composes them."""
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
        + (
            extras["matte"],
            extras["surface"],
            extras["grid"],
            extras["ink2"],
            extras["accent"],
            extras["chip"],
            _blend_hex(extras["surface"], theme["ink"], _RING_ALPHA),
            _blend_hex(theme["plane"], theme["resource"], _NODE_DEPLETED_ALPHA),
        )
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
# The HTML face's neutral steps (slots 20..27): page matte, card surface,
# hairline grid, secondary ink, chrome accent, chip tone, the --ring hairline,
# and the depleted-node resource tint. Slot 0 (_BG) stays the *board* plane —
# the tone the board frame wears; the canvas itself sits on _MATTE.
_MATTE = _TINT0 + _N_TEAM_SLOTS
_SURFACE = _MATTE + 1
_GRID = _MATTE + 2
_INK2 = _MATTE + 3
_ACCENT = _MATTE + 4
_CHIP = _MATTE + 5
_RING = _MATTE + 6
_RESOURCE_TINT = _MATTE + 7

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

    def rounded_rect(self, x: int, y: int, w: int, h: int, r: int, color: int) -> None:
        """A filled rectangle with quarter-disc corners — the raster cousin of
        the HTML face's ``border-radius`` cards, chips, and swatches."""
        if w <= 0 or h <= 0:
            return
        r = max(0, min(r, (min(w, h) - 1) // 2))
        if r == 0:
            self.fill_rect(x, y, w, h, color)
            return
        self.fill_rect(x + r, y, w - 2 * r, h, color)
        self.fill_rect(x, y + r, w, h - 2 * r, color)
        for ccx, ccy in (
            (x + r, y + r),
            (x + w - 1 - r, y + r),
            (x + r, y + h - 1 - r),
            (x + w - 1 - r, y + h - 1 - r),
        ):
            self.disc(ccx, ccy, r, color)

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
    # The HTML board's node verbatim: a diamond (its 22x22 rect rotated 45°,
    # half-diagonal 11√2) carrying the remaining count in bold glyph ink; an
    # exhausted node keeps the shape in the resource tint (``fillOpacity .28``)
    # — shape-coded, never a round mark, so a node can never be mistaken for a
    # unit or a control point even in grayscale.
    r = max(3, _hoff(_NODE_R, cell_px))
    num_scale = _hscale(_NODE_NUM_PX, cell_px)
    for n in nodes:
        cx, cy = _cell_center(x0, y0, cell_px, n["pos"])
        canvas.diamond(cx, cy, r, _RESOURCE if n["remaining"] else _RESOURCE_TINT)
        label = str(n["remaining"])
        canvas.text(
            cx - _text_width(label, num_scale) // 2,
            cy - _text_height(num_scale) // 2,
            label,
            _GLYPH,
            num_scale,
        )


def _draw_missions(canvas: _Canvas, x0: int, y0: int, cell_px: int, missions, team_index) -> None:
    # Parity with the HTML board: only a *deliver* mission wears the r=18 ring
    # (a hold mission's cell is its control point — the HTML gives it no mark
    # of its own). Pending: the thin muted ring (``.m-ring``); done: the
    # heavier ring in the completing team's hue — the neutral secondary ink
    # when shared, so neither team's color claims it (``.m-ring.done``).
    r = _hpx(_MISSION_R, cell_px)
    for m in missions:
        if m["kind"] != "deliver":
            continue
        cx, cy = _cell_center(x0, y0, cell_px, m["pos"])
        completed = m["status"] == "completed" and m["completed_by"]
        if completed:
            color = (
                _team_color(team_index[m["completed_by"][0]])
                if len(m["completed_by"]) == 1
                else _INK2
            )
            canvas.ring(cx, cy, r, _hpx(_MISSION_STROKE_DONE, cell_px), color)
        else:
            canvas.ring(cx, cy, r, _hpx(_MISSION_STROKE, cell_px), _MUTED)


def _draw_control_points(
    canvas: _Canvas, x0: int, y0: int, cell_px: int, control_points, team_index
) -> None:
    # The HTML ``.cp-disc`` verbatim: a FILLED disc under a 2.4px ring —
    # surface fill + line ring when unowned; the owner's .24 tint + team ring
    # when owned, with the hold counter (``.cp-hold``) in secondary ink at its
    # center.
    r = _hpx(_CP_R, cell_px)
    stroke = _hpx(_CP_STROKE, cell_px)
    hold_scale = _hscale(_CP_HOLD_PX, cell_px)
    for c in control_points:
        cx, cy = _cell_center(x0, y0, cell_px, c["pos"])
        if c["owner"] is not None:
            idx = team_index[c["owner"]]
            canvas.disc(cx, cy, r, _team_tint(idx))
            canvas.ring(cx, cy, r, stroke, _team_color(idx))
        else:
            canvas.disc(cx, cy, r, _SURFACE)
            canvas.ring(cx, cy, r, stroke, _LINE)
        if c["hold"]:
            label = str(c["hold"][0][1])
            canvas.text(
                cx - _text_width(label, hold_scale) // 2,
                cy - _text_height(hold_scale) // 2,
                label,
                _INK2,
                hold_scale,
            )


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
        # The HTML board's exact sizes and fan-out: solo units keep the full
        # r=12 disc, stacked ones shrink to r=9 and take STACK_OFFSETS'
        # patterns (1-4 units) or the radius-13 circle fallback beyond that.
        base_r = max(2, _hpx(_U_R if n == 1 else _U_R_STACKED, cell_px))
        if n <= len(_STACK_OFFSETS):
            offsets = [(_hoff(dx, cell_px), _hoff(dy, cell_px)) for dx, dy in _STACK_OFFSETS[n - 1]]
        else:
            spread = max(2, _hoff(_STACK_RING, cell_px))
            offsets = [_stack_offset(i, n, spread) for i in range(n)]
        cx, cy = _cell_center(x0, y0, cell_px, pos)
        for i, u in enumerate(stack):
            dx, dy = offsets[i]
            out[u["id"]] = {
                "x": cx + dx,
                "y": cy + dy,
                "r": base_r,
                "team": u["team"],
                "role": u["role"],
                "carrying": u["carrying"],
            }
    return out


def _paint_unit(canvas: _Canvas, p: Mapping[str, Any], team_index, cell_px: int) -> None:
    ux, uy, base_r = p["x"], p["y"], p["r"]
    # A surface-colored ring under the team disc — the raster of the HTML
    # face's ``.u-body { stroke: var(--surface); stroke-width: 2.4 }`` —
    # separates units from furniture and from each other when stacked.
    ring_w = _hpx(_U_STROKE, cell_px)
    canvas.disc(ux, uy, base_r + ring_w, _SURFACE)
    canvas.disc(ux, uy, base_r, _team_color(team_index[p["team"]]))
    glyph = _ROLE_GLYPH.get(p["role"], (p["role"][:1] or "?").upper())
    glyph_scale = _hscale(_U_GLYPH_PX, cell_px)
    canvas.text(
        ux - _text_width(glyph, glyph_scale) // 2,
        uy - _text_height(glyph_scale) // 2,
        glyph,
        _GLYPH,
        glyph_scale,
    )
    if p["carrying"]:
        # ``.u-carry``: the resource dot at the unit's shoulder — offset
        # translate(r - 2, 2 - r) — with its own thin surface stroke; the
        # count rides inside only when the dot can actually hold a glyph
        # (the HTML's 8px number sits below the bitmap font's floor at
        # small cells).
        dot_r = max(2, _hoff(_CARRY_R, cell_px))
        bx = ux + base_r - _hoff(_CARRY_NUDGE, cell_px)
        by = uy - base_r + _hoff(_CARRY_NUDGE, cell_px)
        canvas.disc(bx, by, dot_r + _hpx(_CARRY_STROKE, cell_px), _SURFACE)
        canvas.disc(bx, by, dot_r, _RESOURCE)
        label = str(p["carrying"])
        if 2 * dot_r + 1 >= _text_height(1) + 2 and _text_width(label, 1) <= 2 * dot_r:
            canvas.text(
                bx - _text_width(label, 1) // 2, by - _text_height(1) // 2, label, _GLYPH, 1
            )


def _paint_units(
    canvas: _Canvas, positions: Mapping[str, dict[str, Any]], team_index, cell_px: int
) -> None:
    for uid in sorted(positions):  # id order — deterministic, stable stacking
        _paint_unit(canvas, positions[uid], team_index, cell_px)


def _draw_units(canvas: _Canvas, x0: int, y0: int, cell_px: int, units, team_index) -> None:
    _paint_units(canvas, _unit_positions(units, x0, y0, cell_px), team_index, cell_px)


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
class _Card:
    """The HTML board card's geometry scaled to this render's cell size —
    every field is one of ``html.py``'s CSS/SVG pixel values through
    ``_hpx``/``_hoff``/``_hscale`` (see the metric constants up top)."""

    pad: int  # .board-card padding
    gap: int  # #board-box gap (header <-> board frame)
    radius: int  # .card border-radius (--r-lg)
    frame_radius: int  # .board-frame border-radius (--r-md)
    board_inset: int  # frame border + .board-frame padding + the SVG's PAD
    mark: int  # .brand .mark side
    mark_radius: int
    brand_gap: int
    title_scale: int  # header h1
    small_scale: int  # turn label / chips / team names
    row_gap: int  # header row 1 <-> row 2
    head_gap: int  # swatch <-> team name
    stats_gap: int  # stat group <-> stat group
    num_gap: int  # stat label <-> numeral
    swatch: int
    swatch_radius: int
    chip_pad_x: int
    chip_pad_y: int
    chip_gap: int


def _card_metrics(cell_px: int) -> _Card:
    return _Card(
        pad=_hpx(_CARD_PAD, cell_px),
        gap=_hpx(_CARD_PAD, cell_px),
        radius=_hpx(_CARD_RADIUS, cell_px),
        frame_radius=_hpx(_FRAME_RADIUS, cell_px),
        board_inset=1 + _hpx(_FRAME_PAD, cell_px) + _hpx(_SVG_PAD, cell_px),
        mark=_hpx(_MARK_SIDE, cell_px),
        mark_radius=_hpx(_MARK_RADIUS, cell_px),
        brand_gap=_hpx(_BRAND_GAP, cell_px),
        title_scale=_hscale(_H1_PX, cell_px),
        small_scale=_hscale(_SMALL_PX, cell_px),
        row_gap=_hpx(_HEADER_ROW_GAP, cell_px),
        head_gap=_hpx(_HEAD_GAP, cell_px),
        stats_gap=_hpx(_STATS_GAP, cell_px),
        num_gap=_hpx(_NUM_GAP, cell_px),
        swatch=_hpx(_SWATCH, cell_px),
        swatch_radius=_hpx(_SWATCH_RADIUS, cell_px),
        chip_pad_x=_hpx(_CHIP_PAD_X, cell_px),
        chip_pad_y=_hpx(_CHIP_PAD_Y, cell_px),
        chip_gap=_hpx(_CHIP_GAP, cell_px),
    )


@dataclass(frozen=True)
class _HeaderCols:
    """Fixed header measurements, taken across ALL frames so the chips and the
    turn readout never shift as scores grow during playback."""

    res_w: int  # widest resource numeral
    msn_w: int  # widest missions numeral
    turn_w: int  # widest turn readout ("TURN limit/limit")
    chip_ws: tuple[int, ...]  # one fixed pill width per team


@dataclass(frozen=True)
class _Layout:
    width: int
    height: int
    card: tuple[int, int, int, int]  # x, y, w, h — the board card on the matte
    frame: tuple[int, int, int, int]  # x, y, w, h — the board frame in the card
    row1_y: int  # header row 1 (brand + title + turn readout)
    row1_h: int
    row2_y: int  # header row 2 (team chips + match line)
    row2_h: int
    board_x: int
    board_y: int
    cols: _HeaderCols
    cm: _Card


def _match_line(data: Mapping[str, Any]) -> str:
    return f"{data['match_id']} {_MDOT} {data['scenario_id']}"


def _header_metrics(data: Mapping[str, Any], cm: _Card) -> _HeaderCols:
    board_frames = data["frames"][1:] or data["frames"]
    limit = data["turn_limit"]
    turn_w = _text_width(f"TURN {limit}/{limit}", cm.small_scale)
    max_res = max((t["resources"] for f in board_frames for t in f["teams"]), default=0)
    res_w = _text_width(str(max_res), cm.small_scale)
    msn_w = _text_width(str(len(data["frames"][0]["missions"])), cm.small_scale)
    chip_ws = tuple(
        2  # the pill's 1px ring border
        + 2 * cm.chip_pad_x
        + cm.swatch
        + cm.head_gap
        + _text_width(t["name"], cm.small_scale)
        + cm.stats_gap
        + _text_width("RES", cm.small_scale)
        + cm.num_gap
        + res_w
        + cm.stats_gap
        + _text_width("MSN", cm.small_scale)
        + cm.num_gap
        + msn_w
        for t in data["teams"]
    )
    return _HeaderCols(res_w=res_w, msn_w=msn_w, turn_w=turn_w, chip_ws=chip_ws)


def _compute_layout(data: Mapping[str, Any], cell_px: int) -> _Layout:
    cm = _card_metrics(cell_px)
    cols = _header_metrics(data, cm)
    grid_w = data["grid"]["width"]
    grid_h = data["grid"]["height"]
    board_w, board_h = grid_w * cell_px, grid_h * cell_px
    frame_min_w = board_w + 2 * cm.board_inset
    frame_h = board_h + 2 * cm.board_inset

    small_h = _text_height(cm.small_scale)
    row1_h = max(cm.mark, _text_height(cm.title_scale), small_h)
    row2_h = 2 + 2 * cm.chip_pad_y + max(cm.swatch, small_h)
    row1_w = (
        cm.mark
        + cm.brand_gap
        + _text_width("LEAGUE OF AGENTS", cm.title_scale)
        + cm.stats_gap
        + cols.turn_w
    )
    chips_w = sum(cols.chip_ws) + cm.chip_gap * max(0, len(cols.chip_ws) - 1)
    row2_w = chips_w + cm.stats_gap + _text_width(_match_line(data), cm.small_scale)

    # The frame stretches to the card's inner width (the HTML's block layout);
    # a wider header widens the card and the board letterboxes centered.
    card_inner_w = max(frame_min_w, row1_w, row2_w)
    card_w = card_inner_w + 2 * (cm.pad + 1)
    card_h = 2 * (cm.pad + 1) + row1_h + cm.row_gap + row2_h + cm.gap + frame_h

    title_w = max(_line_width(line) for line in _title_content(data))
    content_w = max(card_w, title_w, _closing_width(data))
    width = content_w + 2 * _MARGIN
    title_h = _block_height(_title_content(data))
    height = max(card_h, title_h, _closing_block_height(data)) + 2 * _MARGIN

    card_x = (width - card_w) // 2
    card_y = (height - card_h) // 2
    row1_y = card_y + 1 + cm.pad
    row2_y = row1_y + row1_h + cm.row_gap
    frame = (card_x + 1 + cm.pad, row2_y + row2_h + cm.gap, card_inner_w, frame_h)
    board_x = frame[0] + (card_inner_w - board_w) // 2
    board_y = frame[1] + cm.board_inset
    return _Layout(
        width=width,
        height=height,
        card=(card_x, card_y, card_w, card_h),
        frame=frame,
        row1_y=row1_y,
        row1_h=row1_h,
        row2_y=row2_y,
        row2_h=row2_h,
        board_x=board_x,
        board_y=board_y,
        cols=cols,
        cm=cm,
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


def _draw_surface_card(
    canvas: _Canvas, x: int, y: int, w: int, h: int, radius: int, fill: int
) -> None:
    """A rounded card with the 1px ``--ring`` hairline border the HTML face
    puts on every card, chip, and board frame."""
    canvas.rounded_rect(x, y, w, h, radius, _RING)
    canvas.rounded_rect(x + 1, y + 1, w - 2, h - 2, max(0, radius - 1), fill)


def _draw_brand_mark(canvas: _Canvas, x: int, y: int, side: int, radius: int) -> None:
    """The HTML header's ``.brand .mark`` — its 135° clay→violet gradient
    rendered as the two-tone raster: team-0 above the counter-diagonal,
    team-1 below (always palette slots 0 and 1, exactly as the CSS hardcodes
    ``var(--team-0), var(--team-1)``)."""
    canvas.rounded_rect(x, y, side, side, radius, _TEAM0)
    lower = _TEAM0 + 1
    for iy in range(side):
        row = (y + iy) * canvas.width
        for ix in range(side):
            if ix + iy >= side and canvas.buf[row + x + ix] == _TEAM0:
                canvas.buf[row + x + ix] = lower


def _draw_header(
    canvas: _Canvas,
    layout: _Layout,
    data: Mapping[str, Any],
    frame: Mapping[str, Any],
    team_index: dict,
) -> None:
    """The header inside the board card — the raster arrangement of the HTML
    play view's identifying chrome. Row 1: the brand mark and title with the
    turn readout right-aligned (the HTML's ``turn N / limit``). Row 2: one
    live-score pill chip per team (swatch · name · RES/MSN numerals in fixed
    columns) with the match id · scenario line right-aligned. Buttons, slider,
    and tabs are interactive-only HTML chrome and are deliberately not faked."""
    cm, cols = layout.cm, layout.cols
    cx0, _, cw, _ = layout.card
    left = cx0 + 1 + cm.pad
    right = cx0 + cw - 1 - cm.pad
    small_h = _text_height(cm.small_scale)

    y = layout.row1_y
    _draw_brand_mark(canvas, left, y + (layout.row1_h - cm.mark) // 2, cm.mark, cm.mark_radius)
    canvas.text(
        left + cm.mark + cm.brand_gap,
        y + (layout.row1_h - _text_height(cm.title_scale)) // 2,
        "LEAGUE OF AGENTS",
        _INK,
        cm.title_scale,
    )
    counter = f"TURN {frame['turn']}/{data['turn_limit']}"
    canvas.text(
        right - _text_width(counter, cm.small_scale),
        y + (layout.row1_h - small_h) // 2,
        counter,
        _INK2,
        cm.small_scale,
    )

    y = layout.row2_y
    text_y = y + (layout.row2_h - small_h) // 2
    resources = {t["id"]: t["resources"] for t in frame["teams"]}
    x = left
    for t, chip_w in zip(data["teams"], cols.chip_ws):
        _draw_surface_card(canvas, x, y, chip_w, layout.row2_h, layout.row2_h // 2, _CHIP)
        ix = x + 1 + cm.chip_pad_x
        sy = y + (layout.row2_h - cm.swatch) // 2
        canvas.rounded_rect(
            ix, sy, cm.swatch, cm.swatch, cm.swatch_radius, _team_color(team_index[t["id"]])
        )
        ix += cm.swatch + cm.head_gap
        canvas.text(ix, text_y, t["name"], _INK, cm.small_scale)
        ix += _text_width(t["name"], cm.small_scale) + cm.stats_gap
        canvas.text(ix, text_y, "RES", _MUTED, cm.small_scale)
        ix += _text_width("RES", cm.small_scale) + cm.num_gap
        val = str(resources.get(t["id"], 0))
        canvas.text(
            ix + cols.res_w - _text_width(val, cm.small_scale), text_y, val, _INK, cm.small_scale
        )
        ix += cols.res_w + cm.stats_gap
        canvas.text(ix, text_y, "MSN", _MUTED, cm.small_scale)
        ix += _text_width("MSN", cm.small_scale) + cm.num_gap
        done = str(sum(1 for m in frame["missions"] if t["id"] in m["completed_by"]))
        canvas.text(
            ix + cols.msn_w - _text_width(done, cm.small_scale), text_y, done, _INK, cm.small_scale
        )
        x += chip_w + cm.chip_gap
    line = _match_line(data)
    canvas.text(right - _text_width(line, cm.small_scale), text_y, line, _MUTED, cm.small_scale)


def _draw_board_chrome(
    canvas: _Canvas,
    layout: _Layout,
    data: Mapping[str, Any],
    frame: Mapping[str, Any],
    team_index: dict,
    cell_px: int,
) -> None:
    """Everything on a play frame except the units — the HTML board card
    itself: the rounded card surface on the page matte, the header rows inside
    it, and the board frame with its hairline grid and furniture. Turn frames
    and tween frames share this exactly, so their chrome can never drift
    apart."""
    cx0, cy0, cw, ch = layout.card
    _draw_surface_card(canvas, cx0, cy0, cw, ch, layout.cm.radius, _SURFACE)
    _draw_header(canvas, layout, data, frame, team_index)
    fx, fy, fw, fh = layout.frame
    # The board plane: html.py's board-top→board-bot gradient rendered flat at
    # its midpoint — THEMES' plane token is that midpoint by design.
    _draw_surface_card(canvas, fx, fy, fw, fh, layout.cm.frame_radius, _BG)
    grid_w, grid_h = data["grid"]["width"], data["grid"]["height"]
    _draw_grid(canvas, layout.board_x, layout.board_y, grid_w, grid_h, cell_px)
    _draw_resource_nodes(canvas, layout.board_x, layout.board_y, cell_px, frame["resource_nodes"])
    _draw_missions(canvas, layout.board_x, layout.board_y, cell_px, frame["missions"], team_index)
    _draw_control_points(
        canvas, layout.board_x, layout.board_y, cell_px, frame["control_points"], team_index
    )


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
    """An in-between frame: the card chrome (header, board frame, grid, nodes,
    missions, control points) is the *starting* turn's discrete state; only the
    units move, linearly interpolated toward the next turn. So resource counts,
    captures and the turn readout land crisply on turn frames while movement
    flows continuously between them."""
    _draw_board_chrome(canvas, layout, data, frame_a, team_index, cell_px)
    pa = _unit_positions(frame_a["units"], layout.board_x, layout.board_y, cell_px)
    pb = _unit_positions(frame_b["units"], layout.board_x, layout.board_y, cell_px)
    _paint_units(canvas, _tween_positions(pa, pb, frac), team_index, cell_px)


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
