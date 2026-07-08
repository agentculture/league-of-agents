"""Match replay — the human projection of the match log.

One source of truth, four human/agent projections (spec c2/c12/h5, plan
task t6): ``build_replay_data`` derives every fact from the
:class:`~league.engine.events.MatchLog` (the same artifact ``--json``
consumers read); ``render_html`` wraps it in a single self-contained page;
``render_frame`` (plus the ``run_interactive_shell`` curses wrapper) is the
terminal face (see :mod:`league.replay.tui`); ``render_gif`` renders the same
fold to a shareable, offline animated GIF (see :mod:`league.replay.video`).

The continuous lane (cycle 7, plan task t9) gets its own minimal-but-real
face beside these — ``build_continuous_replay_data``/``render_chtml`` (see
:mod:`league.replay.chtml`) — for :class:`~league.engine.continuous.events.
CMatchLog`. Two lanes, both honest: the grid face above is untouched.

The MP4 export additionally carries the match's ambient score
(``synthesize_wav``, cycle-8 t9): a pure-stdlib offline render of the same
seeded music the HTML page synthesizes live (see :mod:`league.replay.audio`).
The GIF stays silent — GIF89a has no audio channel.
"""

from league.replay.audio import samples_for_frames, synthesize_wav
from league.replay.chtml import build_continuous_replay_data, render_chtml
from league.replay.html import build_assessor_guide, build_replay_data, render_html
from league.replay.tui import render_frame, run_interactive_shell
from league.replay.video import (
    DEFAULT_FPS,
    DEFAULT_SCALE,
    DEFAULT_THEME,
    DEFAULT_TWEEN,
    MAX_FPS,
    MAX_SCALE,
    MAX_TWEEN,
    MIN_FPS,
    MIN_SCALE,
    MIN_TWEEN,
    build_frames,
    build_palette,
    indices_to_rgb,
    render_gif,
)

__all__ = [
    "build_assessor_guide",
    "build_replay_data",
    "render_html",
    "samples_for_frames",
    "synthesize_wav",
    "build_continuous_replay_data",
    "render_chtml",
    "render_frame",
    "run_interactive_shell",
    "render_gif",
    "build_frames",
    "build_palette",
    "indices_to_rgb",
    "DEFAULT_SCALE",
    "DEFAULT_FPS",
    "DEFAULT_THEME",
    "DEFAULT_TWEEN",
    "MIN_SCALE",
    "MAX_SCALE",
    "MIN_FPS",
    "MAX_FPS",
    "MIN_TWEEN",
    "MAX_TWEEN",
]
