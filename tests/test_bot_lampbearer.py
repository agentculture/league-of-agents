"""``lampbearer`` — the fog-aware bot lane (plan task t3, spec c8/h4).

Criteria under test:

* the strategy consumes ONLY the fogged public JSON surface (what
  ``league match show --team <id> --fog --json`` returns) — a spy/sentinel
  test enforces this structurally (the same enforcement spirit as
  ``tests/test_bots.py``'s AST import ban), not by code review;
* an explore-toward-unknown baseline: with no control point known yet, every
  living unit heads for the nearest cell the team has never seen
  (``state["cells_seen"]``); once a control point IS known, it behaves like
  ``rusher.py`` (rush the nearest one, hold once arrived);
* the ``bot-file`` driver's new opt-in ``"fogged"`` flag
  (``league.harness.make_bot_file_driver``) actually swaps in the team's
  fogged view — and the full-information lane (the flag unset, or any other
  ``bots/*.py`` strategy) is unchanged, so the omniscience asymmetry warning
  only retires for matches that opt in.

This file is deliberately independent of ``tests/test_bots.py`` (which
covers ``rusher.py`` and the generic bot-lane contract): it lives here so it
never collides with unrelated edits to the shared rusher test file.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import bots.lampbearer as lampbearer
import league.harness as harness
from league.cli import main
from league.engine.state import state_hash
from league.harness import build_driver, driver_kind, run_match
from league.store import Store

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def arena(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _register(team: str, model: str = "bot-file:lampbearer") -> list[str]:
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


def _new_match(match_id: str, scenario: str = "skirmish-1") -> list[str]:
    return [
        "match",
        "new",
        "--scenario",
        scenario,
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


def _fogged_show_json(
    *,
    units: list[dict],
    control_points: list[dict],
    cells_seen: list[list[int]],
    legal_actions: dict,
    grid_width: int = 10,
    grid_height: int = 10,
    turn: int = 0,
) -> dict:
    """A hand-built fixture in EXACTLY the shape ``match show --team --fog
    --json`` returns — see ``league/cli/_commands/match.py:_fogged_state``:
    ``control_points``/``resource_nodes``/``missions`` are the team's KNOWN
    subset (often empty), never the full board, and ``cells_seen`` is the
    accumulated union of vision, not just this turn's."""
    return {
        "state": {
            "match_id": "m-test",
            "scenario_id": "skirmish-1",
            "seed": 7,
            "mode": "competitive",
            "turn": turn,
            "turn_limit": 20,
            "grid_width": grid_width,
            "grid_height": grid_height,
            "status": "active",
            "winner": None,
            "teams": [],
            "units": units,
            "control_points": control_points,
            "missions": [],
            "resource_nodes": [],
            "cells_seen": cells_seen,
        },
        "legal_actions": legal_actions,
        "staged_teams": [],
        "last_turn_rejections": [],
        "driver_kinds": {},
        "map_read": {},
        "unit_comms": {},
        "knowledge": {"team_id": "blue", "turn": turn},
    }


# -- criterion 1: explore-toward-unknown baseline when nothing is known -----


def test_lampbearer_explores_toward_the_nearest_unseen_cell_when_nothing_is_known() -> None:
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
    # Only (0,0), (1,0), (0,1) are seen so far on a 5x5 grid: the nearest
    # never-seen cell (Manhattan distance from (0,0), ties by (x, y)) is
    # (0, 2) — distance 2, and (0, 2) sorts before (1, 1) and (2, 0), the
    # other two distance-2 candidates.
    cells_seen = [[0, 0], [1, 0], [0, 1]]
    legal_actions = {
        "blue-u1": {
            "move": [[1, 0], [0, 1], [1, 1]],
            "gather": False,
            "deliver": False,
            "hold": True,
        }
    }
    show_json = _fogged_show_json(
        units=units,
        control_points=[],
        cells_seen=cells_seen,
        legal_actions=legal_actions,
        grid_width=5,
        grid_height=5,
    )

    orders = lampbearer.decide(show_json, "blue")

    # Of the three legal moves, [0, 1] is closest to the explore target (0, 2).
    assert orders["actions"] == [{"unit_id": "blue-u1", "action": "move", "to": [0, 1]}]
    assert orders["plan"].startswith("lampbearer:")


