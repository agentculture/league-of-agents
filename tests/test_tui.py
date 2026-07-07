"""Acceptance tests for the TUI face (plan task t7, spec c2/c13/c15/h13).

Criteria under test:

* the renderer is a **pure function** ``(build_replay_data, frame_index) ->
  list[str]`` — no terminal, no I/O — and its facts agree with the JSON fold
  on every frame (the h1 "faces are one fold" pattern, in the style of
  ``tests/test_replay_html.py``'s projection-agreement tests);
* a ground-truth vs per-team-knowledge toggle: with ``team=``, the board and
  legend are built from the knowledge fold instead of the snapshot — unseen
  facts are absent, told facts are marked, stale facts carry their age, and
  cells the team has never seen render blank;
* ``league match tui <id> --frame N [--team X] [--no-color]`` is the
  non-interactive CLI path these tests (and any pipe) drive; ``curses`` is
  never imported outside the interactive shell (importing this module, or
  running the whole suite, never touches a real terminal).
"""

from __future__ import annotations

import re

import pytest

from league.cli import main
from league.engine.knowledge import SOURCE_SEEN, SOURCE_TOLD, knowledge_by_turn
from league.harness import run_match
from league.replay import build_replay_data, render_frame
from league.replay.tui import _Cell, _grid_lines, _role_glyph
from tests.test_engine_knowledge import _scripted_log
from tests.test_engine_scoring import _play_match
from tests.test_wave4 import _bot_config

# --- agreement with the JSON fold (ground truth) ---------------------------

_UNIT_RE = re.compile(
    r"id=(?P<id>\S+) team=(?P<team>\S+) role=(?P<role>\S+) pos=(?P<x>-?\d+),(?P<y>-?\d+) "
    r"alive=(?P<alive>\S+) carrying=(?P<carrying>\d+)"
)


def _rendered_units(lines: list[str]) -> dict[str, dict]:
    out = {}
    for line in lines:
        m = _UNIT_RE.search(line)
        if m:
            out[m["id"]] = {
                "team": m["team"],
                "role": m["role"],
                "pos": (int(m["x"]), int(m["y"])),
                "alive": m["alive"] == "True",
                "carrying": int(m["carrying"]),
            }
    return out


def test_renderer_agrees_with_the_json_fold_on_every_frame() -> None:
    log = _play_match()
    data = build_replay_data(log)
    for frame_index, snapshot in enumerate(data["frames"]):
        lines = render_frame(data, frame_index, color=False)
        rendered = _rendered_units(lines)
        expected = {
            u["id"]: {
                "team": u["team"],
                "role": u["role"],
                "pos": tuple(u["pos"]),
                "alive": u["alive"],
                "carrying": u["carrying"],
            }
            for u in snapshot["units"]
        }
        assert rendered == expected, f"frame {frame_index} units disagree with the JSON fold"
        text = "\n".join(lines)
        for team_id, outcome in data["scores"]["outcome"].items():
            assert f"team={team_id} outcome_total={outcome['total']}" in text
            coop = data["scores"]["cooperation"][team_id]
            assert f"cooperation={coop['score']}" in text
        assert f"{data['match_id']} — turn {snapshot['turn']}/{data['turn_limit']}" in lines[0]


def test_control_points_missions_nodes_agree_with_the_fold() -> None:
    log = _play_match()
    data = build_replay_data(log)
    frame_index = len(data["frames"]) - 1
    snapshot = data["frames"][frame_index]
    text = "\n".join(render_frame(data, frame_index, color=False))

    for cp in snapshot["control_points"]:
        hold = cp["hold"][0][1] if cp["hold"] else 0
        assert (
            f"id={cp['id']} pos={cp['pos'][0]},{cp['pos'][1]} owner={cp['owner']} hold={hold}"
            in text
        )
    for mission in snapshot["missions"]:
        completed_by = ",".join(mission["completed_by"])
        assert (
            f"id={mission['id']} kind={mission['kind']} pos={mission['pos'][0]},"
            f"{mission['pos'][1]} amount={mission['amount']} reward={mission['reward']} "
            f"status={mission['status']} completed_by={completed_by}"
        ) in text
    for node in snapshot["resource_nodes"]:
        assert (
            f"id={node['id']} pos={node['pos'][0]},{node['pos'][1]} "
            f"remaining={node['remaining']}" in text
        )


