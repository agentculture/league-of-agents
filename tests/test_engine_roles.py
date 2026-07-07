"""Acceptance tests for the coding-reflective roles (cycle-6 task C6-t3).

The engine gains two NEW roles — ``explorer`` and ``planner`` — that mirror
real coding work as *engine-enforced capability contracts* (not prompt
convention, spec honesty h11):

* **explorer** = reconnaissance / code-reading — extended vision and reach,
  but it CANNOT gather resources and its occupancy never builds or contests a
  control-point capture streak. Both restrictions are rejected/ignored by the
  tick AND absent from ``legal_actions`` — the two must agree both ways.
* **planner** = architect / tech-lead — weak on the board alone (move 1,
  carry 0, baseline vision, cannot gather, cannot capture); it wins by
  coordinating through the EXISTING plan/message channels, no new mechanics.

Binding decision (plan risk r4, pinned JOIN not replace): scout / harvester /
defender keep their exact stats and behaviour; the new roles are additive, and
the ``skirmish-1`` determinism fixture stays byte-identical (asserted here and
by ``tests/test_determinism_gate.py``).
"""

from __future__ import annotations

import dataclasses

import pytest

from league.engine.legal import legal_actions
from league.engine.scenario import get_scenario, instantiate, scenario_ids
from league.engine.state import AgentSlot, MatchState
from league.engine.tick import resolve_turn, start_match

RECON = get_scenario("recon-1")

# recon-1 unit ids follow scenario role order (see scenario.instantiate):
#   u1 explorer, u2 planner, u3 harvester, u4 defender. The AgentSlot id is
# "<team>-<role>"; the Unit id is the positional "<team>-u<n>".
_ROLES = ("explorer", "planner", "harvester", "defender")
_UNIT_SUFFIX = {role: f"u{i + 1}" for i, role in enumerate(_ROLES)}


def _uid(team: str, role: str) -> str:
    return f"{team}-{_UNIT_SUFFIX[role]}"


def _roster(team: str, model: str = "colleague/qwen") -> tuple[AgentSlot, ...]:
    return tuple(AgentSlot(id=f"{team}-{r}", model=model, role=r) for r in _ROLES)


def _recon_match(mode: str = "competitive") -> MatchState:
    if mode == "competitive":
        teams = (
            ("blue", "Blue Foundry", _roster("blue")),
            ("red", "Red Relay", _roster("red", model="claude-sonnet-5")),
        )
    else:
        teams = (("blue", "Blue Foundry", _roster("blue")),)
    state = instantiate(RECON, match_id="m-recon", seed=11, mode=mode, teams=teams)
    state, _ = start_match(state)
    return state


def _place(state: MatchState, unit_id: str, pos, **fields) -> MatchState:
    units = tuple(
        dataclasses.replace(u, pos=pos, **fields) if u.id == unit_id else u for u in state.units
    )
    return dataclasses.replace(state, units=units)


def _rejections(events) -> list[str]:
    return [e.data["reason"] for e in events if e.kind == "action_rejected"]


# -- role-stats / capability data -------------------------------------------


def test_recon_scenario_is_registered_and_rosters_new_roles_with_executors() -> None:
    assert "recon-1" in scenario_ids()
    assert set(RECON.unit_roles) == {"explorer", "planner", "harvester", "defender"}
    assert set(RECON.modes) == {"cooperative", "competitive"}
    # It instantiates and starts like any other scenario.
    state = _recon_match()
    assert state.status == "active"
    assert {u.role for u in state.units if u.team_id == "blue"} == set(_ROLES)


def test_existing_roles_keep_their_stats_and_default_capabilities() -> None:
    """JOIN, not replace: scout/harvester/defender are byte-for-byte unchanged
    and default to the pre-existing behaviour (can gather, can capture)."""
    for sid in ("skirmish-1", "skirmish-2"):
        scenario = get_scenario(sid)
        for role in ("scout", "harvester", "defender"):
            stats = scenario.stats_for(role)
            assert stats.can_gather is True
            assert stats.can_capture is True
    s1 = get_scenario("skirmish-1")
    assert (
        s1.stats_for("scout").move,
        s1.stats_for("scout").carry,
        s1.stats_for("scout").vision,
    ) == (
        3,
        1,
        4,
    )


def test_explorer_has_extended_vision_and_reach() -> None:
    ex = RECON.stats_for("explorer")
    others = [RECON.stats_for(r) for r in ("planner", "harvester", "defender")]
    assert all(ex.vision > o.vision for o in others), "explorer must see farther than every peer"
    assert all(ex.move > o.move for o in others), "explorer must reach farther than every peer"
    assert ex.carry == 0
    assert ex.can_gather is False and ex.can_capture is False
    assert ex.analog  # a documented software-work analog string


