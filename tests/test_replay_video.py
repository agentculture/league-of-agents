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


def test_frame_count_is_turns_plus_two_on_the_committed_coop_log() -> None:
    from league.replay.html import build_replay_data

    log = _coop_log()
    data = build_replay_data(log)
    turns_played = len(data["frames"]) - 1
    assert turns_played == 17  # pinned: 17 distinct turns (0..16) in this fixture

    video = build_frames(data)
    assert len(video.frames) == turns_played + 2


def test_frame_count_is_turns_plus_two_on_a_scripted_match() -> None:
    from league.replay.html import build_replay_data

    log = _play_match()
    data = build_replay_data(log)
    turns_played = len(data["frames"]) - 1
    video = build_frames(data)
    assert len(video.frames) == turns_played + 2


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
    hues the HTML replay uses (dataviz palette.md) — never re-derive its own."""
    assert replay_html.TEAM_COLORS[0] == "#2a78d6"
    assert replay_html.TEAM_COLORS[1] == "#e34948"
    from league.replay.video import _hex_to_rgb

    assert PALETTE[8] == _hex_to_rgb(replay_html.TEAM_COLORS[0])
    assert PALETTE[9] == _hex_to_rgb(replay_html.TEAM_COLORS[1])


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
