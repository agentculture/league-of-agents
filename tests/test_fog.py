"""Continuous fog mode — briefings filtered by the team's union of per-role
vision radii (plan C8-t5, spec c11/h2/c7/c4).

Merge gate for the "continuous fog" section of ``league/charness.py``.
Written before the implementation (TDD). Pins:

1. **Inclusion at the boundary and exclusion past it** (a hand-placed board):
   an entity sitting EXACTLY at a vision-providing unit's radius is visible;
   one milliunit further is not — the boundary is inclusive
   (``dist_sq <= vision_mu ** 2``), matching ``space.arrived``'s own ``<=``
   convention.
2. **The scout lever**: an entity inside the scout's vision (4000 mu) but
   outside a non-scout executor's (2000 mu) is visible to a scout-bearing
   team and invisible to the identical team with a non-scout unit standing
   in the scout's place.
3. **Projection, never mutation**: a driver that ignores the briefing
   entirely (so fog cannot influence what it does) produces a BYTE-IDENTICAL
   log whether fog is on or off — the engine, the log, and (by extension)
   replay/scoring never see fog at all.
4. **Default OFF / backward compatibility**: omitting ``fog`` (from a direct
   ``build_briefing`` call or from a match config) behaves exactly as before
   this task.
5. **Menu honesty**: a ``move`` entry toward a not-yet-discovered point of
   interest is absent from the menu under fog; ``gather``/``take_post``
   entries for an entity the unit is already standing at are never filtered
   (the unit's own presence trivially makes them visible); the initiative
   ``outlook`` drops an invisible enemy unit's entry the same way the board
   does; teammate ``messages`` are never filtered by fog at all.
"""

from __future__ import annotations

from typing import Any, Mapping

import league.charness as charness
from league.charness import build_briefing, run_cmatch
from league.engine.continuous import (
    CAction,
    CAgentSlot,
    CControlPoint,
    CMatchState,
    CMission,
    CResourceNode,
    CTeamState,
    CUnit,
    Pos,
    build_role_table,
    cstate_hash,
    from_units,
    legal_actions_continuous,
)

ROLE_TABLE = build_role_table()


# --------------------------------------------------------------------------- #
# Builders (self-contained — this file owns its own fixtures rather than
# importing tests/test_continuous_harness.py's, mirroring that file's own
# convention of not sharing builders across continuous-lane test modules).
# --------------------------------------------------------------------------- #
def _slot(uid, role):
    return CAgentSlot(id=uid, model="colleague/qwen", role=role)


def _team(tid, name, roster):
    return CTeamState(id=tid, name=name, resources=0, agents=tuple(roster))


def _unit(uid, team, role, pos, *, carrying=0, action=None):
    return CUnit(
        id=uid, team_id=team, agent_id=uid, role=role, pos=pos, carrying=carrying, action=action
    )


def _state(
    *,
    mode="competitive",
    teams,
    units,
    control_points=(),
    missions=(),
    resource_nodes=(),
    time_limit=1000,
):
    return CMatchState(
        match_id="cm-fog",
        scenario_id="fog-test",
        seed=1,
        mode=mode,
        clock=0,
        time_limit=time_limit,
        width=200000,
        height=200000,
        status="pending",
        winner=None,
        teams=tuple(teams),
        units=tuple(units),
        control_points=tuple(control_points),
        missions=tuple(missions),
        resource_nodes=tuple(resource_nodes),
    )


def _briefing_for(state, unit_id, *, fog, menu=None):
    menu = menu if menu is not None else legal_actions_continuous(state, ROLE_TABLE, unit_id)
    return build_briefing(state, unit_id, menu, fog=fog, role_table=ROLE_TABLE)


def _ids(entries):
    return {e["id"] for e in entries}


# --------------------------------------------------------------------------- #
# Criterion 1 — inclusion at the boundary, exclusion just past it
# --------------------------------------------------------------------------- #
def test_board_includes_an_entity_exactly_at_the_vision_radius():
    """defender vision_mu is 2000; an enemy control point exactly 2000 mu away
    (dist_sq == vision_mu**2, the exact boundary) is INCLUDED — inclusive."""
    state = _state(
        teams=(_team("blue", "Blue", (_slot("blue-def", "defender"),)),),
        units=(_unit("blue-def", "blue", "defender", Pos(0, 0)),),
        control_points=(CControlPoint(id="cp-in", pos=Pos(2000, 0)),),
    )
    briefing = _briefing_for(state, "blue-def", fog=True)
    assert _ids(briefing["board"]["control_points"]) == {"cp-in"}


