"""``league team`` — register and inspect the competitors.

``register`` is a write verb and follows the safe-by-default contract: it
prints what it would write and only touches disk with ``--apply``.
"""

from __future__ import annotations

import argparse

from league.cli._errors import EXIT_USER_ERROR, CliError
from league.cli._output import emit_result
from league.engine.state import AgentSlot
from league.store import Store, validate_id


def _safe_id(value: str, what: str) -> str:
    try:
        return validate_id(value, what=what)
    except ValueError as err:
        raise CliError(
            code=EXIT_USER_ERROR,
            message=str(err),
            remediation="ids become filenames; keep them to letters, digits, '.', '_', '-'",
        ) from err


def _parse_agent(spec: str) -> AgentSlot:
    # id is everything before the first colon, role everything after the last;
    # the model keeps any colons of its own (e.g. "bot:greedy").
    parts = spec.split(":")
    if len(parts) < 3 or not (parts[0] and parts[-1] and ":".join(parts[1:-1])):
        raise CliError(
            code=EXIT_USER_ERROR,
            message=f"bad --agent {spec!r}",
            remediation="use --agent <id>:<model>:<role>, e.g. blue-1:claude-sonnet-5:scout",
        )
    return AgentSlot(id=parts[0], model=":".join(parts[1:-1]), role=parts[-1])


def cmd_team_overview(args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json", False))
    data = {
        "noun": "team",
        "description": "The competitors: a team is a named roster of agent seats (id/model/role).",
        "verbs": {
            "register": "create or update a team roster (dry-run by default; --apply writes)",
            "list": "list registered teams",
            "show": "one team's roster",
        },
    }
    if json_mode:
        emit_result(data, json_mode=True)
    else:
        lines = ["league team — the competitors", ""]
        lines += [f"  league team {verb:<9} {desc}" for verb, desc in data["verbs"].items()]
        emit_result("\n".join(lines), json_mode=False)
    return 0


def cmd_team_register(args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json", False))
    _safe_id(args.team_id, "team id")
    agents = tuple(_parse_agent(spec) for spec in args.agent or ())
    if not agents:
        raise CliError(
            code=EXIT_USER_ERROR,
            message="a team needs at least one --agent",
            remediation="pass --agent <id>:<model>:<role> once per seat",
        )
    name = args.name or args.team_id
    store = Store()
    payload = {
        "id": args.team_id,
        "name": name,
        "agents": [a.to_dict() for a in agents],
        "path": str(store.team_path(args.team_id)),
        "applied": bool(args.apply),
    }
    if args.apply:
        store.save_team(args.team_id, name, agents)
    if json_mode:
        emit_result(payload, json_mode=True)
    else:
        verb = "registered" if args.apply else "would register (dry-run; add --apply)"
        roster = ", ".join(f"{a.id} ({a.role}, {a.model})" for a in agents)
        emit_result(f"{verb}: {args.team_id} — {name}\n  roster: {roster}", json_mode=False)
    return 0


def cmd_team_list(args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json", False))
    teams = Store().list_teams()
    if json_mode:
        emit_result({"teams": teams}, json_mode=True)
    else:
        if not teams:
            emit_result("no teams registered (see 'league team register')", json_mode=False)
        else:
            emit_result(
                "\n".join(f"{t['id']} — {t['name']} ({len(t['agents'])} seats)" for t in teams),
                json_mode=False,
            )
    return 0


def cmd_team_show(args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json", False))
    try:
        team = Store().load_team(args.team_id)
    except FileNotFoundError as err:
        raise CliError(
            code=EXIT_USER_ERROR,
            message=str(err),
            remediation="run 'league team list' to see registered teams",
        ) from err
    if json_mode:
        emit_result(team, json_mode=True)
    else:
        lines = [f"{team['id']} — {team['name']}"]
        lines += [f"  {a['id']}: {a['role']} ({a['model']})" for a in team["agents"]]
        emit_result("\n".join(lines), json_mode=False)
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("team", help="Team rosters (see 'league team overview').")
    p.add_argument("--json", action="store_true", help="Emit structured JSON.")
    p.set_defaults(func=cmd_team_overview, json=False)
    noun_sub = p.add_subparsers(dest="team_command", parser_class=type(p))

    ov = noun_sub.add_parser("overview", help="Describe the team noun.")
    ov.add_argument("--json", action="store_true", help="Emit structured JSON.")
    ov.set_defaults(func=cmd_team_overview)

    reg = noun_sub.add_parser("register", help="Register a team roster (dry-run by default).")
    reg.add_argument("team_id", help="Team id, e.g. blue.")
    reg.add_argument("--name", help="Display name (defaults to the id).")
    reg.add_argument(
        "--agent",
        action="append",
        metavar="ID:MODEL:ROLE",
        help="One roster seat; repeatable.",
    )
    reg.add_argument("--apply", action="store_true", help="Actually write (default: dry-run).")
    reg.add_argument("--json", action="store_true", help="Emit structured JSON.")
    reg.set_defaults(func=cmd_team_register)

    ls = noun_sub.add_parser("list", help="List registered teams.")
    ls.add_argument("--json", action="store_true", help="Emit structured JSON.")
    ls.set_defaults(func=cmd_team_list)

    show = noun_sub.add_parser("show", help="Show one team's roster.")
    show.add_argument("team_id", help="Team id.")
    show.add_argument("--json", action="store_true", help="Emit structured JSON.")
    show.set_defaults(func=cmd_team_show)
