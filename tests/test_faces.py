"""Face-agreement tests — the markdown face and the JSON face are one fold (cycle-3 t10).

The faces layer (``league/faces/``) declares the match-brief projection ONCE in
an agentfront registry; ``league match brief`` serves that declaration as
markdown (the agents' face) or as facts JSON (``--json``). These tests prove:

* fact-for-fact agreement: the markdown face is *parsed back into facts* (no
  string-fuzzing) and must equal the JSON payload exactly — every unit
  id/pos, team resource count, mission status, and score;
* the same holds for the fogged per-team variant, which renders the
  per-team knowledge fold (seen/told), never ground truth;
* the CLI verb resolves through the agentfront registry (one declaration);
* agentfront's own cross-surface agreement gate passes for the faces app;
* engine isolation: ``league/faces/`` is the ONLY league code importing
  agentfront — the engine stays dependency-free and deterministic.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any, Callable

import pytest

from league.cli import main

LEAGUE_DIR = Path(__file__).resolve().parent.parent / "league"


# --- markdown-face parser (typed, no string-fuzzing) -----------------------


def _pos(cell: str) -> list[int]:
    x, _, y = cell.partition(",")
    return [int(x), int(y)]


def _opt(convert: Callable[[str], Any]) -> Callable[[str], Any]:
    return lambda cell: None if cell == "none" else convert(cell)


def _yn(cell: str) -> bool:
    return {"yes": True, "no": False}[cell]


def _idlist(cell: str) -> list[str]:
    return [] if cell == "none" else cell.split(", ")


# bullet key -> (facts key, converter); "turn" is handled apart (turn/turn_limit).
_BULLETS: dict[str, tuple[str, Callable[[str], Any]]] = {
    "scenario": ("scenario", str),
    "mode": ("mode", str),
    "seed": ("seed", int),
    "status": ("status", str),
    "winner": ("winner", _opt(str)),
    "team": ("team", str),
    "resources": ("resources", int),
    "cells-seen": ("cells_seen", int),
}

# section title -> (facts key, {column -> (facts field, converter)})
_SECTIONS: dict[str, tuple[str, dict[str, tuple[str, Callable[[str], Any]]]]] = {
    "Teams": (
        "teams",
        {
            "team": ("team", str),
            "resources": ("resources", int),
            "outcome": ("outcome", int),
            "cooperation": ("cooperation", int),
        },
    ),
    "Units": (
        "units",
        {
            "unit": ("unit", str),
            "team": ("team", str),
            "role": ("role", str),
            "pos": ("pos", _pos),
            "carrying": ("carrying", int),
            "alive": ("alive", _yn),
        },
    ),
    "Control points": (
        "control_points",
        {"id": ("id", str), "pos": ("pos", _pos), "owner": ("owner", _opt(str))},
    ),
    "Missions": (
        "missions",
        {
            "id": ("id", str),
            "kind": ("kind", str),
            "pos": ("pos", _pos),
            "amount": ("amount", int),
            "reward": ("reward", int),
            "status": ("status", str),
            "completed-by": ("completed_by", _idlist),
        },
    ),
    "Resource nodes": (
        "resource_nodes",
        {"id": ("id", str), "pos": ("pos", _pos), "remaining": ("remaining", int)},
    ),
    "Known units": (
        "known_units",
        {
            "unit": ("unit", str),
            "team": ("team", str),
            "role": ("role", str),
            "pos": ("pos", _opt(_pos)),
            "alive": ("alive", _opt(_yn)),
            "turn": ("turn", int),
            "source": ("source", str),
        },
    ),
    "Known resource nodes": (
        "known_resource_nodes",
        {
            "id": ("id", str),
            "pos": ("pos", _pos),
            "remaining": ("remaining", _opt(int)),
            "turn": ("turn", int),
            "source": ("source", str),
        },
    ),
    "Known control points": (
        "known_control_points",
        {
            "id": ("id", str),
            "pos": ("pos", _pos),
            "owner": ("owner", _opt(str)),
            "turn": ("turn", int),
            "source": ("source", str),
        },
    ),
}

_TITLE = re.compile(r"^# league match brief — (?P<match_id>\S+)(?: \(team (?P<team>\S+)\))?$")


def parse_brief_markdown(text: str) -> dict[str, Any]:
    """Parse the markdown face back into a facts dict — the agreement oracle.

    Every bullet and every table row is converted with the typed schema above;
    anything unparseable is a hard failure, so the test can assert *exact*
    equality with the JSON face instead of substring matching.
    """
    lines = text.splitlines()
    title = _TITLE.match(lines[0])
    assert title, f"markdown face has no parseable title: {lines[0]!r}"
    facts: dict[str, Any] = {"match_id": title.group("match_id")}

    section: str | None = None
    columns: list[str] = []
    for line in lines[1:]:
        if not line.strip():
            continue
        if line.startswith("## "):
            section = line[3:].strip()
            assert section in _SECTIONS, f"unknown markdown section {section!r}"
            key = _SECTIONS[section][0]
            facts[key] = []
            columns = []
            continue
        if section is None:
            match = re.match(r"^- ([a-z-]+): (.*)$", line)
            assert match, f"unparseable bullet line: {line!r}"
            bullet, value = match.group(1), match.group(2)
            if bullet == "turn":
                turn, _, limit = value.partition("/")
                facts["turn"], facts["turn_limit"] = int(turn), int(limit)
                continue
            assert bullet in _BULLETS, f"unknown bullet {bullet!r}"
            key, convert = _BULLETS[bullet]
            facts[key] = convert(value)
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not columns:
            columns = cells
            continue
        if set("".join(cells)) <= {"-"}:
            continue  # the |---|---| separator row
        key, schema = _SECTIONS[section]
        assert len(cells) == len(columns), f"ragged row in {section!r}: {line!r}"
        row: dict[str, Any] = {}
        for column, cell in zip(columns, cells):
            assert column in schema, f"unknown column {column!r} in section {section!r}"
            field, convert = schema[column]
            row[field] = convert(cell)
        facts[key].append(row)

    if title.group("team") is not None:
        assert facts.get("team") == title.group("team"), "title team != bullet team"
    return facts


# --- a scripted match both faces render ------------------------------------


@pytest.fixture()
def arena(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _register(team: str) -> list[str]:
    return [
        "team",
        "register",
        team,
        "--name",
        f"Team {team}",
        "--agent",
        f"{team}-1:test-model:scout",
        "--agent",
        f"{team}-2:test-model:harvester",
        "--agent",
        f"{team}-3:test-model:defender",
        "--apply",
    ]


def _play_match(capsys: pytest.CaptureFixture[str]) -> str:
    """Two resolved turns of skirmish-1 with a message that *tells* blue facts."""
    match_id = "m-faces"
    assert main(_register("blue")) == 0
    assert main(_register("red")) == 0
    assert (
        main(
            [
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
        )
        == 0
    )
    turns = [
        (
            ["--action", "blue-u1:move:2,1", "--action", "blue-u2:move:1,2"],
            ["--action", "red-u1:move:9,8"],
        ),
        (
            [
                "--message",
                "blue-1:scout ahead — rn-east is stocked and red-u1 moved off spawn",
                "--action",
                "blue-u1:move:5,1",
            ],
            ["--action", "red-u2:move:10,7"],
        ),
    ]
    for blue_extra, red_extra in turns:
        assert main(["match", "act", match_id, "--team", "blue", *blue_extra, "--apply"]) == 0
        assert main(["match", "act", match_id, "--team", "red", *red_extra, "--apply"]) == 0
    capsys.readouterr()
    return match_id


def _faces(
    capsys: pytest.CaptureFixture[str], match_id: str, team: str | None = None
) -> tuple[str, dict[str, Any]]:
    team_args = ["--team", team] if team else []
    assert main(["match", "brief", match_id, *team_args]) == 0
    markdown = capsys.readouterr().out
    assert main(["match", "brief", match_id, *team_args, "--json"]) == 0
    facts = json.loads(capsys.readouterr().out)
    return markdown, facts


# --- acceptance: markdown and JSON are one fold -----------------------------


def test_brief_markdown_and_json_are_one_fold(arena, capsys) -> None:
    """Fact-for-fact: parse the markdown face; it must EQUAL the JSON face."""
    match_id = _play_match(capsys)
    markdown, facts = _faces(capsys, match_id)
    parsed = parse_brief_markdown(markdown)
    assert parsed == facts
    # And the facts are the real fold, not a stub: spot-check ground truth.
    units = {u["unit"]: u for u in facts["units"]}
    assert units["blue-u1"]["pos"] == [5, 1]
    assert units["red-u2"]["pos"] == [10, 7]
    assert facts["turn"] == 2 and facts["status"] == "active"
    assert {t["team"] for t in facts["teams"]} == {"blue", "red"}
    assert {m["id"] for m in facts["missions"]} == {"ms-supply", "ms-outpost"}


def test_fogged_brief_markdown_and_json_are_one_fold(arena, capsys) -> None:
    match_id = _play_match(capsys)
    markdown, facts = _faces(capsys, match_id, team="blue")
    assert parse_brief_markdown(markdown) == facts


def test_fogged_brief_is_knowledge_not_ground_truth(arena, capsys) -> None:
    """Blue's brief carries seen/told facts only — never the full board."""
    match_id = _play_match(capsys)
    _, fogged = _faces(capsys, match_id, team="blue")
    _, full = _faces(capsys, match_id)

    known = {u["unit"]: u for u in fogged["known_units"]}
    # Own units are always known, with live positions (source: seen).
    for unit_id in ("blue-u1", "blue-u2", "blue-u3"):
        assert known[unit_id]["source"] == "seen"
        assert known[unit_id]["pos"] is not None
    # red-u1 was never in vision; it entered knowledge ONLY via the logged
    # message, so it is told-only: identity yes, position no.
    assert known["red-u1"]["source"] == "told"
    assert known["red-u1"]["pos"] is None and known["red-u1"]["alive"] is None
    # red-u2 was neither seen nor mentioned — absent from the fogged face,
    # present in the full face.
    assert "red-u2" not in known
    assert any(u["unit"] == "red-u2" for u in full["units"])
    # rn-east: out of vision, but the message named it — told, remaining unknown.
    nodes = {n["id"]: n for n in fogged["known_resource_nodes"]}
    assert nodes["rn-east"]["source"] == "told" and nodes["rn-east"]["remaining"] is None
    # No leaked scores or opponent resources on the fogged face.
    assert "teams" not in fogged
    assert fogged["resources"] == next(t for t in full["teams"] if t["team"] == "blue")["resources"]


