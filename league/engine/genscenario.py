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

from league.engine.scenario import EarlyEnd, RoleStats, Scenario
from league.engine.state import ControlPoint, Crown, Mission, ResourceNode

# -- the pinned parameter space (see the module docstring) ------------------

GRID_MIN, GRID_MAX = 9, 41
TURN_LIMIT_MIN, TURN_LIMIT_MAX = 8, 200
PAIR_MIN, PAIR_MAX = 1, 8
CAPTURE_MIN, CAPTURE_MAX = 1, 4
EXECUTOR_SCALE_MIN, EXECUTOR_SCALE_MAX = 1, 4
NODE_STOCK_MIN, NODE_STOCK_MAX = 1, 40
DELIVER_AMOUNT_MIN, DELIVER_AMOUNT_MAX = 1, 80
CROWN_VALUE_MIN, CROWN_VALUE_MAX = 1, 40
CROWN_TURNS_MIN, CROWN_TURNS_MAX = 1, 20
THIEVES_MIN, THIEVES_MAX = 0, 2
CP_VISION_MIN, CP_VISION_MAX = 0, 4
EARLY_PCT_MIN, EARLY_PCT_MAX = 1, 100
EARLY_TURNS_MIN, EARLY_TURNS_MAX = 1, 10
_EARLY_TURNS, _EARLY_FROM = 3, 20
_CROWN_TURNS = 5

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

