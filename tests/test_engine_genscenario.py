"""Acceptance tests for the seeded scenario generator (cycle-6 tasks C6-t1/t2).

Criteria under test (the merge gate):

1. ``generate(seed, params)`` is deterministic — same seed → byte-identical
   scenario (canonical JSON), different seeds → structurally different boards —
   and uses NO runtime randomness (the engine import ban still holds).
2. A match played on a generated scenario is re-creatable from its log alone:
   the generated id fully encodes seed+params and lands in the log header.
3. Generated boards are fair by construction — mirror-symmetric spawns and
   objectives per team — while the hand-authored scenarios and every preset
   keep working unchanged.
4. (C6-t2, spec c9) Board scale and complexity knobs reach well past the
   original ceiling — grids to 41x41, turn limits to 200, control/resource/
   mission pairs to 8 — every existing invariant (odd dims, mirror symmetry,
   no furniture collisions, loud validation) still holds, and a large-board
   long-turn scenario plays a full bot-vs-bot match to completion.
5. (C6-t2) The roster-size knob, ``executor_scale``, duplicates the harvester/
   defender executor slots while staying backward compatible (default-roster
   ids are byte-identical to before; old ids without the new id segment still
   parse), and the in-harness greedy bot plays a duplicated-role roster
   without assuming one unit per role.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from league.engine import genscenario
from league.engine.events import MatchLog, fold_events
from league.engine.genscenario import (
    DEFAULT_PARAMS,
    EXECUTOR_SCALE_MAX,
    GenParams,
    generate,
    params_token,
    parse_generated_id,
    rotate180,
    scenario_id,
)
from league.engine.scenario import Scenario, get_scenario, instantiate, scenario_ids
from league.engine.state import AgentSlot, state_hash, state_to_json
from league.harness import run_match
from league.presets import preset_names, resolve
from league.store import Store, validate_id

_SEASON_0 = Path(__file__).parent.parent / "docs" / "playtests" / "season-0"

# -- helpers ----------------------------------------------------------------


def _roster(team: str) -> tuple[AgentSlot, ...]:
    return (
        AgentSlot(id=f"{team}-1", model="bot:greedy", role="scout"),
        AgentSlot(id=f"{team}-2", model="bot:greedy", role="harvester"),
        AgentSlot(id=f"{team}-3", model="bot:greedy", role="defender"),
    )


def _scaled_roster(team: str, executor_scale: int) -> tuple[AgentSlot, ...]:
    """A roster matching ``_unit_roles(executor_scale)``: one scout, then
    ``executor_scale`` distinctly-ided harvesters, then that many defenders —
    every duplicate slot gets its own agent id, never a shared one."""
    agents = [AgentSlot(id=f"{team}-scout", model="bot:greedy", role="scout")]
    agents += [
        AgentSlot(id=f"{team}-harvester-{i + 1}", model="bot:greedy", role="harvester")
        for i in range(executor_scale)
    ]
    agents += [
        AgentSlot(id=f"{team}-defender-{i + 1}", model="bot:greedy", role="defender")
        for i in range(executor_scale)
    ]
    return tuple(agents)


def _scaled_agent_dicts(team: str, executor_scale: int) -> list[dict[str, str]]:
    return [a.to_dict() for a in _scaled_roster(team, executor_scale)]


def _canonical_board(scenario: Scenario) -> str:
    """A canonical-JSON fingerprint of a scenario, via the engine's own state
    projection — the exact artifact that lands in a match log."""
    state = instantiate(
        scenario,
        match_id="m-fingerprint",
        seed=0,
        mode="competitive",
        teams=(
            ("blue", "Blue", _roster("blue")),
            ("red", "Red", _roster("red")),
        ),
    )
    return state_to_json(state)


def _manhattan(a: tuple[int, int], b: tuple[int, int]) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


# -- criterion 1: determinism, novelty, no randomness -----------------------


def test_same_seed_is_byte_identical() -> None:
    a = generate(1234, DEFAULT_PARAMS)
    b = generate(1234, DEFAULT_PARAMS)
    assert a == b
    assert _canonical_board(a) == _canonical_board(b)
    assert state_hash(_state(a)) == state_hash(_state(b))


def _state(scenario: Scenario):
    return instantiate(
        scenario,
        match_id="m-x",
        seed=0,
        mode="competitive",
        teams=(("blue", "Blue", _roster("blue")), ("red", "Red", _roster("red"))),
    )


def test_different_seeds_give_structurally_different_boards() -> None:
    boards = {_canonical_board(generate(seed)) for seed in range(12)}
    # A dozen seeds must not collapse to one board.
    assert len(boards) > 1
    # And two specific, different seeds differ.
    assert _canonical_board(generate(7)) != _canonical_board(generate(8))


def test_engine_still_imports_no_random_or_time() -> None:
    """genscenario must derive pseudo-randomness from hashlib, never random."""
    banned = {"random", "time", "datetime", "secrets", "uuid"}
    module = Path(genscenario.__file__)
    tree = ast.parse(module.read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [alias.name.split(".")[0] for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names.append((node.module or "").split(".")[0])
    assert not (set(names) & banned), f"genscenario imports a banned module: {set(names) & banned}"
    assert "hashlib" in names


# -- id scheme: full seed+params encoding -----------------------------------


@pytest.mark.parametrize(
    "seed, params",
    [
        (0, DEFAULT_PARAMS),
        (42, GenParams(grid_width=15, grid_height=9, turn_limit=24)),
        (
            9999,
            GenParams(
                grid_width=21,
                grid_height=21,
                turn_limit=60,
                control_point_pairs=3,
                resource_node_pairs=2,
                hold_mission_pairs=2,
                capture_hold_turns=4,
            ),
        ),
    ],
)
def test_id_round_trips_seed_and_params(seed: int, params: GenParams) -> None:
    sid = scenario_id(seed, params)
    validate_id(sid, what="scenario id")  # id must survive the store's path guard
    parsed = parse_generated_id(sid)
    assert parsed == (seed, params)
    assert generate(seed, params).id == sid


def test_parse_rejects_non_generated_ids() -> None:
    for candidate in ("skirmish-1", "gen", "gen-1", "gen-1-xyz", "gen-abc-w9y9t8c1r1m1k2", "m-e2e"):
        assert parse_generated_id(candidate) is None


def test_params_validation_is_loud() -> None:
    with pytest.raises(ValueError, match="odd"):
        generate(1, GenParams(grid_width=12))  # even width
    with pytest.raises(ValueError, match="out of range"):
        generate(1, GenParams(grid_width=7))  # below GRID_MIN
    with pytest.raises(ValueError, match="hold_mission_pairs"):
        generate(1, GenParams(control_point_pairs=1, hold_mission_pairs=2))
    with pytest.raises(ValueError, match="non-negative"):
        scenario_id(-1, DEFAULT_PARAMS)


# -- criterion 1/3: the produced scenario is valid --------------------------


def test_generated_scenario_is_well_formed() -> None:
    params = GenParams(control_point_pairs=2, resource_node_pairs=2, hold_mission_pairs=1)
    scenario = generate(3, params)
    assert set(scenario.modes) == {"cooperative", "competitive"}
    assert scenario.unit_roles == ("scout", "harvester", "defender")
    # scout keeps the strictly-widest vision (spec c12)
    visions = {role: stats.vision for role, stats in scenario.role_stats}
    assert all(visions["scout"] > v for role, v in visions.items() if role != "scout")
    # cycle-8 t10: the generated scout is eyes-only too (docs/roles.md) — it
    # keeps gather, but can never capture a control point.
    assert scenario.stats_for("scout").can_gather is True
    assert scenario.stats_for("scout").can_capture is False
    assert scenario.stats_for("harvester").can_capture is True
    assert scenario.stats_for("defender").can_capture is True
    assert len(scenario.control_points) == 2 * params.control_point_pairs
    assert len(scenario.resource_nodes) == 2 * params.resource_node_pairs
    deliver = [m for m in scenario.missions if m.kind == "deliver"]
    holds = [m for m in scenario.missions if m.kind == "hold"]
    assert len(deliver) == 1
    assert len(holds) == 2 * params.hold_mission_pairs
    # every cell is distinct: spawns, control points, resource nodes, missions
    cells = (
        list(scenario.spawns[0])
        + list(scenario.spawns[1])
        + [c.pos for c in scenario.control_points]
        + [n.pos for n in scenario.resource_nodes]
        + [deliver[0].pos]
    )
    assert len(cells) == len(set(cells)), "furniture cells collide"
    # instantiates and starts like any scenario
    state = _state(scenario)
    assert len(state.units) == 6
    assert state.scenario_id == scenario.id


# -- criterion 3: fairness by construction ----------------------------------


@pytest.mark.parametrize(
    "params",
    [
        DEFAULT_PARAMS,
        GenParams(grid_width=15, grid_height=13, control_point_pairs=2, resource_node_pairs=2),
        GenParams(
            grid_width=21,
            grid_height=9,
            control_point_pairs=3,
            resource_node_pairs=3,
            hold_mission_pairs=2,
        ),
    ],
)
def test_boards_are_mirror_symmetric_over_many_seeds(params: GenParams) -> None:
    for seed in range(50):
        scenario = generate(seed, params)
        w, h = scenario.grid_width, scenario.grid_height
        assert w % 2 == 1 and h % 2 == 1
        center = (w // 2, h // 2)

        def rot(pos: tuple[int, int]) -> tuple[int, int]:
            return (w - 1 - pos[0], h - 1 - pos[1])

        # spawns: team 1 is team 0 rotated, slot for slot
        assert tuple(rot(p) for p in scenario.spawns[0]) == scenario.spawns[1]

        # objective SETS are rotation-invariant
        cp_positions = {c.pos for c in scenario.control_points}
        rn_positions = {n.pos for n in scenario.resource_nodes}
        hold_positions = {m.pos for m in scenario.missions if m.kind == "hold"}
        assert {rot(p) for p in cp_positions} == cp_positions
        assert {rot(p) for p in rn_positions} == rn_positions
        assert {rot(p) for p in hold_positions} == hold_positions

        # the one shared objective (deliver) is the fixed center, equidistant
        deliver = next(m for m in scenario.missions if m.kind == "deliver")
        assert deliver.pos == center
        s0, s1 = scenario.spawns[0][0], scenario.spawns[1][0]
        assert _manhattan(s0, deliver.pos) == _manhattan(s1, deliver.pos)

        # per-team spawn→objective distance multisets are identical
        for targets in (cp_positions, rn_positions):
            d0 = sorted(_manhattan(s0, t) for t in targets)
            d1 = sorted(_manhattan(s1, t) for t in targets)
            assert d0 == d1


def test_rotate180_is_an_involution() -> None:
    for seed in range(5):
        s = generate(seed)
        w, h = s.grid_width, s.grid_height
        for pos in [c.pos for c in s.control_points] + list(s.spawns[0]):
            assert rotate180(rotate180(pos, w, h), w, h) == pos


# -- criterion 2 + registry hook: log-alone recreatability ------------------


def test_get_scenario_resolves_generated_ids() -> None:
    scenario = generate(77, GenParams(control_point_pairs=2))
    assert get_scenario(scenario.id) == scenario
    # a generated id with bad params surfaces the generator's precise error
    with pytest.raises(ValueError, match="odd"):
        get_scenario("gen-1-w12y11t30c1r1m1k2")
    # a genuinely unknown, non-generated id stays the loud catalog error
    with pytest.raises(ValueError, match="skirmish-1"):
        get_scenario("does-not-exist")


def test_scenario_reconstructs_from_log_header_alone(tmp_path, monkeypatch) -> None:
    """Criterion 2: the log's scenario_id fully re-derives the board."""
    monkeypatch.chdir(tmp_path)
    sid = scenario_id(314, GenParams(control_point_pairs=2, resource_node_pairs=2))
    scenario = get_scenario(sid)
    state = _state(scenario)
    from league.engine.tick import start_match

    started, events = start_match(state)
    log = MatchLog(initial_state=state, events=events)
    reloaded = MatchLog.from_jsonl(log.to_jsonl())
    header_id = reloaded.initial_state.scenario_id
    assert header_id == sid
    # rebuild the scenario from the id alone and confirm it matches the board
    seed, params = parse_generated_id(header_id)
    assert generate(seed, params) == scenario


