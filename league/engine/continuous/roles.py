"""Continuous-lane role speed and action-duration data (plan C7-t4, spec c7).

This module pins in-game speed as **role DATA**, decoupled from substrate
wall-clock (decision c13: still turn-based, but turn order is speed-based —
"a slow local mind's unit moves exactly as fast as a cloud mind's; thinking
time stays the out-of-game tempo axis, never game time"). It sits beside the
grid lane's ``league/engine/scenario.py`` (``RoleStats``) the same way every
other continuous module sits beside its grid sibling: a parallel shape, a
``C`` prefix, no import of the grid engine (two-lane honesty, spec c11/h11).

:class:`CRoleStats` is the continuous analog of ``RoleStats``: the same
quantitative/capability split, translated into the continuous lane's units —

* ``move_rate_mu`` — milliunits (:data:`~league.engine.continuous.space.SCALE`
  scale) covered per game-time unit. This replaces the grid's per-turn
  ``move`` cells; the resolver (t5) will call
  :func:`~league.engine.continuous.space.move_toward` with this as ``speed``.
* ``vision_mu`` — perception radius in milliunits, the continuous analog of
  the grid's Manhattan ``vision``. Vision never affects movement or
  resolution here either — it only bounds what a unit *knows* (unchanged from
  the grid's convention, ``docs/roles.md``).
* ``carry`` — unchanged in kind from the grid: a plain capacity integer.
* ``gather_duration`` / ``take_post_duration`` / ``deliver_duration`` — how
  many in-game-time units each action takes to complete once started. These
  are new: the grid had no notion of action duration (every unit acted
  exactly once per turn). The continuous resolver (t5) schedules a
  ``ScheduledAction`` on the :class:`~league.engine.continuous.timeline.
  Timeline` using these as the duration.
* ``can_gather`` / ``can_take_post`` — the continuous analog of the grid's
  ``can_gather``/``can_capture`` engine-enforced capability booleans
  (``take_post`` is the continuous action name for occupying/holding a
  control point — see ``ACTION_KINDS`` in ``state.py`` — so ``can_take_post``
  is the direct analog of the grid's ``can_capture``).
* ``analog`` — the coding-work analog string, verbatim convention from cycle
  6 (``docs/roles.md``): what real software-team function this role's
  capability contract represents.

Forbidden-action convention (pinned, validated loudly in ``__post_init__``)
----------------------------------------------------------------------------
A role that cannot perform an action pairs its ``can_*=False`` flag with a
**zero** duration for that action; a role that CAN perform it must have a
STRICTLY POSITIVE duration — an allowed action that takes no game time at all
is a modeling bug (a role cannot be *infinitely* fast), not a legitimately
fast role. Concretely: ``can_gather=False <-> gather_duration == 0`` and
``can_take_post=False <-> take_post_duration == 0``, each direction enforced.

There is no separate ``can_deliver`` flag (mirroring the grid, which gates
delivery on carrying something rather than a role boolean): a role that can
never carry cargo (``carry == 0``) can never meaningfully deliver either, so
the same convention is extended one lever over: ``carry == 0 <->
deliver_duration == 0``.

Numbers (pinned defaults, :data:`DEFAULT_CROLE_STATS`)
-------------------------------------------------------
Simple and relatively spaced, mirroring the grid ratios in ``recon-1`` /
``skirmish-1`` (explorer 4 : scout 3 : harvester/defender 2 : planner 1)
scaled by 250 into milliunits-per-game-time-unit, so the same strategic
shape reads across both lanes: explorer is the strict fastest and
widest-sighted and cannot gather or take posts (produces nothing, holds no
ground); planner is the strict slowest and coordination-only; scout /
harvester / defender are the executor class in between, with harvester the
only high-carry role (it hauls and delivers the payload). Scout is the eyes of
the executor class — it sees widest among the three (``vision_mu`` 4000 vs
2000 for harvester/defender) and keeps its full gather/carry/deliver
contract — but it is forbidden from taking posts (``can_take_post=False``,
``take_post_duration=0``): a human-reviewed amendment (cycle 7, pre-publish)
that only its post-taking is withdrawn, not its economy participation. Its
fog-reducing role (actually narrowing what OTHER units can see, not just what
it itself sees) arrives with the continuous fog work, a later cycle. That
leaves harvester and defender as the only two roles that can take/hold a
control point in the continuous lane. The exact values are data anyone can
rebalance via :func:`build_role_table` — nothing here is hard-coded into the
resolver.

The grain warning (``space.py``'s docstring) is satisfied by construction:
every role's ``move_rate_mu`` times the shortest positive action duration
anywhere in the table clears ``MAX_STEP_UNDERSHOOT_MU`` (3 mu) by two orders
of magnitude (proven in ``tests/test_continuous_roles.py``), so no single
action's displacement can be swallowed by the fixed-point grain.

Scenario-declared, hash-covered (spec c7 acceptance — this task's second half)
-------------------------------------------------------------------------------
:func:`build_role_table` is the validated override mechanism a continuous
scenario (t6) will use to field a table that differs from
:data:`DEFAULT_CROLE_STATS` **without any code change** — a mapping of role
name to a replacement (or brand-new) :class:`CRoleStats`. :func:`role_table_to_json`
gives the table a stable, order-independent canonical JSON projection (sorted
by role name, exactly like ``state.py``'s canonical JSON), and
:func:`role_table_hash` fingerprints it — the primitive t6's scenario-aware
state hash folds in so two scenarios with different speed tables hash
differently even when every other part of the state is byte-identical
(``tests/test_continuous_roles.py::
test_two_scenarios_with_different_speed_tables_hash_differently_for_identical_states``).
``CMatchState`` itself gains no new field here — wiring a role table into a
scenario and its resolved match state is t6's job; this module only has to
prove the data and its hash primitive exist and behave.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

# --------------------------------------------------------------------------
# Strict scalar validation (mirrors timeline.py's discipline: no float, no
# bool masquerading as an int, no silent coercion).
# --------------------------------------------------------------------------


def _require_int(value: Any, label: str) -> None:
    # ``type(...) is int`` deliberately excludes ``bool`` (True/False are not
    # speeds or durations) and ``float`` (no binary floats in the continuous
    # lane — the same discipline every sibling module in this package keeps).
    if type(value) is not int:
        raise ValueError(f"{label} must be an int, got {type(value).__name__}")


def _require_bool(value: Any, label: str) -> None:
    if type(value) is not bool:
        raise ValueError(f"{label} must be a bool, got {type(value).__name__}")


@dataclass(frozen=True)
class CRoleStats:
    """Per-role capability contract for the continuous lane — pure DATA.

    See the module docstring for the field-by-field mapping to the grid's
    ``RoleStats`` and the forbidden-action convention enforced below.
    """

    move_rate_mu: int
    vision_mu: int
    carry: int
    gather_duration: int
    take_post_duration: int
    deliver_duration: int
    can_gather: bool = True
    can_take_post: bool = True
    analog: str = ""

    def __post_init__(self) -> None:
        for label in (
            "move_rate_mu",
            "vision_mu",
            "carry",
            "gather_duration",
            "take_post_duration",
            "deliver_duration",
        ):
            _require_int(getattr(self, label), label)
        _require_bool(self.can_gather, "can_gather")
        _require_bool(self.can_take_post, "can_take_post")
        if not isinstance(self.analog, str):
            raise ValueError(f"analog must be a str, got {type(self.analog).__name__}")

        if self.move_rate_mu <= 0:
            raise ValueError(f"move_rate_mu must be positive, got {self.move_rate_mu}")
        if self.vision_mu <= 0:
            raise ValueError(f"vision_mu must be positive, got {self.vision_mu}")
        if self.carry < 0:
            raise ValueError(f"carry must be non-negative, got {self.carry}")
        for label in ("gather_duration", "take_post_duration", "deliver_duration"):
            value = getattr(self, label)
            if value < 0:
                raise ValueError(f"{label} must be non-negative, got {value}")

        # Forbidden-action convention: can_*=False <-> duration == 0, in both
        # directions, so a permitted action can never be silently instant and a
        # forbidden action can never silently carry a duration nobody schedules.
        self._require_consistent(
            "can_gather", self.can_gather, "gather_duration", self.gather_duration
        )
        self._require_consistent(
            "can_take_post", self.can_take_post, "take_post_duration", self.take_post_duration
        )
        # No separate can_deliver flag: carry == 0 plays that role (a role that
        # can never carry cargo has no meaningful delivery duration, and vice
        # versa a role that can carry must have a real delivery duration).
        self._require_consistent(
            "carry>0", self.carry > 0, "deliver_duration", self.deliver_duration
        )

    @staticmethod
    def _require_consistent(
        flag_label: str, flag_value: bool, duration_label: str, duration_value: int
    ) -> None:
        if flag_value and duration_value <= 0:
            raise ValueError(
                f"{flag_label} is True but {duration_label}={duration_value}: a permitted "
                "action must have a strictly positive duration"
            )
        if not flag_value and duration_value != 0:
            raise ValueError(
                f"{flag_label} is False but {duration_label}={duration_value}: a forbidden "
                "action's duration must be exactly 0"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "move_rate_mu": self.move_rate_mu,
            "vision_mu": self.vision_mu,
            "carry": self.carry,
            "gather_duration": self.gather_duration,
            "take_post_duration": self.take_post_duration,
            "deliver_duration": self.deliver_duration,
            "can_gather": self.can_gather,
            "can_take_post": self.can_take_post,
            "analog": self.analog,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CRoleStats":
        return cls(
            move_rate_mu=d["move_rate_mu"],
            vision_mu=d["vision_mu"],
            carry=d["carry"],
            gather_duration=d["gather_duration"],
            take_post_duration=d["take_post_duration"],
            deliver_duration=d["deliver_duration"],
            can_gather=d["can_gather"],
            can_take_post=d["can_take_post"],
            analog=d["analog"],
        )


# --------------------------------------------------------------------------
# The default coding-reflective roster (cycle 6's roles, continuous stats).
# --------------------------------------------------------------------------

DEFAULT_CROLE_STATS: tuple[tuple[str, CRoleStats], ...] = (
    (
        "explorer",
        CRoleStats(
            move_rate_mu=1000,
            vision_mu=6000,
            carry=0,
            gather_duration=0,
            take_post_duration=0,
            deliver_duration=0,
            can_gather=False,
            can_take_post=False,
            analog="reconnaissance / code-reading: ranges far and sees far, "
            "produces nothing directly and holds no ground",
        ),
    ),
    (
        "planner",
        CRoleStats(
            move_rate_mu=250,
            vision_mu=2000,
            carry=0,
            gather_duration=0,
            take_post_duration=0,
            deliver_duration=0,
            can_gather=False,
            can_take_post=False,
            analog="architect / tech-lead: coordinates via plan + messages, "
            "weak on the board alone",
        ),
    ),
    (
        "scout",
        CRoleStats(
            move_rate_mu=750,
            vision_mu=4000,
            carry=1,
            gather_duration=6,
            take_post_duration=0,
            deliver_duration=4,
            can_take_post=False,
            analog="the eyes — sees widest among executors, forbidden from taking posts; "
            "its fog-reducing role arrives with the continuous fog work",
        ),
    ),
    (
        "harvester",
        CRoleStats(
            move_rate_mu=500,
            vision_mu=2000,
            carry=3,
            gather_duration=8,
            take_post_duration=10,
            deliver_duration=6,
            analog="implementer (executor class): hauls and delivers the payload",
        ),
    ),
    (
        "defender",
        CRoleStats(
            move_rate_mu=500,
            vision_mu=2000,
            carry=1,
            gather_duration=10,
            take_post_duration=6,
            deliver_duration=8,
            analog="implementer (executor class): captures and holds objectives",
        ),
    ),
)


def stats_for(table: tuple[tuple[str, CRoleStats], ...], role: str) -> CRoleStats:
    """Look up ``role``'s stats in ``table``; unknown roles fail loudly.

    Mirrors the grid's ``Scenario.stats_for`` exactly (same failure shape).
    """
    for name, stats in table:
        if name == role:
            return stats
    known = [name for name, _ in table]
    raise ValueError(f"unknown role {role!r}; expected one of {known}")


def build_role_table(
    overrides: Mapping[str, CRoleStats] | None = None,
) -> tuple[tuple[str, CRoleStats], ...]:
    """Build a role table starting from :data:`DEFAULT_CROLE_STATS`, applying
    ``overrides`` (role name -> replacement :class:`CRoleStats`).

    A role present in ``overrides`` but absent from the default table is a new
    role the scenario introduces (t6's scenario module owns actually fielding
    a unit with it); a role present in both is replaced wholesale. Every
    override value must already be a validated :class:`CRoleStats` instance
    (its own ``__post_init__`` enforces internal consistency). Returns a table
    sorted by role name, so its canonical JSON (:func:`role_table_to_json`) is
    independent of override-mapping iteration order. This is the mechanism
    that lets two scenarios field different speed tables without any code
    change — swap the mapping, not the module.
    """
    if overrides is None:
        return DEFAULT_CROLE_STATS
    if not isinstance(overrides, Mapping):
        raise ValueError(
            f"overrides must be a mapping of role name -> CRoleStats, got "
            f"{type(overrides).__name__}"
        )

    merged: dict[str, CRoleStats] = dict(DEFAULT_CROLE_STATS)
    for role, stats in overrides.items():
        if not isinstance(role, str) or not role:
            raise ValueError(f"override role name must be a non-empty string, got {role!r}")
        if not isinstance(stats, CRoleStats):
            raise ValueError(
                f"override for role {role!r} must be a CRoleStats instance, got "
                f"{type(stats).__name__}"
            )
        merged[role] = stats
    return tuple(sorted(merged.items()))


# --------------------------------------------------------------------------
# Canonical JSON + hash (same style as space.py/state.py: sorted keys, compact
# separators, sha256 hex digest).
# --------------------------------------------------------------------------


def role_table_to_json(table: tuple[tuple[str, CRoleStats], ...]) -> str:
    """Canonical JSON projection of a role table: same table -> same bytes,
    regardless of the tuple's own entry order (sorted here by role name)."""
    entries = sorted(table, key=lambda pair: pair[0])
    payload = [[name, stats.to_dict()] for name, stats in entries]
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def role_table_hash(table: tuple[tuple[str, CRoleStats], ...]) -> str:
    """A stable fingerprint of a role table (sha256 of its canonical JSON) —
    the primitive a scenario-aware state hash (t6) folds in so two scenarios
    with different speed tables hash differently even with an otherwise
    identical state."""
    return hashlib.sha256(role_table_to_json(table).encode("utf-8")).hexdigest()
