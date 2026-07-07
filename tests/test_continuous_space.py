"""Acceptance tests for the fixed-point spatial core (cycle-7 plan task t1).

Criteria under test (the merge gate for C7-t1):

* Positions are integer-scaled fixed-point values (milliunits) — **no binary
  float** ever appears in any value the spatial types expose, and a scan proves
  it over many hashlib-derived inputs.
* Canonical JSON round-trips a position exactly (byte-identical), sorted+compact
  the same way ``state_to_json`` is.
* The geometry is exact integer arithmetic — squared distance is exact, scalar
  distance is a documented floored integer sqrt, and ``move_toward`` never
  overshoots and clamps to the target exactly on arrival.
* Determinism: identical operations produce identical results (pure integers),
  pinned against a committed golden digest, and subdividing a journey lands on
  the byte-identical target the single-shot move reaches.

The engine-wide AST import ban (``tests/test_engine_state.py``) already scans
``league/engine/`` recursively, so it covers this new package automatically —
that is where ``random``/``time``/``datetime``/``secrets``/``uuid`` are banned.
This file adds the *value*-level float ban the acceptance criterion asks for.
"""

from __future__ import annotations

import ast
import dataclasses
import hashlib
import json
from pathlib import Path

import pytest

from league.engine.continuous import (
    ARRIVAL_TOLERANCE_MU,
    MAX_STEP_UNDERSHOOT_MU,
    SCALE,
    Pos,
    Vec,
    arrived,
    dist,
    dist_sq,
    from_units,
    isqrt,
    move_toward,
    pos_from_json,
    pos_to_json,
    vec_from_json,
    vec_to_json,
)

SPACE_MODULE = (
    Path(__file__).resolve().parent.parent / "league" / "engine" / "continuous" / "space.py"
)


class _Stream:
    """A deterministic integer stream from ``sha256(material || counter)``.

    Mirrors ``genscenario._SeedStream``: pure ``hashlib``, so property cases are
    reproducible across platforms without importing ``random``.
    """

    def __init__(self, material: str) -> None:
        self._material = material.encode("utf-8")
        self._counter = 0

    def _draw(self) -> int:
        digest = hashlib.sha256(self._material + b"|" + str(self._counter).encode("ascii")).digest()
        self._counter += 1
        return int.from_bytes(digest[:8], "big")

    def below(self, upper: int) -> int:
        return self._draw() % upper

    def signed(self, bound: int) -> int:
        """A value in ``[-bound, bound]``."""
        return self.below(2 * bound + 1) - bound


