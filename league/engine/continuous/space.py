"""The fixed-point spatial core — continuous positions with **exact** arithmetic.

This module pins the spatial representation every later continuous-lane task
builds on (cycle-7 frame parked-unknown *v2*: "fixed-point representation,
scale, and movement model"). It is geometry only — no game rules, no state, no
events (those live in ``state.py``/``events.py`` beside this file). Read this
docstring as the contract; the rest of the continuous lane depends on these
rules staying exactly as written.

Representation and scale (pinned)
---------------------------------
A position is a pair of **integer milliunits**: ``SCALE = 1000`` milliunits per
board unit, so ``1.0`` unit == ``1000`` mu and ``2.375`` units == ``2375`` mu.
Positions and vectors are stored as plain ``int`` inside frozen dataclasses —
never a binary ``float``. Rationale, weighed against the alternatives:

* **Plain ints hash, compare, and serialize exactly** like the grid engine's
  current integer coordinates, so the continuous ``state_hash`` is stable and
  platform-independent for free — the same property the grid earned.
* **No ``Decimal`` context pitfalls**: ``Decimal`` carries a thread-local
  context (precision, rounding) that can drift between environments and is a
  float-adjacent footgun; canonical JSON of a ``Decimal`` is also awkward. Plain
  ints keep canonical JSON pure integers.
* **Milliunits give sub-cell precision** (one part in a thousand of a unit)
  which is finer than any movement a role produces per decision point, so the
  fixed-point grain is invisible to play while the arithmetic stays exact.

Rendering/CLI layers may *format* milliunits as decimals (``format_units``);
they must never store or compute in ``float``.

Distance metric (pinned): Euclidean, via exact squared distance
---------------------------------------------------------------
The metric is **Euclidean**, because movement toward a target must follow a real
straight line and races turn on who is genuinely closer. Euclidean length is
irrational in general, which would break exactness — so the rule is:

* :func:`dist_sq` is the **primary comparison primitive**: an *exact* integer
  (milliunits squared). Every "who is closer / has this been reached" comparison
  in the engine must use squared distances, so it stays exact.
* :func:`dist` is the scalar fallback where a magnitude is unavoidable. It is the
  **floored** integer square root of ``dist_sq`` (:func:`isqrt`): the largest
  integer ``r`` with ``r*r <= dist_sq``. Floor (never round/ceil) is the pinned
  rounding rule, so ``dist`` is deterministic and never overstates separation.

Movement rounding (pinned): floor toward the mover's origin
-----------------------------------------------------------
:func:`move_toward` moves from ``origin`` toward ``target`` at ``speed``
milliunits per time-unit for ``duration`` time-units. Let ``travel = speed *
duration`` (exact int). The rules:

* **Exact arrival clamp.** If ``travel*travel >= dist_sq(origin, target)`` the
  budget reaches (or would overshoot) the target, so the result is ``target``
  *exactly* — an exact integer comparison, never a float epsilon. Arrival is
  therefore byte-exact and identical whether reached in one big step or many
  small ones.
* **Never overshoots.** Otherwise the step advances along the ray toward the
  target by ``travel`` milliunits, but the denominator uses ``ceil(sqrt(dsq))``
  (:func:`_ceil_isqrt`, ``>=`` the true distance) so the displacement magnitude
  is ``travel * L / ceil(L) <= travel`` — the mover always lands *at or before*
  the intended point, never past the target.
* **Floor toward the mover's origin.** Each axis of the displacement is divided
  with truncation toward zero (:func:`_trunc_div`), i.e. its magnitude is
  floored, so rounding error always pulls the result back toward ``origin``.

Consequences proved by ``tests/test_continuous_space.py``: the distance to the
target is monotone non-increasing; the result stays inside the origin→target
bounding box; and once the travel budget suffices, a subdivided journey lands on
the *byte-identical* target the single-shot move reaches (zero drift). Before
arrival, a subdivided partial journey lags the single-shot partial journey by at
most ``steps * MAX_STEP_UNDERSHOOT_MU`` milliunits — a pinned integer bound, not
a float tolerance. Note the fixed-point grain: a step whose ``travel`` is tiny
relative to the distance can round to zero displacement (sub-milliunit moves are
not representable); the engine sizes durations so each decision point produces
real progress.

Arrival tolerance (pinned): ``ARRIVAL_TOLERANCE_MU``
----------------------------------------------------
"Reached the post" is an exact integer test, never a float epsilon:
:func:`arrived` is true when ``dist_sq(a, b) <= ARRIVAL_TOLERANCE_MU**2``. Since
``move_toward`` clamps to the target exactly on arrival, a unit that moves to
reach a point lands on it exactly (distance 0); the tolerance exists so higher
layers can treat a position within one milliunit of a reference as "at" it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

# --------------------------------------------------------------------------
# Pinned constants
# --------------------------------------------------------------------------

#: Milliunits per board unit. ``1.0`` unit == 1000 mu. The one scale constant
#: the whole continuous lane shares.
SCALE = 1000

#: A position within this many milliunits of a reference counts as "arrived"
#: (one part in a thousand of a unit). See :func:`arrived`.
ARRIVAL_TOLERANCE_MU = 1

#: Upper bound on the along-ray milliunits a single :func:`move_toward` step can
#: fall short of the ideal continuous point: two axis floors (< 1 mu each,
#: magnitude < sqrt(2)) plus the ceil-denominator undershoot (< 1 mu). Rounded
#: up to a clean integer with margin. Used to bound subdivided-vs-single drift.
MAX_STEP_UNDERSHOOT_MU = 3


# --------------------------------------------------------------------------
# Exact integer square root (pure, deterministic, cross-platform)
# --------------------------------------------------------------------------


def isqrt(n: int) -> int:
    """Return ``floor(sqrt(n))`` for ``n >= 0`` using pure integer arithmetic.

    Newton's method on integers — no ``float`` ever touches the value, so the
    result is identical on every platform. Raises ``ValueError`` for ``n < 0``.
    """
    if n < 0:
        raise ValueError(f"isqrt is undefined for negative input {n!r}")
    if n == 0:
        return 0
    x = 1 << ((n.bit_length() + 1) // 2)
    while True:
        y = (x + n // x) // 2
        if y >= x:
            return x
        x = y


def _ceil_isqrt(n: int) -> int:
    """The smallest integer ``r`` with ``r*r >= n`` (``ceil(sqrt(n))``)."""
    r = isqrt(n)
    return r if r * r == n else r + 1


def _trunc_div(numerator: int, denominator: int) -> int:
    """Divide, truncating toward zero (so magnitude floors toward the origin).

    Python's ``//`` floors toward negative infinity; movement rounding must
    floor the *magnitude* regardless of sign, hence this sign-aware helper.
    ``denominator`` must be positive.
    """
    quotient = abs(numerator) // denominator
    return quotient if numerator >= 0 else -quotient


# --------------------------------------------------------------------------
# Value types
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Vec:
    """A 2D displacement in integer milliunits."""

    x: int
    y: int

    def __add__(self, other: "Vec") -> "Vec":
        return Vec(self.x + other.x, self.y + other.y)

    def __sub__(self, other: "Vec") -> "Vec":
        return Vec(self.x - other.x, self.y - other.y)

    def length_sq(self) -> int:
        """Exact squared magnitude in milliunits squared."""
        return self.x * self.x + self.y * self.y

    def length(self) -> int:
        """Floored magnitude in milliunits (``floor(sqrt(length_sq))``)."""
        return isqrt(self.length_sq())

    def to_dict(self) -> dict[str, Any]:
        return {"x": self.x, "y": self.y}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Vec":
        return cls(x=d["x"], y=d["y"])


@dataclass(frozen=True)
class Pos:
    """A 2D position in integer milliunits (``SCALE`` mu per board unit)."""

    x: int
    y: int

    def __add__(self, offset: Vec) -> "Pos":
        return Pos(self.x + offset.x, self.y + offset.y)

    def __sub__(self, other: "Pos") -> Vec:
        """Displacement from ``other`` to ``self``."""
        return Vec(self.x - other.x, self.y - other.y)

    def to_dict(self) -> dict[str, Any]:
        return {"x": self.x, "y": self.y}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Pos":
        return cls(x=d["x"], y=d["y"])


def from_units(x_units: int, y_units: int) -> Pos:
    """Build a :class:`Pos` from whole board units (multiplies by ``SCALE``)."""
    return Pos(x_units * SCALE, y_units * SCALE)


# --------------------------------------------------------------------------
# Geometry
# --------------------------------------------------------------------------


def dist_sq(a: Pos, b: Pos) -> int:
    """Exact squared Euclidean distance in milliunits squared — the primary
    comparison primitive (compare these to keep "who is closer" exact)."""
    dx = a.x - b.x
    dy = a.y - b.y
    return dx * dx + dy * dy


def dist(a: Pos, b: Pos) -> int:
    """Floored scalar Euclidean distance in milliunits (``floor(sqrt(dist_sq)))``.

    Floor is the pinned rounding rule; use :func:`dist_sq` for comparisons.
    """
    return isqrt(dist_sq(a, b))


def move_toward(origin: Pos, target: Pos, speed: int, duration: int) -> Pos:
    """Advance from ``origin`` toward ``target`` at ``speed`` milliunits per
    time-unit for ``duration`` time-units and return the exact new position.

    ``travel = speed * duration``. If the budget reaches the target the result
    is ``target`` exactly (exact-arrival clamp); otherwise the step advances
    along the ray, never overshooting and flooring each axis toward ``origin``.
    See the module docstring for the pinned rules. Raises ``ValueError`` on a
    negative ``speed`` or ``duration``.
    """
    if speed < 0:
        raise ValueError(f"speed must be non-negative, got {speed!r}")
    if duration < 0:
        raise ValueError(f"duration must be non-negative, got {duration!r}")

    travel = speed * duration
    dx = target.x - origin.x
    dy = target.y - origin.y
    dsq = dx * dx + dy * dy

    # Exact-arrival clamp: budget reaches or would overshoot the target.
    if travel * travel >= dsq:
        return target

    # ceil(sqrt(dsq)) >= the true distance, so magnitude = travel*L/ceil(L)
    # <= travel: the mover lands at or before the intended point, never past it.
    denom = _ceil_isqrt(dsq)
    step_x = _trunc_div(dx * travel, denom)
    step_y = _trunc_div(dy * travel, denom)
    return Pos(origin.x + step_x, origin.y + step_y)


def arrived(a: Pos, b: Pos, tolerance: int = ARRIVAL_TOLERANCE_MU) -> bool:
    """True when ``a`` is within ``tolerance`` milliunits of ``b`` (exact
    integer test: ``dist_sq(a, b) <= tolerance**2``)."""
    return dist_sq(a, b) <= tolerance * tolerance


# --------------------------------------------------------------------------
# Canonical JSON (same style as state.py: sorted keys, compact separators)
# --------------------------------------------------------------------------


def pos_to_json(p: Pos) -> str:
    """Serialize a position to canonical JSON: same value -> same bytes."""
    return json.dumps(p.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def pos_from_json(payload: str) -> Pos:
    return Pos.from_dict(json.loads(payload))


def vec_to_json(v: Vec) -> str:
    """Serialize a vector to canonical JSON: same value -> same bytes."""
    return json.dumps(v.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def vec_from_json(payload: str) -> Vec:
    return Vec.from_dict(json.loads(payload))


# --------------------------------------------------------------------------
# Presentation helper (formatting only — never used in state or comparisons)
# --------------------------------------------------------------------------


def format_units(milliunits: int) -> str:
    """Render a milliunit scalar as a fixed-point decimal string (``2375`` ->
    ``"2.375"``). Presentation only — the value stays an integer everywhere
    else. Pure integer arithmetic, no ``float``."""
    sign = "-" if milliunits < 0 else ""
    whole, frac = divmod(abs(milliunits), SCALE)
    return f"{sign}{whole}.{frac:03d}"
