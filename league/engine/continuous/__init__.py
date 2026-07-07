"""The continuous arena lane — decimal positions, in-game time, race semantics.

This package lands *beside* the grid engine (``league.engine``), not over it:
the grid engine and every committed grid artifact keep working untouched
(cycle-7 spec, two-lane honesty). Determinism is the same load-bearing property
the grid earned — the engine-wide AST import ban
(``tests/test_engine_state.py``) scans ``league/engine/`` recursively, so it
already forbids ``random``/``time``/``datetime``/``secrets``/``uuid`` here too.

``space.py`` is the fixed-point spatial core every later task imports from this
stable path; ``timeline.py`` is the deterministic initiative queue (time is
integer game-time units, completions order the world); ``state.py`` is the
continuous match-state model (frozen dataclasses, canonical JSON, ``cstate_hash``
— a sibling of the grid's ``state.py`` with :class:`Pos` positions and an
integer game ``clock``); ``events.py`` is its event log and pure fold (the race
made representable in state via a control point's concurrent ``takers``). See
each module's docstring for its pinned decisions (representation/scale/metric/
rounding in ``space.py``, event-queue-over-micro-ticks and the total tie-break in
``timeline.py``, the contested-take vocabulary in ``state.py``/``events.py``).
"""

from league.engine.continuous.events import (
    EVENT_KINDS,
    LOG_VERSION,
    OBSERVATION_KINDS,
    TRANSITION_KINDS,
    CEvent,
    CMatchLog,
    apply_event,
    fold_events,
)
from league.engine.continuous.grades import (
    GRADE_UNIT,
    OFF_ROLE_DEN,
    OFF_ROLE_NUM,
    PURPOSES,
    cgrade_units,
)
from league.engine.continuous.legal import (
    Plan,
    legal_actions_continuous,
    move_duration,
    plan_action,
)
from league.engine.continuous.resolve import (
    CP_POINTS,
    DecisionFn,
    IllegalContinuousAction,
    ResolveResult,
    outcome_points,
    resolve_match,
)
from league.engine.continuous.roles import (
    DEFAULT_CROLE_STATS,
    CRoleStats,
    build_role_table,
    role_table_hash,
    role_table_to_json,
    stats_for,
)
from league.engine.continuous.scenario import (
    CONTINUOUS_ID_PREFIX,
    CScenario,
    cscenario_ids,
    get_cscenario,
    instantiate,
)
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
from league.engine.continuous.state import (
    ACTION_KINDS,
    MATCH_MODES,
    MATCH_STATUSES,
    MISSION_KINDS,
    MISSION_STATUSES,
    CAction,
    CAgentSlot,
    CControlPoint,
    CMatchState,
    CMission,
    CResourceNode,
    CTeamState,
    CUnit,
    TakeAttempt,
    canonical_takers,
    cstate_from_json,
    cstate_hash,
    cstate_to_json,
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
    # continuous match state (state.py)
    "ACTION_KINDS",
    "MATCH_MODES",
    "MATCH_STATUSES",
    "MISSION_KINDS",
    "MISSION_STATUSES",
    "CAction",
    "CAgentSlot",
    "CControlPoint",
    "CMatchState",
    "CMission",
    "CResourceNode",
    "CTeamState",
    "CUnit",
    "TakeAttempt",
    "canonical_takers",
    "cstate_from_json",
    "cstate_hash",
    "cstate_to_json",
    # continuous event log (events.py)
    "EVENT_KINDS",
    "LOG_VERSION",
    "OBSERVATION_KINDS",
    "TRANSITION_KINDS",
    "CEvent",
    "CMatchLog",
    "apply_event",
    "fold_events",
    # continuous per-unit scorecards (grades.py)
    "GRADE_UNIT",
    "OFF_ROLE_DEN",
    "OFF_ROLE_NUM",
    "PURPOSES",
    "cgrade_units",
    # continuous role speed/duration data (roles.py)
    "DEFAULT_CROLE_STATS",
    "CRoleStats",
    "build_role_table",
    "role_table_hash",
    "role_table_to_json",
    "stats_for",
    # continuous legality/menu (legal.py)
    "Plan",
    "legal_actions_continuous",
    "move_duration",
    "plan_action",
    # continuous resolver with race semantics (resolve.py)
    "CP_POINTS",
    "DecisionFn",
    "IllegalContinuousAction",
    "ResolveResult",
    "outcome_points",
    "resolve_match",
    # continuous scenario registry (scenario.py)
    "CONTINUOUS_ID_PREFIX",
    "CScenario",
    "cscenario_ids",
    "get_cscenario",
    "instantiate",
]