def test_board_excludes_an_entity_one_milliunit_past_the_vision_radius():
    """The same setup, but the control point sits at 2001 mu — one milliunit
    past the boundary — and is EXCLUDED."""
    state = _state(
        teams=(_team("blue", "Blue", (_slot("blue-def", "defender"),)),),
        units=(_unit("blue-def", "blue", "defender", Pos(0, 0)),),
        control_points=(CControlPoint(id="cp-out", pos=Pos(2001, 0)),),
    )
    briefing = _briefing_for(state, "blue-def", fog=True)
    assert briefing["board"]["control_points"] == []


def test_boundary_holds_for_resource_nodes_and_missions_too():
    """The same inclusive-boundary rule applies to every spatial board list,
    not just control points."""
    state = _state(
        teams=(_team("blue", "Blue", (_slot("blue-def", "defender"),)),),
        units=(_unit("blue-def", "blue", "defender", Pos(0, 0)),),
        resource_nodes=(
            CResourceNode(id="node-in", pos=Pos(0, 2000), remaining=5),
            CResourceNode(id="node-out", pos=Pos(0, 2001), remaining=5),
        ),
        missions=(
            CMission(id="ms-in", kind="deliver", pos=Pos(-2000, 0), amount=1, reward=1),
            CMission(id="ms-out", kind="deliver", pos=Pos(-2001, 0), amount=1, reward=1),
        ),
    )
    briefing = _briefing_for(state, "blue-def", fog=True)
    assert _ids(briefing["board"]["resource_nodes"]) == {"node-in"}
    assert _ids(briefing["board"]["missions"]) == {"ms-in"}


def test_enemy_unit_visibility_also_pins_the_boundary_inclusively():
    state = _state(
        teams=(
            _team("blue", "Blue", (_slot("blue-def", "defender"),)),
            _team("red", "Red", (_slot("red-in", "defender"), _slot("red-out", "defender"))),
        ),
        units=(
            _unit("blue-def", "blue", "defender", Pos(0, 0)),
            _unit("red-in", "red", "defender", Pos(2000, 0)),
            _unit("red-out", "red", "defender", Pos(2001, 0)),
        ),
    )
    briefing = _briefing_for(state, "blue-def", fog=True)
    assert _ids(briefing["board"]["units"]) == {"blue-def", "red-in"}


def test_own_team_is_always_fully_visible_regardless_of_distance():
    """A team's own units are always known (they 'report in'), even scattered
    far beyond any single unit's vision radius — mirrors the grid lane's
    ``vision.visible_units`` convention."""
    state = _state(
        teams=(_team("blue", "Blue", (_slot("blue-a", "defender"), _slot("blue-b", "defender"))),),
        units=(
            _unit("blue-a", "blue", "defender", Pos(0, 0)),
            _unit("blue-b", "blue", "defender", Pos(100000, 100000)),  # far outside blue-a's vision
        ),
    )
    briefing = _briefing_for(state, "blue-a", fog=True)
    assert _ids(briefing["board"]["units"]) == {"blue-a", "blue-b"}


# --------------------------------------------------------------------------- #
# Criterion 2 — the scout lever
# --------------------------------------------------------------------------- #
def test_scout_lever_entity_visible_with_scout_invisible_without():
    """An enemy control point at 3000 mu sits inside the scout's 4000 mu
    vision but outside a defender's 2000 mu vision. Swapping the scout in for
    a same-position defender is the ONLY difference between the two teams."""
    cp = (CControlPoint(id="secret-cp", pos=Pos(3000, 0)),)

    with_scout = _state(
        teams=(_team("blue", "Blue", (_slot("blue-scout", "scout"),)),),
        units=(_unit("blue-scout", "blue", "scout", Pos(0, 0)),),
        control_points=cp,
    )
    without_scout = _state(
        teams=(_team("blue", "Blue", (_slot("blue-def", "defender"),)),),
        units=(_unit("blue-def", "blue", "defender", Pos(0, 0)),),
        control_points=cp,
    )

    seen = _briefing_for(with_scout, "blue-scout", fog=True)
    unseen = _briefing_for(without_scout, "blue-def", fog=True)

    assert _ids(seen["board"]["control_points"]) == {"secret-cp"}
    assert unseen["board"]["control_points"] == []