def test_planner_is_weak_alone_with_baseline_vision_and_no_field_power() -> None:
    pl = RECON.stats_for("planner")
    baseline = RECON.stats_for("defender").vision
    assert pl.vision == baseline, "planner gets no special sight — coordination is its edge"
    assert pl.vision < RECON.stats_for("explorer").vision
    assert pl.move == 1 and pl.carry == 0
    assert pl.can_gather is False and pl.can_capture is False
    assert pl.analog


# -- explorer: gather is illegal both ways ----------------------------------


def test_explorer_gather_illegal_in_legal_actions_and_rejected_by_tick() -> None:
    state = _recon_match()
    # rn-low sits at (5, 5); park the explorer on it with room to spare.
    state = _place(state, _uid("blue", "explorer"), (5, 5), carrying=0)

    legal = legal_actions(state, RECON, _uid("blue", "explorer"))
    assert legal["gather"] is False
    assert legal["can_gather"] is False

    _, events = resolve_turn(
        state,
        RECON,
        {"blue": {"actions": [{"unit_id": _uid("blue", "explorer"), "action": "gather"}]}},
    )
    assert _rejections(events) == ["this role cannot gather resources"]
    assert not any(e.kind == "resource_gathered" for e in events)


def test_harvester_gather_on_same_node_is_legal_and_resolves() -> None:
    """The both-ways contrast: an executor on the very same node is legal in
    legal_actions AND resolves with no rejection (everything legal resolves)."""
    state = _recon_match()
    state = _place(state, _uid("blue", "harvester"), (5, 5), carrying=0)

    legal = legal_actions(state, RECON, _uid("blue", "harvester"))
    assert legal["gather"] is True
    assert legal["can_gather"] is True

    _, events = resolve_turn(
        state,
        RECON,
        {"blue": {"actions": [{"unit_id": _uid("blue", "harvester"), "action": "gather"}]}},
    )
    assert _rejections(events) == []
    assert any(e.kind == "resource_gathered" for e in events)


# -- explorer: capture/hold is illegal both ways ----------------------------


def test_explorer_occupancy_never_builds_a_capture_streak() -> None:
    state = _recon_match()
    state = _place(state, _uid("blue", "explorer"), (7, 5))  # cp-alpha

    legal = legal_actions(state, RECON, _uid("blue", "explorer"))
    assert legal["can_capture"] is False

    captured = False
    for _ in range(RECON.capture_hold_turns + 1):
        state, events = resolve_turn(
            state,
            RECON,
            {"blue": {"actions": [{"unit_id": _uid("blue", "explorer"), "action": "hold"}]}},
        )
        if any(e.kind == "control_point_captured" for e in events):
            captured = True
    assert not captured
    cp = next(c for c in state.control_points if c.pos == (7, 5))
    assert cp.owner is None
    assert cp.hold == ()


def test_defender_alone_on_the_same_point_does_capture() -> None:
    """Both-ways contrast for capture: an executor holding the identical square
    builds the streak and captures — proving the explorer rule is a real,
    role-scoped restriction, not a broken control point."""
    state = _recon_match()
    state = _place(state, _uid("blue", "defender"), (7, 5))  # cp-alpha

    legal = legal_actions(state, RECON, _uid("blue", "defender"))
    assert legal["can_capture"] is True

    captured_at = None
    for i in range(RECON.capture_hold_turns):
        state, events = resolve_turn(
            state,
            RECON,
            {"blue": {"actions": [{"unit_id": _uid("blue", "defender"), "action": "hold"}]}},
        )
        if any(e.kind == "control_point_captured" for e in events):
            captured_at = i + 1
    assert captured_at == RECON.capture_hold_turns
    cp = next(c for c in state.control_points if c.pos == (7, 5))
    assert cp.owner == "blue"