def test_lampbearer_holds_when_the_whole_grid_is_already_known_and_nothing_is_known() -> None:
    """No control point known AND every cell already seen: nothing to chase,
    nothing to explore — hold, never crash or move at random."""
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
    cells_seen = [[0, 0], [0, 1], [1, 0], [1, 1]]
    legal_actions = {
        "blue-u1": {
            "move": [[0, 1], [1, 0], [1, 1]],
            "gather": False,
            "deliver": False,
            "hold": True,
        }
    }
    show_json = _fogged_show_json(
        units=units,
        control_points=[],
        cells_seen=cells_seen,
        legal_actions=legal_actions,
        grid_width=2,
        grid_height=2,
    )

    orders = lampbearer.decide(show_json, "blue")

    assert orders["actions"] == [{"unit_id": "blue-u1", "action": "hold"}]


# -- criterion 2: sensible behavior once an objective is known --------------


def test_lampbearer_rushes_the_nearest_known_control_point() -> None:
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
    # A control point the fog fold has already told/seen — the fogged shape
    # (KnownControlPoint.to_dict) carries "turn"/"source", never "hold".
    control_points = [
        {"id": "cp-far", "pos": [9, 9], "owner": None, "turn": 1, "source": "told"},
        {"id": "cp-near", "pos": [1, 0], "owner": None, "turn": 2, "source": "seen"},
    ]
    legal_actions = {
        "blue-u1": {
            "move": [[0, 1], [1, 0], [1, 1]],
            "gather": False,
            "deliver": False,
            "hold": True,
        }
    }
    show_json = _fogged_show_json(
        units=units, control_points=control_points, cells_seen=[[0, 0]], legal_actions=legal_actions
    )

    orders = lampbearer.decide(show_json, "blue")

    assert orders["actions"] == [{"unit_id": "blue-u1", "action": "move", "to": [1, 0]}]


def test_lampbearer_holds_once_arrived_at_its_target_control_point() -> None:
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
    control_points = [{"id": "cp-near", "pos": [1, 0], "owner": None, "turn": 3, "source": "seen"}]
    legal_actions = {
        "blue-u1": {"move": [[0, 0], [2, 0]], "gather": False, "deliver": False, "hold": True}
    }
    show_json = _fogged_show_json(
        units=units,
        control_points=control_points,
        cells_seen=[[1, 0]],
        legal_actions=legal_actions,
        turn=5,
    )

    orders = lampbearer.decide(show_json, "blue")

    assert orders["actions"] == [{"unit_id": "blue-u1", "action": "hold"}]
    assert "plan" not in orders


def test_lampbearer_breaks_control_point_ties_by_id_not_iteration_order() -> None:
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
        {"id": "cp-b", "pos": [0, 2], "owner": None, "turn": 1, "source": "seen"},
        {"id": "cp-a", "pos": [2, 0], "owner": None, "turn": 1, "source": "seen"},
    ]
    legal_actions = {
        "blue-u1": {"move": [[1, 0], [0, 1]], "gather": False, "deliver": False, "hold": True}
    }
    show_json = _fogged_show_json(
        units=units, control_points=control_points, cells_seen=[[0, 0]], legal_actions=legal_actions
    )

    orders = lampbearer.decide(show_json, "blue")

    # cp-a sorts before cp-b at equal distance, so the unit heads for [2, 0].
    assert orders["actions"] == [{"unit_id": "blue-u1", "action": "move", "to": [1, 0]}]


def test_lampbearer_ignores_dead_units_and_the_other_teams_units() -> None:
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
            "role": "scout",
            "pos": [0, 0],
            "alive": True,
            "turn": 0,
            "source": "seen",
        },
    ]
    show_json = _fogged_show_json(
        units=units, control_points=[], cells_seen=[[0, 0]], legal_actions={}
    )

    orders = lampbearer.decide(show_json, "blue")

    assert orders["actions"] == []


def test_lampbearer_is_a_pure_deterministic_function_of_its_input() -> None:
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
    legal_actions = {"blue-u1": {"move": [[1, 0]], "gather": False, "deliver": False, "hold": True}}
    show_json = _fogged_show_json(
        units=units, control_points=[], cells_seen=[[0, 0]], legal_actions=legal_actions
    )

    first = lampbearer.decide(show_json, "blue")
    second = lampbearer.decide(show_json, "blue")
    assert first == second


# -- criterion 1: structural spy — sees nothing an agent team would not -----


