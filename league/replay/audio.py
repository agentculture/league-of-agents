"""Offline ambient soundtrack for exported video (cycle-8 t9, spec c17/h10/h11).

The MP4 soundtrack and the HTML replay's ambient score are the SAME piece of
music for the same match. This module is a pure-stdlib port of the decision
engine ``league/replay/html.py`` embeds as JavaScript (cycle-8 t4):

* the seed is FNV-1a over ``f"{match_id}|{seed}"`` — exactly the page's
  ``audioSeed()`` (UTF-16 code units, like ``charCodeAt``);
* every musical decision consumes a :func:`mulberry32` stream, one
  *independent* stream per voice (pads ``seed ^ 0x51AB3C02``, bells
  ``seed ^ 0x9E3779B9``), so the two renderers draw identical chord roots,
  pad progressions, and bell cadences — note for note;
* the musical design mirrors t4's: a warm lydian pad bed (long-envelope
  detuned sine pairs plus a sub-octave triangle, low-pass filtered with the
  same slow LFO breath) under sparse bell tones (near-harmonic partials,
  exponential decay, pentatonic-plus-maj7 with the rare lydian sharp-4),
  at the same conservative level.

The two renderers are deliberately not *sample*-identical — WebAudio's
convolver reverb has no cheap pure-Python equivalent, so the offline render
substitutes a one-pole low-pass for the biquad, drops the synthesized reverb
tail (its seed stream is independent, so skipping it changes no other draw),
and adds a short closing fade-out (the HTML score never ends; an MP4 does).
The *decisions* are pinned equal to the JS in ``tests/test_replay_audio.py``.

Output format: **mono, 16-bit PCM, 44100 Hz** — mono because the HTML graph's
stereo width comes only from its synthesized reverb, which this render omits;
claiming stereo here would be two identical channels. Same log + same sample
count -> byte-identical WAV (unit-tested). The GIF path never touches this
module: GIF89a has no audio channel, so its silence is format truth.

Performance: pads are additively synthesized at ``SAMPLE_RATE / 5`` (their
content sits far below that Nyquist, and they pass a ~950 Hz low-pass anyway)
and linearly upsampled; bells render sparsely at full rate. A one-minute
score lands in a few seconds of pure Python.
"""

from __future__ import annotations

import io
import math
import sys
import wave
from array import array
from typing import Callable

SAMPLE_RATE = 44100
CHANNELS = 1
SAMPLE_WIDTH = 2  # bytes -> 16-bit PCM

# --- constants mirrored verbatim from html.py's embedded score --------------

MASTER_LEVEL = 0.3
ROOT_MIDI = (41, 43, 45, 48)  # F2 G2 A2 C3 — warm roots only
PAD_CHORDS = (
    (0, 7, 14, 16),  # 1 5 9 3 — home, warm
    (0, 7, 16, 21),  # 1 5 3 6 — the add-6 lift
    (2, 9, 14, 18),  # the lydian II — bright, forward-leaning
    (0, 7, 19, 23),  # 1 5 5 maj7 — open, suspended calm
)
BELL_STEPS = (0, 2, 4, 7, 9, 11, 14, 16)  # pentatonic-plus-maj7, two octaves up
PAD_STREAM = 0x51AB3C02  # the pad voice's stream (seed ^ PAD_STREAM)
BELL_STREAM = 0x9E3779B9  # the bell voice's stream (seed ^ BELL_STREAM)

# Bus levels from the HTML audio graph (padBus 0.9, bellBus 0.75, master 0.3).
_PAD_LEVEL = 0.9
_BELL_LEVEL = 0.75

# Offline rendering choices (documented in docs/replay-design.md).
_PAD_DECIMATION = 5  # pads synthesize at 8820 Hz, upsampled x5
_PAD_RATE = SAMPLE_RATE // _PAD_DECIMATION
_FADE_IN_SECONDS = 2.0  # the HTML master's own 2s fade-in
_FADE_OUT_SECONDS = 1.5  # offline-only: an MP4 ends, the page never does
_DETUNE_CENTS = 2.5
_LP_BASE_HZ = 950.0
_LP_LFO_HZ = 0.045
_LP_LFO_DEPTH_HZ = 240.0