# The thief (2026-11-06), fielded only when GenParams.thieves > 0 so every
# thief-free board keeps its exact role table. Fast and light: it cannot
# gather or capture; it takes one unit of cargo from an enemy unit on its cell
# (blocked by an enemy defender there) and delivers like anyone else.
_THIEF_STATS = RoleStats(
    move=3,
    carry=1,
    vision=3,
    can_gather=False,
    can_capture=False,
    can_steal=True,
    analog="the raider — steals one unit of cargo from an enemy unit on its cell "
    "unless an enemy defender is there; cannot gather or capture",
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
    # Economy and turning-point knobs (2026-11-06). Defaults reproduce the
    # pre-existing economy exactly and add no crown, so every older id still
    # names the same board.
    node_stock: int = 12  # resources per node (scarcity)
    deliver_amount: int = 6  # resources the deliver mission needs
    crown_value: int = 0  # 0 = no crown; N = "The Crown" on the center, worth N once taken
    crown_turns: int = _CROWN_TURNS  # consecutive sole-occupancy turns to take the crown
    thieves: int = 0  # thieves per team (0 = no thief role on the board)
    # Early end: 0 = off; N = end when the lead is >= N% of the most the gap
    # could still close by, for early_end_turns turns in a row from turn
    # early_end_from (an out-of-reach lead always ends it when this is on).
    # Home delivery: 0 = one shared deliver mission on the center; 1 = each
    # team delivers at its own spawn corner, for its own deliver mission.
    home_delivery: int = 0
    # Control-point vision radius (0 = off): an owned point watches its area.
    cp_vision: int = 0
    early_end_pct: int = 0
    early_end_turns: int = _EARLY_TURNS
    early_end_from: int = _EARLY_FROM
    # Burden: 1 = a unit carrying cargo moves 1 less (never below 1); 0 = off.
    cargo_slows: int = 0


DEFAULT_PARAMS = GenParams()


def _unit_roles(executor_scale: int, thieves: int = 0) -> tuple[str, ...]:
    """The roster's role vocabulary, in spawn-slot order: one scout (the eyes
    of the team, never duplicated) followed by ``executor_scale`` harvesters
    then ``executor_scale`` defenders. ``executor_scale=1`` reproduces the
    original three-role roster exactly, in the original order."""
    return (
        ("scout",)
        + ("harvester",) * executor_scale
        + ("defender",) * executor_scale
        + ("thief",) * thieves
    )


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
    _require(
        NODE_STOCK_MIN <= params.node_stock <= NODE_STOCK_MAX,
        f"node_stock {params.node_stock} out of range [{NODE_STOCK_MIN}, {NODE_STOCK_MAX}]",
    )
    _require(
        DELIVER_AMOUNT_MIN <= params.deliver_amount <= DELIVER_AMOUNT_MAX,
        f"deliver_amount {params.deliver_amount} out of "
        f"range [{DELIVER_AMOUNT_MIN}, {DELIVER_AMOUNT_MAX}]",
    )
    _require(
        params.crown_value == 0 or CROWN_VALUE_MIN <= params.crown_value <= CROWN_VALUE_MAX,
        f"crown_value {params.crown_value} must be 0 (no crown) or in "
        f"[{CROWN_VALUE_MIN}, {CROWN_VALUE_MAX}]",
    )
    _require(
        CROWN_TURNS_MIN <= params.crown_turns <= CROWN_TURNS_MAX,
        f"crown_turns {params.crown_turns} out of range [{CROWN_TURNS_MIN}, {CROWN_TURNS_MAX}]",
    )
    _require(
        THIEVES_MIN <= params.thieves <= THIEVES_MAX,
        f"thieves {params.thieves} out of range [{THIEVES_MIN}, {THIEVES_MAX}]",
    )
    _require(
        CP_VISION_MIN <= params.cp_vision <= CP_VISION_MAX,
        f"cp_vision {params.cp_vision} out of range [{CP_VISION_MIN}, {CP_VISION_MAX}]",
    )
    _require(
        params.cargo_slows in (0, 1),
        f"cargo_slows {params.cargo_slows} must be 0 (off) or 1 (carrying slows by 1)",
    )
    _require(
        params.home_delivery in (0, 1),
        f"home_delivery {params.home_delivery} must be 0 (shared, center) or 1 (home corners)",
    )
    _require(
        params.early_end_pct == 0 or EARLY_PCT_MIN <= params.early_end_pct <= EARLY_PCT_MAX,
        f"early_end_pct {params.early_end_pct} must be 0 (off) or in "
        f"[{EARLY_PCT_MIN}, {EARLY_PCT_MAX}]",
    )
    _require(
        EARLY_TURNS_MIN <= params.early_end_turns <= EARLY_TURNS_MAX,
        f"early_end_turns {params.early_end_turns} out of "
        f"range [{EARLY_TURNS_MIN}, {EARLY_TURNS_MAX}]",
    )
    _require(
        not params.early_end_pct or 0 <= params.early_end_from <= params.turn_limit,
        f"early_end_from {params.early_end_from} out of [0, turn_limit={params.turn_limit}]",
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

# Further optional trailing segments, each emitted only when not default and
# always in this order: s<node_stock> d<deliver_amount> x<crown_value> z<crown_turns>
# f<thieves> h<home_delivery> o<cp_vision> q<early_end_pct> j<early_end_turns> v<early_end_from>
# b<cargo_slows>.
_TOKEN_RE = re.compile(
    r"^w(\d+)y(\d+)t(\d+)c(\d+)r(\d+)m(\d+)k(\d+)"
    r"(?:e(\d+))?(?:s(\d+))?(?:d(\d+))?(?:x(\d+))?(?:z(\d+))?(?:f(\d+))?(?:h(\d+))?(?:o(\d+))?"
    r"(?:q(\d+))?(?:j(\d+))?(?:v(\d+))?(?:b(\d+))?$"
)
_ID_RE = re.compile(
    r"^gen-(\d+)-(w\d+y\d+t\d+c\d+r\d+m\d+k\d+"
    r"(?:e\d+)?(?:s\d+)?(?:d\d+)?(?:x\d+)?(?:z\d+)?(?:f\d+)?(?:h\d+)?(?:o\d+)?"
    r"(?:q\d+)?(?:j\d+)?(?:v\d+)?(?:b\d+)?)$"
)


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
    if params.node_stock != _NODE_STOCK:
        token += f"s{params.node_stock}"
    if params.deliver_amount != _DELIVER_AMOUNT:
        token += f"d{params.deliver_amount}"
    if params.crown_value:
        token += f"x{params.crown_value}"
    if params.crown_turns != _CROWN_TURNS:
        token += f"z{params.crown_turns}"
    if params.thieves:
        token += f"f{params.thieves}"
    if params.home_delivery:
        token += f"h{params.home_delivery}"
    if params.cp_vision:
        token += f"o{params.cp_vision}"
    if params.early_end_pct:
        token += f"q{params.early_end_pct}"
    if params.early_end_turns != _EARLY_TURNS:
        token += f"j{params.early_end_turns}"
    if params.early_end_from != _EARLY_FROM:
        token += f"v{params.early_end_from}"
    if params.cargo_slows:
        token += f"b{params.cargo_slows}"
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
        node_stock=int(groups[8]) if groups[8] is not None else _NODE_STOCK,
        deliver_amount=int(groups[9]) if groups[9] is not None else _DELIVER_AMOUNT,
        crown_value=int(groups[10]) if groups[10] is not None else 0,
        crown_turns=int(groups[11]) if groups[11] is not None else _CROWN_TURNS,
        thieves=int(groups[12]) if groups[12] is not None else 0,
        home_delivery=int(groups[13]) if groups[13] is not None else 0,
        cp_vision=int(groups[14]) if groups[14] is not None else 0,
        early_end_pct=int(groups[15]) if groups[15] is not None else 0,
        early_end_turns=int(groups[16]) if groups[16] is not None else _EARLY_TURNS,
        early_end_from=int(groups[17]) if groups[17] is not None else _EARLY_FROM,
        cargo_slows=int(groups[18]) if groups[18] is not None else 0,
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

    unit_roles = _unit_roles(params.executor_scale, params.thieves)
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
        resource_nodes.append(
            ResourceNode(id=f"rn-{index}a", pos=near, remaining=params.node_stock)
        )
        resource_nodes.append(ResourceNode(id=f"rn-{index}b", pos=far, remaining=params.node_stock))

    # The single shared, equidistant objective sits on the rotation-fixed
    # center; every hold objective is a mirrored pair on a control-point pair.
    # With home_delivery, each side instead owns a deliver mission on its own
    # spawn corner (a mirrored pair, so still fair).
    if params.home_delivery:
        missions: list[Mission] = [
            Mission(
                id=f"ms-deliver-{tag}",
                kind="deliver",
                pos=spawn[0],
                amount=params.deliver_amount,
                reward=_DELIVER_REWARD,
                side=side,
            )
            for side, (tag, spawn) in enumerate((("a", spawn0), ("b", spawn1)))
        ]
    else:
        missions = [
            Mission(
                id="ms-deliver",
                kind="deliver",
                pos=center,
                amount=params.deliver_amount,
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
        f"{params.executor_scale} defender(s)"
        + (f" + {params.thieves} thief(s)" if params.thieves else "")
        + f" per team ({len(unit_roles)} units)."
        if params.executor_scale != 1 or params.thieves
        else ""
    )
    crown = None
    crown_note = ""
    if params.crown_value:
        # The Crown sits on the rotation-fixed center, equidistant from both
        # teams (shared with the deliver mission unless home_delivery is on).
        crown = Crown(pos=center, value=params.crown_value, hold_turns=params.crown_turns)
        crown_note = (
            f" The Crown sits on the center cell: {params.crown_value} points to the "
            f"first team to hold it alone for {params.crown_turns} consecutive turns."
        )
    home_note = (
        " Each team delivers at its own spawn corner, for its own deliver mission."
        if params.home_delivery
        else ""
    )
    cp_note = (
        f" An owned control point watches every cell within {params.cp_vision} of it "
        "for its owner, from capture until it is captured back."
        if params.cp_vision
        else ""
    )
    burden_note = (
        " Burden: a unit carrying any cargo moves 1 cell less than its role's move "
        "stat (never below 1)."
        if params.cargo_slows
        else ""
    )
    early_end = None
    early_note = ""
    if params.early_end_pct:
        early_end = EarlyEnd(
            ratio_pct=params.early_end_pct,
            turns=params.early_end_turns,
            from_turn=params.early_end_from,
        )
        early_note = (
            f" Early end: an out-of-reach lead ends the match; so does a lead of at "
            f"least {params.early_end_pct}% of the most the gap could still close by, "
            f"held {params.early_end_turns} turns in a row from turn {params.early_end_from}."
        )
    return Scenario(
        id=sid,
        name=f"Generated {width}x{height} — seed {seed}",
        description=(
            f"Seed-{seed} mirror-symmetric board: {width}x{height} grid, "
            f"{len(control_points)} control points, {len(resource_nodes)} resource "
            f"nodes, {2 if params.home_delivery else 1} deliver + "
            f"{2 * params.hold_mission_pairs} hold mission(s). "
            "180-degree rotational symmetry — team spawns and every objective "
            "mirror through the center, so both teams face an identical board."
            f"{roster_note}{home_note}{cp_note}{burden_note}{crown_note}{early_note}"
        ),
        grid_width=width,
        grid_height=height,
        turn_limit=params.turn_limit,
        modes=MODES,
        capture_hold_turns=params.capture_hold_turns,
        unit_roles=unit_roles,
        role_stats=_ROLE_STATS + ((("thief", _THIEF_STATS),) if params.thieves else ()),
        spawns=(spawn0, spawn1),
        control_points=tuple(control_points),
        missions=tuple(missions),
        resource_nodes=tuple(resource_nodes),
        crown=crown,
        early_end=early_end,
        cp_vision=params.cp_vision,
        cargo_slows=bool(params.cargo_slows),
    )
