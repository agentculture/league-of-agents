"""``league arena`` — the scenario catalog (read-only).

Scenarios are the maps/objectives matches run on. This noun is pure
introspection: ``list`` and ``show`` never mutate anything.
"""

from __future__ import annotations

import argparse

from league.cli._errors import EXIT_USER_ERROR, CliError
from league.cli._output import emit_result
from league.engine.scenario import Scenario, get_scenario, scenario_ids


def _role_caps(st) -> str:
    """Compact human note of a role's capability restrictions (h11): only the
    *withheld* capabilities are shown, so an unrestricted executor reads clean
    while an explorer/planner announces what it cannot do."""
    flags = []
    if not st.can_gather:
        flags.append("no-gather")
    if not st.can_capture:
        flags.append("no-capture")
    return f", {', '.join(flags)}" if flags else ""


def _scenario_dict(s: Scenario) -> dict[str, object]:
    return {
        "id": s.id,
        "name": s.name,
        "description": s.description,
        "grid": {"width": s.grid_width, "height": s.grid_height},
        "turn_limit": s.turn_limit,
        "modes": list(s.modes),
        "capture_hold_turns": s.capture_hold_turns,
        "roles": {
            name: {
                "move": st.move,
                "carry": st.carry,
                "vision": st.vision,
                "can_gather": st.can_gather,
                "can_capture": st.can_capture,
                "analog": st.analog,
            }
            for name, st in s.role_stats
        },
        "control_points": [{"id": c.id, "pos": list(c.pos)} for c in s.control_points],
        "missions": [
            {"id": m.id, "kind": m.kind, "pos": list(m.pos), "amount": m.amount, "reward": m.reward}
            for m in s.missions
        ],
        "resource_nodes": [
            {"id": r.id, "pos": list(r.pos), "remaining": r.remaining} for r in s.resource_nodes
        ],
    }


def cmd_arena_overview(args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json", False))
    data = {
        "noun": "arena",
        "description": "Scenario catalog: the maps, objectives and economies matches run on.",
        "verbs": {
            "list": "list available scenario ids",
            "show": "full scenario definition (grid, roles, objectives)",
        },
        "read_only": True,
    }
    if json_mode:
        emit_result(data, json_mode=True)
    else:
        lines = ["league arena — scenario catalog (read-only)", ""]
        lines += [f"  league arena {verb:<6} {desc}" for verb, desc in data["verbs"].items()]
        emit_result("\n".join(lines), json_mode=False)
    return 0


def cmd_arena_list(args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json", False))
    ids = list(scenario_ids())
    if json_mode:
        emit_result({"scenarios": ids}, json_mode=True)
    else:
        emit_result("\n".join(ids), json_mode=False)
    return 0


def cmd_arena_show(args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json", False))
    try:
        scenario = get_scenario(args.scenario_id)
    except ValueError as err:
        raise CliError(
            code=EXIT_USER_ERROR,
            message=str(err),
            remediation="run 'league arena list' to see available scenarios",
        ) from err
    data = _scenario_dict(scenario)
    if json_mode:
        emit_result(data, json_mode=True)
    else:
        lines = [
            f"{scenario.id} — {scenario.name}",
            scenario.description,
            "",
            f"grid {scenario.grid_width}x{scenario.grid_height}, "
            f"turn limit {scenario.turn_limit}, modes: {', '.join(scenario.modes)}",
            "roles: "
            + ", ".join(
                f"{n} (move {s.move}, carry {s.carry}, vision {s.vision}{_role_caps(s)})"
                for n, s in scenario.role_stats
            ),
            f"control points: {', '.join(c.id for c in scenario.control_points)}",
            f"missions: {', '.join(f'{m.id} ({m.kind} {m.amount})' for m in scenario.missions)}",
        ]
        emit_result("\n".join(lines), json_mode=False)
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("arena", help="Scenario catalog (see 'league arena overview').")
    p.add_argument("--json", action="store_true", help="Emit structured JSON.")
    p.set_defaults(func=cmd_arena_overview, json=False)
    noun_sub = p.add_subparsers(dest="arena_command", parser_class=type(p))

    ov = noun_sub.add_parser("overview", help="Describe the arena noun.")
    ov.add_argument("--json", action="store_true", help="Emit structured JSON.")
    ov.set_defaults(func=cmd_arena_overview)

    ls = noun_sub.add_parser("list", help="List available scenarios.")
    ls.add_argument("--json", action="store_true", help="Emit structured JSON.")
    ls.set_defaults(func=cmd_arena_list)

    show = noun_sub.add_parser("show", help="Show one scenario in full.")
    show.add_argument("scenario_id", help="Scenario id (see 'league arena list').")
    show.add_argument("--json", action="store_true", help="Emit structured JSON.")
    show.set_defaults(func=cmd_arena_show)
