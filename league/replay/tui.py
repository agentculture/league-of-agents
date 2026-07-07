"""Terminal replay viewer — the human's third face beside HTML and JSON.

Design (plan task t7, spec c2/c13/c15/h13): one fold, three faces. Just like
:mod:`league.replay.html`, :func:`render_frame` derives every fact it prints
from :func:`league.replay.build_replay_data` (ground truth) or, when a
``team`` is given, from :mod:`league.engine.knowledge`'s per-team fold — never
from live state, never invented. It is a **pure function**
``(data, frame_index, team, knowledge, color) -> list[str]``: no I/O, no
terminal handling, fully unit-testable without a tty. :func:`run_interactive_shell`
is the thin curses wrapper around it — arrow keys move ``frame_index``, Tab
cycles ``team``, and it renders the exact same lines this module would hand
back to a pipe. ``curses`` is only imported inside that function, so importing
this module (or running the non-interactive ``--frame`` CLI path the tests
drive) never touches a real terminal.

**Ground truth vs per-team knowledge.** With no ``team``, the board shows
every unit/control point/mission/resource node from the replay snapshot —
the same facts the HTML replay's frame shows. With ``team=<id>``, the board is
built from that team's :class:`~league.engine.knowledge.KnowledgeFrame` at the
same frame index (knowledge frames zip 1:1 with replay frames by
construction — see ``knowledge_by_turn``): a told-only unit has no known
position and is never placed on the grid (only listed, position ``?,?``); a
seen fact's grid marker encodes its age (blank = this turn, a digit = turns
stale, capped at 9, ``+`` beyond); cells the team has never seen render
blank/dimmed. Missions are **not** part of the knowledge fold (task t3 never
folded them), so the fog board omits them rather than inventing per-team
mission visibility — the legend says so explicitly.

**Color.** Board cells encode team identity redundantly: a team letter
character AND (when enabled) an ANSI color, so identity never depends on
color alone and the render degrades to plain ASCII glyphs cleanly. Color is
off when ``color=False`` is passed, when ``--no-color`` is given on the CLI,
or when the ``NO_COLOR`` environment variable is set (checked by the caller).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from league.engine.knowledge import SOURCE_TOLD, KnowledgeFrame

# Parity with league/replay/html.py's JS ``GLYPH`` map — the same role reads
# as the same letter on every face.
_ROLE_GLYPH = {"scout": "S", "harvester": "H", "defender": "D", "striker": "K", "support": "U"}

# Index-based, not id-based (mirrors html.py's ``teamIndex``): unique
# regardless of how similar two team ids look.
_TEAM_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

_RESET = "\x1b[0m"
_DIM = "\x1b[2m"
_TEAM_ANSI = ("\x1b[34m", "\x1b[31m", "\x1b[32m", "\x1b[33m", "\x1b[35m", "\x1b[36m")


def _team_letter(index: int) -> str:
    return _TEAM_LETTERS[index % len(_TEAM_LETTERS)]


def _team_index_map(data: Mapping[str, Any]) -> dict[str, int]:
    return {team["id"]: i for i, team in enumerate(data["teams"])}


def _role_glyph(role: str) -> str:
    return _ROLE_GLYPH.get(role, role[:1].upper() or "?")


def _age_marker(age: int) -> str:
    if age <= 0:
        return " "
    if age >= 10:
        return "+"
    return str(age)


@dataclass(frozen=True)
class _Cell:
    """One grid cell's render: a role/entity glyph, a value tag, a fog marker."""

    glyph: str
    tag: str
    marker: str = " "
    team_index: int | None = None
    dim: bool = False


_GROUND = _Cell(".", " ")
_UNSEEN = _Cell(" ", " ", dim=True)


def _paint(cell: _Cell, *, color: bool) -> str:
    body = f"{cell.glyph}{cell.tag}{cell.marker}"
    if not color:
        return body
    if cell.dim:
        return f"{_DIM}{body}{_RESET}"
    if cell.team_index is not None:
        return f"{_TEAM_ANSI[cell.team_index % len(_TEAM_ANSI)]}{body}{_RESET}"
    return body