def _iter_values(obj: object):
    """Yield every scalar reachable from a spatial value: dataclass fields,
    ``to_dict`` outputs, and nested containers."""
    if isinstance(obj, (Pos, Vec)):
        for f in dataclasses.fields(obj):
            yield from _iter_values(getattr(obj, f.name))
        yield from _iter_values(obj.to_dict())
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from _iter_values(k)
            yield from _iter_values(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _iter_values(v)
    else:
        yield obj


# -- fixed-point representation ---------------------------------------------


def test_scale_and_constants_are_pinned_ints() -> None:
    assert SCALE == 1000
    assert type(SCALE) is int
    assert type(ARRIVAL_TOLERANCE_MU) is int and ARRIVAL_TOLERANCE_MU >= 0
    assert type(MAX_STEP_UNDERSHOOT_MU) is int and MAX_STEP_UNDERSHOOT_MU >= 1


def test_from_units_scales_by_milliunits() -> None:
    assert from_units(1, 2) == Pos(1000, 2000)
    assert from_units(0, 0) == Pos(0, 0)
    assert from_units(-3, 5) == Pos(-3000, 5000)


def test_pos_and_vec_are_frozen() -> None:
    p = Pos(1, 2)
    v = Vec(3, 4)
    with pytest.raises(dataclasses.FrozenInstanceError):
        p.x = 9  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        v.y = 9  # type: ignore[misc]


# -- no binary floats anywhere the types expose -----------------------------


def test_no_binary_float_in_any_exposed_spatial_value() -> None:
    """The honesty scan: exercise every operation over many derived inputs and
    assert not one exposed scalar is a ``float`` (ints only; bool excluded)."""
    stream = _Stream("c7-t1/float-scan")
    checked = 0
    for _ in range(600):
        a = Pos(stream.signed(50_000), stream.signed(50_000))
        b = Pos(stream.signed(50_000), stream.signed(50_000))
        speed = stream.below(5000)
        duration = stream.below(50)
        produced = [
            a,
            b,
            a - b,
            b - a,
            a + (b - a),
            dist_sq(a, b),
            dist(a, b),
            move_toward(a, b, speed, duration),
            (b - a).length_sq(),
            (b - a).length(),
        ]
        for value in produced:
            for scalar in _iter_values(value):
                assert not isinstance(scalar, float), f"float leaked: {scalar!r} from {value!r}"
                assert not isinstance(scalar, bool)
                assert isinstance(scalar, (int, str)), f"unexpected scalar type {type(scalar)}"
                checked += 1
    assert checked > 0


def test_space_source_has_no_float_literals_or_casts() -> None:
    """Belt-and-suspenders: the module source contains no float literal and no
    ``float(...)`` cast — exactness cannot be undone by a later edit."""
    tree = ast.parse(SPACE_MODULE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant):
            assert not isinstance(node.value, float), f"float literal {node.value!r} in space.py"
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id != "float", "float() cast in space.py"


# -- canonical JSON round-trips exactly -------------------------------------


def test_pos_json_round_trips_byte_identical() -> None:
    stream = _Stream("c7-t1/json")
    for _ in range(400):
        p = Pos(stream.signed(10**9), stream.signed(10**9))
        payload = pos_to_json(p)
        assert payload == json.dumps(
            json.loads(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        restored = pos_from_json(payload)
        assert restored == p
        assert pos_to_json(restored) == payload
        assert type(restored.x) is int and type(restored.y) is int


def test_vec_json_round_trips_byte_identical() -> None:
    v = Vec(-12345, 67890)
    payload = vec_to_json(v)
    assert vec_from_json(payload) == v
    assert vec_to_json(vec_from_json(payload)) == payload


# -- exact integer geometry -------------------------------------------------


def test_isqrt_is_exact_floor() -> None:
    for n in [0, 1, 2, 3, 4, 8, 9, 10, 15, 16, 17, 10**6, 10**12 + 1]:
        r = isqrt(n)
        assert r * r <= n < (r + 1) * (r + 1)
    with pytest.raises(ValueError):
        isqrt(-1)


def test_dist_sq_is_exact_and_symmetric() -> None:
    stream = _Stream("c7-t1/distsq")
    for _ in range(500):
        a = Pos(stream.signed(10**6), stream.signed(10**6))
        b = Pos(stream.signed(10**6), stream.signed(10**6))
        dx, dy = b.x - a.x, b.y - a.y
        assert dist_sq(a, b) == dx * dx + dy * dy
        assert dist_sq(a, b) == dist_sq(b, a)


def test_dist_is_floored_integer_sqrt() -> None:
    stream = _Stream("c7-t1/dist")
    for _ in range(500):
        a = Pos(stream.signed(10**6), stream.signed(10**6))
        b = Pos(stream.signed(10**6), stream.signed(10**6))
        d = dist(a, b)
        dsq = dist_sq(a, b)
        assert d * d <= dsq < (d + 1) * (d + 1)
        assert dist(a, b) == dist(b, a)


# -- movement: exact, monotone, never overshoots ----------------------------


def test_move_toward_never_overshoots_and_moves_closer() -> None:
    stream = _Stream("c7-t1/move")
    for _ in range(1000):
        origin = Pos(stream.signed(200_000), stream.signed(200_000))
        target = Pos(stream.signed(200_000), stream.signed(200_000))
        speed = stream.below(3000)
        duration = stream.below(80)
        travel = speed * duration
        new = move_toward(origin, target, speed, duration)
        # never moves farther from the target than it started
        assert dist_sq(new, target) <= dist_sq(origin, target)
        # never travels more than the budget along the way (no overshoot)
        assert dist(origin, new) <= travel
        # stays within the origin->target bounding box (moved toward, not past)
        lo_x, hi_x = sorted((origin.x, target.x))
        lo_y, hi_y = sorted((origin.y, target.y))
        assert lo_x <= new.x <= hi_x
        assert lo_y <= new.y <= hi_y


def test_move_toward_arrives_exactly_when_budget_suffices() -> None:
    stream = _Stream("c7-t1/arrive")
    for _ in range(500):
        origin = Pos(stream.signed(100_000), stream.signed(100_000))
        target = Pos(stream.signed(100_000), stream.signed(100_000))
        d = dist(origin, target)
        # a budget strictly exceeding the exact distance must land ON target
        new = move_toward(origin, target, speed=d + 2, duration=1)
        assert new == target
        assert arrived(new, target)


def test_zero_budget_or_zero_distance_is_a_noop() -> None:
    p = Pos(1234, -5678)
    assert move_toward(p, Pos(9000, 9000), speed=0, duration=10) == p
    assert move_toward(p, Pos(9000, 9000), speed=10, duration=0) == p
    assert move_toward(p, p, speed=999, duration=999) == p


def test_move_toward_rejects_negative_rate() -> None:
    p, q = Pos(0, 0), Pos(10, 10)
    with pytest.raises(ValueError):
        move_toward(p, q, speed=-1, duration=1)
    with pytest.raises(ValueError):
        move_toward(p, q, speed=1, duration=-1)


# -- subdivision lands on the byte-identical target -------------------------


def test_subdivision_and_single_shot_land_on_identical_target() -> None:
    """The headline exact property: when the total budget reaches the target,
    N small steps and one big step land on the byte-identical integer target.
    Because arrival clamps exactly, the drift in the arrival case is *zero*."""
    stream = _Stream("c7-t1/subdivide")
    for _ in range(200):
        origin = Pos(stream.signed(80_000), stream.signed(80_000))
        target = Pos(stream.signed(80_000), stream.signed(80_000))
        d = dist(origin, target)
        if d == 0:
            continue
        for n in (2, 3, 5, 8, 13):
            # per-step travel that eventually overruns the remaining distance
            step_travel = max(2, d // (n - 1) + 1)
            cur = origin
            for _step in range(n + 2):
                cur = move_toward(cur, target, speed=step_travel, duration=1)
            single = move_toward(origin, target, speed=d + 1, duration=1)
            assert single == target
            assert cur == target  # byte-identical to the single-shot arrival


def test_subdivision_drift_is_bounded_before_arrival() -> None:
    """Before arrival, a subdivided partial journey lags a single-shot partial
    journey by no more than ``steps * MAX_STEP_UNDERSHOOT_MU`` — a pinned,
    documented bound (no float epsilon)."""
    stream = _Stream("c7-t1/drift")
    for _ in range(200):
        origin = Pos(stream.signed(120_000), stream.signed(120_000))
        target = Pos(stream.signed(120_000), stream.signed(120_000))
        d = dist(origin, target)
        if d < 5000:
            continue
        total_travel = d // 2  # partial: guaranteed not to arrive
        n = 10
        step = total_travel // n
        if step < 2:
            continue
        cur = origin
        for _step in range(n):
            cur = move_toward(cur, target, speed=step, duration=1)
        single = move_toward(origin, target, speed=step * n, duration=1)
        # neither arrived; the subdivided endpoint lags but stays within bound
        assert dist_sq(cur, target) > 0
        assert dist(cur, single) <= n * MAX_STEP_UNDERSHOOT_MU


# -- arrival predicate ------------------------------------------------------


def test_arrived_predicate() -> None:
    p = Pos(50_000, 50_000)
    assert arrived(p, p)
    assert arrived(p, Pos(50_000 + ARRIVAL_TOLERANCE_MU, 50_000))
    assert not arrived(p, Pos(50_000 + ARRIVAL_TOLERANCE_MU + 2, 50_000))
    assert not arrived(p, Pos(60_000, 60_000))


# -- vector algebra ---------------------------------------------------------


def test_pos_vec_algebra() -> None:
    a = Pos(1000, 2000)
    b = Pos(4000, 6000)
    v = b - a
    assert v == Vec(3000, 4000)
    assert a + v == b
    assert v.length_sq() == 3000 * 3000 + 4000 * 4000
    assert v.length() == 5000  # exact 3-4-5


# -- pinned cross-platform determinism digest -------------------------------

# Regression anchor: a sha256 over a scripted sequence of pure-integer spatial
# operations. Pure integers are platform-independent, so this digest is stable
# on any machine; a change means the geometry rules changed (update knowingly).
_GOLDEN_SPATIAL_DIGEST = "d412b5a883288985dc18b933f24255db4074a07a07176c44fe5571088963c7dd"


def _scripted_digest() -> str:
    h = hashlib.sha256()
    stream = _Stream("c7-t1/golden-script")
    for _ in range(300):
        origin = Pos(stream.signed(500_000), stream.signed(500_000))
        target = Pos(stream.signed(500_000), stream.signed(500_000))
        speed = stream.below(4000)
        duration = stream.below(120)
        new = move_toward(origin, target, speed, duration)
        row = "|".join(
            str(x)
            for x in (
                new.x,
                new.y,
                dist_sq(origin, target),
                dist(origin, target),
                dist_sq(new, target),
            )
        )
        h.update(row.encode("ascii"))
    return h.hexdigest()


def test_scripted_sequence_matches_committed_digest() -> None:
    assert _scripted_digest() == _GOLDEN_SPATIAL_DIGEST
