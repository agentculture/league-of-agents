"""Acceptance tests for the offline ambient soundtrack (cycle-8 plan task t9,
spec c17/h10/h11).

The MP4 soundtrack and the HTML replay's ambient score must be the SAME piece
of music for the same match: the WAV synthesizer in ``league.replay.audio``
ports the HTML page's seeded decision engine — FNV-1a over ``match_id|seed``
into ``mulberry32``, one independent stream per voice — so the chord roots,
pad progression, and bell cadence match note for note (the two renderers are
not sample-identical; the *decisions* are).

Every pinned constant below was extracted from the exact JavaScript that
``league/replay/html.py`` embeds (its ``mulberry32``/``audioSeed`` functions
and the ``startScore`` scheduling loops, copied verbatim into a node harness
and dumped as JSON). If a pin ever disagrees, the Python port has drifted
from the HTML score — fix the port, never the pin, unless the HTML engine
itself changed in the same PR (then regenerate the pins from its new JS and
say so).
"""

from __future__ import annotations

import io
import time
import wave

import pytest

from league.replay.audio import (
    BELL_STREAM,
    CHANNELS,
    PAD_STREAM,
    SAMPLE_RATE,
    SAMPLE_WIDTH,
    mulberry32,
    samples_for_frames,
    score_events,
    score_seed,
    synthesize_wav,
)

# --- pinned reference values (extracted from html.py's own JS, see above) ----

# audioSeed(match_id, seed) = FNV-1a over `${match_id}|${seed}`, uint32.
_JS_AUDIO_SEEDS = {
    ("m-rec", 7): 2986472778,
    ("m-x", 42): 183063309,
    ("memory-longhorizon", 11): 2948331592,
    ("m-rec-live", 1): 3276458619,
}

# First 12 raw uint32 outputs of mulberry32(seed) — the value the JS computes
# right before its `/ 4294967296`. Includes the actual per-voice stream seeds
# the m-x|42 match derives (seed ^ PAD_STREAM, seed ^ BELL_STREAM).
_JS_MULBERRY_U32 = {
    0: [
        1144304738,
        1416247,
        958946056,
        627933444,
        2007157716,
        2340967985,
        2642484575,
        2787370982,
        1958536065,
        2496316458,
        1057668038,
        420269829,
    ],
    1: [
        2693262067,
        11749833,
        2265367787,
        4213581821,
        4159151403,
        1207330352,
        2632122864,
        3095568220,
        1828783984,
        4272732017,
        1955374602,
        2099329838,
    ],
    183063309: [  # score_seed("m-x", 42)
        2538348709,
        2423403793,
        4168984307,
        1993928458,
        2860058794,
        335485996,
        3211941931,
        3448216896,
        1068728634,
        4191777326,
        739795633,
        1971369626,
    ],
    1531080463: [  # score_seed("m-x", 42) ^ 0x51AB3C02 — the pad voice
        418171161,
        2876472924,
        3494188796,
        653038526,
        1548285160,
        4273766985,
        814824789,
        2882318943,
        733545814,
        179838083,
        2351953515,
        2585023975,
    ],
    2497587892: [  # score_seed("m-x", 42) ^ 0x9E3779B9 — the bell voice
        3682982315,
        1297052774,
        98727217,
        2539109723,
        1180499364,
        4283777373,
        919233362,
        3408416068,
        2555528381,
        3203276341,
        459001393,
        4023948008,
    ],
    1831565813: [  # 0 + 0x6D2B79F5: one step into stream 0
        1416247,
        958946056,
        627933444,
        2007157716,
        2340967985,
        2642484575,
        2787370982,
        1958536065,
        2496316458,
        1057668038,
        420269829,
        3880206403,
    ],
}

# The full JS decision table for match m-x seed 42, first 60 seconds: the
# root draw, every pad chord (start, duration incl. the +8s release tail,
# chord steps), every bell (time, frequency, velocity) — answer bells
# included, in schedule order.
_JS_DECISIONS_M_X_42 = {
    "root_hz": 110.0,
    "pads": [
        (0.0, 26.778904484584928, (0, 7, 14, 16)),
        (18.778904484584928, 32.50843381136656, (0, 7, 19, 23)),
        (43.287338295951486, 28.883905842900276, (0, 7, 14, 16)),
    ],
    "bells": [
        (4.5725334289018065, 440.0, 0.6374282133765519),
        (9.249674753285944, 739.9888454232688, 0.5534347948851064),
        (16.861582778859884, 830.6093951598903, 0.6053573964163661),
        (24.857797312899493, 830.6093951598903, 0.7669910729164258),
        (30.85379387298599, 493.883301256124, 0.8158566855126992),
        (36.40403506718576, 659.25511382574, 0.7043637762544677),
        # the ~22% soft answering bell, a fifth above the 36.4s bell (JS
        # argument order: the frequency argument's interval draw comes
        # before the time argument's offset draw)
        (37.83622813895345, 987.7666025122484, 0.38740007693995726),
        (44.670003114733845, 1661.2187903197805, 0.9402729370631278),
        (52.58820580516476, 622.2539674441618, 0.6768138383049518),
        (59.99602797697298, 880.0, 0.8227498376509175),
    ],
}

_JS_DECISIONS_M_REC_7 = {
    "root_hz": 110.0,
    "n_pads": 3,
    "n_bells": 9,
    "first_bell": (4.5189082231372595, 1661.2187903197805, 0.8997999831335619),
}


def _u32_stream(seed: int, n: int) -> list[int]:
    rnd = mulberry32(seed)
    # mulberry32 divides by 2**32 (a power of two), so the division is exact
    # and the uint32 is recoverable exactly from the float.
    return [int(rnd() * 4294967296) for _ in range(n)]