_U32 = 0xFFFFFFFF
_TWO_PI = 2.0 * math.pi


def mulberry32(seed: int) -> Callable[[], float]:
    """The exact PRNG the HTML score embeds, bit-for-bit.

    Every JS operation is 32-bit (``Math.imul``, ``>>>``), so masking each
    step to uint32 reproduces the identical sequence; the final division by
    2**32 is exact in binary, so the floats match too (pinned against the
    JS's own uint32 output in tests/test_replay_audio.py).
    """
    a = seed & _U32

    def rnd() -> float:
        nonlocal a
        a = (a + 0x6D2B79F5) & _U32
        t = ((a ^ (a >> 15)) * (a | 1)) & _U32
        t = ((t + (((t ^ (t >> 7)) * (t | 61)) & _U32)) ^ t) & _U32
        return (t ^ (t >> 14)) / 4294967296.0

    return rnd


def score_seed(match_id: str, seed: int) -> int:
    """FNV-1a (32-bit) over ``f"{match_id}|{seed}"`` — the page's audioSeed().

    Iterates UTF-16 code units to match ``charCodeAt`` exactly (match ids are
    ASCII in practice, but the port should not quietly diverge on the day one
    isn't).
    """
    data = f"{match_id}|{seed}".encode("utf-16-le")
    h = 2166136261
    for i in range(0, len(data), 2):
        h ^= data[i] | (data[i + 1] << 8)
        h = (h * 16777619) & _U32
    return h


def _midi_hz(m: int) -> float:
    return 440.0 * 2.0 ** ((m - 69) / 12)


def score_events(
    seed: int, duration: float
) -> tuple[float, list[tuple[float, float, tuple[int, ...]]], list[tuple[float, float, float]]]:
    """The seeded musical timeline: the same draws, in the same order, as the
    HTML page's ``startScore()`` scheduler.

    Returns ``(root_hz, pads, bells)`` where each pad is ``(start_seconds,
    duration_seconds, chord_steps)`` (duration includes the JS's +8s release
    tail) and each bell — answering bells included, in schedule order — is
    ``(start_seconds, frequency_hz, velocity)``.

    Because each voice draws from its own independent stream, generating all
    pads and then all bells consumes the streams exactly as the JS look-ahead
    scheduler does, whatever its wall-clock tick cadence interleaved. Events
    are emitted while they *start* before ``duration``; a shorter render is a
    strict prefix of a longer one.
    """
    pad_rnd = mulberry32(seed ^ PAD_STREAM)
    bell_rnd = mulberry32(seed ^ BELL_STREAM)
    root_hz = _midi_hz(ROOT_MIDI[int(mulberry32(seed)() * len(ROOT_MIDI))])

    pads: list[tuple[float, float, tuple[int, ...]]] = []
    pad_t = 0.0
    chord = 0
    while pad_t < duration:
        dur = 18 + pad_rnd() * 8
        pads.append((pad_t, dur + 8, PAD_CHORDS[chord]))
        chord = (chord + 1 + int(pad_rnd() * (len(PAD_CHORDS) - 1))) % len(PAD_CHORDS)
        pad_t += dur

    bells: list[tuple[float, float, float]] = []
    bell_t = 2 + bell_rnd() * 3
    while bell_t < duration:
        curious = bell_rnd() < 0.11  # the rare lydian sharp-4 color
        step = 6 if curious else BELL_STEPS[int(bell_rnd() * len(BELL_STEPS))]
        f = root_hz * 2.0 ** ((24 + step + (12 if bell_rnd() < 0.3 else 0)) / 12)
        vel = 0.5 + bell_rnd() * 0.5
        bells.append((bell_t, f, vel))
        if bell_rnd() < 0.22:  # an occasional soft answering bell
            interval = 7 if bell_rnd() < 0.5 else 4
            bells.append((bell_t + 0.7 + bell_rnd() * 0.8, f * 2.0 ** (interval / 12), vel * 0.55))
        bell_t += 3.5 + bell_rnd() * 5.5
    return root_hz, pads, bells