def _grid_lines(
    width: int,
    height: int,
    cells: Mapping[tuple[int, int], _Cell],
    cells_seen: frozenset[tuple[int, int]] | None,
    *,
    color: bool,
) -> list[str]:
    """Render the board. ``cells_seen`` is ``None`` for ground truth (nothing
    is ever unexplored); for a fog board it's the team's ``cells_seen`` —
    a position outside it and absent from ``cells`` renders blank/dimmed."""
    lines = ["    " + "".join(f"{x % 10:<3}" for x in range(width))]
    for y in range(height):
        row = [f"{y:>3} "]
        for x in range(width):
            pos = (x, y)
            if pos in cells:
                cell = cells[pos]
            elif cells_seen is not None and pos not in cells_seen:
                cell = _UNSEEN
            else:
                cell = _GROUND
            row.append(_paint(cell, color=color))
        lines.append("".join(row))
    return lines


# --- ground truth: cells + legend, straight from build_replay_data ---------


def _ground_cells(snapshot: Mapping[str, Any], team_index: Mapping[str, int]) -> dict:
    """Priority low → high (later overwrites): nodes, missions, control
    points, units — units render on top, mirroring the HTML replay's SVG
    draw order (units are drawn last there too)."""
    cells: dict[tuple[int, int], _Cell] = {}
    for node in snapshot["resource_nodes"]:
        cells[tuple(node["pos"])] = _Cell("$", str(node["remaining"] % 10))
    for mission in snapshot["missions"]:
        if mission["status"] == "completed" and mission["completed_by"]:
            tag = (
                "+"
                if len(mission["completed_by"]) > 1
                else _team_letter(team_index[mission["completed_by"][0]])
            )
        else:
            tag = "."
        cells[tuple(mission["pos"])] = _Cell("M", tag)
    for cp in snapshot["control_points"]:
        owner = cp["owner"]
        idx = team_index[owner] if owner is not None else None
        tag = _team_letter(idx) if idx is not None else "-"
        cells[tuple(cp["pos"])] = _Cell("O", tag, team_index=idx)
    for unit in snapshot["units"]:
        if not unit["alive"]:
            continue
        idx = team_index[unit["team"]]
        cells[tuple(unit["pos"])] = _Cell(
            _role_glyph(unit["role"]), _team_letter(idx), team_index=idx
        )
    return cells


def _ground_legend(snapshot: Mapping[str, Any], team_index: Mapping[str, int]) -> list[str]:
    lines = ["Units:"]
    for unit in sorted(snapshot["units"], key=lambda u: (u["team"], u["id"])):
        idx = team_index[unit["team"]]
        tag = f"{_role_glyph(unit['role'])}{_team_letter(idx)}"
        x, y = unit["pos"]
        lines.append(
            f"  {tag} id={unit['id']} team={unit['team']} role={unit['role']} "
            f"pos={x},{y} alive={unit['alive']} carrying={unit['carrying']}"
        )
    lines.append("Control points:")
    for cp in snapshot["control_points"]:
        x, y = cp["pos"]
        hold = cp["hold"][0][1] if cp["hold"] else 0
        lines.append(f"  id={cp['id']} pos={x},{y} owner={cp['owner']} hold={hold}")
    lines.append("Missions:")
    for mission in snapshot["missions"]:
        x, y = mission["pos"]
        completed_by = ",".join(mission["completed_by"])
        lines.append(
            f"  id={mission['id']} kind={mission['kind']} pos={x},{y} amount={mission['amount']} "
            f"reward={mission['reward']} status={mission['status']} completed_by={completed_by}"
        )
    lines.append("Resource nodes:")
    for node in snapshot["resource_nodes"]:
        x, y = node["pos"]
        lines.append(f"  id={node['id']} pos={x},{y} remaining={node['remaining']}")
    return lines


# --- per-team knowledge: cells + legend, straight from the knowledge fold --


def _fog_cells(frame: KnowledgeFrame, team_index: Mapping[str, int], current_turn: int) -> dict:
    cells: dict[tuple[int, int], _Cell] = {}
    for node in frame.resource_nodes:
        marker = "?" if node.source == SOURCE_TOLD else _age_marker(current_turn - node.turn)
        tag = "?" if node.remaining is None else str(node.remaining % 10)
        cells[node.pos] = _Cell("$", tag, marker)
    for cp in frame.control_points:
        marker = "?" if cp.source == SOURCE_TOLD else _age_marker(current_turn - cp.turn)
        if cp.source == SOURCE_TOLD:
            tag, idx = "?", None
        elif cp.owner is None:
            tag, idx = "-", None
        else:
            idx = team_index[cp.owner]
            tag = _team_letter(idx)
        cells[cp.pos] = _Cell("O", tag, marker, team_index=idx)
    for unit in frame.units:
        if unit.pos is None:
            continue  # told-only: no known position, legend-only (never placed)
        idx = team_index[unit.team_id]
        marker = _age_marker(current_turn - unit.turn)  # always SOURCE_SEEN when pos is known
        cells[unit.pos] = _Cell(_role_glyph(unit.role), _team_letter(idx), marker, team_index=idx)
    return cells


