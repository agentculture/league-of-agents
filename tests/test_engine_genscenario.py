"""Acceptance tests for the seeded scenario generator (cycle-6 task C6-t1).

Criteria under test (the merge gate):

1. ``generate(seed, params)`` is deterministic — same seed → byte-identical
   scenario (canonical JSON), different seeds → structurally different boards —
   and uses NO runtime randomness (the engine import ban still holds).
2. A match played on a generated scenario is re-creatable from its log alone:
   the generated id fully encodes seed+params and lands in the log header.
3. Generated boards are fair by construction — mirror-symmetric spawns and
   objectives per team — while the hand-authored scenarios and every preset
   keep working unchanged.
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
    GenParams,
    generate,
    parse_generated_id,
    rotate180,
    scenario_id,
)
from league.engine.scenario import Scenario, get_scenario, instantiate, scenario_ids
from league.engine.state import AgentSlot, state_hash, state_to_json
from league.harness import run_match
from league.presets import preset_names, resolve
from league.store import Store, validate_id

# -- helpers ----------------------------------------------------------------


def _roster(team: str) -> tuple[AgentSlot, ...]:
    return (
        AgentSlot(id=f"{team}-1", model="bot:greedy", role="scout"),
        AgentSlot(id=f"{team}-2", model="bot:greedy", role="harvester"),
        AgentSlot(id=f"{team}-3", model="bot:greedy", role="defender"),
    )


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