def test_scout_lever_is_a_team_union_not_just_the_acting_unit():
    """The vision that matters is the TEAM's union, not only the unit being
    briefed: a harvester teammate's briefing still sees what the team's own
    scout reveals, even though the harvester's own vision (2000 mu) alone
    would not reach the entity."""
    state = _state(
        teams=(
            _team("blue", "Blue", (_slot("blue-scout", "scout"), _slot("blue-harv", "harvester"))),
        ),
        units=(
            _unit("blue-scout", "blue", "scout", Pos(0, 0)),
            _unit("blue-harv", "blue", "harvester", Pos(50000, 50000)),  # far from the CP
        ),
        control_points=(CControlPoint(id="secret-cp", pos=Pos(3000, 0)),),
    )
    briefing = _briefing_for(state, "blue-harv", fog=True)
    assert _ids(briefing["board"]["control_points"]) == {"secret-cp"}


# --------------------------------------------------------------------------- #
# Criterion 4 — default OFF / backward compatibility
# --------------------------------------------------------------------------- #
def test_fog_off_by_default_board_is_fogless():
    """Omitting ``fog`` entirely (the historical call shape, every pre-fog
    test) leaves the board fogless — a far-outside-vision entity still shows
    up. Compat: no existing caller's behavior changes."""
    state = _state(
        teams=(_team("blue", "Blue", (_slot("blue-def", "defender"),)),),
        units=(_unit("blue-def", "blue", "defender", Pos(0, 0)),),
        control_points=(CControlPoint(id="cp-far", pos=Pos(100000, 100000)),),
    )
    menu = legal_actions_continuous(state, ROLE_TABLE, "blue-def")
    briefing = build_briefing(state, "blue-def", menu)  # no fog kwarg at all
    assert _ids(briefing["board"]["control_points"]) == {"cp-far"}


def test_fog_false_explicit_is_also_fogless():
    state = _state(
        teams=(_team("blue", "Blue", (_slot("blue-def", "defender"),)),),
        units=(_unit("blue-def", "blue", "defender", Pos(0, 0)),),
        control_points=(CControlPoint(id="cp-far", pos=Pos(100000, 100000)),),
    )
    briefing = _briefing_for(state, "blue-def", fog=False)
    assert _ids(briefing["board"]["control_points"]) == {"cp-far"}


def test_run_cmatch_default_config_has_no_fog_key():
    """A config with no ``"fog"`` key at all (every committed config/fixture
    today) drives an unfogged match — proving the flag's absence, not just
    ``False``, is the historical default."""
    calls: list[dict[str, Any]] = []

    def spy(briefing: Mapping[str, Any], unit_id: str, team_id: str) -> dict[str, Any]:
        calls.append(dict(briefing))
        return {"action": None}

    cfg = {"match": {"id": "cm-nofog"}, "teams": [{"id": "blue", "driver": {"type": "bot"}}]}
    state = _state(
        teams=(_team("blue", "Blue", (_slot("blue-def", "defender"),)),),
        units=(_unit("blue-def", "blue", "defender", Pos(0, 0)),),
        control_points=(CControlPoint(id="cp-far", pos=Pos(100000, 100000)),),
    )
    run_cmatch(cfg, initial_state=state, choosers={"blue": spy})
    assert calls
    assert _ids(calls[0]["board"]["control_points"]) == {"cp-far"}


def test_run_cmatch_fog_true_filters_the_briefing_a_driver_receives():
    """The end-to-end wiring: ``config["fog"] = True`` reaches every briefing
    built inside ``run_cmatch``, not just direct ``build_briefing`` calls."""
    calls: list[dict[str, Any]] = []

    def spy(briefing: Mapping[str, Any], unit_id: str, team_id: str) -> dict[str, Any]:
        calls.append(dict(briefing))
        return {"action": None}

    cfg = {
        "match": {"id": "cm-fog"},
        "teams": [{"id": "blue", "driver": {"type": "bot"}}],
        "fog": True,
    }
    state = _state(
        teams=(_team("blue", "Blue", (_slot("blue-def", "defender"),)),),
        units=(_unit("blue-def", "blue", "defender", Pos(0, 0)),),
        control_points=(CControlPoint(id="cp-far", pos=Pos(100000, 100000)),),
    )
    run_cmatch(cfg, initial_state=state, choosers={"blue": spy})
    assert calls
    assert calls[0]["board"]["control_points"] == []


