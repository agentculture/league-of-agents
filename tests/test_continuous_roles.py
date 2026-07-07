"""Acceptance tests for continuous-lane role speed/duration data (plan C7-t4).

These are the merge gate for ``league/engine/continuous/roles.py``. Written
before the implementation (TDD), they pin the two acceptance criteria:

1. Continuous role stats carry in-game speed (``move_rate_mu``, milliunits per
   game-time unit) and per-action durations (``gather_duration``,
   ``take_post_duration``, ``deliver_duration``, in game-time units) as pure
   role DATA. The coding-reflective roster (explorer/planner, cycle 6) gets
   continuous stats consistent with its grid capability contract
   (``league/engine/scenario.py``'s ``RoleStats``, ``docs/roles.md``): explorer
   is strictly fastest and widest-sighted and cannot gather or take posts;
   planner is strictly slowest and coordination-only; scout/harvester/defender
   are executor-class, in between, with harvester the only high-carry role.
2. Role data is scenario-declared and hash-covered: :class:`CRoleStats` is a
   frozen dataclass, :data:`DEFAULT_CROLE_STATS` is the default table, and
   :func:`build_role_table` is a validated override mechanism a scenario (t6)
   will use to field a different speed table *without code changes*. A test
   proves two different tables produce different hashes when folded into an
   otherwise byte-identical :class:`~league.engine.continuous.CMatchState`.

Forbidden-action convention (documented + enforced here, loudly): a role that
cannot perform an action pairs ``can_gather=False``/``can_take_post=False``
with a **zero** duration for that action; a role that CAN perform it must have
a strictly positive duration (an allowed action that takes no time is a
modeling bug, not a fast role). The same convention extends to ``deliver``
via ``carry`` — there is no separate ``can_deliver`` flag (a role that can
never carry cargo, ``carry == 0``, has no meaningful delivery duration either)
so ``carry == 0`` <-> ``deliver_duration == 0`` is enforced the same way.
"""

from __future__ import annotations

import hashlib

import pytest

from league.engine.continuous import (
    MAX_STEP_UNDERSHOOT_MU,
    CAgentSlot,
    CMatchState,
    CRoleStats,
    CTeamState,
    CUnit,
    build_role_table,
    cstate_hash,
    cstate_to_json,
    from_units,
    stats_for,
)
from league.engine.continuous.roles import (
    DEFAULT_CROLE_STATS,
    role_table_hash,
    role_table_to_json,
)

_DEFAULT_ROLE_NAMES = {name for name, _ in DEFAULT_CROLE_STATS}


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _base_kwargs(**overrides: object) -> dict:
    """A valid CRoleStats kwargs set (executor-class shape), overridable per test."""
    kwargs: dict = dict(
        move_rate_mu=500,
        vision_mu=2000,
        carry=1,
        gather_duration=8,
        take_post_duration=8,
        deliver_duration=8,
        can_gather=True,
        can_take_post=True,
        analog="test executor",
    )
    kwargs.update(overrides)
    return kwargs


def _minimal_state(role_of_unit: str = "scout") -> CMatchState:
    """A tiny, otherwise-fixed CMatchState — used to prove role-table hash
    coverage without depending on anything role-table-shaped being in state."""
    return CMatchState(
        match_id="cm-roles-0001",
        scenario_id="roles-fixture",
        seed=7,
        mode="cooperative",
        clock=0,
        time_limit=1000,
        width=10 * 1000,
        height=10 * 1000,
        status="active",
        winner=None,
        teams=(
            CTeamState(
                id="blue",
                name="Blue",
                resources=0,
                agents=(CAgentSlot(id="blue-a1", model="claude-sonnet-5", role=role_of_unit),),
            ),
        ),
        units=(
            CUnit(
                id="blue-u1",
                team_id="blue",
                agent_id="blue-a1",
                role=role_of_unit,
                pos=from_units(0, 0),
            ),
        ),
        control_points=(),
        missions=(),
        resource_nodes=(),
    )


# --------------------------------------------------------------------------- #
# Criterion 1a — the default coding-reflective roster, shape and ranking
# --------------------------------------------------------------------------- #
def test_default_table_has_the_five_coding_reflective_roles() -> None:
    assert _DEFAULT_ROLE_NAMES == {"explorer", "planner", "scout", "harvester", "defender"}


def test_explorer_is_strictly_fastest_and_widest_and_cannot_gather_or_take_post() -> None:
    explorer = stats_for(DEFAULT_CROLE_STATS, "explorer")
    others = [stats for name, stats in DEFAULT_CROLE_STATS if name != "explorer"]

    assert all(explorer.move_rate_mu > o.move_rate_mu for o in others)
    assert all(explorer.vision_mu > o.vision_mu for o in others)
    assert explorer.carry == 0
    assert explorer.can_gather is False
    assert explorer.can_take_post is False
    assert explorer.gather_duration == 0
    assert explorer.take_post_duration == 0
    assert explorer.deliver_duration == 0