def test_full_brief_agrees_with_replay_fold(arena, capsys) -> None:
    """The brief is the same fold the HTML replay consumes — one log, one truth."""
    match_id = _play_match(capsys)
    _, facts = _faces(capsys, match_id)
    assert main(["match", "replay", match_id, "--json"]) == 0
    replay = json.loads(capsys.readouterr().out)
    last = replay["frames"][-1]
    assert {u["unit"]: u["pos"] for u in facts["units"]} == {
        u["id"]: u["pos"] for u in last["units"]
    }
    assert {t["team"]: t["resources"] for t in facts["teams"]} == {
        t["id"]: t["resources"] for t in last["teams"]
    }
    for team in facts["teams"]:
        assert team["outcome"] == replay["scores"]["outcome"][team["team"]]["total"]
        assert team["cooperation"] == replay["scores"]["cooperation"][team["team"]]["score"]


# --- the agentfront registry is the single declaration ----------------------


def test_cli_brief_serves_the_agentfront_registry_declaration(arena, capsys) -> None:
    """One declaration, two faces: the verb's output IS the registry tool's output."""
    from league.faces import faces_app, render_brief_markdown

    match_id = _play_match(capsys)
    entry = faces_app().get_by_path(("match", "brief"))
    assert entry is not None, "faces registry must declare the ('match','brief') tool"
    registry_facts = entry.func(match_id, "")
    markdown, cli_facts = _faces(capsys, match_id)
    assert cli_facts == registry_facts
    assert markdown == render_brief_markdown(registry_facts) + "\n"
    # The fogged projection is the same single declaration, parameterized.
    _, fogged_cli = _faces(capsys, match_id, team="blue")
    assert fogged_cli == entry.func(match_id, "blue")