# --------------------------------------------------------------------------- #
# Criterion 5 — menu honesty (never reference a fogged entity) + outlook +
# unfiltered messages
# --------------------------------------------------------------------------- #
def test_menu_drops_a_move_toward_an_undiscovered_point_of_interest():
    state = _state(
        teams=(_team("blue", "Blue", (_slot("blue-def", "defender"),)),),
        units=(_unit("blue-def", "blue", "defender", Pos(0, 0)),),
        resource_nodes=(CResourceNode(id="node-far", pos=Pos(50000, 50000), remaining=5),),
    )
    fogless = _briefing_for(state, "blue-def", fog=False)
    fogged = _briefing_for(state, "blue-def", fog=True)

    fogless_moves = {e.get("target") for e in fogless["menu"] if e["kind"] == "move"}
    fogged_moves = {e.get("target") for e in fogged["menu"] if e["kind"] == "move"}
    assert "node-far" in fogless_moves
    assert "node-far" not in fogged_moves


def test_menu_keeps_a_move_toward_a_visible_point_of_interest():
    state = _state(
        teams=(_team("blue", "Blue", (_slot("blue-def", "defender"),)),),
        units=(_unit("blue-def", "blue", "defender", Pos(0, 0)),),
        resource_nodes=(CResourceNode(id="node-near", pos=Pos(1000, 0), remaining=5),),
    )
    fogged = _briefing_for(state, "blue-def", fog=True)
    moves = {e.get("target") for e in fogged["menu"] if e["kind"] == "move"}
    assert "node-near" in moves


def test_menu_never_filters_gather_or_take_post_on_the_entity_youre_standing_at():
    """gather/take_post always target an entity the acting unit has already
    ARRIVED at — trivially within any positive vision radius — so fog can
    never remove them, even when nothing else on the board is visible."""
    state = _state(
        teams=(_team("blue", "Blue", (_slot("blue-def", "defender"),)),),
        units=(_unit("blue-def", "blue", "defender", Pos(3000, 3000)),),
        control_points=(CControlPoint(id="cp-here", pos=Pos(3000, 3000)),),
        resource_nodes=(CResourceNode(id="node-here", pos=Pos(3000, 3000), remaining=5),),
    )
    fogged = _briefing_for(state, "blue-def", fog=True)
    kinds_targets = {(e["kind"], e.get("target")) for e in fogged["menu"]}
    assert ("take_post", "cp-here") in kinds_targets
    assert ("gather", "node-here") in kinds_targets


def test_outlook_drops_an_invisible_enemy_units_entry():
    """An enemy unit mid-action far outside vision leaks nothing about its
    completion time under fog; the same enemy within vision still shows."""
    busy_far = CAction(kind="move", start_time=0, completion_time=9, target_pos=Pos(1, 1))
    busy_near = CAction(kind="move", start_time=0, completion_time=9, target_pos=Pos(1, 1))
    state = _state(
        teams=(
            _team("blue", "Blue", (_slot("blue-def", "defender"),)),
            _team(
                "red",
                "Red",
                (_slot("red-far", "defender"), _slot("red-near", "defender")),
            ),
        ),
        units=(
            _unit("blue-def", "blue", "defender", Pos(0, 0)),
            _unit("red-far", "red", "defender", Pos(100000, 100000), action=busy_far),
            _unit("red-near", "red", "defender", Pos(1000, 0), action=busy_near),
        ),
    )
    briefing = _briefing_for(state, "blue-def", fog=True)
    outlook_ids = {e["unit_id"] for e in briefing["outlook"]}
    assert outlook_ids == {"red-near"}


def test_outlook_always_keeps_the_teams_own_busy_units():
    busy = CAction(kind="move", start_time=0, completion_time=9, target_pos=Pos(1, 1))
    state = _state(
        teams=(_team("blue", "Blue", (_slot("blue-a", "defender"), _slot("blue-b", "defender"))),),
        units=(
            _unit("blue-a", "blue", "defender", Pos(0, 0)),
            _unit("blue-b", "blue", "defender", Pos(100000, 100000), action=busy),
        ),
    )
    briefing = _briefing_for(state, "blue-a", fog=True)
    assert {e["unit_id"] for e in briefing["outlook"]} == {"blue-b"}