def samples_for_frames(held_frames: int, output_fps: int) -> int:
    """Exact WAV length for an MP4 holding ``held_frames`` constant-rate
    frames at ``output_fps`` — the same numbers ``_render_mp4`` pipes, so the
    soundtrack covers the video to the nearest sample."""
    return round(held_frames * SAMPLE_RATE / output_fps)


# --- rendering ---------------------------------------------------------------


def _pad_envelope(n_local: int, dur: float) -> list[float]:
    """The JS pad gain envelope at pad rate: 0 -> 0.05 over 6s, hold, then
    -> 0 over the final 7s (``dur`` already includes the +8s tail)."""
    env = [0.05] * n_local
    attack_n = min(n_local, int(6 * _PAD_RATE))
    step = 0.05 / (6 * _PAD_RATE)
    for k in range(attack_n):
        env[k] = k * step
    release_from = max(attack_n, int((dur - 7) * _PAD_RATE) + 1)
    end = dur * _PAD_RATE
    step = 0.05 / (7 * _PAD_RATE)
    for k in range(release_from, n_local):
        v = (end - k) * step
        env[k] = v if v > 0.0 else 0.0
    return env


def _mix_pad_chord(
    buf: array, start: float, dur: float, steps: tuple[int, ...], root_hz: float
) -> None:
    """One pad chord, additively, into the pad-rate buffer.

    Each chord tone is the JS's detuned sine pair (±2.5 cents) folded into
    product form — ``sin(a)+sin(b) = 2·sin(center)·cos(beat)`` — with the
    very slow beat cosine held per 128-sample block (< 0.03 rad of drift, far
    below audibility) so the inner loop pays for one ``sin`` per pair, plus
    the quiet sub-octave triangle.
    """
    s0 = int(start * _PAD_RATE)
    n_local = min(int(dur * _PAD_RATE), len(buf) - s0)
    if n_local <= 0:
        return
    env = _pad_envelope(n_local, dur)
    sin = math.sin
    cos = math.cos
    detune = 2.0 ** (_DETUNE_CENTS / 1200)
    for st in steps:
        f = root_hz * 2.0 ** (st / 12)
        w_hi = _TWO_PI * f * detune / _PAD_RATE
        w_lo = _TWO_PI * f / detune / _PAD_RATE
        wc = (w_hi + w_lo) / 2
        wb = (w_hi - w_lo) / 2
        for b0 in range(0, n_local, 128):
            b1 = min(b0 + 128, n_local)
            beat2 = 2.0 * cos(wb * (b0 + b1) * 0.5)
            for k in range(b0, b1):
                buf[s0 + k] += env[k] * beat2 * sin(wc * k)
    # The sub-octave triangle root (JS: rootHz * 2**(steps[0]/12) / 2).
    f_sub = root_hz * 2.0 ** (steps[0] / 12) / 2
    per = f_sub / _PAD_RATE
    for k in range(n_local):
        p = (k * per + 0.75) % 1.0
        buf[s0 + k] += env[k] * (4.0 * (p - 0.5 if p > 0.5 else 0.5 - p) - 1.0)


def _lowpass_with_lfo(buf: array) -> None:
    """One-pole low-pass at pad rate, cutoff breathing exactly like the JS
    biquad's LFO: 950 Hz ± 240 Hz at 0.045 Hz (coefficient updated per
    256-sample block — the LFO moves glacially)."""
    y = 0.0
    n = len(buf)
    exp = math.exp
    sin = math.sin
    for b0 in range(0, n, 256):
        t = (b0 + 128) / _PAD_RATE
        fc = _LP_BASE_HZ + _LP_LFO_DEPTH_HZ * sin(_TWO_PI * _LP_LFO_HZ * t)
        alpha = 1.0 - exp(-_TWO_PI * fc / _PAD_RATE)
        for i in range(b0, min(b0 + 256, n)):
            y += alpha * (buf[i] - y)
            buf[i] = y