def test_grid_places_units_at_their_board_position() -> None:
    log = _play_match()
    data = build_replay_data(log)
    team_letters = {t["id"]: chr(ord("A") + i) for i, t in enumerate(data["teams"])}
    frame_index = len(data["frames"]) - 1
    snapshot = data["frames"][frame_index]
    lines = render_frame(data, frame_index, color=False)
    board_start = lines.index("Board:") + 2  # skip "Board:" and the column-index header row

    by_cell: dict[tuple[int, int], list] = {}
    for unit in snapshot["units"]:
        if unit["alive"]:
            by_cell.setdefault(tuple(unit["pos"]), []).append(unit)
    for (x, y), units in by_cell.items():
        row = lines[board_start + y]
        cell = row[4 + x * 3 : 4 + x * 3 + 3]
        # Deterministic pick when stacked: canonical (team, id) order — the
        # same processing order the tick resolves actions in.
        winner = sorted(units, key=lambda u: (u["team"], u["id"]))[-1]
        assert cell[0] == _role_glyph(winner["role"])
        assert cell[1] == team_letters[winner["team"]]


def test_out_of_range_frame_raises() -> None:
    log = _play_match()
    data = build_replay_data(log)
    with pytest.raises(ValueError):
        render_frame(data, len(data["frames"]))


def test_unknown_team_raises() -> None:
    log = _play_match()
    data = build_replay_data(log)
    with pytest.raises(ValueError):
        render_frame(data, 0, team="green")


def test_fog_without_knowledge_raises() -> None:
    log = _play_match()
    data = build_replay_data(log)
    with pytest.raises(ValueError):
        render_frame(data, 0, team="blue")


def test_color_enabled_adds_ansi_and_strips_back_to_the_plain_render() -> None:
    log = _play_match()
    data = build_replay_data(log)
    frame_index = len(data["frames"]) - 1
    colored = "\n".join(render_frame(data, frame_index, color=True))
    plain = "\n".join(render_frame(data, frame_index, color=False))
    assert "\x1b[" in colored
    assert "\x1b[" not in plain
    stripped = re.sub(r"\x1b\[[0-9;]*m", "", colored)
    assert stripped == plain


# --- ground truth vs per-team knowledge toggle ------------------------------


def test_fog_view_only_shows_known_facts() -> None:
    log, scenario = _scripted_log()
    data = build_replay_data(log)
    knowledge = knowledge_by_turn(log, scenario)
    frame_index = len(data["frames"]) - 1

    ground_lines = render_frame(data, frame_index, color=False)
    fog_lines = render_frame(data, frame_index, team="blue", knowledge=knowledge, color=False)
    assert "view: ground truth" in ground_lines[2]
    assert "view: blue knowledge (fog of war)" in fog_lines[2]

    blue_frame = knowledge["blue"][frame_index]
    known_unit_ids = {u.id for u in blue_frame.units}
    ground_unit_ids = {u["id"] for u in data["frames"][frame_index]["units"]}
    assert known_unit_ids <= ground_unit_ids
    unseen = ground_unit_ids - known_unit_ids
    assert unseen, "the fixture must actually exercise partial knowledge"
    fog_text = "\n".join(fog_lines)
    for unit_id in unseen:
        assert f"id={unit_id} " not in fog_text


def test_told_facts_marked_and_stale_facts_carry_their_age() -> None:
    log, scenario = _scripted_log()
    knowledge = knowledge_by_turn(log, scenario)
    data = build_replay_data(log)
    frame_index = len(data["frames"]) - 1
    frame = knowledge["blue"][frame_index]
    current_turn = data["frames"][frame_index]["turn"]
    lines = render_frame(data, frame_index, team="blue", knowledge=knowledge, color=False)
    text = "\n".join(lines)

    told = next(
        f
        for f in (*frame.units, *frame.resource_nodes, *frame.control_points)
        if f.source == SOURCE_TOLD
    )
    assert f"id={told.id} " in text
    told_line = next(line for line in lines if f"id={told.id} " in line)
    assert "source=told" in told_line

    stale = next(
        (
            f
            for f in (*frame.units, *frame.resource_nodes, *frame.control_points)
            if f.source == SOURCE_SEEN and f.turn < current_turn
        ),
        None,
    )
    if stale is not None:
        stale_line = next(line for line in lines if f"id={stale.id} " in line)
        assert f"age={current_turn - stale.turn}" in stale_line


def test_missions_are_ground_truth_only_and_the_fog_view_says_so() -> None:
    log, scenario = _scripted_log()
    knowledge = knowledge_by_turn(log, scenario)
    data = build_replay_data(log)
    frame_index = len(data["frames"]) - 1

    fog_text = "\n".join(
        render_frame(data, frame_index, team="blue", knowledge=knowledge, color=False)
    )
    assert "Missions: not tracked by the per-team knowledge fold" in fog_text

    ground_text = "\n".join(render_frame(data, frame_index, color=False))
    assert any(f"id={m['id']}" in ground_text for m in data["frames"][frame_index]["missions"])


