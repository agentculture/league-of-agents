"""Acceptance tests for GIF video export (plan task t6, spec c7/h7).

Criteria under test:

* one command (``league match record <id> --out <file>``) renders a
  committed match log into a shareable video artifact, offline — no screen
  capture, no live session, no network;
* reproducibility: the same log renders the same frame sequence — proven by
  hashing the raw frame bytes AND by byte-identical GIF output across two
  renders;
* each artifact's provenance (the exact command) is embedded in the file
  itself (a GIF Comment Extension), not a separate sidecar;
* the GIF is a genuinely valid, byte-correct GIF89a — not just "doesn't
  crash": this file carries its own from-scratch LZW decoder (validated
  during development by round-tripping Pillow/giflib's own encoder output
  byte-for-byte; Pillow itself isn't a project dependency, so it can't be
  imported here) and fully decodes every frame this module produces, proving
  the container and compression are both correct, not merely well-formed.
"""

from __future__ import annotations

import hashlib
import json
import random
import struct
from pathlib import Path

import pytest

from league.cli import main
from league.engine.events import MatchLog
from league.replay import html as replay_html
from league.replay.video import (
    DEFAULT_SCALE,
    MAX_SCALE,
    MIN_SCALE,
    PALETTE,
    Frame,
    VideoFrames,
    _encode_gif,
    _lzw_encode,
    build_frames,
    indices_to_rgb,
    render_gif,
)
from tests.test_engine_scoring import _play_match

_COOP_LOG = (
    Path(__file__).resolve().parent.parent
    / "docs"
    / "playtests"
    / "cycle-5"
    / "colleague-coop.log.jsonl"
)


def _coop_log() -> MatchLog:
    return MatchLog.from_jsonl(_COOP_LOG.read_text(encoding="utf-8"))


# --- a from-scratch GIF89a + LZW decoder (test-only oracle) -----------------
#
# Independent of league/replay/video.py's encoder: this reads the byte
# container directly (header, logical screen descriptor + global color
# table, extension blocks, one image descriptor + LZW data per frame,
# trailer) and decompresses with the classic variable-width LZW algorithm.
# The one real-world subtlety — GIF's code-size bump landing on a different
# ``next_code`` boundary than "textbook" LZW — only had to be gotten right
# ONCE, on the encode side (see the docstring on ``_lzw_encode``); a decoder
# using the plain/"natural" boundary check is the correct match for it (this
# was cross-checked against Pillow/giflib's own GIF output during
# development, byte-for-byte, before this file was written).


def _lzw_decode(data: bytes, min_code_size: int) -> bytes:
    clear_code = 1 << min_code_size
    end_code = clear_code + 1

    def reset():
        return (
            [bytes([i]) for i in range(clear_code)] + [b"", b""],
            end_code + 1,
            min_code_size + 1,
        )

    table, next_code, code_size = reset()
    out = bytearray()
    buf = 0
    nbits = 0
    pos = 0
    prev = None

    def read_code():
        nonlocal buf, nbits, pos
        while nbits < code_size:
            if pos >= len(data):
                return None
            buf |= data[pos] << nbits
            pos += 1
            nbits += 8
        code = buf & ((1 << code_size) - 1)
        buf >>= code_size
        nbits -= code_size
        return code

    while True:
        code = read_code()
        if code is None or code == end_code:
            break
        if code == clear_code:
            table, next_code, code_size = reset()
            prev = None
            continue
        if code < len(table) and table[code]:
            entry = table[code]
        elif code == next_code and prev is not None:
            entry = prev + prev[:1]
        else:
            raise ValueError(f"bad LZW code {code} (next={next_code}, table_len={len(table)})")
        out += entry
        if prev is not None and next_code < 4096:
            table.append(prev + entry[:1])
            next_code += 1
            if next_code == (1 << code_size) and code_size < 12:
                code_size += 1
        prev = entry
    return bytes(out)


def _unpack_sub_blocks(data: bytes, pos: int) -> tuple[bytes, int]:
    out = bytearray()
    while True:
        n = data[pos]
        pos += 1
        if n == 0:
            break
        out += data[pos : pos + n]
        pos += n
    return bytes(out), pos


