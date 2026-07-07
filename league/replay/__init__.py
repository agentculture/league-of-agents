"""Match replay — the human projection of the match log.

One source of truth, four human/agent projections (spec c2/c12/h5, plan
task t6): ``build_replay_data`` derives every fact from the
:class:`~league.engine.events.MatchLog` (the same artifact ``--json``
consumers read); ``render_html`` wraps it in a single self-contained page;
``render_frame`` (plus the ``run_interactive_shell`` curses wrapper) is the
terminal face (see :mod:`league.replay.tui`); ``render_gif`` renders the same
fold to a shareable, offline animated GIF (see :mod:`league.replay.video`).
"""

from league.replay.html import build_assessor_guide, build_replay_data, render_html
from league.replay.tui import render_frame, run_interactive_shell
from league.replay.video import (
    DEFAULT_FPS,
    DEFAULT_SCALE,
    MAX_FPS,
    MAX_SCALE,
    MIN_FPS,
    MIN_SCALE,
    build_frames,
    indices_to_rgb,
    render_gif,
)

__all__ = [
    "build_assessor_guide",
    "build_replay_data",
    "render_html",
    "render_frame",
    "run_interactive_shell",
    "render_gif",
    "build_frames",
    "indices_to_rgb",
    "DEFAULT_SCALE",
    "DEFAULT_FPS",
    "MIN_SCALE",
    "MAX_SCALE",
    "MIN_FPS",
    "MAX_FPS",
]