def test_grid_lines_blank_for_unseen_ground_dot_for_explored_empty() -> None:
    """White-box check of the shared grid renderer: an entity's cell shows
    its glyph; an explored-but-empty cell shows walkable ground ('.'); a
    cell the team has never seen renders blank, distinct from both."""
    cells = {(0, 0): _Cell("$", "5")}
    seen = frozenset({(0, 0), (1, 0)})
    lines = _grid_lines(3, 1, cells, seen, color=False)
    row = lines[1]
    assert row[4:7] == "$5 "
    assert row[7:10] == ".  "
    assert row[10:13] == "   "

    # Ground truth (cells_seen=None) never dims — every cell is walkable
    # ground or an entity, there is no "unexplored".
    ground_lines = _grid_lines(3, 1, {}, None, color=False)
    assert ground_lines[1] == f"{0:>3} " + ".  " * 3


# --- CLI: the non-interactive path tests (and pipes) drive ------------------


@pytest.fixture()
def arena(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_cli_tui_non_interactive_frame_prints_ground_truth(arena, capsys) -> None:
    run_match(_bot_config("m-tui-1"))
    capsys.readouterr()
    assert main(["match", "tui", "m-tui-1", "--frame", "0"]) == 0
    out = capsys.readouterr().out
    assert "m-tui-1" in out
    assert "Board:" in out
    assert "view: ground truth" in out


def test_cli_tui_default_frame_is_the_last_one(arena, capsys) -> None:
    run_match(_bot_config("m-tui-1b"))
    capsys.readouterr()
    assert main(["match", "tui", "m-tui-1b", "--frame", "-1"]) == 0
    negative = capsys.readouterr().out
    assert main(["match", "tui", "m-tui-1b"]) == 0  # non-tty stdout under pytest: non-interactive
    default = capsys.readouterr().out
    assert negative == default


def test_cli_tui_team_flag_renders_fog(arena, capsys) -> None:
    run_match(_bot_config("m-tui-2"))
    capsys.readouterr()
    assert main(["match", "tui", "m-tui-2", "--frame", "1", "--team", "blue"]) == 0
    out = capsys.readouterr().out
    assert "blue knowledge (fog of war)" in out


def test_cli_tui_unknown_team_is_a_user_error(arena, capsys) -> None:
    run_match(_bot_config("m-tui-3"))
    capsys.readouterr()
    rc = main(["match", "tui", "m-tui-3", "--frame", "0", "--team", "green"])
    assert rc == 1
    err = capsys.readouterr().err
    assert err.startswith("error:")
    assert "hint:" in err


def test_cli_tui_frame_out_of_range_is_a_user_error(arena, capsys) -> None:
    run_match(_bot_config("m-tui-4"))
    capsys.readouterr()
    rc = main(["match", "tui", "m-tui-4", "--frame", "9999"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "hint:" in err


def test_cli_tui_no_color_flag_and_no_color_env(arena, capsys, monkeypatch) -> None:
    run_match(_bot_config("m-tui-5"))
    capsys.readouterr()
    assert main(["match", "tui", "m-tui-5", "--frame", "0", "--no-color"]) == 0
    assert "\x1b[" not in capsys.readouterr().out

    monkeypatch.setenv("NO_COLOR", "1")
    assert main(["match", "tui", "m-tui-5", "--frame", "0"]) == 0
    assert "\x1b[" not in capsys.readouterr().out


def test_cli_tui_color_enabled_by_default(arena, capsys) -> None:
    run_match(_bot_config("m-tui-6"))
    capsys.readouterr()
    assert main(["match", "tui", "m-tui-6", "--frame", "0"]) == 0
    assert "\x1b[" in capsys.readouterr().out


def test_cli_tui_unknown_match_id_is_a_user_error(arena, capsys) -> None:
    rc = main(["match", "tui", "no-such-match", "--frame", "0"])
    assert rc == 1
    err = capsys.readouterr().err
    assert err.startswith("error:")
    assert "hint:" in err


def test_explain_match_tui_resolves(capsys) -> None:
    assert main(["explain", "match", "tui"]) == 0
    assert "league match" in capsys.readouterr().out


def test_tui_module_never_imports_curses_at_module_scope() -> None:
    """``curses`` is only ever touched inside run_interactive_shell — importing
    the module (as every test above does) must never require a real tty."""
    import ast
    from pathlib import Path

    source = Path(__file__).resolve().parent.parent / "league" / "replay" / "tui.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    for node in tree.body:  # module-level statements only, not inside functions
        if isinstance(node, ast.Import):
            assert all(alias.name != "curses" for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.module != "curses"
