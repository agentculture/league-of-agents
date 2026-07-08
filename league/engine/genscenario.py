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
purpose. Cycle-6 task C6-t2 ("board scale and complexity knobs", spec c9)
widened every ceiling below well past season-0's 30-turn, two-scenario board —
sized to actually assess long-running tasks, many agents, and memory, not just
claim scale in the abstract.

===========================  =============  =========  ==================================
field                        range          default    meaning
===========================  =============  =========  ==================================
``grid_width``                9..41 odd     13         board width (odd → one center cell)
``grid_height``                9..41 odd     11         board height (odd → one center cell)
``turn_limit``                 8..200        30         turns before the match closes
``control_point_pairs``        1..8          1          control points = 2 x this (mirrored)
``resource_node_pairs``        1..8          1          resource nodes = 2 x this (mirrored)
``hold_mission_pairs``         0..cp_pairs   1          hold missions = 2 x this (mirrored)
``capture_hold_turns``         1..4          2          sole-occupancy turns to capture
``executor_scale``             1..4          1          harvester/defender COPIES per team
===========================  =============  =========  ==================================

**Odd dimensions are required, not cosmetic.** 180-degree rotational symmetry
has exactly one fixed cell — the board center ``(w//2, h//2)`` — only when both
dimensions are odd; that fixed cell is the single shared, equidistant objective
(the deliver mission). An even dimension is rejected loudly.

**The roster-size knob: ``executor_scale`` (C6-t2, spec c9).** The ROLE SET
stays pinned (scout/harvester/defender, same fixed ``RoleStats`` as before —
scout move 3 / carry 2 / vision 4, strictly the widest vision, spec c12, and
(cycle-8 t10) ``can_capture=False`` — eyes-only, parity with the continuous
lane's cycle-7 amendment, see ``docs/roles.md``; harvester move 2 / carry 3;
defender move 2 / carry 1); what now scales is
roster SIZE. ``executor_scale`` duplicates the two EXECUTOR roles — harvester
and defender, the units that actually run the economy and hold points — this
many times each; the scout stays singular (it is "the eyes of the team", a
role about vantage, not headcount). ``executor_scale=1`` is the original
3-unit roster byte-for-byte (same spawn cluster, same id token — see below);
``executor_scale=4`` fields 1 scout + 4 harvesters + 4 defenders = 9 units per
team (18 on the board), well past "one mind, one seat, one unit" and squarely
into "does a mind's coordination degrade as headcount grows" territory (spec
c10's span-of-control question, from the harness side rather than the
orchestrator side). This was safe to add because both consumers already treat
a unit's role as a lookup key, never an identity: ``league.harness
.make_bot_driver`` groups living units by team and reads ``roles[unit["role"]]``
per unit — nothing assumes one unit per role — and ``scenario.instantiate``'s
role→agent assignment (fixed alongside this task, see ``scenario.py``) now
walks a per-role QUEUE of roster agents instead of a single dict-by-role
mapping, so N agents sharing a role each get their own unit deterministically
in roster order, instead of the dict silently collapsing to the last one.

**What stays deliberately NOT seeded, and why (also a risk-r3 decision).**
Team COUNT stays fixed at exactly two for competitive matches, one for
cooperative — ``scenario.instantiate`` enforces this directly. This is not an
oversight: the whole fairness guarantee this module documents (see below) is
built on 180-degree rotational symmetry, which has exactly ONE natural
mirror-pair partner per side. Generalizing to N>2 teams needs a genuinely
different geometry (e.g. N-fold rotational symmetry, or a non-rotational
fairness argument entirely) plus matching changes to ``tick.py``'s canonical
resolution order assumptions and ``scoring.py``'s win-condition math — a
redesign, not an additive knob, and squarely a later cycle's frame. The
mission economy constants (deliver amount/reward, hold amount/reward, node
stock) also stay fixed. Only board GEOMETRY, OBJECTIVE MIX, and now roster
SIZE (via ``executor_scale``) vary by seed/params — keeping the greedy bot,
the coded-strategy bots, scoring, and the fog projection working on a
generated board with zero (or, for the roster knob, minimally-scoped) code
changes.

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

GRID_MIN, GRID_MAX = 9, 41
TURN_LIMIT_MIN, TURN_LIMIT_MAX = 8, 200
PAIR_MIN, PAIR_MAX = 1, 8
CAPTURE_MIN, CAPTURE_MAX = 1, 4
EXECUTOR_SCALE_MIN, EXECUTOR_SCALE_MAX = 1, 4

# Fixed, non-seeded role vocabulary + economy (a risk-r3 decision, see the
# docstring): kept canonical so the whole CLI/harness/bot/scoring stack plays
# a generated board unchanged. Roster SIZE (how many of each role) is the one
# axis that now scales, via GenParams.executor_scale — see _unit_roles below.
_ROLE_STATS: tuple[tuple[str, RoleStats], ...] = (
    # can_capture=False (cycle-8 t10): the generated scout is eyes-only too —
    # docs/roles.md's Decision section, parity with the continuous lane.
    (
        "scout",
        RoleStats(
            move=3,
            carry=2,
            vision=4,
            can_capture=False,
            analog="the eyes — sees widest of the three, forbidden from capturing "
            "control points (cycle-8 grid eyes-only-scout decision); keeps "
            "gather/carry/deliver untouched",
        ),
    ),
    ("harvester", RoleStats(move=2, carry=3, vision=2)),
    ("defender", RoleStats(move=2, carry=1, vision=2)),
)

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
    executor_scale: int = 1


DEFAULT_PARAMS = GenParams()


def _unit_roles(executor_scale: int) -> tuple[str, ...]:
    """The roster's role vocabulary, in spawn-slot order: one scout (the eyes
    of the team, never duplicated) followed by ``executor_scale`` harvesters
    then ``executor_scale`` defenders. ``executor_scale=1`` reproduces the
    original three-role roster exactly, in the original order."""
    return ("scout",) + ("harvester",) * executor_scale + ("defender",) * executor_scale


def _spawn_cluster(n: int) -> tuple[tuple[int, int], ...]:
    """The first ``n`` cells of a deterministic corner cluster, nearest-to-
    ``(0, 0)`` first: anti-diagonals of increasing ``x + y``, ``x`` descending
    within a diagonal. ``n=3`` reproduces the original hand-picked spawn
    cluster byte-for-byte — ``(0, 0), (1, 0), (0, 1)`` — so
    ``executor_scale=1`` (the default) changes nothing about existing
    generated boards; larger ``n`` (from ``executor_scale`` > 1) extends the
    same cluster outward, compactly, with no gaps."""
    cells: list[tuple[int, int]] = []
    diagonal = 0
    while len(cells) < n:
        for x in range(diagonal, -1, -1):
            if len(cells) >= n:
                break
            cells.append((x, diagonal - x))
        diagonal += 1
    return tuple(cells)


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
    _require(
        EXECUTOR_SCALE_MIN <= params.executor_scale <= EXECUTOR_SCALE_MAX,
        f"executor_scale {params.executor_scale} out of "
        f"range [{EXECUTOR_SCALE_MIN}, {EXECUTOR_SCALE_MAX}]",
    )
    return params


# -- scenario identity: seed + params, fully encoded, id-safe ---------------
#
# The token uses one letter per field so it round-trips unambiguously and stays
# inside league.store.validate_id's alphabet (letters/digits/'-'): "gen-<seed>-
# w<W>y<H>t<TL>c<CPP>r<RNP>m<HMP>k<CAP>[e<ES>]". Distinct letters (y for
# height, m for hold-mission pairs) avoid the two-'h' ambiguity a naive scheme
# would hit. ``e<ES>`` (C6-t2's roster-scale knob) is OPTIONAL and trailing —
# emitted only when ``executor_scale != 1`` (see params_token) — so every id
# minted before this task, and every default-roster id minted after it, is
# byte-for-byte unchanged: backward compatibility by construction, not a
# version segment (parse_generated_id defaults a missing segment to 1).

_TOKEN_RE = re.compile(r"^w(\d+)y(\d+)t(\d+)c(\d+)r(\d+)m(\d+)k(\d+)(?:e(\d+))?$")
_ID_RE = re.compile(r"^gen-(\d+)-(w\d+y\d+t\d+c\d+r\d+m\d+k\d+(?:e\d+)?)$")


def params_token(params: GenParams) -> str:
    """The reversible ``w…y…t…c…r…m…k…[e…]`` encoding of ``params`` (no seed).

    The trailing ``e<executor_scale>`` segment is OMITTED entirely when
    ``executor_scale == 1`` (the default) — so a default-roster scenario's id
    is identical to what it was before this field existed.
    """
    token = (
        f"w{params.grid_width}y{params.grid_height}t{params.turn_limit}"
        f"c{params.control_point_pairs}r{params.resource_node_pairs}"
        f"m{params.hold_mission_pairs}k{params.capture_hold_turns}"
    )
    if params.executor_scale != 1:
        token += f"e{params.executor_scale}"
    return token


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
    groups = token_match.groups()
    fields = [int(g) for g in groups[:7]]
    # The trailing executor_scale segment is optional (absent → default 1) —
    # every id minted before C6-t2, and every default-roster id minted since,
    # parses identically (see params_token's omission rule above).
    executor_scale = int(groups[7]) if groups[7] is not None else 1
    params = GenParams(
        grid_width=fields[0],
        grid_height=fields[1],
        turn_limit=fields[2],
        control_point_pairs=fields[3],
        resource_node_pairs=fields[4],
        hold_mission_pairs=fields[5],
        capture_hold_turns=fields[6],
        executor_scale=executor_scale,
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
    ``(seed, params)``. Raises ``ValueError`` on out-of-range params, a spawn
    cluster too big for the grid, or a board too small for the requested
    objective count."""
    params = validate_params(params)
    width, height = params.grid_width, params.grid_height
    center = (width // 2, height // 2)
    sid = scenario_id(seed, params)
    # The id already encodes seed+params, so it is the perfect stream material:
    # identical scenarios draw identically, distinct ones diverge.
    stream = _SeedStream(sid)

    unit_roles = _unit_roles(params.executor_scale)
    spawn0 = _spawn_cluster(len(unit_roles))
    _require(
        all(0 <= x < width and 0 <= y < height for x, y in spawn0),
        f"grid {width}x{height} too small for executor_scale "
        f"{params.executor_scale} (a {len(unit_roles)}-unit roster needs more "
        "room near the corner)",
    )
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

    roster_note = (
        f" Roster: 1 scout + {params.executor_scale} harvester(s) + "
        f"{params.executor_scale} defender(s) per team ({len(unit_roles)} units)."
        if params.executor_scale != 1
        else ""
    )
    return Scenario(
        id=sid,
        name=f"Generated {width}x{height} — seed {seed}",
        description=(
            f"Seed-{seed} mirror-symmetric board: {width}x{height} grid, "
            f"{len(control_points)} control points, {len(resource_nodes)} resource "
            f"nodes, 1 deliver + {2 * params.hold_mission_pairs} hold mission(s). "
            "180-degree rotational symmetry — team spawns and every objective "
            f"mirror through the center, so both teams face an identical board.{roster_note}"
        ),
        grid_width=width,
        grid_height=height,
        turn_limit=params.turn_limit,
        modes=MODES,
        capture_hold_turns=params.capture_hold_turns,
        unit_roles=unit_roles,
        role_stats=_ROLE_STATS,
        spawns=(spawn0, spawn1),
        control_points=tuple(control_points),
        missions=tuple(missions),
        resource_nodes=tuple(resource_nodes),
    )