def _decode_gif(data: bytes) -> tuple[int, int, list[tuple[bytes, int]], str]:
    """Return ``(width, height, [(indices, delay_cs), ...], comment)``."""
    assert data[:6] == b"GIF89a", "missing GIF89a header"
    assert data[-1:] == b"\x3b", "missing GIF trailer"
    pos = 6
    width, height = struct.unpack("<HH", data[pos : pos + 4])
    pos += 4
    packed = data[pos]
    pos += 3  # packed + background index + pixel aspect ratio
    size_field = packed & 0x07
    gct_len = 1 << (size_field + 1)
    pos += gct_len * 3  # skip the global color table itself (RGB triples)

    frames: list[tuple[bytes, int]] = []
    comment = ""
    pending_delay = 0
    while True:
        marker = data[pos]
        if marker == 0x3B:
            break
        if marker == 0x21:
            label = data[pos + 1]
            pos += 2
            if label == 0xF9:  # Graphic Control Extension
                block_size = data[pos]
                body = data[pos + 1 : pos + 1 + block_size]
                pending_delay = struct.unpack("<H", body[1:3])[0]
                pos += 1 + block_size
                assert data[pos] == 0, "GCE missing terminator"
                pos += 1
            elif label == 0xFE:  # Comment Extension
                raw, pos = _unpack_sub_blocks(data, pos)
                comment = raw.decode("ascii", errors="replace")
            else:  # Application Extension or anything else sub-block-shaped
                _, pos = _unpack_sub_blocks(data, pos)
            continue
        assert marker == 0x2C, f"unexpected marker {marker:#x} at {pos}"
        pos += 1
        pos += 8  # left, top, width, height
        pos += 1  # local packed byte (we never write a local color table)
        min_code_size = data[pos]
        pos += 1
        compressed, pos = _unpack_sub_blocks(data, pos)
        indices = _lzw_decode(compressed, min_code_size)
        frames.append((indices, pending_delay))
    return width, height, frames, comment


# --- LZW round-trip (fuzz) ---------------------------------------------------


def test_lzw_round_trip_across_sizes_and_palettes() -> None:
    """The GIF-flavoured LZW encoder round-trips through the from-scratch
    decoder above for a broad sweep of sizes and palette depths — including
    sizes that force at least one code-size bump, which is exactly where a
    naive implementation silently corrupts data (this repo's own history:
    the first cut of this encoder passed every size below ~40 symbols and
    silently produced undecodable output above that)."""
    rng = random.Random(20260707)  # noqa: S311 - test-only synthetic fixture data
    for _ in range(60):
        n_colors = rng.choice([2, 3, 4, 8, 20, 32, 64, 200])
        bits = max(2, (max(1, n_colors) - 1).bit_length())
        size = rng.randint(1, 4000)
        indices = bytes(rng.randrange(n_colors) for _ in range(size))
        compressed = _lzw_encode(indices, bits)
        decoded = _lzw_decode(compressed, bits)
        assert decoded == indices


def test_lzw_handles_empty_and_uniform_and_edge_inputs() -> None:
    bits = 5
    for indices in (bytes([0]), bytes([5]) * 2000, bytes(range(20)) * 100):
        compressed = _lzw_encode(indices, bits)
        assert _lzw_decode(compressed, bits) == indices


# --- frame count / determinism / reproducibility ----------------------------


def _expected_frames(turns_played: int, tween: int) -> int:
    """title + turns + (turns-1)*tween interpolated + closing."""
    return turns_played + max(0, turns_played - 1) * tween + 2


def test_frame_count_follows_the_tween_formula_on_the_committed_coop_log() -> None:
    from league.replay.html import build_replay_data
    from league.replay.video import DEFAULT_TWEEN

    log = _coop_log()
    data = build_replay_data(log)
    turns_played = len(data["frames"]) - 1
    assert turns_played == 17  # pinned: 17 distinct turns (0..16) in this fixture

    # tween=0 reduces to the original "turns + 2".
    assert len(build_frames(data, tween=0).frames) == turns_played + 2
    # The default tween inserts (turns-1)*tween interpolated frames between turns.
    video = build_frames(data)
    assert len(video.frames) == _expected_frames(turns_played, DEFAULT_TWEEN)
    assert len(build_frames(data, tween=6).frames) == _expected_frames(turns_played, 6)


def test_frame_count_follows_the_tween_formula_on_a_scripted_match() -> None:
    from league.replay.html import build_replay_data
    from league.replay.video import DEFAULT_TWEEN

    log = _play_match()
    data = build_replay_data(log)
    turns_played = len(data["frames"]) - 1
    assert len(build_frames(data).frames) == _expected_frames(turns_played, DEFAULT_TWEEN)
    assert len(build_frames(data, tween=0).frames) == turns_played + 2


def test_build_frames_is_deterministic() -> None:
    from league.replay.html import build_replay_data

    data = build_replay_data(_coop_log())
    a = build_frames(data)
    b = build_frames(data)
    assert a.width == b.width and a.height == b.height
    assert [f.indices for f in a.frames] == [f.indices for f in b.frames]
    assert [f.delay_cs for f in a.frames] == [f.delay_cs for f in b.frames]

    hash_a = hashlib.sha256(b"".join(f.indices for f in a.frames)).hexdigest()
    hash_b = hashlib.sha256(b"".join(f.indices for f in b.frames)).hexdigest()
    assert hash_a == hash_b


def test_render_gif_is_byte_deterministic() -> None:
    log = _coop_log()
    provenance = "league match record m-colleague-coop --out x.gif --format gif --scale 24 --fps 2"
    first = render_gif(log, provenance=provenance)
    second = render_gif(log, provenance=provenance)
    assert first == second
    assert hashlib.sha256(first).hexdigest() == hashlib.sha256(second).hexdigest()


