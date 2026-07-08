"""``c-frontier-1`` — the cycle-8 fogged-frontier scenario (plan C8-t12).

Every bound below is computed from the scenario's own positions and role
stats via ``move_duration``'s exact integer math — never a hard-coded
duration — mirroring ``test_continuous_scenario.py``'s discipline, so
retuning the board or the role table re-checks the inequalities instead of
silently invalidating the claims in the module docstring.
"""

from __future__ import annotations

import league.charness as charness
from league.engine.continuous.legal import move_duration
from league.engine.continuous.scenario import cscenario_ids, get_cscenario, instantiate
from league.engine.continuous.space import dist_sq, from_units
from league.engine.continuous.state import CAgentSlot


def _frontier():
    return get_cscenario("c-frontier-1")


def _roster(team: str) -> tuple[CAgentSlot, ...]:
    return tuple(
        CAgentSlot(id=f"{team}-{role}", model="claude-sonnet", role=role)
        for role in ("scout", "harvester", "defender")
    )


def _move(scn, src, dst) -> int:
    return move_duration(dist_sq(src, dst), scn.stats_for("defender").move_rate_mu)


def test_frontier_registers_and_instantiates_three_units_per_team() -> None:
    assert "c-frontier-1" in cscenario_ids()
    scn = _frontier()
    state = instantiate(
        scn,
        mode="competitive",
        seed=1,
        match_id="c-frontier-smoke",
        teams=(("blue", "Blue", _roster("blue")), ("red", "Red", _roster("red"))),
    )
    assert len(state.units) == 6
    roles = sorted(u.role for u in state.units if u.team_id == "blue")
    assert roles == ["defender", "harvester", "scout"]


def test_the_head_on_race_is_asymmetric_by_exactly_one_time_unit() -> None:
    """Blue's defender completes its take at t=12; red's at t=13 — the
    deliberate asymmetry that pushes red toward the delivery contest."""
    scn = _frontier()
    (cp,) = scn.control_points
    take = scn.stats_for("defender").take_post_duration
    blue_done = _move(scn, scn.spawns[0][2], cp.pos) + take
    red_done = _move(scn, scn.spawns[1][2], cp.pos) + take
    assert blue_done == 12
    assert red_done == 13
    assert red_done - blue_done == 1


def test_red_defender_reaches_the_shared_bank_before_any_delivery() -> None:
    """The camp is live from t=6 — seventeen time units before a beelining
    harvester's earliest delivery completion at t=23."""
    scn = _frontier()
    supply = next(m for m in scn.missions if m.kind == "deliver")
    camp_at = _move(scn, scn.spawns[1][2], supply.pos)
    harvester = scn.stats_for("harvester")
    harvest_move = move_duration(dist_sq(scn.spawns[0][1], supply.pos), harvester.move_rate_mu)
    earliest_delivery = harvester.gather_duration + harvest_move + harvester.deliver_duration
    assert camp_at == 6
    assert earliest_delivery == 23
    assert camp_at < earliest_delivery


def test_no_single_unit_completes_both_missions_within_the_limit() -> None:
    scn = _frontier()
    (cp,) = scn.control_points
    supply = next(m for m in scn.missions if m.kind == "deliver")
    node = scn.resource_nodes[0]

    d = scn.stats_for("defender")
    defender_serial = (
        _move(scn, scn.spawns[0][2], cp.pos)
        + d.take_post_duration
        + move_duration(dist_sq(cp.pos, node.pos), d.move_rate_mu)
        + d.gather_duration
        + move_duration(dist_sq(node.pos, supply.pos), d.move_rate_mu)
        + d.deliver_duration
    )
    assert defender_serial == 47
    assert defender_serial > scn.time_limit

    h = scn.stats_for("harvester")
    harvester_serial = (
        h.gather_duration
        + move_duration(dist_sq(scn.spawns[0][1], supply.pos), h.move_rate_mu)
        + h.deliver_duration
        + move_duration(dist_sq(supply.pos, cp.pos), h.move_rate_mu)
        + h.take_post_duration
    )
    assert harvester_serial == 35
    assert harvester_serial > scn.time_limit

    assert scn.stats_for("scout").can_take_post is False


def test_fog_lever_only_a_scout_sees_the_camped_bank() -> None:
    """A unit standing on the shared delivery square is inside a mid-board
    scout's 4000 mu vision and outside every executor's 2000 mu vision from
    their natural positions — computed from the scenario's own geometry."""
    scn = _frontier()
    supply = next(m for m in scn.missions if m.kind == "deliver")
    table = dict(scn.role_table)

    scout_post = from_units(5, 4)
    assert dist_sq(scout_post, supply.pos) <= table["scout"].vision_mu ** 2

    blue_spawns = scn.spawns[0]
    for role, spawn in (("harvester", blue_spawns[1]), ("defender", blue_spawns[2])):
        assert dist_sq(spawn, supply.pos) > table[role].vision_mu ** 2


def test_fog_briefing_hides_the_camped_bank_without_the_scout() -> None:
    """End to end through the real briefing path: the same red defender camped
    on the shared square is in the blue scout's fogged board and absent from a
    scoutless blue team's fogged board."""
    scn = _frontier()
    supply = next(m for m in scn.missions if m.kind == "deliver")
    state = instantiate(
        scn,
        mode="competitive",
        seed=1,
        match_id="c-frontier-fog",
        teams=(("blue", "Blue", _roster("blue")), ("red", "Red", _roster("red"))),
    )
    # move blue's scout to its mid-board post and camp red's defender on the bank
    import dataclasses

    units = []
    for u in state.units:
        if u.role == "scout" and u.team_id == "blue":
            u = dataclasses.replace(u, pos=from_units(5, 4))
        if u.role == "defender" and u.team_id == "red":
            u = dataclasses.replace(u, pos=supply.pos)
        units.append(u)
    state = dataclasses.replace(state, units=tuple(units))

    blue_scout = next(u for u in state.units if u.team_id == "blue" and u.role == "scout")
    blue_harvester = next(u for u in state.units if u.team_id == "blue" and u.role == "harvester")
    red_defender = next(u for u in state.units if u.team_id == "red" and u.role == "defender")

    briefing = charness.build_briefing(
        state, blue_scout.id, {"actions": []}, fog=True, role_table=scn.role_table
    )
    seen_ids = {u["id"] for u in briefing["board"]["units"]}
    assert red_defender.id in seen_ids

    # the harvester's own briefing also sees it (team union) — but a team
    # whose scout is elsewhere/absent must not: drop the scout to the far
    # corner so no blue unit covers the square
    units = tuple(
        dataclasses.replace(u, pos=from_units(0, 0)) if u.id == blue_scout.id else u
        for u in state.units
    )
    state_no_eyes = dataclasses.replace(state, units=units)
    blind = charness.build_briefing(
        state_no_eyes, blue_harvester.id, {"actions": []}, fog=True, role_table=scn.role_table
    )
    blind_ids = {u["id"] for u in blind["board"]["units"]}
    assert red_defender.id not in blind_ids