# --- the PRNG port matches the HTML page's JS, bit for bit ------------------


def test_score_seed_matches_the_html_pages_fnv1a() -> None:
    for (match_id, seed), expected in _JS_AUDIO_SEEDS.items():
        assert score_seed(match_id, seed) == expected


def test_mulberry32_matches_the_js_uint32_stream() -> None:
    for seed, expected in _JS_MULBERRY_U32.items():
        assert _u32_stream(seed, len(expected)) == expected


def test_voice_stream_seeds_mirror_the_html_score() -> None:
    """The per-voice XOR constants are the HTML score's own — pads and bells
    draw from independent streams, exactly as startScore() derives them."""
    assert PAD_STREAM == 0x51AB3C02
    assert BELL_STREAM == 0x9E3779B9
    base = score_seed("m-x", 42)
    assert base ^ PAD_STREAM == 1531080463
    assert base ^ BELL_STREAM == 2497587892


# --- the musical decision sequence matches the HTML score -------------------


def test_score_events_replays_the_js_decision_sequence() -> None:
    ref = _JS_DECISIONS_M_X_42
    root_hz, pads, bells = score_events(score_seed("m-x", 42), 60.0)
    assert root_hz == ref["root_hz"]  # A2 — one of the four warm roots
    assert len(pads) == len(ref["pads"])
    for (start, dur, steps), (r_start, r_dur, r_steps) in zip(pads, ref["pads"]):
        assert start == pytest.approx(r_start, rel=1e-12, abs=1e-12)
        assert dur == pytest.approx(r_dur, rel=1e-12)
        assert tuple(steps) == r_steps
    assert len(bells) == len(ref["bells"])
    for (t, f, vel), (r_t, r_f, r_vel) in zip(bells, ref["bells"]):
        assert t == pytest.approx(r_t, rel=1e-12)
        assert f == pytest.approx(r_f, rel=1e-12)
        assert vel == pytest.approx(r_vel, rel=1e-12)


def test_score_events_second_match_pins() -> None:
    ref = _JS_DECISIONS_M_REC_7
    root_hz, pads, bells = score_events(score_seed("m-rec", 7), 60.0)
    assert root_hz == ref["root_hz"]
    assert len(pads) == ref["n_pads"]
    assert len(bells) == ref["n_bells"]
    t, f, vel = bells[0]
    r_t, r_f, r_vel = ref["first_bell"]
    assert t == pytest.approx(r_t, rel=1e-12)
    assert f == pytest.approx(r_f, rel=1e-12)
    assert vel == pytest.approx(r_vel, rel=1e-12)


def test_score_events_prefix_property() -> None:
    """A shorter render is a strict prefix of a longer one — the decision
    stream never depends on the requested duration (the same guarantee the
    HTML score's look-ahead scheduler provides)."""
    seed = score_seed("m-x", 42)
    root_a, pads_a, bells_a = score_events(seed, 20.0)
    root_b, pads_b, bells_b = score_events(seed, 60.0)
    assert root_a == root_b
    assert pads_a == pads_b[: len(pads_a)]
    assert bells_a == bells_b[: len(bells_a)]


# --- WAV synthesis: deterministic, exact, valid -----------------------------


def test_wav_is_byte_deterministic() -> None:
    n = SAMPLE_RATE * 12
    a = synthesize_wav("m-x", 42, num_samples=n)
    b = synthesize_wav("m-x", 42, num_samples=n)
    assert a == b
    # ... and it's actually music, not digital silence.
    with wave.open(io.BytesIO(a), "rb") as w:
        frames = w.readframes(w.getnframes())
    assert any(byte != 0 for byte in frames)


def test_different_match_identity_changes_the_music() -> None:
    n = SAMPLE_RATE * 8
    base = synthesize_wav("m-x", 42, num_samples=n)
    assert synthesize_wav("m-y", 42, num_samples=n) != base
    assert synthesize_wav("m-x", 43, num_samples=n) != base


def test_wav_header_and_exact_sample_count() -> None:
    for n in (0, 1, 4410, SAMPLE_RATE + 7):
        raw = synthesize_wav("m-rec", 7, num_samples=n)
        with wave.open(io.BytesIO(raw), "rb") as w:
            assert w.getnchannels() == CHANNELS == 1
            assert w.getsampwidth() == SAMPLE_WIDTH == 2
            assert w.getframerate() == SAMPLE_RATE == 44100
            assert w.getnframes() == n


def test_samples_for_frames_covers_the_video_exactly() -> None:
    """The CLI sizes the WAV from the same numbers _render_mp4 feeds ffmpeg:
    total held output frames at the container rate."""
    assert samples_for_frames(100, 10) == 441000  # 10s of video -> 10s of audio
    assert samples_for_frames(0, 10) == 0
    # a non-integer duration rounds to the nearest sample, deterministically
    assert samples_for_frames(1, 3) == round(SAMPLE_RATE / 3)


def test_realistic_duration_synthesizes_in_seconds() -> None:
    """Pure-stdlib synthesis must stay usable at real replay lengths: a
     60-second score (a typical recorded match with cards and tweens) has to
    land well inside interactive time even on a slow CI worker."""
    started = time.monotonic()
    raw = synthesize_wav("m-memory-longhorizon", 20260714, num_samples=SAMPLE_RATE * 60)
    elapsed = time.monotonic() - started
    with wave.open(io.BytesIO(raw), "rb") as w:
        assert w.getnframes() == SAMPLE_RATE * 60
    assert elapsed < 30.0, f"60s of audio took {elapsed:.1f}s to synthesize"


def test_synthesize_wav_rejects_negative_sample_counts() -> None:
    with pytest.raises(ValueError):
        synthesize_wav("m-x", 42, num_samples=-1)