def test_generated_scenario_plays_bot_vs_bot_and_folds(tmp_path, monkeypatch) -> None:
    """End-to-end: generate, play a bot-vs-bot match via the harness, reload the
    log, and confirm the fold reproduces the final state exactly."""
    monkeypatch.chdir(tmp_path)
    sid = scenario_id(5, DEFAULT_PARAMS)
    config = {
        "match": {"scenario": sid, "mode": "competitive", "seed": 9, "id": "m-gen-e2e"},
        "teams": [
            {
                "id": "blue",
                "name": "Blue",
                "driver": {"type": "bot"},
                "agents": [a.to_dict() for a in _roster("blue")],
            },
            {
                "id": "red",
                "name": "Red",
                "driver": {"type": "bot"},
                "agents": [a.to_dict() for a in _roster("red")],
            },
        ],
    }
    result = run_match(config)
    assert result["match_id"] == "m-gen-e2e"
    assert result["status"] == "finished"
    assert result["turns_played"] > 0

    store = Store()
    log = store.load_match("m-gen-e2e")
    # the fold IS the replay: reloading and refolding reproduces the final state
    refolded = fold_events(log.initial_state, log.events)
    assert state_hash(refolded) == state_hash(log.final_state())
    # and the board is recoverable from the header id with nothing else
    assert log.initial_state.scenario_id == sid
    seed, params = parse_generated_id(log.initial_state.scenario_id)
    assert generate(seed, params) == get_scenario(sid)


