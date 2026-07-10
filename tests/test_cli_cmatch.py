"""``league cmatch`` -- the continuous lane's external-driver CLI parity (issue #28).

Covers the five verbs (``new``/``show``/``act``/``tick``/``run``) end to end
through the public CLI surface ONLY (``league.cli.main``, never
``league.charness``/``league.engine`` directly except to build a reference log
for the parity proof and to register fixture teams) -- exactly the way an
external, subprocess-only harness would drive it. Suspend/resume is exercised
directly: every scenario here issues multiple, independent ``main()`` calls
that each re-read the match from ``.league/`` on disk, the same as if they
were separate OS processes.
"""

from __future__ import annotations

import dataclasses
import json
import pathlib

import pytest

from league.charness import run_cmatch
from league.cli import main
from league.engine.continuous.events import CMatchLog
from league.explain import known_paths
from league.store import Store

_PLAYTESTS = pathlib.Path(__file__).resolve().parent.parent / "docs" / "playtests"
_GRID_LOG_REL = "cycle-5/colleague-coop.log.jsonl"


@pytest.fixture()
def arena(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _register_teams(capsys) -> None:
    assert (
        main(
            [
                "team",
                "register",
                "blue",
                "--agent",
                "blue-1:m:defender",
                "--agent",
                "blue-2:m:harvester",
                "--apply",
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "team",
                "register",
                "red",
                "--agent",
                "red-1:m:defender",
                "--agent",
                "red-2:m:harvester",
                "--apply",
            ]
        )
        == 0
    )
    capsys.readouterr()  # discard the two "registered: ..." lines


# --------------------------------------------------------------------------- #
# overview / noun scaffolding / explain catalog
# --------------------------------------------------------------------------- #


def test_cmatch_overview_and_bare_noun(arena, capsys) -> None:
    assert main(["cmatch", "overview"]) == 0
    text = capsys.readouterr().out
    assert "league cmatch" in text
    assert main(["cmatch"]) == 0  # bare noun falls back to its overview
    capsys.readouterr()


def test_cmatch_overview_json_shape(arena, capsys) -> None:
    assert main(["cmatch", "overview", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["noun"] == "cmatch"
    assert {"new", "show", "act", "tick", "run"} <= set(data["verbs"])


def test_every_cmatch_path_has_a_catalog_entry() -> None:
    paths = set(known_paths())
    for verb in ("", "overview", "new", "show", "act", "tick", "run"):
        path = ("cmatch",) if not verb else ("cmatch", verb)
        assert path in paths, f"missing explain catalog entry for {path}"


def test_every_cmatch_catalog_path_resolves(arena, capsys) -> None:
    for path in known_paths():
        if path and path[0] == "cmatch":
            rc = main(["explain", *path])
            assert rc == 0, f"explain {' '.join(path)} failed"
            capsys.readouterr()


# --------------------------------------------------------------------------- #
# new
# --------------------------------------------------------------------------- #


def test_new_dry_run_writes_nothing(arena, capsys) -> None:
    _register_teams(capsys)
    rc = main(
        [
            "cmatch",
            "new",
            "--scenario",
            "c-skirmish-1",
            "--team",
            "blue",
            "--team",
            "red",
            "--id",
            "cm-dry",
            "--json",
        ]
    )
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["applied"] is False
    assert "log" not in data
    assert not (arena / ".league" / "matches" / "cm-dry").exists()


def test_new_apply_persists_a_continuous_log_and_starts_the_match(arena, capsys) -> None:
    _register_teams(capsys)
    rc = main(
        [
            "cmatch",
            "new",
            "--scenario",
            "c-skirmish-1",
            "--team",
            "blue",
            "--team",
            "red",
            "--driver",
            "blue:bot",
            "--driver",
            "red:bot",
            "--id",
            "cm-created",
            "--apply",
            "--json",
        ]
    )
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["applied"] is True
    assert data["driver_kinds"] == {"blue": "bot", "red": "bot"}
    assert sorted(data["due"]) == ["blue-u1", "blue-u2", "red-u1", "red-u2"]
    path = arena / ".league" / "matches" / "cm-created" / "log.jsonl"
    assert path.is_file()
    clog = CMatchLog.from_jsonl(path.read_text(encoding="utf-8"))
    assert [e.kind for e in clog.events] == ["match_started"]
    assert clog.final_state().status == "active"


def test_new_auto_generates_a_match_id(arena, capsys) -> None:
    _register_teams(capsys)
    assert (
        main(
            [
                "cmatch",
                "new",
                "--scenario",
                "c-skirmish-1",
                "--team",
                "blue",
                "--team",
                "red",
                "--apply",
                "--json",
            ]
        )
        == 0
    )
    data = json.loads(capsys.readouterr().out)
    assert data["match_id"].startswith("cm-c-skirmish-1-competitive-s0-")


def test_new_rejects_a_second_apply_with_the_same_id(arena, capsys) -> None:
    _register_teams(capsys)
    assert (
        main(
            [
                "cmatch",
                "new",
                "--scenario",
                "c-skirmish-1",
                "--team",
                "blue",
                "--team",
                "red",
                "--id",
                "cm-dupe",
                "--apply",
            ]
        )
        == 0
    )
    capsys.readouterr()
    rc = main(
        [
            "cmatch",
            "new",
            "--scenario",
            "c-skirmish-1",
            "--team",
            "blue",
            "--team",
            "red",
            "--id",
            "cm-dupe",
            "--apply",
        ]
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert err.startswith("error:")
    assert "hint:" in err


def test_new_unknown_scenario_is_a_clean_error(arena, capsys) -> None:
    _register_teams(capsys)
    rc = main(
        ["cmatch", "new", "--scenario", "c-nope", "--team", "blue", "--team", "red", "--apply"]
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert err.startswith("error:") and "hint:" in err


def test_new_unregistered_team_is_a_clean_error(arena, capsys) -> None:
    rc = main(
        [
            "cmatch",
            "new",
            "--scenario",
            "c-skirmish-1",
            "--team",
            "ghost",
            "--team",
            "red",
            "--apply",
        ]
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert err.startswith("error:") and "hint:" in err


def test_new_bad_driver_flag_is_a_clean_error(arena, capsys) -> None:
    _register_teams(capsys)
    rc = main(
        [
            "cmatch",
            "new",
            "--scenario",
            "c-skirmish-1",
            "--team",
            "blue",
            "--team",
            "red",
            "--driver",
            "blue:not-a-kind",
            "--apply",
        ]
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert "unknown driver kind" in err


def test_new_malformed_driver_flag_missing_colon_is_a_clean_error(arena, capsys) -> None:
    _register_teams(capsys)
    rc = main(
        [
            "cmatch",
            "new",
            "--scenario",
            "c-skirmish-1",
            "--team",
            "blue",
            "--team",
            "red",
            "--driver",
            "blue-no-colon",
            "--apply",
        ]
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert "bad --driver" in err


def test_new_driver_flag_for_a_team_not_in_team_is_a_clean_error(arena, capsys) -> None:
    _register_teams(capsys)
    rc = main(
        [
            "cmatch",
            "new",
            "--scenario",
            "c-skirmish-1",
            "--team",
            "blue",
            "--team",
            "red",
            "--driver",
            "green:bot",
            "--apply",
        ]
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert "not one of --team" in err


def test_new_driver_flag_bot_file_bad_strategy_name_is_a_clean_error(arena, capsys) -> None:
    _register_teams(capsys)
    rc = main(
        [
            "cmatch",
            "new",
            "--scenario",
            "c-skirmish-1",
            "--team",
            "blue",
            "--team",
            "red",
            "--driver",
            "blue:bot-file:../escape",
            "--apply",
        ]
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert "bad --driver" in err


def test_new_config_resident_and_command_driver_labels(arena, capsys) -> None:
    config = json.dumps(
        {
            "match": {"scenario": "c-skirmish-1", "id": "cm-labels"},
            "teams": [
                {
                    "id": "blue",
                    "driver": {"type": "resident"},
                    "agents": [{"id": "b1", "role": "defender"}, {"id": "b2", "role": "harvester"}],
                },
                {
                    "id": "red",
                    "driver": {"type": "command", "residency": "resident"},
                    "agents": [{"id": "r1", "role": "defender"}, {"id": "r2", "role": "harvester"}],
                },
            ],
        }
    )
    rc = main(["cmatch", "new", "--config", config, "--apply", "--json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["driver_kinds"] == {"blue": "resident", "red": "resident"}


def test_new_config_bot_file_without_strategy_is_a_clean_error(arena, capsys) -> None:
    config = json.dumps(
        {
            "match": {"scenario": "c-skirmish-1", "id": "cm-nostrategy"},
            "teams": [
                {
                    "id": "blue",
                    "driver": {"type": "bot-file"},
                    "agents": [{"id": "b1", "role": "defender"}],
                }
            ],
        }
    )
    rc = main(["cmatch", "new", "--config", config, "--apply"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "strategy" in err


def test_new_config_unknown_driver_type_is_a_clean_error(arena, capsys) -> None:
    config = json.dumps(
        {
            "match": {"scenario": "c-skirmish-1", "id": "cm-baddriver"},
            "teams": [
                {
                    "id": "blue",
                    "driver": {"type": "telepathy"},
                    "agents": [{"id": "b1", "role": "defender"}],
                }
            ],
        }
    )
    rc = main(["cmatch", "new", "--config", config, "--apply"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "unknown driver type" in err


def test_new_config_bad_command_residency_is_a_clean_error(arena, capsys) -> None:
    config = json.dumps(
        {
            "match": {"scenario": "c-skirmish-1", "id": "cm-badresidency"},
            "teams": [
                {
                    "id": "blue",
                    "driver": {"type": "command", "residency": "eternal"},
                    "agents": [{"id": "b1", "role": "defender"}],
                }
            ],
        }
    )
    rc = main(["cmatch", "new", "--config", config, "--apply"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "unknown residency" in err


def test_new_config_missing_team_id_is_a_clean_error(arena, capsys) -> None:
    config = json.dumps(
        {
            "match": {"scenario": "c-skirmish-1", "id": "cm-noteamid"},
            "teams": [{"agents": [{"id": "b1", "role": "defender"}]}],
        }
    )
    rc = main(["cmatch", "new", "--config", config, "--apply"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "needs an 'id'" in err


def test_new_config_missing_scenario_is_a_clean_error(arena, capsys) -> None:
    config = json.dumps({"match": {"id": "cm-noscenario"}, "teams": []})
    rc = main(["cmatch", "new", "--config", config, "--apply"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "match.scenario" in err


def test_new_missing_scenario_flag_is_a_clean_error(arena, capsys) -> None:
    rc = main(["cmatch", "new", "--team", "blue", "--apply"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "--scenario is required" in err


def test_tick_unknown_bot_file_strategy_is_an_environment_error(arena, capsys) -> None:
    config = json.dumps(
        {
            "match": {"scenario": "c-skirmish-1", "id": "cm-badstrategy"},
            "teams": [
                {
                    "id": "blue",
                    "driver": {"type": "bot-file", "strategy": "no-such-strategy"},
                    "agents": [{"id": "b1", "role": "defender"}, {"id": "b2", "role": "harvester"}],
                },
                {
                    "id": "red",
                    "driver": {"type": "bot"},
                    "agents": [{"id": "r1", "role": "defender"}, {"id": "r2", "role": "harvester"}],
                },
            ],
        }
    )
    assert main(["cmatch", "new", "--config", config, "--apply"]) == 0
    capsys.readouterr()
    rc = main(["cmatch", "tick", "cm-badstrategy", "--apply"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "cannot load bot strategy" in err


def test_new_config_json_inline(arena, capsys) -> None:
    config = json.dumps(
        {
            "match": {"scenario": "c-skirmish-1", "id": "cm-cfg", "seed": 3},
            "teams": [
                {
                    "id": "blue",
                    "driver": {"type": "bot"},
                    "agents": [{"id": "b1", "role": "defender"}, {"id": "b2", "role": "harvester"}],
                },
                {
                    "id": "red",
                    "driver": {"type": "bot-file", "strategy": "crusher"},
                    "agents": [{"id": "r1", "role": "defender"}, {"id": "r2", "role": "harvester"}],
                },
            ],
        }
    )
    rc = main(["cmatch", "new", "--config", config, "--apply", "--json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["match_id"] == "cm-cfg"
    assert data["seed"] == 3
    assert data["driver_kinds"] == {"blue": "bot", "red": "bot-file:crusher"}


def test_new_config_rejects_fog(arena, capsys) -> None:
    config = json.dumps(
        {
            "match": {"scenario": "c-skirmish-1", "id": "cm-fog"},
            "teams": [
                {
                    "id": "blue",
                    "driver": {"type": "bot"},
                    "agents": [{"id": "b1", "role": "defender"}],
                },
            ],
            "fog": True,
        }
    )
    rc = main(["cmatch", "new", "--config", config, "--apply"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "fog" in err
    assert "cmatch run" in err


def test_new_config_bad_json_is_a_clean_error(arena, capsys) -> None:
    rc = main(["cmatch", "new", "--config", "{not json", "--apply"])
    assert rc == 1
    err = capsys.readouterr().err
    assert err.startswith("error:") and "hint:" in err


# --------------------------------------------------------------------------- #
# show
# --------------------------------------------------------------------------- #


def test_show_missing_match_is_a_clean_error(arena, capsys) -> None:
    rc = main(["cmatch", "show", "c-nope"])
    assert rc == 1
    err = capsys.readouterr().err
    assert err.startswith("error:") and "hint:" in err


def test_show_on_a_grid_log_is_a_clean_error(arena, capsys) -> None:
    from league.engine.events import MatchLog

    raw = (_PLAYTESTS / _GRID_LOG_REL).read_text(encoding="utf-8")
    match_id = MatchLog.from_jsonl(raw).initial_state.match_id
    grid_dir = arena / ".league" / "matches" / match_id
    grid_dir.mkdir(parents=True)
    (grid_dir / "log.jsonl").write_text(raw, encoding="utf-8")

    rc = main(["cmatch", "show", match_id])
    assert rc == 1
    err = capsys.readouterr().err
    assert err.startswith("error:") and "hint:" in err
    assert "continuous" in err


def test_show_scopes_to_one_unit(arena, capsys) -> None:
    _register_teams(capsys)
    assert (
        main(
            [
                "cmatch",
                "new",
                "--scenario",
                "c-skirmish-1",
                "--team",
                "blue",
                "--team",
                "red",
                "--id",
                "cm-show",
                "--apply",
            ]
        )
        == 0
    )
    capsys.readouterr()

    assert main(["cmatch", "show", "cm-show", "--unit", "blue-u1", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert [d["unit_id"] for d in data["decisions"]] == ["blue-u1"]
    assert data["decisions"][0]["briefing"]["you"]["unit_id"] == "blue-u1"


def test_show_unit_not_due_is_a_clean_error(arena, capsys) -> None:
    _register_teams(capsys)
    assert (
        main(
            [
                "cmatch",
                "new",
                "--scenario",
                "c-skirmish-1",
                "--team",
                "blue",
                "--team",
                "red",
                "--id",
                "cm-show2",
                "--apply",
            ]
        )
        == 0
    )
    capsys.readouterr()
    rc = main(["cmatch", "show", "cm-show2", "--unit", "no-such-unit"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "not currently due" in err


def test_show_text_mode_renders_something_readable(arena, capsys) -> None:
    _register_teams(capsys)
    assert (
        main(
            [
                "cmatch",
                "new",
                "--scenario",
                "c-skirmish-1",
                "--team",
                "blue",
                "--team",
                "red",
                "--id",
                "cm-text",
                "--apply",
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert main(["cmatch", "show", "cm-text"]) == 0
    text = capsys.readouterr().out
    assert "cm-text" in text
    assert "blue-u1" in text


# --------------------------------------------------------------------------- #
# act
# --------------------------------------------------------------------------- #


def test_act_dry_run_writes_nothing(arena, capsys) -> None:
    _register_teams(capsys)
    assert (
        main(
            [
                "cmatch",
                "new",
                "--scenario",
                "c-skirmish-1",
                "--team",
                "blue",
                "--team",
                "red",
                "--id",
                "cm-act-dry",
                "--apply",
            ]
        )
        == 0
    )
    capsys.readouterr()
    rc = main(
        [
            "cmatch",
            "act",
            "cm-act-dry",
            "--unit",
            "blue-u1",
            "--action-json",
            '{"kind": "move", "target_pos": {"x": 5000, "y": 4000}}',
            "--json",
        ]
    )
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["applied"] is False
    log_before = (arena / ".league" / "matches" / "cm-act-dry" / "log.jsonl").read_text()
    assert "action_started" not in log_before


def test_act_apply_appends_events_and_advances_due(arena, capsys) -> None:
    _register_teams(capsys)
    assert (
        main(
            [
                "cmatch",
                "new",
                "--scenario",
                "c-skirmish-1",
                "--team",
                "blue",
                "--team",
                "red",
                "--id",
                "cm-act",
                "--apply",
            ]
        )
        == 0
    )
    capsys.readouterr()
    rc = main(
        [
            "cmatch",
            "act",
            "cm-act",
            "--unit",
            "blue-u1",
            "--action-json",
            '{"kind": "move", "target_pos": {"x": 5000, "y": 4000}}',
            "--apply",
            "--json",
        ]
    )
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["applied"] is True
    assert data["events_appended"] == 2  # decision_point + action_started
    assert "blue-u1" not in data["due"]
    assert data["due"] == ["blue-u2", "red-u1", "red-u2"]


def test_act_park_with_null_action(arena, capsys) -> None:
    _register_teams(capsys)
    assert (
        main(
            [
                "cmatch",
                "new",
                "--scenario",
                "c-skirmish-1",
                "--team",
                "blue",
                "--team",
                "red",
                "--id",
                "cm-park",
                "--apply",
            ]
        )
        == 0
    )
    capsys.readouterr()
    rc = main(
        [
            "cmatch",
            "act",
            "cm-park",
            "--unit",
            "blue-u1",
            "--action-json",
            "null",
            "--apply",
            "--json",
        ]
    )
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["events_appended"] == 1  # decision_point only, no action_started
    assert data["action"] is None


def test_act_omitted_action_json_also_parks(arena, capsys) -> None:
    _register_teams(capsys)
    assert (
        main(
            [
                "cmatch",
                "new",
                "--scenario",
                "c-skirmish-1",
                "--team",
                "blue",
                "--team",
                "red",
                "--id",
                "cm-park2",
                "--apply",
            ]
        )
        == 0
    )
    capsys.readouterr()
    rc = main(["cmatch", "act", "cm-park2", "--unit", "blue-u1", "--apply", "--json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["action"] is None
    assert data["events_appended"] == 1


def test_act_wrong_order_is_a_clean_error_naming_the_front_of_the_queue(arena, capsys) -> None:
    _register_teams(capsys)
    assert (
        main(
            [
                "cmatch",
                "new",
                "--scenario",
                "c-skirmish-1",
                "--team",
                "blue",
                "--team",
                "red",
                "--id",
                "cm-order",
                "--apply",
            ]
        )
        == 0
    )
    capsys.readouterr()
    rc = main(["cmatch", "act", "cm-order", "--unit", "red-u1", "--apply"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "must be answered first" in err
    assert "blue-u1" in err


def test_act_unknown_unit_is_a_clean_error(arena, capsys) -> None:
    _register_teams(capsys)
    assert (
        main(
            [
                "cmatch",
                "new",
                "--scenario",
                "c-skirmish-1",
                "--team",
                "blue",
                "--team",
                "red",
                "--id",
                "cm-unk",
                "--apply",
            ]
        )
        == 0
    )
    capsys.readouterr()
    rc = main(["cmatch", "act", "cm-unk", "--unit", "nope", "--apply"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "not currently due" in err


def test_act_illegal_action_is_a_clean_error_and_does_not_write(arena, capsys) -> None:
    _register_teams(capsys)
    assert (
        main(
            [
                "cmatch",
                "new",
                "--scenario",
                "c-skirmish-1",
                "--team",
                "blue",
                "--team",
                "red",
                "--id",
                "cm-illegal",
                "--apply",
            ]
        )
        == 0
    )
    capsys.readouterr()
    rc = main(
        [
            "cmatch",
            "act",
            "cm-illegal",
            "--unit",
            "blue-u1",
            "--action-json",
            '{"kind": "take_post", "target_id": "no-such-cp"}',
            "--apply",
        ]
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert "not legal" in err
    log = (arena / ".league" / "matches" / "cm-illegal" / "log.jsonl").read_text()
    assert "action_started" not in log


def test_act_on_a_match_with_no_due_units_is_a_clean_error(arena, capsys) -> None:
    """'active, but nothing currently due' is not reachable by driving the
    cmatch verbs alone -- advance_external's own auto-cascade (the SAME
    discipline resolve_match uses) always leaves a completed 'act'/'tick'
    call at either a fresh due round or a finished match, never in between.
    It IS a legitimate log shape though (every unit simply mid-action, e.g.
    right after a harness fires off several long moves in one breath, with
    nothing having completed yet) -- exercise it directly against a
    hand-built log, the same way a hand-edited/replayed log could reach it,
    and confirm 'act' points the caller at 'tick' instead of anything
    unit-specific."""
    from league.engine.continuous.events import CMatchLog
    from league.engine.continuous.resolve import due_decisions, resolve_match
    from league.engine.continuous.scenario import get_cscenario, instantiate
    from league.engine.continuous.state import CAgentSlot

    scenario = get_cscenario("c-skirmish-1")
    teams = [
        (
            "blue",
            "blue",
            (
                CAgentSlot(id="blue-1", model="m", role="defender"),
                CAgentSlot(id="blue-2", model="m", role="harvester"),
            ),
        ),
        (
            "red",
            "red",
            (
                CAgentSlot(id="red-1", model="m", role="defender"),
                CAgentSlot(id="red-2", model="m", role="harvester"),
            ),
        ),
    ]
    initial = instantiate(scenario, match_id="cm-nodue", seed=0, mode="competitive", teams=teams)

    def start_everyone_moving(uid, state, menu):
        for entry in menu["actions"]:
            if entry["kind"] == "move":
                return entry
        return None  # nothing to move toward -- park (never happens here)

    result = resolve_match(initial, scenario.role_table, start_everyone_moving)
    # Truncate right after every unit's OWN first action_started (before any
    # of them completes) -- the exact "everyone busy, nobody due yet" cut.
    cutoff = (
        next(
            i
            for i, e in enumerate(result.log.events)
            if e.kind == "action_started" and e.data["unit_id"] == "red-u2"
        )
        + 1
    )
    clog = CMatchLog(initial_state=initial, events=result.log.events[:cutoff])
    assert clog.final_state().status == "active"
    assert due_decisions(clog) == []  # confirms the fixture reaches the state under test
    Store().log_path("cm-nodue").parent.mkdir(parents=True, exist_ok=True)
    Store().log_path("cm-nodue").write_text(clog.to_jsonl(), encoding="utf-8")

    rc = main(["cmatch", "act", "cm-nodue", "--unit", "blue-u1", "--apply"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "no unit is currently due" in err
    assert "tick" in err


def test_act_bad_action_json_is_a_clean_error(arena, capsys) -> None:
    _register_teams(capsys)
    assert (
        main(
            [
                "cmatch",
                "new",
                "--scenario",
                "c-skirmish-1",
                "--team",
                "blue",
                "--team",
                "red",
                "--id",
                "cm-badjson",
                "--apply",
            ]
        )
        == 0
    )
    capsys.readouterr()
    rc = main(
        [
            "cmatch",
            "act",
            "cm-badjson",
            "--unit",
            "blue-u1",
            "--action-json",
            "{not json",
            "--apply",
        ]
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert err.startswith("error:")


def test_act_text_mode(arena, capsys) -> None:
    _register_teams(capsys)
    assert (
        main(
            [
                "cmatch",
                "new",
                "--scenario",
                "c-skirmish-1",
                "--team",
                "blue",
                "--team",
                "red",
                "--id",
                "cm-acttext",
                "--apply",
            ]
        )
        == 0
    )
    capsys.readouterr()
    rc = main(
        [
            "cmatch",
            "act",
            "cm-acttext",
            "--unit",
            "blue-u1",
            "--action-json",
            '{"kind": "move", "target_pos": {"x": 5000, "y": 4000}}',
            "--apply",
        ]
    )
    assert rc == 0
    text = capsys.readouterr().out
    assert "blue-u1" in text
    assert "move" in text


# --------------------------------------------------------------------------- #
# tick
# --------------------------------------------------------------------------- #


def test_tick_dry_run_writes_nothing(arena, capsys) -> None:
    _register_teams(capsys)
    assert (
        main(
            [
                "cmatch",
                "new",
                "--scenario",
                "c-skirmish-1",
                "--team",
                "blue",
                "--team",
                "red",
                "--driver",
                "blue:bot",
                "--driver",
                "red:bot",
                "--id",
                "cm-tickdry",
                "--apply",
            ]
        )
        == 0
    )
    capsys.readouterr()
    rc = main(["cmatch", "tick", "cm-tickdry", "--json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["applied"] is False
    assert sorted(data["would_resolve"]) == ["blue-u1", "blue-u2", "red-u1", "red-u2"]
    log = (arena / ".league" / "matches" / "cm-tickdry" / "log.jsonl").read_text()
    assert "decision_point" not in log


def test_tick_apply_resolves_bot_driven_units_and_advances(arena, capsys) -> None:
    _register_teams(capsys)
    assert (
        main(
            [
                "cmatch",
                "new",
                "--scenario",
                "c-skirmish-1",
                "--team",
                "blue",
                "--team",
                "red",
                "--driver",
                "blue:bot",
                "--driver",
                "red:bot",
                "--id",
                "cm-tick",
                "--apply",
            ]
        )
        == 0
    )
    capsys.readouterr()
    rc = main(["cmatch", "tick", "cm-tick", "--apply", "--json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["applied"] is True
    assert data["events_appended"] > 0
    assert sorted(set(data["resolved"])) == ["blue-u1", "blue-u2", "red-u1", "red-u2"]


def test_tick_resolves_a_bot_file_driven_team(arena, capsys) -> None:
    """The other half of the coded-strategy bot lane (bots/crusher.py, the
    continuous reference strategy): 'bot-file:<name>' is reconstructed from
    the log header's own driver label -- no separate config file needed --
    and ticks a match to completion exactly like the plain 'bot' driver."""
    config = json.dumps(
        {
            "match": {"scenario": "c-skirmish-1", "id": "cm-crusher"},
            "teams": [
                {
                    "id": "blue",
                    "driver": {"type": "bot-file", "strategy": "crusher"},
                    "agents": [{"id": "b1", "role": "defender"}, {"id": "b2", "role": "harvester"}],
                },
                {
                    "id": "red",
                    "driver": {"type": "bot"},
                    "agents": [{"id": "r1", "role": "defender"}, {"id": "r2", "role": "harvester"}],
                },
            ],
        }
    )
    assert main(["cmatch", "new", "--config", config, "--apply"]) == 0
    capsys.readouterr()

    finished = False
    data = None
    for _ in range(20):
        assert main(["cmatch", "tick", "cm-crusher", "--apply", "--json"]) == 0
        data = json.loads(capsys.readouterr().out)
        if data["finished"]:
            finished = True
            break
    assert finished
    assert data["status"] == "finished"
    assert "blue-u1" in data["resolved"] or "blue-u2" in data["resolved"]


def test_tick_repeated_calls_run_a_bot_vs_bot_match_to_completion(arena, capsys) -> None:
    """Repeated, independent 'tick --apply' calls (suspend/resume between
    every single one) drive a fully bot-driven match all the way to
    match_finished -- the offline equivalent of 'cmatch run', one CLI call at
    a time."""
    _register_teams(capsys)
    assert (
        main(
            [
                "cmatch",
                "new",
                "--scenario",
                "c-skirmish-1",
                "--team",
                "blue",
                "--team",
                "red",
                "--driver",
                "blue:bot",
                "--driver",
                "red:bot",
                "--id",
                "cm-tickloop",
                "--apply",
            ]
        )
        == 0
    )
    capsys.readouterr()

    finished = False
    for _ in range(20):
        rc = main(["cmatch", "tick", "cm-tickloop", "--apply", "--json"])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        if data["finished"]:
            finished = True
            break
    assert finished
    assert data["winner"] == "blue"
    assert data["status"] == "finished"


def test_tick_pauses_on_a_stateless_team_without_timeout_park(arena, capsys) -> None:
    _register_teams(capsys)
    assert (
        main(
            [
                "cmatch",
                "new",
                "--scenario",
                "c-skirmish-1",
                "--team",
                "blue",
                "--team",
                "red",
                "--driver",
                "blue:bot",
                "--driver",
                "red:stateless",
                "--id",
                "cm-mixed",
                "--apply",
            ]
        )
        == 0
    )
    capsys.readouterr()
    rc = main(["cmatch", "tick", "cm-mixed", "--apply", "--json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert sorted(data["resolved"]) == ["blue-u1", "blue-u2"]
    assert data["parked"] == []
    assert "red-u1" in data["due_now"] and "red-u2" in data["due_now"]
    assert data["finished"] is False


def test_tick_timeout_park_parks_the_stateless_team(arena, capsys) -> None:
    _register_teams(capsys)
    assert (
        main(
            [
                "cmatch",
                "new",
                "--scenario",
                "c-skirmish-1",
                "--team",
                "blue",
                "--team",
                "red",
                "--driver",
                "blue:bot",
                "--driver",
                "red:stateless",
                "--id",
                "cm-park-timeout",
                "--apply",
            ]
        )
        == 0
    )
    capsys.readouterr()
    rc = main(["cmatch", "tick", "cm-park-timeout", "--timeout-park", "--apply", "--json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert sorted(data["parked"]) == ["red-u1", "red-u2"]
    assert data["due_now"] == []  # both red units asked-and-parked; blue mid-action


def test_tick_on_an_inactive_match_is_a_clean_error(arena, capsys) -> None:
    rc = main(["cmatch", "tick", "no-such-match", "--apply"])
    assert rc == 1
    err = capsys.readouterr().err
    assert err.startswith("error:") and "hint:" in err


# --------------------------------------------------------------------------- #
# run
# --------------------------------------------------------------------------- #


def _run_config(match_id: str) -> str:
    return json.dumps(
        {
            "match": {"scenario": "c-skirmish-1", "id": match_id},
            "teams": [
                {
                    "id": "blue",
                    "driver": {"type": "bot"},
                    "agents": [{"id": "b1", "role": "defender"}, {"id": "b2", "role": "harvester"}],
                },
                {
                    "id": "red",
                    "driver": {"type": "bot"},
                    "agents": [{"id": "r1", "role": "defender"}, {"id": "r2", "role": "harvester"}],
                },
            ],
        }
    )


def test_run_dry_run_writes_nothing(arena, capsys) -> None:
    rc = main(["cmatch", "run", "--config", _run_config("cm-rundry"), "--json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["applied"] is False
    assert not (arena / ".league" / "matches" / "cm-rundry").exists()


def test_run_apply_persists_and_finishes(arena, capsys) -> None:
    rc = main(["cmatch", "run", "--config", _run_config("cm-runapply"), "--apply", "--json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["match_id"] == "cm-runapply"
    assert data["status"] == "finished"
    assert data["winner"] == "blue"
    path = arena / ".league" / "matches" / "cm-runapply" / "log.jsonl"
    assert path.is_file()


def test_run_refuses_to_clobber_an_existing_match(arena, capsys) -> None:
    assert main(["cmatch", "run", "--config", _run_config("cm-clobber"), "--apply"]) == 0
    capsys.readouterr()
    rc = main(["cmatch", "run", "--config", _run_config("cm-clobber"), "--apply"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "already exists" in err


def test_run_config_file_path(arena, capsys, tmp_path) -> None:
    cfg_path = tmp_path / "cfg.json"
    cfg_path.write_text(_run_config("cm-fromfile"), encoding="utf-8")
    rc = main(["cmatch", "run", "--config", str(cfg_path), "--apply", "--json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["match_id"] == "cm-fromfile"


def test_run_matches_still_replay_and_score_through_the_grid_verbs(arena, capsys) -> None:
    """Issue #28's ask: 'match score'/'match replay' keep working on cmatch
    logs unchanged -- they already lane-sniff (PR #33)."""
    assert main(["cmatch", "run", "--config", _run_config("cm-lanecheck"), "--apply"]) == 0
    capsys.readouterr()
    assert main(["match", "score", "cm-lanecheck", "--json"]) == 0
    score = json.loads(capsys.readouterr().out)
    assert score["winner"] == "blue"
    assert main(["match", "replay", "cm-lanecheck"]) == 0
    assert capsys.readouterr().out.startswith("<!DOCTYPE html>")


# --------------------------------------------------------------------------- #
# suspend/resume: kill between ANY two CLI calls, resume from the same dir
# --------------------------------------------------------------------------- #


def test_full_loop_survives_interleaved_act_and_tick_across_many_calls(arena, capsys) -> None:
    """Drive a whole match to completion through nothing but separate 'main()'
    calls -- mixing 'act' (external, per-unit) and 'tick' (bot auto-resolve),
    each call re-reading '.league/' from disk exactly as a fresh process
    would. Proves 'killing between any two CLI calls and re-running from the
    same directory continues correctly' (mission hard constraint)."""
    _register_teams(capsys)
    assert (
        main(
            [
                "cmatch",
                "new",
                "--scenario",
                "c-skirmish-1",
                "--team",
                "blue",
                "--team",
                "red",
                "--driver",
                "blue:bot",
                "--driver",
                "red:bot",
                "--id",
                "cm-mixed-loop",
                "--apply",
            ]
        )
        == 0
    )
    capsys.readouterr()

    # Externally answer the very first due unit by hand...
    assert (
        main(
            [
                "cmatch",
                "act",
                "cm-mixed-loop",
                "--unit",
                "blue-u1",
                "--action-json",
                '{"kind": "move", "target_pos": {"x": 5000, "y": 4000}}',
                "--apply",
            ]
        )
        == 0
    )
    capsys.readouterr()

    # ...then let 'tick' (bot-driven) finish the rest, across as many
    # independent calls as it takes.
    finished = False
    data = None
    for _ in range(20):
        assert main(["cmatch", "tick", "cm-mixed-loop", "--apply", "--json"]) == 0
        data = json.loads(capsys.readouterr().out)
        if data["finished"]:
            finished = True
            break
    assert finished
    assert data["status"] == "finished"

    # A totally fresh 'show' call (its own main() invocation) sees the same
    # finished match, nothing due.
    assert main(["cmatch", "show", "cm-mixed-loop", "--json"]) == 0
    show = json.loads(capsys.readouterr().out)
    assert show["status"] == "finished"
    assert show["due"] == []


# --------------------------------------------------------------------------- #
# THE parity proof: stepwise CLI driving == an equivalent run_cmatch call
# --------------------------------------------------------------------------- #


def test_cli_stepwise_driving_matches_run_cmatch_byte_for_byte(arena, capsys) -> None:
    """The mission's hard constraint, proven at the CLI boundary: a fully
    bot-driven match built via 'cmatch new --apply' and driven to completion
    through nothing but repeated, independent 'cmatch tick --apply' calls
    (each one a separate main() invocation reading the match back off disk)
    produces a log whose TRANSITION + decision_point events -- i.e. everything
    but the harness's own wall-clock 'seat_latency' instrumentation, which a
    direct/tick-driven decision never has an analog for -- are byte-identical,
    in order, to a single in-process 'league.charness.run_cmatch' call given
    the identical scenario/seed/roster/bot drivers.
    """
    store = Store()
    team_slots = {
        "blue": ("blue", "blue", (("blue-1", "defender"), ("blue-2", "harvester"))),
        "red": ("red", "red", (("red-1", "defender"), ("red-2", "harvester"))),
    }
    for team_id, (_, _name, roster) in team_slots.items():
        # No --name: both paths must fall back to the same default (the team
        # id itself) so the reference config (which also omits "name") and
        # the registered roster produce identical CTeamState.name values.
        args = ["team", "register", team_id]
        for agent_id, role in roster:
            args += ["--agent", f"{agent_id}:m:{role}"]
        args.append("--apply")
        assert main(args) == 0
        capsys.readouterr()

    reference_config = {
        "match": {
            "scenario": "c-skirmish-1",
            "mode": "competitive",
            "seed": 0,
            "id": "cm-reference",
        },
        "teams": [
            {
                "id": team_id,
                "driver": {"type": "bot"},
                "agents": [
                    {"id": agent_id, "model": "m", "role": role} for agent_id, role in roster
                ],
            }
            for team_id, (_, _, roster) in team_slots.items()
        ],
    }
    reference = run_cmatch(reference_config)
    reference_events = [e for e in reference["log"].events if e.kind != "seat_latency"]

    assert (
        main(
            [
                "cmatch",
                "new",
                "--scenario",
                "c-skirmish-1",
                "--team",
                "blue",
                "--team",
                "red",
                "--driver",
                "blue:bot",
                "--driver",
                "red:bot",
                "--seed",
                "0",
                "--id",
                "cm-stepwise",
                "--apply",
            ]
        )
        == 0
    )
    capsys.readouterr()

    finished = False
    for _ in range(20):
        assert main(["cmatch", "tick", "cm-stepwise", "--apply", "--json"]) == 0
        data = json.loads(capsys.readouterr().out)
        if data["finished"]:
            finished = True
            break
    assert finished

    path = store.log_path("cm-stepwise")
    stepwise_clog = CMatchLog.from_jsonl(path.read_text(encoding="utf-8"))

    stepwise_dicts = [e.to_dict() for e in stepwise_clog.events]
    reference_dicts = [e.to_dict() for e in reference_events]
    assert stepwise_dicts == reference_dicts
    # match_id legitimately differs (two distinct match ids by test
    # construction) -- normalize it before comparing everything else.
    stepwise_final = stepwise_clog.final_state()
    reference_final = reference["log"].final_state()
    assert dataclasses.replace(stepwise_final, match_id=reference_final.match_id) == reference_final