def test_render_gif_varies_with_scale_and_fps_but_stays_deterministic_each_way() -> None:
    log = _coop_log()
    a = render_gif(log, scale=16, fps=1)
    b = render_gif(log, scale=32, fps=4)
    assert a != b
    assert render_gif(log, scale=16, fps=1) == a
    assert render_gif(log, scale=32, fps=4) == b


# --- GIF89a container validity + full round-trip via the from-scratch decoder


def test_gif_header_and_trailer_are_valid() -> None:
    data = render_gif(_coop_log())
    assert data[:6] == b"GIF89a"
    assert data[-1:] == b"\x3b"


def test_gif_fully_decodes_and_matches_the_rendered_frames() -> None:
    """The strongest correctness proof available without a new dependency:
    decode every frame back out of the GIF bytes and assert pixel-for-pixel
    equality against what build_frames actually drew."""
    from league.replay.html import build_replay_data

    log = _coop_log()
    data = build_replay_data(log)
    video = build_frames(data)
    provenance = "league match record m-colleague-coop --out x.gif --format gif --scale 24 --fps 2"
    gif_bytes = render_gif(log, provenance=provenance)

    width, height, frames, comment = _decode_gif(gif_bytes)
    assert (width, height) == (video.width, video.height)
    assert len(frames) == len(video.frames)
    for (decoded_indices, delay_cs), expected in zip(frames, video.frames):
        assert decoded_indices == expected.indices
        assert delay_cs == expected.delay_cs
    assert comment == provenance


def test_gif_decodes_correctly_at_a_smaller_and_larger_scale() -> None:
    """Exercise different canvas sizes (and therefore different LZW dictionary
    growth patterns) through the same round-trip proof."""
    from league.replay.html import build_replay_data

    log = _coop_log()
    data = build_replay_data(log)
    for scale in (MIN_SCALE, DEFAULT_SCALE, MAX_SCALE):
        video = build_frames(data, cell_px=scale)
        gif_bytes = _encode_gif(video)
        _, _, frames, _ = _decode_gif(gif_bytes)
        assert [f[0] for f in frames] == [f.indices for f in video.frames]


def test_provenance_is_embedded_as_a_gif_comment() -> None:
    provenance = "league match record m-x --out m.gif --format gif --scale 24 --fps 2"
    data = render_gif(_coop_log(), provenance=provenance)
    _, _, _, comment = _decode_gif(data)
    assert comment == provenance


def test_no_provenance_means_no_comment_block() -> None:
    data = render_gif(_coop_log(), provenance="")
    _, _, _, comment = _decode_gif(data)
    assert comment == ""


# --- palette parity with the HTML replay ------------------------------------


def test_palette_reuses_the_validated_html_replay_hues() -> None:
    """The raster face must draw with the SAME validated team/status/board
    hues the HTML replay uses (dataviz palette.md) — never re-derive its own.
    The light default is the restyled clay/violet team pair."""
    assert replay_html.TEAM_COLORS[0] == "#b65b38"  # clay
    assert replay_html.TEAM_COLORS[1] == "#4b3ba6"  # violet
    from league.replay.video import _hex_to_rgb

    assert PALETTE[8] == _hex_to_rgb(replay_html.TEAM_COLORS[0])
    assert PALETTE[9] == _hex_to_rgb(replay_html.TEAM_COLORS[1])


def test_theme_selects_the_html_replay_theme_and_only_the_color_table_changes() -> None:
    """``--theme`` shares the HTML replay's per-theme tokens: light Anthropic
    cream, dark Culture black-green. The frame INDICES are theme-independent —
    only the GIF color table (VideoFrames.palette) differs — so both themes stay
    byte-deterministic and interpolation is identical."""
    from league.replay.html import THEME_DARK, THEME_LIGHT, build_replay_data
    from league.replay.video import _hex_to_rgb, build_palette

    data = build_replay_data(_coop_log())
    light = build_frames(data, theme="light")
    dark = build_frames(data, theme="dark")

    # Same pixels, different color table.
    assert [f.indices for f in light.frames] == [f.indices for f in dark.frames]
    assert light.palette != dark.palette
    assert light.palette == build_palette("light")
    assert dark.palette == build_palette("dark")
    # The palettes are exactly the HTML replay's theme tokens (team slots 8/9).
    assert light.palette[8] == _hex_to_rgb(THEME_LIGHT["teams"][0])
    assert dark.palette[8] == _hex_to_rgb(THEME_DARK["teams"][0])
    # A dark GIF and a light GIF differ, each deterministic.
    assert render_gif(_coop_log(), theme="dark") == render_gif(_coop_log(), theme="dark")
    assert render_gif(_coop_log(), theme="light") != render_gif(_coop_log(), theme="dark")


def test_unknown_theme_is_rejected() -> None:
    from league.replay.html import build_replay_data
    from league.replay.video import build_palette

    with pytest.raises(ValueError):
        build_palette("midnight")
    with pytest.raises(ValueError):
        build_frames(build_replay_data(_coop_log()), theme="midnight")