def test_planner_is_strictly_slowest_and_coordination_only() -> None:
    planner = stats_for(DEFAULT_CROLE_STATS, "planner")
    others = [stats for name, stats in DEFAULT_CROLE_STATS if name != "planner"]

    assert all(planner.move_rate_mu < o.move_rate_mu for o in others)
    assert planner.carry == 0
    assert planner.can_gather is False
    assert planner.can_take_post is False
    assert planner.gather_duration == 0
    assert planner.take_post_duration == 0
    assert planner.deliver_duration == 0


def test_harvester_is_the_only_high_carry_role() -> None:
    harvester = stats_for(DEFAULT_CROLE_STATS, "harvester")
    others = [stats for name, stats in DEFAULT_CROLE_STATS if name != "harvester"]

    assert all(harvester.carry > o.carry for o in others)


def test_executor_class_roles_can_act_and_have_positive_durations() -> None:
    for role in ("scout", "harvester", "defender"):
        stats = stats_for(DEFAULT_CROLE_STATS, role)
        assert stats.can_gather is True
        assert stats.can_take_post is True
        assert stats.gather_duration > 0
        assert stats.take_post_duration > 0
        assert stats.deliver_duration > 0
        assert stats.carry > 0
        # executor class sits strictly between explorer and planner in speed.
        assert stats_for(DEFAULT_CROLE_STATS, "planner").move_rate_mu < stats.move_rate_mu
        assert stats.move_rate_mu < stats_for(DEFAULT_CROLE_STATS, "explorer").move_rate_mu


# --------------------------------------------------------------------------- #
# Criterion 1b — the grain warning (space.py): a real single-action displacement
# --------------------------------------------------------------------------- #
def test_every_role_produces_real_progress_over_the_shortest_action_duration() -> None:
    """The smallest nonzero duration ANYWHERE in the table is the shortest slice
    of game time any role's move could be measured over; even the slowest mover
    (planner) must cover well more than MAX_STEP_UNDERSHOOT_MU (3 mu) in that
    slice, or the fixed-point grain could swallow a real action's movement."""
    nonzero_durations = [
        d
        for _, stats in DEFAULT_CROLE_STATS
        for d in (stats.gather_duration, stats.take_post_duration, stats.deliver_duration)
        if d > 0
    ]
    assert nonzero_durations, "expected at least one role with a positive action duration"
    shortest = min(nonzero_durations)

    for name, stats in DEFAULT_CROLE_STATS:
        progress = stats.move_rate_mu * shortest
        assert progress > MAX_STEP_UNDERSHOOT_MU * 10, (
            f"{name}: move_rate_mu({stats.move_rate_mu}) * shortest_duration({shortest}) "
            f"= {progress} mu is not well above the grain (MAX_STEP_UNDERSHOOT_MU="
            f"{MAX_STEP_UNDERSHOOT_MU})"
        )


# --------------------------------------------------------------------------- #
# Validation — negative/zero rates, forbidden-action convention, loud lookup
# --------------------------------------------------------------------------- #
def test_zero_or_negative_move_rate_rejected() -> None:
    with pytest.raises(ValueError):
        CRoleStats(**_base_kwargs(move_rate_mu=0))
    with pytest.raises(ValueError):
        CRoleStats(**_base_kwargs(move_rate_mu=-5))


def test_zero_or_negative_vision_rejected() -> None:
    with pytest.raises(ValueError):
        CRoleStats(**_base_kwargs(vision_mu=0))
    with pytest.raises(ValueError):
        CRoleStats(**_base_kwargs(vision_mu=-1))


def test_negative_carry_rejected() -> None:
    with pytest.raises(ValueError):
        CRoleStats(**_base_kwargs(carry=-1))


@pytest.mark.parametrize(
    "flag_field,duration_field",
    [("can_gather", "gather_duration"), ("can_take_post", "take_post_duration")],
)
def test_forbidden_action_with_nonzero_duration_rejected(flag_field, duration_field) -> None:
    kwargs = _base_kwargs(**{flag_field: False, duration_field: 5})
    with pytest.raises(ValueError):
        CRoleStats(**kwargs)


@pytest.mark.parametrize(
    "flag_field,duration_field",
    [("can_gather", "gather_duration"), ("can_take_post", "take_post_duration")],
)
def test_permitted_action_with_zero_duration_rejected(flag_field, duration_field) -> None:
    kwargs = _base_kwargs(**{flag_field: True, duration_field: 0})
    with pytest.raises(ValueError):
        CRoleStats(**kwargs)


def test_zero_carry_with_nonzero_deliver_duration_rejected() -> None:
    with pytest.raises(ValueError):
        CRoleStats(**_base_kwargs(carry=0, deliver_duration=5))


