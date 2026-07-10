"""The coded-strategy bot lane (plan task t2, spec c3/h2).

Criteria under test:

* the reference bot's strategy (``bots/rusher.py``) is readable committed
  source, and its matches are deterministic given the seed: the same config
  played twice produces identical logs (state hashes match);
* a coded bot touches no league internals: the strategy function receives
  ONLY the parsed JSON dict ``league match show --json`` returns (``state``,
  ``legal_actions``, ``staged_teams``, ...) — never an engine object, never
  anything the CLI itself doesn't expose.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import pytest

import bots.lampbearer as lampbearer
import bots.rusher as rusher
import bots.shambler as shambler
import bots.vanguard as vanguard
import league.harness as harness
from league.cli import main
from league.engine.events import MatchLog
from league.engine.state import state_hash
from league.harness import build_driver, driver_kind, run_match
from league.store import Store

REPO_ROOT = Path(__file__).resolve().parent.parent
BOTS_DIR = REPO_ROOT / "bots"

# The roster's declared tier vocabulary (plan task t4, spec c12/h11) — a
# small, ordered set so "higher tier" has one unambiguous meaning across the
# whole bot lane. bots/README.md carries the human-readable roster table;
# this is the machine-checked mirror of the same ordering.
TIER_ORDER = ("bronze", "silver", "gold")

# The same determinism bar the engine itself is held to
# (tests/test_engine_state.py::test_engine_never_imports_time_or_random).
_BANNED_MODULES = {"random", "time", "datetime", "secrets", "uuid"}


@pytest.fixture()
def arena(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _game_events(log: MatchLog) -> list[dict]:
    """Every logged event except ``seat_latency`` (plan t1, spec c10/h9): real
    wall-clock instrumentation the harness appends per turn, excluded here
    because it varies run to run by construction even when game logic does
    not — it is a fold no-op, never part of state-hash determinism."""
    return [e.to_dict() for e in log.events if e.kind != "seat_latency"]


def _register(team: str, model: str = "bot-file:rusher") -> list[str]:
    return [
        "team",
        "register",
        team,
        "--name",
        f"Team {team}",
        "--agent",
        f"{team}-1:{model}:scout",
        "--agent",
        f"{team}-2:{model}:harvester",
        "--agent",
        f"{team}-3:{model}:defender",
    ]


def _new_match(match_id: str) -> list[str]:
    return [
        "match",
        "new",
        "--scenario",
        "skirmish-1",
        "--team",
        "blue",
        "--team",
        "red",
        "--seed",
        "7",
        "--id",
        match_id,
        "--apply",
    ]


# -- criterion 1: committed, readable source; no nondeterministic/internal --
# -- imports ------------------------------------------------------------


def test_rusher_strategy_is_committed_readable_source() -> None:
    path = BOTS_DIR / "rusher.py"
    assert path.is_file(), "bots/rusher.py must be committed source, not generated at runtime"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    top_level = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    assert "decide" in top_level, "bots/rusher.py must export a module-level decide(...)"


def test_bots_never_import_nondeterministic_or_league_internal_modules() -> None:
    """Every ``bots/*.py`` strategy is held to the engine's own determinism
    bar (no random/time/datetime/secrets/uuid) PLUS a stricter rule: no
    ``league.*`` import at all — a strategy sees only the JSON dict the
    bot-file driver hands it, never engine or store code."""
    offenders: list[str] = []
    py_files = sorted(BOTS_DIR.glob("*.py"))
    assert py_files, "expected at least one bots/*.py strategy to check"
    for module in py_files:
        tree = ast.parse(module.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [(node.module or "").split(".")[0]]
            else:
                continue
            for name in names:
                if name in _BANNED_MODULES or name == "league":
                    offenders.append(f"{module.name}: {name}")
    assert not offenders, f"banned imports in bots/: {offenders}"


# -- criterion 1: rusher's own decision logic (direct, no harness) ----------


def _show_json(units: list[dict], control_points: list[dict], legal_actions: dict) -> dict:
    return {
        "state": {"turn": 0, "units": units, "control_points": control_points},
        "legal_actions": legal_actions,
        "staged_teams": [],
        "last_turn_rejections": [],
        "driver_kinds": {},
    }


def test_rusher_rushes_the_nearest_control_point() -> None:
    units = [
        {
            "id": "blue-u1",
            "team_id": "blue",
            "agent_id": "blue-1",
            "role": "scout",
            "pos": [0, 0],
            "carrying": 0,
            "alive": True,
        }
    ]
    control_points = [
        {"id": "cp-far", "pos": [9, 9], "owner": None, "hold": []},
        {"id": "cp-near", "pos": [1, 0], "owner": None, "hold": []},
    ]
    legal_actions = {
        "blue-u1": {
            "move": [[0, 1], [1, 0], [1, 1]],
            "gather": False,
            "deliver": False,
            "hold": True,
        }
    }

    orders = rusher.decide(_show_json(units, control_points, legal_actions), "blue")

    assert orders["actions"] == [{"unit_id": "blue-u1", "action": "move", "to": [1, 0]}]
    assert orders["plan"].startswith("rusher:")


def test_rusher_holds_once_arrived_at_its_target_control_point() -> None:
    units = [
        {
            "id": "blue-u1",
            "team_id": "blue",
            "agent_id": "blue-1",
            "role": "scout",
            "pos": [1, 0],
            "carrying": 0,
            "alive": True,
        }
    ]
    control_points = [{"id": "cp-near", "pos": [1, 0], "owner": None, "hold": []}]
    legal_actions = {
        "blue-u1": {"move": [[0, 0], [2, 0]], "gather": False, "deliver": False, "hold": True}
    }
    show_json = _show_json(units, control_points, legal_actions)
    show_json["state"]["turn"] = 5  # not the first decision: no 'plan' expected

    orders = rusher.decide(show_json, "blue")

    assert orders["actions"] == [{"unit_id": "blue-u1", "action": "hold"}]
    assert "plan" not in orders


def test_rusher_breaks_control_point_ties_by_id_not_iteration_order() -> None:
    units = [
        {
            "id": "blue-u1",
            "team_id": "blue",
            "agent_id": "blue-1",
            "role": "scout",
            "pos": [0, 0],
            "carrying": 0,
            "alive": True,
        }
    ]
    # Both points are equidistant from (0, 0); listed in reverse-id order so a
    # non-deterministic (e.g. dict/set-order-dependent) pick would show up.
    control_points = [
        {"id": "cp-b", "pos": [0, 2], "owner": None, "hold": []},
        {"id": "cp-a", "pos": [2, 0], "owner": None, "hold": []},
    ]
    legal_actions = {
        "blue-u1": {"move": [[1, 0], [0, 1]], "gather": False, "deliver": False, "hold": True}
    }

    orders = rusher.decide(_show_json(units, control_points, legal_actions), "blue")

    # cp-a sorts before cp-b, so the unit heads for [2, 0] — the legal move
    # that gets closest to it is [1, 0].
    assert orders["actions"] == [{"unit_id": "blue-u1", "action": "move", "to": [1, 0]}]


def test_rusher_ignores_dead_units_and_the_other_teams_units() -> None:
    units = [
        {
            "id": "blue-u1",
            "team_id": "blue",
            "agent_id": "blue-1",
            "role": "scout",
            "pos": [0, 0],
            "carrying": 0,
            "alive": False,
        },
        {
            "id": "red-u1",
            "team_id": "red",
            "agent_id": "red-1",
            "role": "scout",
            "pos": [0, 0],
            "carrying": 0,
            "alive": True,
        },
    ]
    control_points = [{"id": "cp-a", "pos": [5, 5], "owner": None, "hold": []}]

    orders = rusher.decide(_show_json(units, control_points, {}), "blue")

    assert orders["actions"] == []


# -- criterion 1: matches are deterministic given the seed ------------------


def _rusher_vs_greedy_config(match_id: str) -> dict:
    return {
        "match": {
            "scenario": "skirmish-1",
            "mode": "competitive",
            "seed": 7,
            "id": match_id,
        },
        "teams": [
            {
                "id": "blue",
                "name": "Blue Foundry",
                "driver": {"type": "bot-file", "strategy": "rusher"},
                "agents": [
                    {"id": "blue-1", "model": "bot-file:rusher", "role": "scout"},
                    {"id": "blue-2", "model": "bot-file:rusher", "role": "harvester"},
                    {"id": "blue-3", "model": "bot-file:rusher", "role": "defender"},
                ],
            },
            {
                "id": "red",
                "name": "Red Relay",
                "driver": {"type": "bot"},
                "agents": [
                    {"id": "red-1", "model": "bot:greedy", "role": "scout"},
                    {"id": "red-2", "model": "bot:greedy", "role": "harvester"},
                    {"id": "red-3", "model": "bot:greedy", "role": "defender"},
                ],
            },
        ],
        "max_rounds": 10,
    }


def test_rusher_matches_are_deterministic_given_the_seed(tmp_path, monkeypatch, capsys) -> None:
    config = _rusher_vs_greedy_config("m-rusher-det")

    run1 = tmp_path / "run1"
    run1.mkdir()
    monkeypatch.chdir(run1)
    run_match(config)
    capsys.readouterr()
    log1 = Store().load_match("m-rusher-det")

    run2 = tmp_path / "run2"
    run2.mkdir()
    monkeypatch.chdir(run2)
    run_match(config)
    capsys.readouterr()
    log2 = Store().load_match("m-rusher-det")

    # Same config, same seed, played twice: byte-identical logs, MODULO
    # `seat_latency` events (plan t1, spec c10/h9) — real wall-clock
    # instrumentation the harness appends per turn, which by construction
    # varies run to run even when everything the engine resolves does not.
    # It is a fold no-op (league/engine/events.py OBSERVATION_KINDS), so it
    # never touches game-logic determinism — see the exclusion below.
    assert _game_events(log1) == _game_events(log2)
    # ...and therefore identical final-state hashes (the same fingerprint the
    # determinism CI gate compares — tests/test_determinism_gate.py).
    assert state_hash(log1.final_state()) == state_hash(log2.final_state())
    # Sanity: the match actually played (not a zero-turn no-op).
    assert log1.final_state().turn > 0


# -- criterion 2: the strategy touches no league internals ------------------

_SPY_STRATEGY = '''"""Test-only spy: records exactly what the driver hands to decide()."""
from __future__ import annotations

import json
from pathlib import Path

_CAPTURE = Path(__file__).with_name("capture.json")


def decide(show_json, team_id):
    _CAPTURE.write_text(json.dumps({
        "team_id": team_id,
        "type": type(show_json).__name__,
        "keys": sorted(show_json.keys()),
        "state_type": type(show_json.get("state")).__name__,
        "json_round_trips": json.loads(json.dumps(show_json, sort_keys=True)) == show_json,
    }))
    return {"actions": []}
'''


def test_bot_file_driver_hands_strategy_only_the_public_json_dict(
    arena, monkeypatch, capsys
) -> None:
    """The bot-file driver never gives the strategy an engine object: it
    calls `match show --json` itself and hands the strategy exactly that
    parsed dict — the SAME public surface an external bot process would see
    (spec c3/h2)."""
    spy_dir = arena / "spybots"
    spy_dir.mkdir()
    (spy_dir / "spy.py").write_text(_SPY_STRATEGY)
    monkeypatch.setattr(harness, "_BOTS_DIR", spy_dir)

    assert main(_register("blue") + ["--apply"]) == 0
    assert main(_register("red") + ["--apply"]) == 0
    capsys.readouterr()
    assert main(_new_match("m-spy")) == 0
    capsys.readouterr()

    assert main(["match", "show", "m-spy", "--json"]) == 0
    shown = json.loads(capsys.readouterr().out)

    driver = build_driver({"type": "bot-file", "strategy": "spy"}, scenario={})
    context = {
        "legal_actions": shown["legal_actions"],
        "rejections": shown["last_turn_rejections"],
    }
    driver(shown["state"], "blue", 1, context)

    capture = json.loads((spy_dir / "capture.json").read_text())
    assert capture["team_id"] == "blue"
    # Exactly a plain dict (never an engine dataclass)...
    assert capture["type"] == "dict"
    assert capture["state_type"] == "dict"
    # ...with exactly the public `match show --json` fields, nothing more...
    assert capture["keys"] == sorted(
        [
            "state",
            "legal_actions",
            "staged_teams",
            "last_turn_rejections",
            "driver_kinds",
            "map_read",
            "unit_comms",
            "max_actions",
        ]
    )
    # ...and fully JSON-round-trippable — no non-serializable engine object
    # could be hiding inside it.
    assert capture["json_round_trips"] is True


def test_build_driver_bot_file_requires_strategy_name() -> None:
    with pytest.raises(ValueError, match="requires a 'strategy' name"):
        build_driver({"type": "bot-file"}, {})


def test_build_driver_bot_file_rejects_path_traversal_in_strategy_name() -> None:
    with pytest.raises(ValueError, match="invalid bot strategy name"):
        build_driver({"type": "bot-file", "strategy": "../evil"}, {})


def test_build_driver_bot_file_rejects_unknown_strategy() -> None:
    with pytest.raises(ValueError, match="unknown bot strategy"):
        build_driver({"type": "bot-file", "strategy": "does-not-exist"}, {})


def test_build_driver_bot_file_loads_rusher() -> None:
    driver = build_driver({"type": "bot-file", "strategy": "rusher"}, {})
    assert callable(driver)


def test_driver_kind_reports_bot_file_as_bot() -> None:
    """A coded strategy is the same fairness-axis peer as the in-harness
    greedy bot — a residency question about HOW minds were invoked, and a
    coded strategy is no more (or less) of a 'mind' than the greedy one."""
    assert driver_kind({"type": "bot-file", "strategy": "rusher"}) == "bot"


def test_build_driver_rejects_unknown_type_mentions_bot_file() -> None:
    with pytest.raises(ValueError, match="bot-file"):
        build_driver({"type": "telepathy"}, {})


# -- the house-bot roster: named strategies at declared difficulty tiers ----
# (plan task t4, spec c12/h11) --------------------------------------------
#
# Three named strategies, three distinct tiers: bots/shambler.py (bronze,
# legal-but-purposeless), bots/rusher.py (silver, the existing reference —
# untouched), bots/vanguard.py (gold, runs the delivery economy AND splits
# control points instead of letting units duplicate coverage). bots/README.md
# carries the human roster table; TIER_ORDER above is its machine mirror.


def test_every_roster_bot_declares_a_tier_from_the_ordered_vocabulary() -> None:
    for module in (shambler, rusher, vanguard, lampbearer):
        tier = getattr(module, "TIER", None)
        assert (
            tier in TIER_ORDER
        ), f"{module.__name__}.TIER must be one of {TIER_ORDER}, got {tier!r}"


def test_roster_covers_at_least_three_distinct_tiers() -> None:
    tiers = {shambler.TIER, rusher.TIER, vanguard.TIER}
    assert tiers == set(TIER_ORDER), "the roster must cover every declared tier exactly once"


# -- criterion 1 (bronze): shambler is committed, readable, legal-but-poor --


def test_shambler_strategy_is_committed_readable_source() -> None:
    path = BOTS_DIR / "shambler.py"
    assert path.is_file(), "bots/shambler.py must be committed source, not generated at runtime"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    top_level = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    assert "decide" in top_level, "bots/shambler.py must export a module-level decide(...)"


def test_shambler_holds_every_turn_even_when_it_could_legally_move() -> None:
    """The bronze floor: every declared action is legal (hold is always
    legal), but the strategy never converts a legal move into progress
    toward any control point, mission, or resource node — the 'poor
    decisions' half of the bronze tier's contract."""
    units = [
        {
            "id": "blue-u1",
            "team_id": "blue",
            "agent_id": "blue-1",
            "role": "scout",
            "pos": [0, 0],
            "carrying": 0,
            "alive": True,
        }
    ]
    control_points = [{"id": "cp-near", "pos": [1, 0], "owner": None, "hold": []}]
    legal_actions = {
        "blue-u1": {
            "move": [[0, 1], [1, 0], [1, 1]],
            "gather": False,
            "deliver": False,
            "hold": True,
        }
    }
    orders = shambler.decide(_show_json(units, control_points, legal_actions), "blue")

    assert orders["actions"] == [{"unit_id": "blue-u1", "action": "hold"}]
    assert orders["plan"].startswith("shambler:")


def test_shambler_ignores_a_resource_node_it_is_standing_on() -> None:
    """Even a 'free' gather right under its feet goes untaken — the bronze
    tier's whole point is that it never plays for the economy either."""
    units = [
        {
            "id": "blue-u1",
            "team_id": "blue",
            "agent_id": "blue-1",
            "role": "harvester",
            "pos": [0, 5],
            "carrying": 0,
            "alive": True,
        }
    ]
    legal_actions = {
        "blue-u1": {"move": [[0, 4], [1, 5]], "gather": True, "deliver": False, "hold": True}
    }
    show_json = _show_json(units, [], legal_actions)
    show_json["state"]["turn"] = 3

    orders = shambler.decide(show_json, "blue")

    assert orders["actions"] == [{"unit_id": "blue-u1", "action": "hold"}]
    assert "plan" not in orders


def test_shambler_ignores_dead_units_and_the_other_teams_units() -> None:
    units = [
        {
            "id": "blue-u1",
            "team_id": "blue",
            "agent_id": "blue-1",
            "role": "scout",
            "pos": [0, 0],
            "carrying": 0,
            "alive": False,
        },
        {
            "id": "red-u1",
            "team_id": "red",
            "agent_id": "red-1",
            "role": "scout",
            "pos": [0, 0],
            "carrying": 0,
            "alive": True,
        },
    ]
    orders = shambler.decide(_show_json(units, [], {}), "blue")
    assert orders["actions"] == []


# -- criterion 1 (gold): vanguard runs the economy + splits control points --


def test_vanguard_strategy_is_committed_readable_source() -> None:
    path = BOTS_DIR / "vanguard.py"
    assert path.is_file(), "bots/vanguard.py must be committed source, not generated at runtime"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    top_level = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    assert "decide" in top_level, "bots/vanguard.py must export a module-level decide(...)"


def _vanguard_show_json(units: list[dict], **extra: Any) -> dict:
    state = {
        "turn": 5,
        "units": units,
        "control_points": extra.get("control_points", []),
        "missions": extra.get("missions", []),
        "resource_nodes": extra.get("resource_nodes", []),
    }
    return {
        "state": state,
        "legal_actions": extra.get("legal_actions", {}),
        "staged_teams": [],
        "last_turn_rejections": [],
        "driver_kinds": {},
    }


def test_vanguard_harvester_delivers_when_legal() -> None:
    units = [
        {
            "id": "blue-u2",
            "team_id": "blue",
            "agent_id": "blue-2",
            "role": "harvester",
            "pos": [6, 5],
            "carrying": 3,
            "alive": True,
        }
    ]
    missions = [{"id": "ms-supply", "kind": "deliver", "pos": [6, 5], "amount": 6, "reward": 10}]
    legal_actions = {
        "blue-u2": {"move": [[5, 5], [7, 5]], "gather": False, "deliver": True, "hold": True}
    }
    show_json = _vanguard_show_json(units, missions=missions, legal_actions=legal_actions)

    orders = vanguard.decide(show_json, "blue")

    assert orders["actions"] == [{"unit_id": "blue-u2", "action": "deliver"}]


def test_vanguard_harvester_gathers_when_legal_and_not_yet_full() -> None:
    units = [
        {
            "id": "blue-u2",
            "team_id": "blue",
            "agent_id": "blue-2",
            "role": "harvester",
            "pos": [0, 5],
            "carrying": 0,
            "alive": True,
        }
    ]
    resource_nodes = [{"id": "rn-west", "pos": [0, 5], "remaining": 12}]
    missions = [{"id": "ms-supply", "kind": "deliver", "pos": [6, 5], "amount": 6, "reward": 10}]
    legal_actions = {
        "blue-u2": {"move": [[0, 4], [1, 5]], "gather": True, "deliver": False, "hold": True}
    }
    show_json = _vanguard_show_json(
        units, resource_nodes=resource_nodes, missions=missions, legal_actions=legal_actions
    )

    orders = vanguard.decide(show_json, "blue")

    assert orders["actions"] == [{"unit_id": "blue-u2", "action": "gather"}]


def test_vanguard_harvester_heads_for_delivery_square_once_loaded() -> None:
    units = [
        {
            "id": "blue-u2",
            "team_id": "blue",
            "agent_id": "blue-2",
            "role": "harvester",
            "pos": [0, 5],
            "carrying": 3,
            "alive": True,
        }
    ]
    missions = [{"id": "ms-supply", "kind": "deliver", "pos": [6, 5], "amount": 6, "reward": 10}]
    legal_actions = {
        "blue-u2": {
            "move": [[1, 5], [0, 4], [0, 6]],
            "gather": False,
            "deliver": False,
            "hold": True,
        }
    }
    show_json = _vanguard_show_json(units, missions=missions, legal_actions=legal_actions)

    orders = vanguard.decide(show_json, "blue")

    assert orders["actions"] == [{"unit_id": "blue-u2", "action": "move", "to": [1, 5]}]


def test_vanguard_splits_control_points_between_its_own_units() -> None:
    """Unlike rusher (every unit independently rushes its OWN nearest point),
    vanguard's non-harvesters claim DISTINCT points this turn — two units
    equidistant from the same point must not both head for it."""
    units = [
        {
            "id": "blue-u1",
            "team_id": "blue",
            "agent_id": "blue-1",
            "role": "scout",
            "pos": [5, 5],
            "carrying": 0,
            "alive": True,
        },
        {
            "id": "blue-u3",
            "team_id": "blue",
            "agent_id": "blue-3",
            "role": "defender",
            "pos": [7, 5],
            "carrying": 0,
            "alive": True,
        },
    ]
    control_points = [
        {"id": "cp-a", "pos": [6, 5], "owner": None, "hold": []},
        {"id": "cp-b", "pos": [6, 6], "owner": None, "hold": []},
    ]
    legal_actions = {
        "blue-u1": {"move": [[6, 5], [6, 4]], "gather": False, "deliver": False, "hold": True},
        "blue-u3": {"move": [[6, 5], [6, 6]], "gather": False, "deliver": False, "hold": True},
    }
    show_json = _vanguard_show_json(
        units, control_points=control_points, legal_actions=legal_actions
    )

    orders = vanguard.decide(show_json, "blue")

    moves = {a["unit_id"]: tuple(a["to"]) for a in orders["actions"] if a["action"] == "move"}
    # blue-u1 (sorted first) claims the nearer/lowest-id point cp-a; blue-u3
    # must NOT also head for [6, 5] — it claims the remaining point cp-b.
    assert moves["blue-u1"] == (6, 5)
    assert moves["blue-u3"] == (6, 6)


def test_vanguard_ignores_dead_units_and_the_other_teams_units() -> None:
    units = [
        {
            "id": "blue-u1",
            "team_id": "blue",
            "agent_id": "blue-1",
            "role": "scout",
            "pos": [0, 0],
            "carrying": 0,
            "alive": False,
        },
        {
            "id": "red-u1",
            "team_id": "red",
            "agent_id": "red-1",
            "role": "scout",
            "pos": [0, 0],
            "carrying": 0,
            "alive": True,
        },
    ]
    orders = vanguard.decide(_vanguard_show_json(units), "blue")
    assert orders["actions"] == []


# -- criterion 2 (recorded proof): a higher tier beats a lower tier ---------


def _tiered_config(match_id: str, gold_id: str, silver_id: str, seed: int) -> dict:
    """A gold-tier team vs a silver-tier team on skirmish-1, both bot-file."""
    return {
        "match": {"scenario": "skirmish-1", "mode": "competitive", "seed": seed, "id": match_id},
        "teams": [
            {
                "id": "blue",
                "name": "Blue",
                "driver": {"type": "bot-file", "strategy": gold_id},
                "agents": [
                    {"id": "blue-1", "model": f"bot-file:{gold_id}", "role": "scout"},
                    {"id": "blue-2", "model": f"bot-file:{gold_id}", "role": "harvester"},
                    {"id": "blue-3", "model": f"bot-file:{gold_id}", "role": "defender"},
                ],
            },
            {
                "id": "red",
                "name": "Red",
                "driver": {"type": "bot-file", "strategy": silver_id},
                "agents": [
                    {"id": "red-1", "model": f"bot-file:{silver_id}", "role": "scout"},
                    {"id": "red-2", "model": f"bot-file:{silver_id}", "role": "harvester"},
                    {"id": "red-3", "model": f"bot-file:{silver_id}", "role": "defender"},
                ],
            },
        ],
        "max_rounds": 32,
    }


@pytest.mark.parametrize("seed", [101, 202])
def test_vanguard_gold_beats_rusher_silver(tmp_path, monkeypatch, capsys, seed) -> None:
    """Recorded proof, re-run cheaply here (deterministic — no seed affects
    resolution, spec c9): gold beats silver over multiple seeds, matching
    the artifacts committed under docs/playtests/house-tiers/."""
    run_dir = tmp_path / f"gold-vs-silver-{seed}"
    run_dir.mkdir()
    monkeypatch.chdir(run_dir)

    config = _tiered_config(f"m-tier-gold-silver-{seed}", "vanguard", "rusher", seed)
    result = run_match(config)
    capsys.readouterr()

    assert result["winner"] == "blue"
    from league.engine.scoring import score_match

    log = Store().load_match(config["match"]["id"])
    report = score_match(log)
    assert report["outcome"]["blue"]["total"] > report["outcome"]["red"]["total"]


@pytest.mark.parametrize("seed", [101, 202])
def test_rusher_silver_beats_shambler_bronze(tmp_path, monkeypatch, capsys, seed) -> None:
    run_dir = tmp_path / f"silver-vs-bronze-{seed}"
    run_dir.mkdir()
    monkeypatch.chdir(run_dir)

    config = _tiered_config(f"m-tier-silver-bronze-{seed}", "rusher", "shambler", seed)
    result = run_match(config)
    capsys.readouterr()

    assert result["winner"] == "blue"
    from league.engine.scoring import score_match

    log = Store().load_match(config["match"]["id"])
    report = score_match(log)
    assert report["outcome"]["blue"]["total"] > report["outcome"]["red"]["total"]