def test_cli_arena_show_and_match_new_accept_generated_ids(tmp_path, monkeypatch, capsys) -> None:
    from league.cli import main

    monkeypatch.chdir(tmp_path)
    sid = scenario_id(21, GenParams(control_point_pairs=2))

    assert main(["arena", "show", sid, "--json"]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["id"] == sid
    assert len(shown["control_points"]) == 4

    for team in ("blue", "red"):
        assert (
            main(
                [
                    "team",
                    "register",
                    team,
                    "--agent",
                    f"{team}-1:bot:greedy:scout",
                    "--agent",
                    f"{team}-2:bot:greedy:harvester",
                    "--agent",
                    f"{team}-3:bot:greedy:defender",
                    "--apply",
                ]
            )
            == 0
        )
    capsys.readouterr()
    assert (
        main(
            [
                "match",
                "new",
                "--scenario",
                sid,
                "--team",
                "blue",
                "--team",
                "red",
                "--id",
                "m-gen-cli",
                "--apply",
                "--json",
            ]
        )
        == 0
    )
    created = json.loads(capsys.readouterr().out)
    assert created["applied"] is True
    assert (tmp_path / ".league" / "matches" / "m-gen-cli" / "log.jsonl").is_file()


# -- criterion 3: nothing existing regresses --------------------------------


def test_hand_authored_scenarios_and_presets_unchanged() -> None:
    # The hand-authored boards must stay registered; other tasks may ADD
    # scenarios (cycle-6 t3 registered recon-1), so this asserts presence,
    # not an exact registry tuple.
    assert {"skirmish-1", "skirmish-2"} <= set(scenario_ids())
    for known in scenario_ids():
        assert get_scenario(known).id == known
    # every bundled preset still resolves to a launchable config
    for name in preset_names():
        config = resolve(name)
        assert config["match"]["scenario"] in scenario_ids()


# -- C6-t2 criterion 4: board scale and complexity knobs ---------------------
#
# The pinned ceilings widened from 21x21/80-turn/4-pair to 41x41/200-turn/
# 8-pair (module docstring). Every existing invariant — odd dims, mirror
# symmetry, no furniture collisions, loud out-of-range validation — must still
# hold at the new ceiling, and just past it must still raise loudly.


def test_new_ceiling_values_are_valid_and_well_formed() -> None:
    params = GenParams(
        grid_width=41,
        grid_height=41,
        turn_limit=200,
        control_point_pairs=8,
        resource_node_pairs=8,
        hold_mission_pairs=8,
        capture_hold_turns=4,
    )
    scenario = generate(1, params)
    assert (scenario.grid_width, scenario.grid_height) == (41, 41)
    assert scenario.turn_limit == 200
    assert len(scenario.control_points) == 16
    assert len(scenario.resource_nodes) == 16
    assert len([m for m in scenario.missions if m.kind == "hold"]) == 16
    # every cell distinct: spawns, control points, resource nodes, deliver
    cells = (
        list(scenario.spawns[0])
        + list(scenario.spawns[1])
        + [c.pos for c in scenario.control_points]
        + [n.pos for n in scenario.resource_nodes]
        + [m.pos for m in scenario.missions if m.kind == "deliver"]
    )
    assert len(cells) == len(set(cells)), "furniture cells collide at the new ceiling"
    # instantiates cleanly, like any scenario
    state = _state(scenario)
    assert state.scenario_id == scenario.id


@pytest.mark.parametrize(
    "field, value, match",
    [
        ("grid_width", 43, "out of range"),
        ("grid_height", 43, "out of range"),
        ("turn_limit", 201, "out of range"),
        ("control_point_pairs", 9, "out of range"),
        ("resource_node_pairs", 9, "out of range"),
    ],
)
def test_just_past_the_new_ceiling_still_raises_loudly(field: str, value: int, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        generate(1, GenParams(**{field: value}))


def test_ceiling_constants_document_the_widened_range() -> None:
    # Locks in the actual numbers the module docstring promises (C6-t2, spec
    # c9): a silent constant change here would desync the docs from the code.
    assert (genscenario.GRID_MIN, genscenario.GRID_MAX) == (9, 41)
    assert (genscenario.TURN_LIMIT_MIN, genscenario.TURN_LIMIT_MAX) == (8, 200)
    assert (genscenario.PAIR_MIN, genscenario.PAIR_MAX) == (1, 8)


def test_cli_match_new_accepts_scale_and_roster_knobs_at_the_ceiling(
    tmp_path, monkeypatch, capsys
) -> None:
    """The CLI surface itself (not just ``generate``/the harness) accepts the
    widened ranges: ``arena show``/``match new --scenario gen-...`` need no
    change of their own — ``get_scenario`` already re-derives any generated id
    — but this proves it at the new ceiling, combined with a non-default
    ``executor_scale``, exactly the 'match new / play surfaces accept ...
    parameters' acceptance line. Dry (no turns played), so it stays cheap."""
    from league.cli import main

    monkeypatch.chdir(tmp_path)
    executor_scale = 2
    sid = scenario_id(
        3,
        GenParams(
            grid_width=41,
            grid_height=41,
            turn_limit=200,
            control_point_pairs=8,
            resource_node_pairs=8,
            hold_mission_pairs=8,
            executor_scale=executor_scale,
        ),
    )

    assert main(["arena", "show", sid, "--json"]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["id"] == sid
    assert shown["grid"] == {"width": 41, "height": 41}
    assert shown["turn_limit"] == 200
    assert len(shown["control_points"]) == 16

    for team in ("blue", "red"):
        argv = ["team", "register", team, "--agent", f"{team}-scout:bot:greedy:scout"]
        for i in range(executor_scale):
            argv += ["--agent", f"{team}-harvester-{i + 1}:bot:greedy:harvester"]
        for i in range(executor_scale):
            argv += ["--agent", f"{team}-defender-{i + 1}:bot:greedy:defender"]
        assert main(argv + ["--apply"]) == 0
    capsys.readouterr()

    assert (
        main(
            [
                "match",
                "new",
                "--scenario",
                sid,
                "--team",
                "blue",
                "--team",
                "red",
                "--id",
                "m-gen-ceiling",
                "--apply",
                "--json",
            ]
        )
        == 0
    )
    created = json.loads(capsys.readouterr().out)
    assert created["applied"] is True
    assert created["turn_limit"] == 200
    assert (tmp_path / ".league" / "matches" / "m-gen-ceiling" / "log.jsonl").is_file()


def test_large_board_long_turn_scenario_plays_full_bot_vs_bot_and_folds(
    tmp_path, monkeypatch
) -> None:
    """The headline C6-t2 acceptance test: a 41x41 grid, 200-turn scenario with
    several objective pairs runs a FULL bot-vs-bot match to completion via the
    harness (coded, fast bots) — proving the engine actually scales, not just
    that generate() accepts the params. Stays well under the <30s test budget
    (measured ~7s on a dev machine) because grid size never drives an O(w*h)
    per-turn cost anywhere in the engine (legal.py/vision.py/tick.py bound
    their work by move/vision radius, never the board)."""
    monkeypatch.chdir(tmp_path)
    params = GenParams(
        grid_width=41,
        grid_height=41,
        turn_limit=200,
        control_point_pairs=8,
        resource_node_pairs=4,
        hold_mission_pairs=4,
        capture_hold_turns=2,
    )
    sid = scenario_id(5, params)
    config = {
        "match": {"scenario": sid, "mode": "competitive", "seed": 9, "id": "m-gen-scale"},
        "teams": [
            {
                "id": "blue",
                "name": "Blue",
                "driver": {"type": "bot"},
                "agents": [a.to_dict() for a in _roster("blue")],
            },
            {
                "id": "red",
                "name": "Red",
                "driver": {"type": "bot"},
                "agents": [a.to_dict() for a in _roster("red")],
            },
        ],
    }
    result = run_match(config)
    assert result["status"] == "finished"
    assert result["turns_played"] > 0

    store = Store()
    log = store.load_match("m-gen-scale")
    refolded = fold_events(log.initial_state, log.events)
    assert state_hash(refolded) == state_hash(log.final_state())
    # the whole board is recoverable from the log header's id alone
    assert log.initial_state.scenario_id == sid
    seed, parsed_params = parse_generated_id(log.initial_state.scenario_id)
    assert generate(seed, parsed_params) == get_scenario(sid)


# -- C6-t2 criterion 5: the roster-size knob (executor_scale) ---------------


def test_executor_scale_default_is_byte_identical_to_the_original_roster() -> None:
    """executor_scale=1 (the default) must reproduce the original 3-unit
    roster and spawn cluster exactly — no change for anyone not opting in."""
    assert DEFAULT_PARAMS.executor_scale == 1
    scenario = generate(3, DEFAULT_PARAMS)
    assert scenario.unit_roles == ("scout", "harvester", "defender")
    assert scenario.spawns[0][:3] == ((0, 0), (1, 0), (0, 1))
    # and the id token itself carries no 'e' segment (backward compatible)
    assert params_token(DEFAULT_PARAMS) == "w13y11t30c1r1m1k2"


@pytest.mark.parametrize("executor_scale", [2, 3, EXECUTOR_SCALE_MAX])
def test_executor_scale_extends_roster_and_spawn_cluster(executor_scale: int) -> None:
    params = GenParams(executor_scale=executor_scale)
    scenario = generate(11, params)
    expected_roles = ("scout",) + ("harvester",) * executor_scale + ("defender",) * executor_scale
    assert scenario.unit_roles == expected_roles
    assert len(scenario.spawns[0]) == len(expected_roles)
    assert len(scenario.spawns[1]) == len(expected_roles)
    # spawn cells are all distinct and on the grid
    assert len(set(scenario.spawns[0])) == len(expected_roles)
    for x, y in scenario.spawns[0]:
        assert 0 <= x < scenario.grid_width
        assert 0 <= y < scenario.grid_height
    # mirror symmetry: team 1 is exactly team 0 rotated, slot for slot
    w, h = scenario.grid_width, scenario.grid_height
    assert tuple(rotate180(p, w, h) for p in scenario.spawns[0]) == scenario.spawns[1]
    # instantiates with a matching duplicated-role roster
    state = _state_scaled(scenario, executor_scale)
    assert len(state.units) == 2 * len(expected_roles)


def _state_scaled(scenario: Scenario, executor_scale: int):
    return instantiate(
        scenario,
        match_id="m-scaled",
        seed=0,
        mode="competitive",
        teams=(
            ("blue", "Blue", _scaled_roster("blue", executor_scale)),
            ("red", "Red", _scaled_roster("red", executor_scale)),
        ),
    )


def test_executor_scale_out_of_range_raises_loudly() -> None:
    with pytest.raises(ValueError, match="executor_scale"):
        generate(1, GenParams(executor_scale=EXECUTOR_SCALE_MAX + 1))
    with pytest.raises(ValueError, match="executor_scale"):
        generate(1, GenParams(executor_scale=0))


def test_executor_scale_id_omitted_at_default_present_otherwise() -> None:
    # default: no 'e' segment at all (byte-identical to a pre-C6-t2 id)
    default_id = scenario_id(7, GenParams(executor_scale=1))
    assert "e" not in default_id.rsplit("k", 1)[-1]
    # non-default: present and round-trips
    scaled_params = GenParams(executor_scale=3)
    scaled_id = scenario_id(7, scaled_params)
    assert scaled_id.endswith("e3")
    assert parse_generated_id(scaled_id) == (7, scaled_params)
    assert generate(7, scaled_params).id == scaled_id


def test_old_style_ids_without_executor_segment_still_parse() -> None:
    """Backward compatibility, asserted against LITERAL pre-existing id
    strings (not round-tripped through today's encoder): any id minted before
    this task parses to executor_scale=1, identically."""
    for old_id in ("gen-1-w9y9t8c1r1m1k2", "gen-9999-w21y21t60c3r2m2k4"):
        parsed = parse_generated_id(old_id)
        assert parsed is not None
        seed, params = parsed
        assert params.executor_scale == 1
        # and the id the generator itself would mint for that exact seed+params
        # is the same string — round-tripping through today's code changes
        # nothing about a pre-existing default-roster id.
        assert scenario_id(seed, params) == old_id


def test_executor_scale_bot_vs_bot_plays_the_duplicated_roster(tmp_path, monkeypatch) -> None:
    """The design guidance's own instruction: verify, don't assume, that the
    in-harness greedy bot (``league.harness.make_bot_driver``) plays a
    duplicated-role roster — it groups units by team and looks up
    ``roles[unit["role"]]`` per unit, never assuming one unit per role, but
    this proves it end to end rather than trusting the reading."""
    monkeypatch.chdir(tmp_path)
    executor_scale = 3
    params = GenParams(
        grid_width=21,
        grid_height=21,
        turn_limit=60,
        control_point_pairs=3,
        resource_node_pairs=2,
        hold_mission_pairs=2,
        capture_hold_turns=2,
        executor_scale=executor_scale,
    )
    sid = scenario_id(5, params)
    config = {
        "match": {"scenario": sid, "mode": "competitive", "seed": 9, "id": "m-gen-roster"},
        "teams": [
            {
                "id": "blue",
                "name": "Blue",
                "driver": {"type": "bot"},
                "agents": _scaled_agent_dicts("blue", executor_scale),
            },
            {
                "id": "red",
                "name": "Red",
                "driver": {"type": "bot"},
                "agents": _scaled_agent_dicts("red", executor_scale),
            },
        ],
    }
    result = run_match(config)
    assert result["status"] == "finished"
    assert result["turns_played"] > 0

    store = Store()
    log = store.load_match("m-gen-roster")
    final = log.final_state()
    # every duplicated unit is alive-or-dead as a real unit, never merged:
    # 1 scout + executor_scale harvesters + executor_scale defenders per team
    for team_id in ("blue", "red"):
        team_units = [u for u in final.units if u.team_id == team_id]
        assert len(team_units) == 1 + 2 * executor_scale
        assert len({u.agent_id for u in team_units}) == len(
            team_units
        ), "each unit must map to its own distinct agent id"
    refolded = fold_events(log.initial_state, log.events)
    assert state_hash(refolded) == state_hash(final)


# -- C6-t2 compatibility spot check (t11's full sweep is a separate task) ----


def test_season_0_log_still_folds_after_the_scale_change() -> None:
    """One spot check, not the wave-1 t11 full sweep: a committed season-0 log
    must still fold to its recorded final state after this task's changes —
    board-scale/roster work touched genscenario.py and scenario.py's
    instantiate(), neither of which this pre-existing log's fold depends on
    (it predates the generator entirely)."""
    log = MatchLog.from_jsonl((_SEASON_0 / "opener.log.jsonl").read_text())
    final = log.final_state()
    assert final.status == "finished"
    assert final.winner == "blue"
    assert final.turn == 30
    assert state_hash(final) == "f7ff342a54aff87c9d77267c99681a2ac6b0d9db5ba1850de7879a9509aff54d"