def test_enemy_explorer_does_not_contest_a_capture_streak() -> None:
    """An explorer never counts as an occupant: it can neither build a streak
    NOR contest one. A blue defender captures with an enemy explorer standing
    on the point; the same setup with an enemy *defender* resets the streak."""
    # Explorer present: streak survives and captures.
    state = _recon_match()
    state = _place(state, _uid("blue", "defender"), (7, 5))
    state = _place(state, _uid("red", "explorer"), (7, 5))
    captured = False
    for _ in range(RECON.capture_hold_turns):
        state, events = resolve_turn(
            state,
            RECON,
            {"blue": {"actions": [{"unit_id": _uid("blue", "defender"), "action": "hold"}]}},
        )
        if any(e.kind == "control_point_captured" for e in events):
            captured = True
    assert captured
    assert next(c for c in state.control_points if c.pos == (7, 5)).owner == "blue"

    # Same board but an enemy *defender* (a capturer) contests → streak resets.
    state = _recon_match()
    state = _place(state, _uid("blue", "defender"), (7, 5))
    state, _ = resolve_turn(
        state,
        RECON,
        {"blue": {"actions": [{"unit_id": _uid("blue", "defender"), "action": "hold"}]}},
    )
    assert next(c for c in state.control_points if c.pos == (7, 5)).hold == (("blue", 1),)
    state = _place(state, _uid("red", "defender"), (7, 5))
    state, _ = resolve_turn(
        state,
        RECON,
        {"blue": {"actions": [{"unit_id": _uid("blue", "defender"), "action": "hold"}]}},
    )
    cp = next(c for c in state.control_points if c.pos == (7, 5))
    assert cp.hold == ()
    assert cp.owner is None


# -- planner: coordination is its real function -----------------------------


def test_planner_cannot_gather_or_capture_but_coordinates_through_channels() -> None:
    state = _recon_match()
    # On a node: gather illegal both ways.
    state = _place(state, _uid("blue", "planner"), (5, 5), carrying=0)
    legal = legal_actions(state, RECON, _uid("blue", "planner"))
    assert legal["gather"] is False and legal["can_gather"] is False
    assert legal["can_capture"] is False

    # The planner's real power: hand a plan + a message to teammates through
    # the EXISTING channels while it holds. All three must land on the record,
    # and the planner's own hold must not be rejected.
    _, events = resolve_turn(
        state,
        RECON,
        {
            "blue": {
                "plan": "explorer scouts the beacon; harvester relays; defender holds cp-alpha",
                "messages": [{"from": "blue-planner", "text": "relay through (6,6)"}],
                "actions": [
                    {"unit_id": _uid("blue", "planner"), "action": "gather"},
                    {"unit_id": _uid("blue", "harvester"), "action": "hold"},
                ],
            }
        },
    )
    kinds = [e.kind for e in events]
    assert "plan_declared" in kinds
    assert "message_sent" in kinds
    assert _rejections(events) == ["this role cannot gather resources"]


def test_planner_occupancy_never_builds_a_capture_streak() -> None:
    state = _recon_match("cooperative")
    state = _place(state, _uid("blue", "planner"), (7, 5))
    for _ in range(RECON.capture_hold_turns + 1):
        state, events = resolve_turn(
            state,
            RECON,
            {"blue": {"actions": [{"unit_id": _uid("blue", "planner"), "action": "hold"}]}},
        )
        assert not any(e.kind == "control_point_captured" for e in events)
    cp = next(c for c in state.control_points if c.pos == (7, 5))
    assert cp.owner is None and cp.hold == ()


# -- universal: everything legal_actions offers actually resolves ------------


def test_every_legal_move_and_hold_resolves_for_recon_roles() -> None:
    """The other half of 'agree both ways': every move legal_actions offers a
    recon-1 unit resolves with no rejection, for all four roles including the
    new explorer/planner."""
    state = _recon_match()
    for unit in [u for u in state.units if u.team_id == "blue"]:
        legal = legal_actions(state, RECON, unit.id)
        # hold is always legal and always resolves.
        _, ev = resolve_turn(
            state, RECON, {"blue": {"actions": [{"unit_id": unit.id, "action": "hold"}]}}
        )
        assert _rejections(ev) == []
        # every offered move target resolves too.
        for target in legal["move"]:
            _, ev = resolve_turn(
                state,
                RECON,
                {"blue": {"actions": [{"unit_id": unit.id, "action": "move", "to": target}]}},
            )
            assert _rejections(ev) == [], f"{unit.role} move to {target} was offered but rejected"


def test_recon_determinism_hash_is_unaffected_by_the_new_roles() -> None:
    """Adding roles/scenarios must not perturb the committed skirmish-1 match —
    RoleStats is scenario config, never part of MatchState/state_hash."""
    from tests.test_determinism_gate import FIXTURE, compute_final_hash

    if FIXTURE.is_file():
        assert compute_final_hash() == FIXTURE.read_text(encoding="utf-8").strip()


def test_unknown_role_lookup_stays_loud() -> None:
    with pytest.raises(ValueError):
        RECON.stats_for("wizard")