def _fog_legend(
    frame: KnowledgeFrame, team_index: Mapping[str, int], current_turn: int
) -> list[str]:
    lines = [f"Units known by {frame.team_id}:"]
    for unit in frame.units:
        idx = team_index[unit.team_id]
        tag = f"{_role_glyph(unit.role)}{_team_letter(idx)}"
        pos = "?,?" if unit.pos is None else f"{unit.pos[0]},{unit.pos[1]}"
        age = current_turn - unit.turn
        lines.append(
            f"  {tag} id={unit.id} team={unit.team_id} role={unit.role} pos={pos} "
            f"alive={unit.alive} source={unit.source} turn={unit.turn} age={age}"
        )
    lines.append("Control points known:")
    for cp in frame.control_points:
        age = current_turn - cp.turn
        lines.append(
            f"  id={cp.id} pos={cp.pos[0]},{cp.pos[1]} owner={cp.owner} "
            f"source={cp.source} turn={cp.turn} age={age}"
        )
    lines.append("Resource nodes known:")
    for node in frame.resource_nodes:
        age = current_turn - node.turn
        lines.append(
            f"  id={node.id} pos={node.pos[0]},{node.pos[1]} remaining={node.remaining} "
            f"source={node.source} turn={node.turn} age={age}"
        )
    lines.append("Missions: not tracked by the per-team knowledge fold (ground truth only)")
    return lines


# --- turn feed + scores, shared by both views ------------------------------

_FEED: dict[str, Callable[[dict], str | None]] = {
    "match_started": lambda d: "match started",
    "plan_declared": lambda d: f"{d.get('team_id')} plan: {d.get('text')}",
    "message_sent": lambda d: f"{d.get('from')}: {d.get('text')}",
    "action_declared": lambda d: (
        f"{d.get('unit_id')} declares {d.get('action')}"
        + (f" to {tuple(d['to'])}" if d.get("to") else "")
    ),
    "action_rejected": lambda d: f"{d.get('unit_id', '?')} rejected — {d.get('reason')}",
    "unit_moved": lambda d: f"{d.get('unit_id')} moves to {tuple(d.get('to', ()))}",
    "resource_gathered": (
        lambda d: f"{d.get('unit_id')} gathers {d.get('amount')} from {d.get('node_id')}"
    ),
    "resource_delivered": lambda d: f"{d.get('unit_id')} delivers {d.get('amount')}",
    "control_point_captured": lambda d: f"{d.get('team_id')} captures {d.get('cp_id')}",
    "control_point_held": lambda d: (
        f"{d.get('team_id')} holds {d.get('cp_id')} ({d.get('turns')})" if d.get("turns") else None
    ),
    "unit_defeated": lambda d: f"{d.get('unit_id')} is down",
    "mission_completed": lambda d: f"{d.get('team_id')} completes {d.get('mission_id')}",
    "match_finished": lambda d: (
        f"match over — {d['winner']} wins" if d.get("winner") else "match over"
    ),
    "turn_advanced": lambda d: None,
    "turn_resolved": lambda d: None,
}


def _feed_lines(data: Mapping[str, Any], turn: int, frame_index: int) -> list[str]:
    if frame_index == 0:
        return ["  (initial state)"]
    events = data["events_by_turn"].get(str(turn), [])
    lines = []
    for event in events:
        fmt = _FEED.get(event["kind"])
        text = fmt(event["data"]) if fmt else None
        if text is not None:
            lines.append(f"  {text}")
    return lines or ["  (nothing happened this turn)"]


def _score_lines(scores: Mapping[str, Any]) -> list[str]:
    lines = [f"  winner={scores.get('winner') or '-'}"]
    for team_id, outcome in scores["outcome"].items():
        coop = scores["cooperation"][team_id]
        lines.append(
            f"  team={team_id} outcome_total={outcome['total']} missions={outcome['missions']} "
            f"control={outcome['control']} resources={outcome['resources']} "
            f"cooperation={coop['score']}"
        )
    return lines


# --- the public pure renderer ----------------------------------------------