def test_faces_surfaces_agree() -> None:
    """agentfront's own cross-surface gate: registry/CLI/MCP/HTTP cannot drift."""
    from agentfront.testing import assert_surfaces_agree

    from league.faces import faces_app

    assert_surfaces_agree(faces_app())


# --- engine isolation --------------------------------------------------------


def test_agentfront_is_imported_only_by_the_faces_layer() -> None:
    """The runtime dep never reaches the engine: league/faces/ is the only importer."""
    offenders: list[str] = []
    for module in sorted(LEAGUE_DIR.rglob("*.py")):
        tree = ast.parse(module.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [(node.module or "").split(".")[0]]
            else:
                continue
            if "agentfront" in names and module.parent.name != "faces":
                offenders.append(str(module.relative_to(LEAGUE_DIR)))
    assert not offenders, f"agentfront imported outside league/faces/: {offenders}"
    faces = LEAGUE_DIR / "faces"
    assert any(
        "agentfront" in p.read_text(encoding="utf-8") for p in faces.glob("*.py")
    ), "league/faces/ must actually build on agentfront (decision c17)"


# --- error contract + introspection surface ---------------------------------


def test_brief_unknown_match_is_user_error(arena, capsys) -> None:
    assert main(["match", "brief", "m-nope"]) == 1
    err = capsys.readouterr().err
    assert err.startswith("error:")
    assert "hint:" in err


def test_brief_unknown_team_is_user_error(arena, capsys) -> None:
    match_id = _play_match(capsys)
    assert main(["match", "brief", match_id, "--team", "chartreuse"]) == 1
    err = capsys.readouterr().err
    assert err.startswith("error:")
    assert "hint:" in err


def test_match_overview_lists_brief(arena, capsys) -> None:
    assert main(["match", "overview", "--json"]) == 0
    verbs = json.loads(capsys.readouterr().out)["verbs"]
    assert "brief" in verbs