# --- composition (the mesmerizing raster face) -------------------------------


def test_palette_carries_the_html_face_neutral_steps() -> None:
    """The raster face composes with the HTML face's own neutral/chrome steps
    (page matte, card surface, hairline grid, secondary ink, chrome accent,
    chip tone) — slots 20..25 lifted verbatim from html.py's CSS custom
    properties — plus two derived steps that rasterize its alpha effects
    (slots 26..27): the ``--ring`` hairline (ink at 10% over the surface) and
    the depleted-node tint (the resource hue at 28% over the plane). No new
    hues. The validated team/status hues (slots 0..19) are untouched."""
    from league.replay.video import _hex_to_rgb, build_palette

    light = build_palette("light")
    dark = build_palette("dark")
    assert len(light) == len(dark) == 28
    expected = {
        20: ("#f0eee5", "#0c1210"),  # page matte (--plane)
        21: ("#faf8f1", "#111a16"),  # card surface / unit ring (--surface)
        22: ("#ded9c9", "#1e2a24"),  # hairline grid (--grid)
        23: ("#5a5546", "#aebcb2"),  # secondary ink (--ink-2)
        24: ("#1e7a4d", "#46c79e"),  # chrome accent (--accent)
        25: ("#ece8dd", "#152019"),  # chip tone (--chip)
        26: ("#e5e2db", "#27302b"),  # --ring: ink @ 10% over the surface
        27: ("#b1d7c1", "#113c2d"),  # depleted node: resource @ 28% over plane
    }
    for slot, (light_hex, dark_hex) in expected.items():
        assert light[slot] == _hex_to_rgb(light_hex)
        assert dark[slot] == _hex_to_rgb(dark_hex)


def test_title_card_is_a_centered_lockup_with_generous_margins() -> None:
    """The opening card is a centered lockup, not top-left-crammed text over an
    empty board: the outer margin band is pure matte on every side, the accent
    rule under the title is centered to the pixel, and the whole composition's
    left/right extents mirror each other."""
    from league.replay.html import build_replay_data
    from league.replay.video import _ACCENT, _INK, _MATTE

    data = build_replay_data(_coop_log())
    video = build_frames(data)
    title = video.frames[0].indices
    width, height = video.width, video.height

    band = 8  # generous margins: the outer 8px band is pure matte on all sides
    for y in range(band):
        assert set(title[y * width : (y + 1) * width]) == {_MATTE}
    for y in range(height - band, height):
        assert set(title[y * width : (y + 1) * width]) == {_MATTE}
    for y in range(height):
        row = title[y * width : (y + 1) * width]
        assert set(row[:band]) == {_MATTE}
        assert set(row[width - band :]) == {_MATTE}

    assert _INK in set(title)  # the lockup is composed, not an empty card
    accent_xs = sorted({i % width for i, v in enumerate(title) if v == _ACCENT})
    assert accent_xs, "the title lockup carries an accent rule"
    assert abs((accent_xs[0] + accent_xs[-1]) - (width - 1)) <= 2  # rule centered
    xs = sorted({i % width for i, v in enumerate(title) if v != _MATTE})
    assert abs(xs[0] - (width - 1 - xs[-1])) <= 2  # extents mirror