class _AllowlistedState(dict):
    """A dict subclass standing in for ``show_json["state"]`` that raises the
    moment anything reads a key outside the fogged-state contract
    (``league/cli/_commands/match.py:_fogged_state``'s own output keys).

    This is the "sentinel" side of the spy pattern the task brief asks for:
    rather than trusting that ``lampbearer.decide`` only reads documented
    fields, it structurally enforces it — the same "caught by the test
    harness, not by code review" spirit as ``tests/test_bots.py``'s AST
    import ban. If a future edit to this strategy ever reaches for some
    undeclared, full-board-only key (an omniscience leak), this fixture
    fails loudly instead of the leak going unnoticed.
    """

    _ALLOWED = {
        "match_id",
        "scenario_id",
        "seed",
        "mode",
        "turn",
        "turn_limit",
        "grid_width",
        "grid_height",
        "status",
        "winner",
        "teams",
        "units",
        "control_points",
        "missions",
        "resource_nodes",
        "cells_seen",
    }

    def __getitem__(self, key: str) -> Any:
        assert key in self._ALLOWED, f"lampbearer read undeclared fogged state key {key!r}"
        return super().__getitem__(key)

    def get(self, key: str, default: Any = None) -> Any:
        assert key in self._ALLOWED, f"lampbearer read undeclared fogged state key {key!r}"
        return super().get(key, default)


class _AllowlistedShowJson(dict):
    """Same idea, one level up: ``show_json`` itself must only ever be read
    for the documented ``bot-file`` contract keys (``bots/README.md``)."""

    _ALLOWED = {
        "state",
        "legal_actions",
        "staged_teams",
        "last_turn_rejections",
        "driver_kinds",
        "map_read",
        "unit_comms",
        "knowledge",
    }

    def __getitem__(self, key: str) -> Any:
        assert key in self._ALLOWED, f"lampbearer read undeclared show_json key {key!r}"
        return super().__getitem__(key)

    def get(self, key: str, default: Any = None) -> Any:
        assert key in self._ALLOWED, f"lampbearer read undeclared show_json key {key!r}"
        return super().get(key, default)


def test_lampbearer_never_reads_a_key_outside_the_fogged_contract() -> None:
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
    control_points = [{"id": "cp-a", "pos": [3, 3], "owner": None, "turn": 1, "source": "told"}]
    legal_actions = {
        "blue-u1": {"move": [[1, 0], [0, 1]], "gather": False, "deliver": False, "hold": True}
    }
    plain = _fogged_show_json(
        units=units, control_points=control_points, cells_seen=[[0, 0]], legal_actions=legal_actions
    )
    trapped = _AllowlistedShowJson({**plain, "state": _AllowlistedState(plain["state"])})

    # Must not raise: every key lampbearer touches is in the fogged contract.
    orders = lampbearer.decide(trapped, "blue")
    assert orders["actions"]


def test_lampbearer_source_never_imports_league_internals_or_nondeterministic_modules() -> None:
    """Belt-and-suspenders: the generic scan in tests/test_bots.py already
    covers every bots/*.py file (including this one) by AST — this repeats
    the check narrowly scoped to lampbearer.py so this file stands alone."""
    import ast

    path = REPO_ROOT / "bots" / "lampbearer.py"
    assert path.is_file()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    banned = {"random", "time", "datetime", "secrets", "uuid", "league"}
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name.split(".")[0] for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [(node.module or "").split(".")[0]]
        else:
            continue
        offenders.extend(n for n in names if n in banned)
    assert not offenders, f"lampbearer.py imports banned modules: {offenders}"
    top_level = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    assert "decide" in top_level


# -- criterion 3: the bot-file driver's opt-in "fogged" flag ----------------


_SPY_STRATEGY = '''"""Test-only spy: records exactly what the driver hands to decide()."""
from __future__ import annotations

import json
from pathlib import Path

_CAPTURE = Path(__file__).with_name("capture.json")


def decide(show_json, team_id):
    _CAPTURE.write_text(json.dumps({
        "team_id": team_id,
        "keys": sorted(show_json.keys()),
        "state_keys": sorted(show_json.get("state", {}).keys()),
    }))
    return {"actions": []}
'''


def _spy_capture(spy_dir: Path, spec: dict, state: dict, team_id: str) -> dict:
    driver = build_driver(spec, scenario={})
    driver(state, team_id, 1, {})
    return json.loads((spy_dir / "capture.json").read_text())


