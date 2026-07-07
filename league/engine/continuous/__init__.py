"""The continuous arena lane — decimal positions, in-game time, race semantics.

This package lands *beside* the grid engine (``league.engine``), not over it:
the grid engine and every committed grid artifact keep working untouched
(cycle-7 spec, two-lane honesty). Determinism is the same load-bearing property
the grid earned — the engine-wide AST import ban
(``tests/test_engine_state.py``) scans ``league/engine/`` recursively, so it
already forbids ``random``/``time``/``datetime``/``secrets``/``uuid`` here too.

``space.py`` is the fixed-point spatial core every later task imports from this
stable path; ``timeline.py`` is the deterministic initiative queue (time is
integer game-time units, completions order the world); ``state.py``/
``events.py`` join them as their tasks land. See each module's docstring for
its pinned decisions (representation/scale/metric/rounding in ``space.py``,
event-queue-over-micro-ticks and the total tie-break in ``timeline.py``).
"""

from league.engine.continuous.space import (
    ARRIVAL_TOLERANCE_MU,
    MAX_STEP_UNDERSHOOT_MU,
    SCALE,
    Pos,
    Vec,
    arrived,
    dist,
    dist_sq,
    format_units,
    from_units,
    isqrt,
    move_toward,
    pos_from_json,
    pos_to_json,
    vec_from_json,
    vec_to_json,
)
from league.engine.continuous.timeline import ScheduledAction, Timeline

__all__ = [
    "ARRIVAL_TOLERANCE_MU",
    "MAX_STEP_UNDERSHOOT_MU",
    "SCALE",
    "Pos",
    "ScheduledAction",
    "Timeline",
    "Vec",
    "arrived",
    "dist",
    "dist_sq",
    "format_units",
    "from_units",
    "isqrt",
    "move_toward",
    "pos_from_json",
    "pos_to_json",
    "vec_from_json",
    "vec_to_json",
]