def test_messages_are_never_filtered_by_fog():
    """Fog hides the board, never coordination — teammate messages reach a
    briefing exactly the same way whether fog is on or off."""
    state = _state(
        teams=(_team("blue", "Blue", (_slot("blue-def", "defender"),)),),
        units=(_unit("blue-def", "blue", "defender", Pos(0, 0)),),
    )
    menu = legal_actions_continuous(state, ROLE_TABLE, "blue-def")
    msgs = [{"from": "blue-harv", "text": "covering your take", "game_time": 3}]
    fogged = build_briefing(state, "blue-def", menu, msgs, fog=True, role_table=ROLE_TABLE)
    assert fogged["messages"] == msgs


# --------------------------------------------------------------------------- #
# Criterion 3 — fog is a projection, never an engine mutation
# --------------------------------------------------------------------------- #
class _StepClock:
    """A deterministic fake wall-clock (mirrors tests/test_continuous_harness.py's
    own double): every reading advances by a fixed step, so both runs'
    ``seat_latency`` observations line up exactly."""

    def __init__(self, step_ms: int) -> None:
        self._t = 0.0
        self._step = step_ms / 1000.0

    def __call__(self) -> float:
        now = self._t
        self._t += self._step
        return now


def _scripted_chooser(script: dict[str, list[dict[str, Any]]]):
    """A driver that IGNORES the briefing entirely, returning the next
    pre-scripted action per unit (parking once the script runs out). Since
    this chooser never reads ``menu``/``board``/``outlook``, fog cannot
    possibly change what it does — any log difference between a fog-on and a
    fog-off run of the SAME script would have to come from the engine itself
    seeing fog, which the module docstring's design claims never happens."""
    counters: dict[str, int] = {}

    def choose(briefing: Mapping[str, Any], unit_id: str, team_id: str) -> dict[str, Any]:
        i = counters.get(unit_id, 0)
        counters[unit_id] = i + 1
        actions = script.get(unit_id, [])
        action = actions[i] if i < len(actions) else None
        return {"action": action}

    return choose


def _hold_state():
    """One defender a step from an unowned post with a hold mission — real
    move + take_post transitions, then the mission's synthetic hold-expiry
    window finishes the match with no further decision needed."""
    return _state(
        mode="cooperative",
        teams=(_team("blue", "Blue", (_slot("blue-def", "defender"),)),),
        units=(_unit("blue-def", "blue", "defender", from_units(1, 3)),),
        control_points=(CControlPoint(id="cp", pos=from_units(3, 3)),),
        missions=(CMission(id="hm", kind="hold", pos=from_units(3, 3), amount=4, reward=9),),
    )


_HOLD_SCRIPT = {
    "blue-def": [
        {"kind": "move", "target_pos": from_units(3, 3).to_dict()},
        {"kind": "take_post", "target_id": "cp"},
    ]
}


def _events(log):
    return [(e.game_time, e.kind, e.data) for e in log.events]


def test_fog_is_a_projection_never_an_engine_mutation(monkeypatch):
    """The exact same scripted match, run with fog off then on, produces a
    BYTE-IDENTICAL log both times — proving fog only narrows what a mind
    SEES, never what the resolver ticks or writes to the log (the honesty
    condition: 'fog is projection, never mutation')."""
    cfg_off = {"match": {"id": "cm-fog-off"}, "teams": [{"id": "blue", "driver": {"type": "bot"}}]}
    cfg_on = {**cfg_off, "fog": True}

    monkeypatch.setattr(charness, "_monotonic", _StepClock(1))
    off = run_cmatch(
        cfg_off, initial_state=_hold_state, choosers={"blue": _scripted_chooser(_HOLD_SCRIPT)}
    )

    monkeypatch.setattr(charness, "_monotonic", _StepClock(1))
    on = run_cmatch(
        cfg_on, initial_state=_hold_state, choosers={"blue": _scripted_chooser(_HOLD_SCRIPT)}
    )

    assert _events(off["log"]) == _events(on["log"])
    assert cstate_hash(off["log"].final_state()) == cstate_hash(on["log"].final_state())
    assert off["status"] == on["status"] == "finished"
    assert off["winner"] == on["winner"] == "blue"
    assert off["outcome_points"] == on["outcome_points"]