def test_bot_file_driver_fogged_flag_hands_the_strategy_the_teams_fogged_view(
    arena, monkeypatch, capsys
) -> None:
    spy_dir = arena / "spybots"
    spy_dir.mkdir()
    (spy_dir / "spy.py").write_text(_SPY_STRATEGY)
    monkeypatch.setattr(harness, "_BOTS_DIR", spy_dir)

    assert main(_register("blue") + ["--apply"]) == 0
    assert main(_register("red") + ["--apply"]) == 0
    capsys.readouterr()
    assert main(_new_match("m-lampbearer-spy")) == 0
    capsys.readouterr()
    assert main(["match", "show", "m-lampbearer-spy", "--json"]) == 0
    state = json.loads(capsys.readouterr().out)["state"]

    fogged_capture = _spy_capture(
        spy_dir, {"type": "bot-file", "strategy": "spy", "fogged": True}, state, "blue"
    )
    # "knowledge" only ever appears in the fogged response
    # (league/cli/_commands/match.py:cmd_match_show) — its presence here is
    # proof the driver really called `--team --fog`, not the plain view.
    assert "knowledge" in fogged_capture["keys"]
    assert "cells_seen" in fogged_capture["state_keys"]

    plain_capture = _spy_capture(spy_dir, {"type": "bot-file", "strategy": "spy"}, state, "blue")
    assert "knowledge" not in plain_capture["keys"], (
        "the flag is opt-in: a bot-file spec that omits 'fogged' must keep "
        "today's full-information behavior, unchanged (the full-information "
        "lane stays available for unfogged play)"
    )


def test_driver_kind_reports_fogged_bot_file_as_bot_too() -> None:
    """Fog-awareness is a strategy policy question, not a residency one — a
    fog-aware coded strategy is still the same fairness-axis peer as the
    greedy in-harness bot and rusher."""
    assert driver_kind({"type": "bot-file", "strategy": "lampbearer", "fogged": True}) == "bot"


# -- end-to-end: a fogged match with lampbearer on both sides completes and -
# -- stays deterministic given the seed -------------------------------------


def _lampbearer_config(match_id: str) -> dict:
    return {
        "match": {"scenario": "skirmish-2", "mode": "competitive", "seed": 7, "id": match_id},
        "teams": [
            {
                "id": "blue",
                "name": "Blue Foundry",
                "driver": {"type": "bot-file", "strategy": "lampbearer", "fogged": True},
                "agents": [
                    {"id": "blue-1", "model": "bot-file:lampbearer", "role": "scout"},
                    {"id": "blue-2", "model": "bot-file:lampbearer", "role": "harvester"},
                    {"id": "blue-3", "model": "bot-file:lampbearer", "role": "defender"},
                ],
            },
            {
                "id": "red",
                "name": "Red Relay",
                "driver": {"type": "bot-file", "strategy": "lampbearer", "fogged": True},
                "agents": [
                    {"id": "red-1", "model": "bot-file:lampbearer", "role": "scout"},
                    {"id": "red-2", "model": "bot-file:lampbearer", "role": "harvester"},
                    {"id": "red-3", "model": "bot-file:lampbearer", "role": "defender"},
                ],
            },
        ],
        "max_rounds": 8,
        "fog": True,
    }


def test_fogged_lampbearer_vs_lampbearer_match_completes_and_is_deterministic(
    tmp_path, monkeypatch, capsys
) -> None:
    config = _lampbearer_config("m-lampbearer-fog")

    run1 = tmp_path / "run1"
    run1.mkdir()
    monkeypatch.chdir(run1)
    result1 = run_match(config)
    capsys.readouterr()
    log1 = Store().load_match("m-lampbearer-fog")

    run2 = tmp_path / "run2"
    run2.mkdir()
    monkeypatch.chdir(run2)
    run_match(config)
    capsys.readouterr()
    log2 = Store().load_match("m-lampbearer-fog")

    # seat_latency is real wall-clock instrumentation (plan C4-t1, spec
    # c10/h9) — a fold no-op that varies run to run by construction, so the
    # byte-for-byte comparison excludes it; state_hash below is the real
    # determinism invariant.
    game1 = [e.to_dict() for e in log1.events if e.kind != "seat_latency"]
    game2 = [e.to_dict() for e in log2.events if e.kind != "seat_latency"]
    assert game1 == game2
    assert state_hash(log1.final_state()) == state_hash(log2.final_state())
    assert log1.final_state().turn > 0
    assert result1["turns_played"] > 0
