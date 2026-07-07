"""The seeded scenario generator — novelty from a seed, byte-identical rematch.

A generated scenario is a pure function of ``(seed, params)``: the same pair
always rebuilds the *same* board (canonical JSON equality), a different seed
draws a *structurally different* board, and NO runtime randomness is used —
the engine-wide import ban (``tests/test_engine_state.py::
test_engine_never_imports_time_or_random``) stands, so pseudo-randomness is
derived from ``hashlib.sha256(id || counter)`` (:class:`_SeedStream`), never
the ``random`` module.

Scenario identity IS the seed+params: a generated scenario's ``id`` fully
encodes both (:func:`scenario_id` / :func:`parse_generated_id`), so
``get_scenario`` (``league.engine.scenario``) re-derives any generated board
from its id alone. That single registry hook is why the whole CLI / harness /
replay / scoring stack plays a generated board unchanged — ``match new
--scenario gen-… --apply`` resolves, and because the id lands in the match
log header's ``initial_state.scenario_id``, every match is re-creatable from
its log alone (acceptance criterion 2, proven in
``tests/test_engine_genscenario.py``).

The pinned parameter space (plan risk r3 — "the parameter space you pin here
IS the decision")
------------------------------------------------------------------------------
``GenParams`` is the whole knob set; ranges and defaults are pinned here on
purpose.

===========================  ==========  =========  ==================================
field                        range       default    meaning
===========================  ==========  =========  ==================================
``grid_width``               9..21 odd   13         board width (odd → one center cell)
``grid_height``              9..21 odd   11         board height (odd → one center cell)
``turn_limit``               8..80       30         turns before the match closes
``control_point_pairs``      1..4        1          control points = 2 x this (mirrored)
``resource_node_pairs``      1..4        1          resource nodes = 2 x this (mirrored)
``hold_mission_pairs``       0..cp_pairs 1          hold missions = 2 x this (mirrored)
``capture_hold_turns``       1..4        2          sole-occupancy turns to capture
===========================  ==========  =========  ==================================

**Odd dimensions are required, not cosmetic.** 180-degree rotational symmetry
has exactly one fixed cell — the board center ``(w//2, h//2)`` — only when both
dimensions are odd; that fixed cell is the single shared, equidistant objective
(the deliver mission). An even dimension is rejected loudly.

**What is deliberately NOT seeded (also a risk-r3 decision).** The roster is
pinned to the canonical two-team, scout/harvester/defender composition with
fixed role stats (scout move 3 / carry 2 / vision 4 — strictly the widest
vision, spec c12; harvester move 2 / carry 3; defender move 2 / carry 1), and
the mission economy constants (deliver amount/reward, hold amount/reward, node
stock) are fixed. Only board GEOMETRY and OBJECTIVE MIX vary by seed/params.
This keeps the greedy bot, the coded-strategy bots, scoring, and the fog
projection working on a generated board with zero code changes; widening the
roster/team-count axis is a later cycle's frame, not this one's.

The fairness guarantee
----------------------
Because resolution is canonical-order ``(team_id, unit_id)``, fairness has to
be POSITIONAL. Every generated board is invariant under "reflect through the
center + swap the two teams": team 1's spawn cluster is the 180-degree rotation
of team 0's, and the set of every objective (control points, resource nodes,
hold-mission squares) is rotation-invariant, with the deliver mission on the
rotation-fixed center. Consequences, asserted as property tests over many
seeds: the deliver mission is exactly equidistant from both teams' spawns, each
team is equidistant to its own near member of every mirrored pair, and the
per-team multiset of spawn→objective distances is identical. Team 1 plays team
0's board, rotated.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from league.engine.scenario import RoleStats, Scenario
from league.engine.state import ControlPoint, Mission, ResourceNode

# -- the pinned parameter space (see the module docstring) ------------------

GRID_MIN, GRID_MAX = 9, 21
TURN_LIMIT_MIN, TURN_LIMIT_MAX = 8, 80
PAIR_MIN, PAIR_MAX = 1, 4
CAPTURE_MIN, CAPTURE_MAX = 1, 4

# Fixed, non-seeded roster + economy (a risk-r3 decision, see the docstring):
# kept canonical so the whole CLI/harness/bot/scoring stack plays a generated
# board unchanged.
_ROSTER_ROLES: tuple[str, ...] = ("scout", "harvester", "defender")
_ROLE_STATS: tuple[tuple[str, RoleStats], ...] = (
    ("scout", RoleStats(move=3, carry=2, vision=4)),
    ("harvester", RoleStats(move=2, carry=3, vision=2)),
    ("defender", RoleStats(move=2, carry=1, vision=2)),
)
# One corner cell per roster role, in role order; team 1 is the rotation of it.
_SPAWN_CLUSTER: tuple[tuple[int, int], ...] = ((0, 0), (1, 0), (0, 1))

_DELIVER_AMOUNT, _DELIVER_REWARD = 6, 10
_HOLD_AMOUNT, _HOLD_REWARD = 3, 8
_NODE_STOCK = 12

MODES: tuple[str, ...] = ("cooperative", "competitive")


@dataclass(frozen=True)
class GenParams:
    """The seeded generator's whole knob set (ranges/defaults in the module
    docstring). Frozen and hashable so a scenario is a pure function of it."""

    grid_width: int = 13
    grid_height: int = 11
    turn_limit: int = 30
    control_point_pairs: int = 1
    resource_node_pairs: int = 1
    hold_mission_pairs: int = 1
    capture_hold_turns: int = 2


DEFAULT_PARAMS = GenParams()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(f"invalid scenario params: {message}")


def validate_params(params: GenParams) -> GenParams:
    """Raise ``ValueError`` (loud, named fix) on anything outside the pinned
    space; return the params unchanged when valid."""
    _require(
        GRID_MIN <= params.grid_width <= GRID_MAX,
        f"grid_width {params.grid_width} out of range [{GRID_MIN}, {GRID_MAX}]",
    )
    _require(params.grid_width % 2 == 1, "grid_width must be odd (a single center cell)")
    _require(
        GRID_MIN <= params.grid_height <= GRID_MAX,
        f"grid_height {params.grid_height} out of range [{GRID_MIN}, {GRID_MAX}]",
    )
    _require(params.grid_height % 2 == 1, "grid_height must be odd (a single center cell)")
    _require(
        TURN_LIMIT_MIN <= params.turn_limit <= TURN_LIMIT_MAX,
        f"turn_limit {params.turn_limit} out of range [{TURN_LIMIT_MIN}, {TURN_LIMIT_MAX}]",
    )
    _require(
        PAIR_MIN <= params.control_point_pairs <= PAIR_MAX,
        f"control_point_pairs {params.control_point_pairs} out of range [{PAIR_MIN}, {PAIR_MAX}]",
    )
    _require(
        PAIR_MIN <= params.resource_node_pairs <= PAIR_MAX,
        f"resource_node_pairs {params.resource_node_pairs} out of range [{PAIR_MIN}, {PAIR_MAX}]",
    )
    _require(
        0 <= params.hold_mission_pairs <= params.control_point_pairs,
        f"hold_mission_pairs {params.hold_mission_pairs} out of "
        f"[0, control_point_pairs={params.control_point_pairs}]",
    )
    _require(
        CAPTURE_MIN <= params.capture_hold_turns <= CAPTURE_MAX,
        f"capture_hold_turns {params.capture_hold_turns} out of "
        f"range [{CAPTURE_MIN}, {CAPTURE_MAX}]",
    )
    return params


# -- scenario identity: seed + params, fully encoded, id-safe ---------------
#
# The token uses one letter per field so it round-trips unambiguously and stays
# inside league.store.validate_id's alphabet (letters/digits/'-'): "gen-<seed>-
# w<W>y<H>t<TL>c<CPP>r<RNP>m<HMP>k<CAP>". Distinct letters (y for height, m for
# hold-mission pairs) avoid the two-'h' ambiguity a naive scheme would hit.

_TOKEN_RE = re.compile(r"^w(\d+)y(\d+)t(\d+)c(\d+)r(\d+)m(\d+)k(\d+)$")
_ID_RE = re.compile(r"^gen-(\d+)-(w\d+y\d+t\d+c\d+r\d+m\d+k\d+)$")


def params_token(params: GenParams) -> str:
    """The reversible ``w…y…t…c…r…m…k…`` encoding of ``params`` (no seed)."""
    return (
        f"w{params.grid_width}y{params.grid_height}t{params.turn_limit}"
        f"c{params.control_point_pairs}r{params.resource_node_pairs}"
        f"m{params.hold_mission_pairs}k{params.capture_hold_turns}"
    )


def scenario_id(seed: int, params: GenParams = DEFAULT_PARAMS) -> str:
    """The stable id for the scenario ``generate(seed, params)`` produces.

    Fully encodes seed+params, so it is both the ``match new --scenario`` handle
    and the sole record needed to re-derive the board from a log.
    """
    seed = int(seed)
    _require(seed >= 0, f"seed must be a non-negative int, got {seed}")
    return f"gen-{seed}-{params_token(validate_params(params))}"


def parse_generated_id(candidate: str) -> tuple[int, GenParams] | None:
    """``gen-<seed>-<token>`` → ``(seed, params)``; ``None`` if not that grammar.

    Grammar match only — RANGE validation is left to :func:`generate` /
    :func:`validate_params` so a structurally-valid-but-out-of-range id (e.g. an
    even width) surfaces the precise "grid_width must be odd" error rather than
    a misleading "unknown scenario".
    """
    match = _ID_RE.match(candidate)
    if match is None:
        return None
    token_match = _TOKEN_RE.match(match.group(2))
    if token_match is None:  # pragma: no cover - _ID_RE already guarantees it
        return None
    fields = [int(g) for g in token_match.groups()]
    params = GenParams(
        grid_width=fields[0],
        grid_height=fields[1],
        turn_limit=fields[2],
        control_point_pairs=fields[3],
        resource_node_pairs=fields[4],
        hold_mission_pairs=fields[5],
        capture_hold_turns=fields[6],
    )
    return int(match.group(1)), params


# -- seed-derived pseudo-randomness, hashlib only (no random/secrets) --------


class _SeedStream:
    """A deterministic integer stream from ``sha256(material || counter)``.

    Pure ``hashlib`` — the engine import ban forbids ``random``/``secrets``, and
    a fixed material string means the same scenario id always draws the same
    sequence. Modulo bias is irrelevant here: determinism, not statistical
    uniformity, is the property that matters for board layout.
    """

    def __init__(self, material: str) -> None:
        self._material = material.encode("utf-8")
        self._counter = 0

    def _draw(self) -> int:
        digest = hashlib.sha256(self._material + b"|" + str(self._counter).encode("ascii")).digest()
        self._counter += 1
        return int.from_bytes(digest[:8], "big")

    def below(self, upper: int) -> int:
        """A value in ``[0, upper)``; ``upper`` must be positive."""
        return self._draw() % upper


# -- geometry ---------------------------------------------------------------


def rotate180(pos: tuple[int, int], width: int, height: int) -> tuple[int, int]:
    """The 180-degree rotation of ``pos`` about the board center — an involution
    that preserves Manhattan distance, the backbone of the fairness guarantee."""
    return (width - 1 - pos[0], height - 1 - pos[1])


def _first_half_cells(width: int, height: int) -> list[tuple[int, int]]:
    """One representative per mirror pair: cells strictly before their own
    rotation in ``(x, y)`` order. Excludes the self-symmetric center, so every
    representative pairs with a distinct partner. Deterministic order."""
    cells: list[tuple[int, int]] = []
    for x in range(width):
        for y in range(height):
            cell = (x, y)
            if cell < rotate180(cell, width, height):
                cells.append(cell)
    return cells


# -- generation -------------------------------------------------------------


def generate(seed: int, params: GenParams = DEFAULT_PARAMS) -> Scenario:
    """Build the deterministic, mirror-symmetric :class:`Scenario` for
    ``(seed, params)``. Raises ``ValueError`` on out-of-range params or a board
    too small for the requested objective count."""
    params = validate_params(params)
    width, height = params.grid_width, params.grid_height
    center = (width // 2, height // 2)
    sid = scenario_id(seed, params)
    # The id already encodes seed+params, so it is the perfect stream material:
    # identical scenarios draw identically, distinct ones diverge.
    stream = _SeedStream(sid)

    spawn0 = _SPAWN_CLUSTER
    spawn1 = tuple(rotate180(cell, width, height) for cell in spawn0)
    occupied: set[tuple[int, int]] = set(spawn0) | set(spawn1) | {center}
    half = _first_half_cells(width, height)

    def pick_pair() -> tuple[tuple[int, int], tuple[int, int]]:
        candidates = [
            cell
            for cell in half
            if cell not in occupied and rotate180(cell, width, height) not in occupied
        ]
        _require(bool(candidates), "board too small for the requested objective count")
        chosen = candidates[stream.below(len(candidates))]
        mirror = rotate180(chosen, width, height)
        occupied.add(chosen)
        occupied.add(mirror)
        return chosen, mirror

    cp_pairs = [pick_pair() for _ in range(params.control_point_pairs)]
    rn_pairs = [pick_pair() for _ in range(params.resource_node_pairs)]

    control_points: list[ControlPoint] = []
    for index, (near, far) in enumerate(cp_pairs, start=1):
        control_points.append(ControlPoint(id=f"cp-{index}a", pos=near))
        control_points.append(ControlPoint(id=f"cp-{index}b", pos=far))

    resource_nodes: list[ResourceNode] = []
    for index, (near, far) in enumerate(rn_pairs, start=1):
        resource_nodes.append(ResourceNode(id=f"rn-{index}a", pos=near, remaining=_NODE_STOCK))
        resource_nodes.append(ResourceNode(id=f"rn-{index}b", pos=far, remaining=_NODE_STOCK))

    # The single shared, equidistant objective sits on the rotation-fixed
    # center; every hold objective is a mirrored pair on a control-point pair.
    missions: list[Mission] = [
        Mission(
            id="ms-deliver",
            kind="deliver",
            pos=center,
            amount=_DELIVER_AMOUNT,
            reward=_DELIVER_REWARD,
        )
    ]
    for index in range(params.hold_mission_pairs):
        near, far = cp_pairs[index]
        missions.append(
            Mission(
                id=f"ms-hold-{index + 1}a",
                kind="hold",
                pos=near,
                amount=_HOLD_AMOUNT,
                reward=_HOLD_REWARD,
            )
        )
        missions.append(
            Mission(
                id=f"ms-hold-{index + 1}b",
                kind="hold",
                pos=far,
                amount=_HOLD_AMOUNT,
                reward=_HOLD_REWARD,
            )
        )

    return Scenario(
        id=sid,
        name=f"Generated {width}x{height} — seed {seed}",
        description=(
            f"Seed-{seed} mirror-symmetric board: {width}x{height} grid, "
            f"{len(control_points)} control points, {len(resource_nodes)} resource "
            f"nodes, 1 deliver + {2 * params.hold_mission_pairs} hold mission(s). "
            "180-degree rotational symmetry — team spawns and every objective "
            "mirror through the center, so both teams face an identical board."
        ),
        grid_width=width,
        grid_height=height,
        turn_limit=params.turn_limit,
        modes=MODES,
        capture_hold_turns=params.capture_hold_turns,
        unit_roles=_ROSTER_ROLES,
        role_stats=_ROLE_STATS,
        spawns=(spawn0, spawn1),
        control_points=tuple(control_points),
        missions=tuple(missions),
        resource_nodes=tuple(resource_nodes),
    )
