"""Match replay — the human projection of the match log.

One source of truth, two projections (spec c12/h5): ``build_replay_data``
derives every fact in the replay from the :class:`~league.engine.events.MatchLog`
(the same artifact ``--json`` consumers read), and ``render_html`` wraps it in a
single self-contained page — no external requests, shareable as a file.
"""

from league.replay.html import build_replay_data, render_html

__all__ = ["build_replay_data", "render_html"]