def render_frame(
    data: Mapping[str, Any],
    frame_index: int,
    *,
    team: str | None = None,
    knowledge: Mapping[str, Sequence[KnowledgeFrame]] | None = None,
    color: bool = True,
) -> list[str]:
    """Render one frame as plain text lines — the pure function the CLI's
    non-interactive path and the curses shell both call.

    ``data`` is :func:`league.replay.build_replay_data`'s output (ground
    truth); ``knowledge`` is :func:`league.engine.knowledge.knowledge_by_turn`'s
    output, required only when ``team`` is given (fog view). Raises
    ``ValueError`` for an out-of-range frame, an unknown team, or a fog
    request with no knowledge supplied — callers translate that into whatever
    error contract they use (the CLI wraps it as a ``CliError``).
    """
    frames = data["frames"]
    if not 0 <= frame_index < len(frames):
        raise ValueError(f"frame {frame_index} out of range 0..{len(frames) - 1}")
    snapshot = frames[frame_index]
    team_index = _team_index_map(data)

    lines = [
        f"{data['match_id']} — turn {snapshot['turn']}/{data['turn_limit']} "
        f"({data['mode']}, seed {data['seed']})",
    ]
    if snapshot["status"] == "finished":
        lines.append(f"status: finished, winner={snapshot['winner'] or 'draw/unresolved'}")
    else:
        lines.append(f"status: {snapshot['status']}")
    lines.append(f"view: {'ground truth' if team is None else f'{team} knowledge (fog of war)'}")
    lines.append("")
    lines.append("Board:")

    if team is None:
        cells = _ground_cells(snapshot, team_index)
        lines.extend(
            _grid_lines(data["grid"]["width"], data["grid"]["height"], cells, None, color=color)
        )
        lines.append("")
        lines.extend(_ground_legend(snapshot, team_index))
    else:
        if team not in team_index:
            raise ValueError(f"unknown team {team!r}; known teams: {sorted(team_index)}")
        if knowledge is None or team not in knowledge:
            raise ValueError(f"no knowledge frames supplied for team {team!r}")
        kframe = knowledge[team][frame_index]
        cells = _fog_cells(kframe, team_index, snapshot["turn"])
        lines.extend(
            _grid_lines(
                data["grid"]["width"], data["grid"]["height"], cells, kframe.cells_seen, color=color
            )
        )
        lines.append("")
        lines.extend(_fog_legend(kframe, team_index, snapshot["turn"]))

    lines.append("")
    lines.append("Turn feed:")
    lines.extend(_feed_lines(data, snapshot["turn"], frame_index))
    lines.append("")
    lines.append("Scores (final):")
    lines.extend(_score_lines(data["scores"]))
    return lines


def run_interactive_shell(
    data: Mapping[str, Any],
    knowledge: Mapping[str, Sequence[KnowledgeFrame]] | None,
    *,
    initial_team: str | None = None,
) -> None:
    """The curses shell: arrow keys step frames, Tab cycles ground-truth →
    each team → back. Zero logic beyond translating a keypress into the next
    ``(frame_index, team)`` passed to :func:`render_frame` — everything the
    board/legend/feed/scores show comes from that one pure call.

    ``curses`` is imported here, not at module load, so a non-tty run (every
    test, every pipe, ``--frame N``) never touches it.
    """
    import curses

    teams: list[str | None] = [None, *(t["id"] for t in data["teams"])]
    start = teams.index(initial_team) if initial_team in teams else 0

    def _loop(stdscr: "curses._CursesWindow") -> None:
        curses.curs_set(0)
        stdscr.keypad(True)
        frame = len(data["frames"]) - 1
        team_idx = start
        while True:
            team = teams[team_idx]
            lines = render_frame(data, frame, team=team, knowledge=knowledge, color=False)
            stdscr.erase()
            max_y, max_x = stdscr.getmaxyx()
            for row, line in enumerate(lines[: max_y - 1]):
                stdscr.addstr(row, 0, line[: max(max_x - 1, 0)])
            footer = "arrows: step frame | tab: toggle team | q: quit"
            stdscr.addstr(max_y - 1, 0, footer[: max(max_x - 1, 0)])
            stdscr.refresh()
            key = stdscr.getch()
            if key == curses.KEY_LEFT:
                frame = max(0, frame - 1)
            elif key == curses.KEY_RIGHT:
                frame = min(len(data["frames"]) - 1, frame + 1)
            elif key in (ord("\t"), ord("t")):
                team_idx = (team_idx + 1) % len(teams)
            elif key in (ord("q"), 27):
                return

    curses.wrapper(_loop)