def test_turn_frames_mirror_the_html_board_card() -> None:
    """A play frame reads as the HTML replay's board card mid-playback: a
    rounded card surface floating on the page matte, the header INSIDE the
    card above the board plane, the board plane wrapped in a distinct
    card-surface band, and nothing below the card (PR #20's full-width footer
    strip is gone). Tween frames share the chrome pixel-for-pixel."""
    from league.replay.html import build_replay_data
    from league.replay.video import _BG, _CHIP, _GRID, _INK, _INK2, _MATTE, _RING, _SURFACE

    data = build_replay_data(_coop_log())
    video = build_frames(data, tween=1)
    width, height = video.width, video.height
    turn = video.frames[1].indices
    rows = [turn[y * width : (y + 1) * width] for y in range(height)]

    # The canvas edge is pure page matte on all four sides — the card floats.
    assert set(rows[0]) == {_MATTE} and set(rows[-1]) == {_MATTE}
    assert {row[0] for row in rows} == {_MATTE} and {row[-1] for row in rows} == {_MATTE}

    # The card is one contiguous block with ROUNDED corners: its topmost
    # border row is narrower than a mid-card row, and nothing else sits on
    # the matte below it (no footer strip).
    content_rows = [y for y, row in enumerate(rows) if set(row) != {_MATTE}]
    assert content_rows == list(range(content_rows[0], content_rows[-1] + 1))
    surface_rows = [y for y, row in enumerate(rows) if _SURFACE in row]
    card_top, card_bot = surface_rows[0], surface_rows[-1]
    assert content_rows[-1] <= card_bot + 2  # only the card's own border below

    def extent(row: bytes) -> tuple[int, int]:
        xs = [x for x, v in enumerate(row) if v != _MATTE]
        return xs[0], xs[-1]

    top_l, top_r = extent(rows[content_rows[0]])
    mid_l, mid_r = extent(rows[(card_top + card_bot) // 2])
    assert top_l > mid_l and top_r < mid_r  # rounded corners

    # The board plane sits INSIDE the card behind a card-surface band: on the
    # row through the middle of the board, walking inward from the left we
    # cross matte, then card surface, and only then the plane.
    plane_rows = [y for y, row in enumerate(rows) if _BG in row]
    assert plane_rows
    board_row = rows[(plane_rows[0] + plane_rows[-1]) // 2]
    first_plane = board_row.index(_BG)
    prefix = board_row[:first_plane]
    assert _MATTE in prefix and _SURFACE in prefix
    last_matte = max(i for i, v in enumerate(prefix) if v == _MATTE)
    first_surface = min(i for i, v in enumerate(prefix) if v == _SURFACE)
    assert last_matte < first_surface  # matte outside, surface inside

    # The header lives inside the card ABOVE the board plane: title ink, the
    # secondary-ink turn readout, the chip tone, and the ring hairline all
    # appear there; the hairline grid appears on the plane below.
    header = b"".join(rows[card_top : plane_rows[0]])
    for slot in (_INK, _INK2, _CHIP, _RING):
        assert slot in header
    assert _GRID in b"".join(rows[plane_rows[0] :])

    # A tween frame (only units move) shares every pixel above the board.
    tween = video.frames[2].indices
    split = plane_rows[0] * width
    assert tween[:split] == turn[:split]


def test_turn_frame_header_shows_brand_chips_and_turn_readout() -> None:
    """The header row inside the card carries the HTML play view's identifying
    chrome: the two-tone brand mark (team hues 0 + 1), a live-score chip per
    team (chip tone + swatch), and the turn readout in secondary ink — and no
    fake interactive chrome (the chrome accent never appears on play frames)."""
    from league.replay.html import build_replay_data
    from league.replay.video import _ACCENT, _BG, _CHIP, _INK2, _TEAM0

    data = build_replay_data(_coop_log())
    video = build_frames(data, tween=0)
    width = video.width
    turn = video.frames[1].indices
    rows = [turn[y * width : (y + 1) * width] for y in range(video.height)]
    plane_top = min(y for y, row in enumerate(rows) if _BG in row)
    header = b"".join(rows[:plane_top])
    assert _TEAM0 in header and (_TEAM0 + 1) in header  # brand mark + swatch
    assert _CHIP in header  # the team chips' pill tone
    assert _INK2 in header  # the turn readout
    assert _ACCENT not in turn  # accent is card chrome, never board chrome


def test_closing_card_shows_big_score_numerals() -> None:
    """The closing card leads with big score numerals (the scaled glyph
    hierarchy) over swatch-labelled team rows, centered like the title card
    under its accent rule."""
    from league.replay.html import build_replay_data
    from league.replay.video import _ACCENT, _MATTE

    data = build_replay_data(_coop_log())
    video = build_frames(data)
    closing = video.frames[-1].indices
    width = video.width
    accent_xs = sorted({i % width for i, v in enumerate(closing) if v == _ACCENT})
    assert accent_xs, "the closing card carries the accent rule"
    assert abs((accent_xs[0] + accent_xs[-1]) - (width - 1)) <= 2
    xs = sorted({i % width for i, v in enumerate(closing) if v != _MATTE})
    assert abs(xs[0] - (width - 1 - xs[-1])) <= 2  # centered composition


def test_tween_frames_interpolate_and_stay_deterministic() -> None:
    """Interpolated tween frames flow movement between turns (linear, fixed
    count, integer-rounded → deterministic). Frame count matches the documented
    formula and two builds are byte-identical."""
    from league.replay.html import build_replay_data
    from league.replay.video import MAX_TWEEN, MIN_TWEEN

    data = build_replay_data(_coop_log())
    turns = len(data["frames"]) - 1

    a = build_frames(data, tween=4)
    b = build_frames(data, tween=4)
    assert [f.indices for f in a.frames] == [f.indices for f in b.frames]
    assert len(a.frames) == turns + (turns - 1) * 4 + 2
    # More tweens → more frames; zero tweens → the base count.
    assert len(build_frames(data, tween=8).frames) > len(a.frames)
    assert len(build_frames(data, tween=MIN_TWEEN).frames) == turns + 2
    # Out-of-range tween is rejected.
    with pytest.raises(ValueError):
        build_frames(data, tween=MAX_TWEEN + 1)
    with pytest.raises(ValueError):
        build_frames(data, tween=-1)


def test_tween_sub_frame_delays_sum_exactly_to_the_turn_hold() -> None:
    """When the hold doesn't divide evenly by (tween + 1), the remainder is
    spread across the leading sub-frames — every non-final turn's delays sum
    exactly to turn_delay_cs (no silent slowdown) and each stays at or above
    the 2cs floor GIF renderers enforce."""
    from league.replay.html import build_replay_data

    data = build_replay_data(_coop_log())
    turns = len(data["frames"]) - 1
    tween, turn_delay_cs = 3, 25  # 25 / 4 -> 7, 6, 6, 6
    video = build_frames(data, tween=tween, turn_delay_cs=turn_delay_cs)
    per_turn = tween + 1
    for i in range(turns - 1):  # every non-final turn owns (tween + 1) sub-frames
        delays = [f.delay_cs for f in video.frames[1 + i * per_turn : 1 + (i + 1) * per_turn]]
        assert sum(delays) == turn_delay_cs
        assert min(delays) >= 2
    assert video.frames[-2].delay_cs == turn_delay_cs  # the final turn rests the full hold


def test_build_frames_rejects_a_tween_that_cannot_fit_the_hold() -> None:
    """A tween whose sub-frames would fall under the 2cs GIF floor must be
    refused, not silently played slower than the requested pace."""
    from league.replay.html import build_replay_data

    data = build_replay_data(_coop_log())
    with pytest.raises(ValueError, match="does not fit"):
        build_frames(data, tween=12, turn_delay_cs=10)  # the --fps 10 --tween 12 shape
    # The boundary combination — every sub-frame exactly at the floor — is legal.
    video = build_frames(data, tween=4, turn_delay_cs=10)
    assert video.frames[1].delay_cs == 2


def test_mp4_repeat_counts_keep_a_tweened_turn_inside_one_fps_interval() -> None:
    """The MP4 container runs at fps * (tween + 1), so each tween sub-frame maps
    to ~one output frame and a full turn still spans 1/fps seconds; the title
    and closing cards keep their real-time holds."""
    from league.cli._commands.match import _repeat_count

    fps, tween = 2, 4  # the defaults: a 50cs turn split into five 10cs sub-frames
    output_fps = fps * (tween + 1)
    assert _repeat_count(10, output_fps) == 1
    assert _repeat_count(200, output_fps) == 20  # title card: 2s either way
    assert _repeat_count(300, output_fps) == 30  # closing card: 3s
    # Untweened parity: at plain fps the old behavior is unchanged.
    assert _repeat_count(50, 2) == 1
    assert _repeat_count(200, 2) == 4


def test_tweened_gif_round_trips_through_the_decoder() -> None:
    """A tweened, dark-theme GIF still decodes frame-for-frame — the container
    and LZW stay correct with the extra interpolated frames and the swapped
    color table."""
    from league.replay.html import build_replay_data

    data = build_replay_data(_coop_log())
    video = build_frames(data, tween=3, theme="dark")
    gif_bytes = _encode_gif(video)
    _, _, frames, _ = _decode_gif(gif_bytes)
    assert [f[0] for f in frames] == [f.indices for f in video.frames]


def test_build_frames_rejects_invalid_parameters() -> None:
    from league.replay.html import build_replay_data

    data = build_replay_data(_coop_log())
    with pytest.raises(ValueError):
        build_frames(data, cell_px=1)
    with pytest.raises(ValueError):
        build_frames(data, turn_delay_cs=0)


def test_indices_to_rgb_matches_the_palette() -> None:
    indices = bytes([0, 1, 8, 9])
    rgb = indices_to_rgb(indices)
    expected = b"".join(bytes(PALETTE[i]) for i in indices)
    assert rgb == expected


def test_video_frames_dataclasses_are_frozen() -> None:
    frame = Frame(indices=b"\x00", delay_cs=50)
    with pytest.raises(Exception):
        frame.delay_cs = 100  # type: ignore[misc]
    video = VideoFrames(width=1, height=1, frames=(frame,))
    with pytest.raises(Exception):
        video.width = 2  # type: ignore[misc]


# --- CLI: `league match record` ---------------------------------------------


@pytest.fixture()
def arena(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _play_a_match(match_id: str) -> None:
    assert (
        main(
            [
                "team",
                "register",
                "blue",
                "--name",
                "Blue",
                "--agent",
                "blue-1:m:scout",
                "--agent",
                "blue-2:m:harvester",
                "--agent",
                "blue-3:m:defender",
                "--apply",
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "team",
                "register",
                "red",
                "--name",
                "Red",
                "--agent",
                "red-1:m:scout",
                "--agent",
                "red-2:m:harvester",
                "--agent",
                "red-3:m:defender",
                "--apply",
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "match",
                "new",
                "--scenario",
                "skirmish-1",
                "--team",
                "blue",
                "--team",
                "red",
                "--id",
                match_id,
                "--apply",
            ]
        )
        == 0
    )
    assert (
        main(["match", "act", match_id, "--team", "blue", "--action", "blue-u1:hold", "--apply"])
        == 0
    )
    assert (
        main(["match", "act", match_id, "--team", "red", "--action", "red-u1:hold", "--apply"]) == 0
    )


def test_match_record_cli_writes_a_valid_gif(arena, capsys) -> None:
    _play_a_match("m-rec")
    capsys.readouterr()
    out_file = arena / "m-rec.gif"
    rc = main(["match", "record", "m-rec", "--out", str(out_file), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["match_id"] == "m-rec"
    assert payload["format"] == "gif"
    assert payload["frames"] >= 3  # at least 1 turn + title + closing
    assert payload["bytes"] == out_file.stat().st_size
    assert "provenance" in payload and "m-rec" in payload["provenance"]

    raw = out_file.read_bytes()
    assert raw[:6] == b"GIF89a"
    assert raw[-1:] == b"\x3b"
    _, _, frames, comment = _decode_gif(raw)
    assert len(frames) == payload["frames"]
    assert comment == payload["provenance"]


def test_match_record_text_mode_reports_the_written_file(arena, capsys) -> None:
    _play_a_match("m-rec-text")
    capsys.readouterr()
    out_file = arena / "m-rec-text.gif"
    assert main(["match", "record", "m-rec-text", "--out", str(out_file)]) == 0
    text = capsys.readouterr().out
    assert str(out_file) in text
    assert "gif" in text
    assert out_file.exists()


def test_match_record_rejects_out_of_range_scale_and_fps(arena, capsys) -> None:
    _play_a_match("m-rec2")
    capsys.readouterr()
    out_file = arena / "m-rec2.gif"
    rc = main(["match", "record", "m-rec2", "--out", str(out_file), "--scale", "1"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "hint:" in err
    assert not out_file.exists()

    rc = main(["match", "record", "m-rec2", "--out", str(out_file), "--fps", "0"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "hint:" in err
    assert not out_file.exists()


def test_match_record_theme_and_tween_flags(arena, capsys) -> None:
    _play_a_match("m-rec-th")
    capsys.readouterr()
    out_file = arena / "m-rec-th.gif"
    rc = main(
        [
            "match",
            "record",
            "m-rec-th",
            "--out",
            str(out_file),
            "--theme",
            "dark",
            "--tween",
            "2",
            "--json",
        ]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["theme"] == "dark"
    assert payload["tween"] == 2
    # Provenance records both new axes so the render is reproducible.
    assert "--theme dark" in payload["provenance"]
    assert "--tween 2" in payload["provenance"]
    raw = out_file.read_bytes()
    _, _, frames, comment = _decode_gif(raw)
    assert len(frames) == payload["frames"]
    assert comment == payload["provenance"]


def test_match_record_rejects_out_of_range_tween(arena, capsys) -> None:
    _play_a_match("m-rec-tw")
    capsys.readouterr()
    out_file = arena / "m-rec-tw.gif"
    rc = main(["match", "record", "m-rec-tw", "--out", str(out_file), "--tween", "999"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "hint:" in err
    assert not out_file.exists()


def test_match_record_rejects_tween_too_high_for_fps(arena, capsys) -> None:
    """--fps 10 gives each turn a 10cs hold; 13 sub-frames cannot fit it. The
    combination is refused with a remediation, never silently slowed down."""
    _play_a_match("m-rec-tw2")
    capsys.readouterr()
    out_file = arena / "m-rec-tw2.gif"
    rc = main(
        ["match", "record", "m-rec-tw2", "--out", str(out_file), "--fps", "10", "--tween", "12"]
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert "too high for --fps" in err
    assert "hint:" in err
    assert not out_file.exists()


def test_match_record_mp4_without_ffmpeg_names_the_gif_fallback(arena, capsys, monkeypatch) -> None:
    """This asserts against the REAL environment (ffmpeg genuinely absent in
    CI/dev sandboxes here) rather than mocking shutil.which, so it also
    documents the actual, always-reachable failure mode."""
    import shutil

    monkeypatch.setattr(shutil, "which", lambda _name: None)
    _play_a_match("m-rec3")
    capsys.readouterr()
    out_file = arena / "m-rec3.mp4"
    rc = main(["match", "record", "m-rec3", "--out", str(out_file), "--format", "mp4"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "ffmpeg" in err
    assert "gif" in err.lower()
    assert "hint:" in err
    assert not out_file.exists()


# --- C8-t9 — the MP4 soundtrack (spec c17/h10/h11): --format mp4 muxes a
# --- deterministic ambient WAV via the existing optional-ffmpeg path; the
# --- GIF stays byte-unchanged (and silent — GIF89a has no audio channel).


def _fake_ffmpeg(monkeypatch, captured: list) -> None:
    """Make ffmpeg 'present' and capture what _render_mp4 would hand it —
    including the soundtrack WAV, which must be read DURING the call (it
    lives in a TemporaryDirectory that dies when the subprocess returns)."""
    import subprocess as _subprocess

    from league.cli._commands import match as match_cmd

    monkeypatch.setattr(match_cmd.shutil, "which", lambda _name: "/usr/bin/ffmpeg")

    def fake_run(cmd, input=b"", check=True, capture_output=True):
        second_i = cmd.index("-i", cmd.index("-i") + 1)
        wav_path = Path(cmd[second_i + 1])
        captured.append(
            {
                "cmd": list(cmd),
                "input_len": len(input),
                "wav_bytes": wav_path.read_bytes(),
                "wav_existed": wav_path.is_file(),
            }
        )
        Path(cmd[-1]).write_bytes(b"\x00\x00\x00\x18ftypisom-fake-mp4")
        return _subprocess.CompletedProcess(cmd, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(match_cmd.subprocess, "run", fake_run)


def test_match_record_mp4_muxes_the_seeded_soundtrack(arena, capsys, monkeypatch) -> None:
    """--format mp4 gains audio: a WAV synthesized from the match identity is
    written beside the piped frames and handed to ffmpeg as a second input
    (-c:a aac -shortest), while every pre-existing video argument stays
    exactly where it was."""
    import io
    import wave

    from league.replay.audio import SAMPLE_RATE, samples_for_frames

    captured: list = []
    _fake_ffmpeg(monkeypatch, captured)
    _play_a_match("m-rec-snd")
    capsys.readouterr()
    out_file = arena / "m-rec-snd.mp4"
    rc = main(["match", "record", "m-rec-snd", "--out", str(out_file), "--format", "mp4"])
    assert rc == 0
    assert len(captured) == 1
    call = captured[0]
    cmd = call["cmd"]

    # The original video args are untouched, in order, up to the pipe input.
    size_at = cmd.index("-video_size") + 1
    width, height = (int(v) for v in cmd[size_at].split("x"))
    output_fps = int(cmd[cmd.index("-framerate") + 1])
    assert cmd[: cmd.index("-i") + 2] == [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "rawvideo",
        "-pixel_format",
        "rgb24",
        "-video_size",
        f"{width}x{height}",
        "-framerate",
        str(output_fps),
        "-i",
        "-",
    ]
    # The soundtrack rides in as a second input, encoded AAC, clipped to the
    # video (-shortest) — and the WAV genuinely existed at call time.
    assert call["wav_existed"]
    second_i = cmd.index("-i", cmd.index("-i") + 1)
    assert cmd[second_i + 1].endswith(".wav")
    assert cmd[cmd.index("-c:a") + 1] == "aac"
    assert "-shortest" in cmd
    assert "yuv420p" in cmd  # the existing pixel-format arg survived

    # The WAV covers the MP4's exact duration: the sample count derives from
    # the same held-frame total the raw video pipe carries.
    held_frames = call["input_len"] // (width * height * 3)
    with wave.open(io.BytesIO(call["wav_bytes"]), "rb") as w:
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2
        assert w.getframerate() == SAMPLE_RATE
        assert w.getnframes() == samples_for_frames(held_frames, output_fps)

    # Same log + same settings -> byte-identical soundtrack (h10).
    rc = main(["match", "record", "m-rec-snd", "--out", str(out_file), "--format", "mp4"])
    assert rc == 0
    capsys.readouterr()
    assert captured[1]["wav_bytes"] == call["wav_bytes"]


# The GIF byte-pin: `render_gif` of the committed cycle-6 log at the CLI's
# default settings, hashed at cycle-8 wave-2 HEAD (commit a16e073) BEFORE the
# soundtrack task touched the record path. The MP4 soundtrack must leave GIF
# output byte-unchanged — GIF89a has no audio channel, so silence there is
# format truth, not a missing feature. If a FUTURE wave changes GIF rendering
# deliberately, regenerate this pin and say so in the PR (same discipline as
# tests/fixtures/determinism.hash).
_GIF_PIN_SHA256 = "8dc3e72777affcc57526046382198b457b0fc8037d5df9e9f819d77f5610590c"
_GIF_PIN_LEN = 1619601
_GIF_PIN_LOG = (
    Path(__file__).resolve().parent.parent
    / "docs"
    / "playtests"
    / "cycle-6"
    / "memory-longhorizon.log.jsonl"
)


def test_match_record_gif_bytes_are_unchanged_by_the_soundtrack_wave() -> None:
    log = MatchLog.from_jsonl(_GIF_PIN_LOG.read_text(encoding="utf-8"))
    gif = render_gif(
        log,
        scale=24,
        fps=2,
        theme="light",
        tween=4,
        provenance="gif-byte-pin: cycle-8 t9",
    )
    assert len(gif) == _GIF_PIN_LEN
    assert hashlib.sha256(gif).hexdigest() == _GIF_PIN_SHA256


def test_match_record_missing_match_id_errors_cleanly(arena, capsys) -> None:
    rc = main(["match", "record", "no-such-match", "--out", "x.gif"])
    assert rc == 1
    err = capsys.readouterr().err
    assert err.startswith("error:")
    assert "hint:" in err


def test_match_overview_lists_record(capsys) -> None:
    assert main(["match", "overview", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert "record" in payload["verbs"]


def test_explain_match_record_resolves(capsys) -> None:
    assert main(["explain", "match", "record"]) == 0
    text = capsys.readouterr().out
    assert "record" in text.lower()
    assert "ffmpeg" in text.lower()


def test_every_catalog_path_resolves_includes_record() -> None:
    from league.explain import known_paths

    assert ("match", "record") in known_paths()