def test_positive_carry_with_zero_deliver_duration_rejected() -> None:
    with pytest.raises(ValueError):
        CRoleStats(**_base_kwargs(carry=1, deliver_duration=0))


def test_negative_durations_rejected() -> None:
    with pytest.raises(ValueError):
        CRoleStats(**_base_kwargs(gather_duration=-1))
    with pytest.raises(ValueError):
        CRoleStats(**_base_kwargs(take_post_duration=-1))
    with pytest.raises(ValueError):
        CRoleStats(**_base_kwargs(deliver_duration=-1))


def test_unknown_role_lookup_is_loud() -> None:
    with pytest.raises(ValueError, match="wizard"):
        stats_for(DEFAULT_CROLE_STATS, "wizard")


# --------------------------------------------------------------------------- #
# Criterion 2 — scenario-declared, validated override mechanism
# --------------------------------------------------------------------------- #
def test_build_role_table_with_no_overrides_returns_the_default_table() -> None:
    assert build_role_table() == DEFAULT_CROLE_STATS
    assert build_role_table(None) == DEFAULT_CROLE_STATS


def test_build_role_table_override_replaces_one_role_leaving_others_untouched() -> None:
    faster_harvester = CRoleStats(**_base_kwargs(move_rate_mu=999, carry=3))
    table = build_role_table({"harvester": faster_harvester})

    assert stats_for(table, "harvester") == faster_harvester
    # every other role is byte-identical to the default table's entry.
    for name, stats in DEFAULT_CROLE_STATS:
        if name != "harvester":
            assert stats_for(table, name) == stats


def test_build_role_table_can_introduce_a_brand_new_role() -> None:
    table = build_role_table({"skirmisher": CRoleStats(**_base_kwargs())})
    assert stats_for(table, "skirmisher") == CRoleStats(**_base_kwargs())
    # the default roster is otherwise untouched.
    for name, stats in DEFAULT_CROLE_STATS:
        assert stats_for(table, name) == stats


def test_build_role_table_rejects_non_mapping_overrides() -> None:
    with pytest.raises(ValueError):
        build_role_table([("harvester", CRoleStats(**_base_kwargs()))])  # type: ignore[arg-type]


def test_build_role_table_rejects_non_crolestats_override_value() -> None:
    with pytest.raises(ValueError):
        build_role_table({"harvester": {"move_rate_mu": 999}})  # type: ignore[dict-item]


def test_build_role_table_rejects_empty_role_name() -> None:
    with pytest.raises(ValueError):
        build_role_table({"": CRoleStats(**_base_kwargs())})


# --------------------------------------------------------------------------- #
# Criterion 2 — canonical JSON + hash coverage
# --------------------------------------------------------------------------- #
def test_role_table_to_json_is_order_independent_and_deterministic() -> None:
    table_a = tuple(DEFAULT_CROLE_STATS)
    table_b = tuple(reversed(DEFAULT_CROLE_STATS))

    assert role_table_to_json(table_a) == role_table_to_json(table_b)
    # calling twice on the same table produces byte-identical output.
    assert role_table_to_json(table_a) == role_table_to_json(table_a)


def test_role_table_hash_is_stable_for_an_equal_table() -> None:
    rebuilt = build_role_table()
    assert role_table_hash(DEFAULT_CROLE_STATS) == role_table_hash(rebuilt)


def test_role_table_hash_changes_when_a_role_stat_changes() -> None:
    tweaked = build_role_table({"scout": CRoleStats(**_base_kwargs(move_rate_mu=751))})
    assert role_table_hash(tweaked) != role_table_hash(DEFAULT_CROLE_STATS)


def test_two_scenarios_with_different_speed_tables_hash_differently_for_identical_states() -> None:
    """The acceptance test: fold each role table's canonical JSON alongside an
    OTHERWISE BYTE-IDENTICAL CMatchState's canonical JSON. The plain state hash
    alone is identical (CMatchState carries no role data yet — wiring that in
    is t6's job), but the combined fingerprint a scenario-aware hash (t6) would
    compute differs solely because the role tables differ, proving two
    scenarios CAN field different speed tables without any code change."""
    state = _minimal_state(role_of_unit="scout")

    table_a = DEFAULT_CROLE_STATS
    table_b = build_role_table({"scout": CRoleStats(**_base_kwargs(move_rate_mu=1500))})
    assert table_a != table_b  # the two tables are genuinely different

    # the bare state hash does not yet see role data at all (t6 wires this in).
    assert cstate_hash(state) == cstate_hash(state)

    combined_a = cstate_to_json(state) + role_table_to_json(table_a)
    combined_b = cstate_to_json(state) + role_table_to_json(table_b)
    assert combined_a != combined_b

    hash_a = hashlib.sha256(combined_a.encode("utf-8")).hexdigest()
    hash_b = hashlib.sha256(combined_b.encode("utf-8")).hexdigest()
    assert hash_a != hash_b