def _upsample_pads_into(mix: array, pad_buf: array, num_samples: int) -> None:
    dec = _PAD_DECIMATION
    for i in range(len(pad_buf) - 1):
        base = i * dec
        if base >= num_samples:
            break
        a = pad_buf[i] * _PAD_LEVEL
        step = (pad_buf[i + 1] * _PAD_LEVEL - a) / dec
        for j in range(min(dec, num_samples - base)):
            mix[base + j] = a + step * j


def _mix_bells(mix: array, bells: list[tuple[float, float, float]], num_samples: int) -> None:
    """Bells at full rate: three near-harmonic partials (1 / 2.01 / 3.02),
    12 ms linear attack, exponential decay to the JS ramp's 1e-4 floor at
    ``5 / ratio`` seconds."""
    sin = math.sin
    attack_n = int(0.012 * SAMPLE_RATE)
    for t0, f, vel in bells:
        n0 = int(t0 * SAMPLE_RATE)
        if n0 >= num_samples:
            continue
        for ratio, amp in ((1.0, 1.0), (2.01, 0.38), (3.02, 0.13)):
            gain = 0.16 * vel * amp
            peak = gain * _BELL_LEVEL
            w = _TWO_PI * f * ratio / SAMPLE_RATE
            total_n = int(5.0 / ratio * SAMPLE_RATE)
            step = peak / attack_n
            for k in range(min(attack_n, num_samples - n0)):
                mix[n0 + k] += (k * step) * sin(w * k)
            decay_n = total_n - attack_n
            r = (0.0001 / gain) ** (1.0 / decay_n)
            e = peak
            for k in range(attack_n, min(total_n, num_samples - n0)):
                e *= r
                mix[n0 + k] += e * sin(w * k)


def _quantize(mix: array, num_samples: int) -> bytes:
    """Master gain (with the HTML score's 2s fade-in and the offline closing
    fade-out), gentle soft-knee limiting, and 16-bit little-endian PCM."""
    out = array("h", bytes(2 * num_samples))
    tanh = math.tanh
    fade_in_n = min(int(_FADE_IN_SECONDS * SAMPLE_RATE), num_samples)
    fade_out_n = min(int(_FADE_OUT_SECONDS * SAMPLE_RATE), num_samples)
    fade_out_from = num_samples - fade_out_n
    for i in range(num_samples):
        v = mix[i] * MASTER_LEVEL
        if i < fade_in_n:
            v *= i / fade_in_n
        if i >= fade_out_from:
            v *= (num_samples - i) / fade_out_n
        if v > 0.9:
            v = 0.9 + 0.1 * tanh((v - 0.9) * 10.0)
        elif v < -0.9:
            v = -0.9 - 0.1 * tanh((-0.9 - v) * 10.0)
        out[i] = int(v * 32767.0)
    if sys.byteorder == "big":  # pragma: no cover - WAV PCM is little-endian
        out.byteswap()
    return out.tobytes()


def synthesize_wav(match_id: str, seed: int, *, num_samples: int) -> bytes:
    """Synthesize the match's ambient score as WAV bytes: mono 16-bit PCM at
    44100 Hz, exactly ``num_samples`` frames long.

    Same ``(match_id, seed, num_samples)`` -> byte-identical output; the
    same identity is what seeds the HTML replay's score, so the MP4 and the
    page play the same piece.
    """
    if num_samples < 0:
        raise ValueError(f"num_samples must be >= 0, got {num_samples}")
    mix = array("d", bytes(8 * num_samples))
    if num_samples:
        duration = num_samples / SAMPLE_RATE
        root_hz, pads, bells = score_events(score_seed(match_id, seed), duration)
        pad_buf = array("d", bytes(8 * (num_samples // _PAD_DECIMATION + 2)))
        for start, dur, steps in pads:
            _mix_pad_chord(pad_buf, start, dur, steps, root_hz)
        _lowpass_with_lfo(pad_buf)
        _upsample_pads_into(mix, pad_buf, num_samples)
        _mix_bells(mix, bells, num_samples)
    pcm = _quantize(mix, num_samples)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(CHANNELS)
        w.setsampwidth(SAMPLE_WIDTH)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm)
    return buf.getvalue()
