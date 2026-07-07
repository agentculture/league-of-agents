"""Match replay — the human projection of the match log.

One source of truth, three human/agent projections (spec c2/c12/h5):
``build_replay_data`` derives every fact from the
:class:`~league.engine.events.MatchLog` (the same artifact ``--json``
consumers read); ``render_html`` wraps it in a single self-contained page;
``render_frame`` (plus the ``run_interactive_shell`` curses wrapper) is the
terminal face — see :mod:`league.replay.tui`.
"""

from league.replay.html import build_assessor_guide, build_replay_data, render_html
from league.replay.tui import render_frame, run_interactive_shell

__all__ = [
    "build_assessor_guide",
    "build_replay_data",
    "render_html",
    "render_frame",
    "run_interactive_shell",
]
