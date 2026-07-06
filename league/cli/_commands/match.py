"""``league match`` — create, play, and inspect matches.

The play loop is agent-first and safe by default:

* ``match new`` / ``match act`` / ``match tick`` are write verbs — dry-run
  unless ``--apply`` (a stray call in an agent loop never advances the game);
* teams *declare* orders with ``act``; the turn resolves when every team has
  staged (or when ``tick`` forces it, e.g. on a timeout);
* ``show``/``score`` are ``--json``-friendly reads; ``replay`` prints the
  self-contained HTML to stdout — redirect it to a file and open it.
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from league.cli._errors import EXIT_USER_ERROR, CliError
from league.cli._output import emit_result
from league.engine.events import MatchLog
from league.engine.scenario import get_scenario, instantiate
from league.engine.scoring import score_match
from league.engine.tick import resolve_turn, start_match
from league.replay import render_html
from league.store import Store


def _load(store: Store, match_id: str) -> MatchLog:
    try:
        return store.load_match(match_id)
    except FileNotFoundError as err:
        raise CliError(
            code=EXIT_USER_ERROR,
            message=str(err),
            remediation="run 'league match list' to see matches",
        ) from err


def cmd_match_overview(args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json", False))
    data = {
        "noun": "match",
        "description": (
            "The play loop: teams declare orders each turn; the deterministic tick "
            "resolves them. The match log is the single source of truth."
        ),
        "verbs": {
            "new": "create a match from a scenario + registered teams (dry-run; --apply)",
            "list": "list matches in this arena",
            "show": "current state + staged teams (--json for the full state)",
            "act": "stage a team's orders; resolves when all teams have staged "
            "(dry-run; --apply)",
            "tick": "force-resolve the turn with whatever is staged (dry-run; --apply)",
            "score": "outcome + cooperation scores from the log",
            "replay": "self-contained HTML replay on stdout",
        },
    }
    if json_mode:
        emit_result(data, json_mode=True)
    else:
        lines = ["league match — the play loop", ""]
        lines += [f"  league match {verb:<7} {desc}" for verb, desc in data["verbs"].items()]
        emit_result("\n".join(lines), json_mode=False)
    return 0


def cmd_match_new(args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json", False))
    store = Store()
    try:
        scenario = get_scenario(args.scenario)
    except ValueError as err:
        raise CliError(
            code=EXIT_USER_ERROR,
            message=str(err),
            remediation="run 'league arena list' to see scenarios",
        ) from err

    team_ids = args.team or []
    teams = []
    for team_id in team_ids:
        try:
            teams.append(store.team_slots(team_id))
        except FileNotFoundError as err:
            raise CliError(
                code=EXIT_USER_ERROR,
                message=str(err),
                remediation="register it first: league team register ... --apply",
            ) from err

    match_id = args.id or (
        f"m-{args.scenario}-{args.mode}-s{args.seed}-{len(store.list_matches()) + 1:03d}"
    )
    try:
        state = instantiate(
            scenario, match_id=match_id, seed=args.seed, mode=args.mode, teams=teams
        )
    except ValueError as err:
        raise CliError(
            code=EXIT_USER_ERROR,
            message=str(err),
            remediation="check --mode/--team against 'league arena show'",
        ) from err
    state, events = start_match(state)

    payload = {
        "match_id": match_id,
        "scenario": args.scenario,
        "mode": args.mode,
        "seed": args.seed,
        "teams": [t[0] for t in teams],
        "turn_limit": state.turn_limit,
        "applied": bool(args.apply),
    }
    if args.apply:
        initial = instantiate(
            scenario, match_id=match_id, seed=args.seed, mode=args.mode, teams=teams
        )
        log = MatchLog(initial_state=initial, events=events)
        try:
            path = store.create_match(log)
        except FileExistsError as err:
            raise CliError(
                code=EXIT_USER_ERROR,
                message=str(err),
                remediation="pass a fresh --id",
            ) from err
        payload["log"] = str(path)
    if json_mode:
        emit_result(payload, json_mode=True)
    else:
        verb = "created" if args.apply else "would create (dry-run; add --apply)"
        emit_result(
            f"{verb}: {match_id} — {args.scenario} ({args.mode}, seed {args.seed}, "
            f"teams: {', '.join(payload['teams']) or 'none'})",
            json_mode=False,
        )
    return 0


def cmd_match_list(args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json", False))
    store = Store()
    rows = []
    for match_id in store.list_matches():
        state = store.load_match(match_id).final_state()
        rows.append(
            {
                "match_id": match_id,
                "status": state.status,
                "turn": state.turn,
                "turn_limit": state.turn_limit,
                "winner": state.winner,
            }
        )
    if json_mode:
        emit_result({"matches": rows}, json_mode=True)
    elif not rows:
        emit_result("no matches yet (see 'league match new')", json_mode=False)
    else:
        emit_result(
            "\n".join(
                f"{r['match_id']}: {r['status']} turn {r['turn']}/{r['turn_limit']}"
                + (f" — winner {r['winner']}" if r["winner"] else "")
                for r in rows
            ),
            json_mode=False,
        )
    return 0


def cmd_match_show(args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json", False))
    store = Store()
    log = _load(store, args.match_id)
    state = log.final_state()
    pending = sorted(store.pending_orders(args.match_id))
    if json_mode:
        emit_result({"state": state.to_dict(), "staged_teams": pending}, json_mode=True)
        return 0
    lines = [
        f"{state.match_id}: {state.status} — turn {state.turn}/{state.turn_limit} "
        f"({state.mode}, seed {state.seed})",
    ]
    if state.winner:
        lines.append(f"winner: {state.winner}")
    for team in state.teams:
        units = [u for u in state.units if u.team_id == team.id and u.alive]
        lines.append(
            f"  {team.id}: resources {team.resources}, units "
            + ", ".join(f"{u.id}@{u.pos[0]},{u.pos[1]}" for u in units)
        )
    for cp in state.control_points:
        hold = f", streak {cp.hold[0][1]} ({cp.hold[0][0]})" if cp.hold else ""
        lines.append(f"  {cp.id}: owner {cp.owner or '—'}{hold}")
    for mission in state.missions:
        who = f" by {mission.completed_by}" if mission.completed_by else ""
        lines.append(f"  {mission.id}: {mission.status}{who}")
    if pending:
        lines.append(f"staged orders: {', '.join(pending)}")
    emit_result("\n".join(lines), json_mode=False)
    return 0


def _orders_from_args(args: argparse.Namespace) -> dict[str, Any]:
    if args.orders_json:
        try:
            orders = json.loads(args.orders_json)
        except json.JSONDecodeError as err:
            raise CliError(
                code=EXIT_USER_ERROR,
                message=f"--orders-json is not valid JSON: {err}",
                remediation='pass e.g. \'{"actions": [{"unit_id": "blue-u1", '
                '"action": "hold"}]}\'',
            ) from err
        if not isinstance(orders, dict):
            raise CliError(
                code=EXIT_USER_ERROR,
                message="--orders-json must be a JSON object",
                remediation='shape: {"plan": ..., "messages": [...], "actions": [...]}',
            )
        return orders
    orders: dict[str, Any] = {"actions": []}
    if args.plan:
        orders["plan"] = args.plan
    for spec in args.message or ():
        sender, _, text = spec.partition(":")
        if not text:
            raise CliError(
                code=EXIT_USER_ERROR,
                message=f"bad --message {spec!r}",
                remediation="use --message <from-agent>:<text>",
            )
        orders.setdefault("messages", []).append({"from": sender, "text": text})
    for spec in args.action or ():
        parts = spec.split(":")
        if len(parts) == 2:
            orders["actions"].append({"unit_id": parts[0], "action": parts[1]})
        elif len(parts) == 3 and "," in parts[2]:
            x, _, y = parts[2].partition(",")
            try:
                to = [int(x), int(y)]
            except ValueError as err:
                raise CliError(
                    code=EXIT_USER_ERROR,
                    message=f"bad --action target in {spec!r}",
                    remediation="use --action <unit>:move:<x>,<y>",
                ) from err
            orders["actions"].append({"unit_id": parts[0], "action": parts[1], "to": to})
        else:
            raise CliError(
                code=EXIT_USER_ERROR,
                message=f"bad --action {spec!r}",
                remediation="use <unit>:<verb> or <unit>:move:<x>,<y>",
            )
    return orders


def _resolve(store: Store, match_id: str, log: MatchLog) -> tuple[MatchLog, dict[str, Any]]:
    state = log.final_state()
    scenario = get_scenario(state.scenario_id)
    orders = store.pending_orders(match_id)
    new_state, events = resolve_turn(state, scenario, orders, seq_start=len(log.events))
    store.append_events(match_id, events)
    store.clear_pending(match_id)
    summary = {
        "turn": new_state.turn,
        "status": new_state.status,
        "winner": new_state.winner,
        "events": len(events),
        "rejected": sum(1 for e in events if e.kind == "action_rejected"),
    }
    return MatchLog(initial_state=log.initial_state, events=log.events + events), summary


def cmd_match_act(args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json", False))
    store = Store()
    log = _load(store, args.match_id)
    state = log.final_state()
    if state.status != "active":
        raise CliError(
            code=EXIT_USER_ERROR,
            message=f"match {args.match_id!r} is {state.status}, not active",
            remediation="start a new match with 'league match new'",
        )
    if args.team not in {t.id for t in state.teams}:
        raise CliError(
            code=EXIT_USER_ERROR,
            message=f"team {args.team!r} is not in this match",
            remediation=f"teams here: {', '.join(t.id for t in state.teams)}",
        )
    orders = _orders_from_args(args)
    staged = set(store.pending_orders(args.match_id)) | {args.team}
    would_resolve = staged >= {t.id for t in state.teams}
    payload: dict[str, Any] = {
        "match_id": args.match_id,
        "team": args.team,
        "orders": orders,
        "staged_teams": sorted(staged),
        "resolves_turn": would_resolve,
        "applied": bool(args.apply),
    }
    if args.apply:
        store.stage_orders(args.match_id, args.team, orders)
        if would_resolve:
            _, summary = _resolve(store, args.match_id, log)
            payload["resolution"] = summary
    if json_mode:
        emit_result(payload, json_mode=True)
    else:
        if not args.apply:
            emit_result(
                f"would stage orders for {args.team} on {args.match_id} "
                f"({'and resolve the turn' if would_resolve else 'waiting on other teams'}) "
                "— dry-run; add --apply",
                json_mode=False,
            )
        elif would_resolve:
            s = payload["resolution"]
            tail = f" — {s['status']}" + (f", winner {s['winner']}" if s["winner"] else "")
            emit_result(
                f"orders in; turn {s['turn']} resolved ({s['events']} events, "
                f"{s['rejected']} rejected){tail}",
                json_mode=False,
            )
        else:
            emit_result(
                f"orders staged for {args.team}; waiting on "
                f"{', '.join(sorted({t.id for t in state.teams} - staged))}",
                json_mode=False,
            )
    return 0


def cmd_match_tick(args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json", False))
    store = Store()
    log = _load(store, args.match_id)
    state = log.final_state()
    if state.status != "active":
        raise CliError(
            code=EXIT_USER_ERROR,
            message=f"match {args.match_id!r} is {state.status}, not active",
            remediation="only active matches tick",
        )
    staged = sorted(store.pending_orders(args.match_id))
    payload: dict[str, Any] = {
        "match_id": args.match_id,
        "staged_teams": staged,
        "applied": bool(args.apply),
    }
    if args.apply:
        _, summary = _resolve(store, args.match_id, log)
        payload["resolution"] = summary
        if json_mode:
            emit_result(payload, json_mode=True)
        else:
            s = summary
            tail = f" — {s['status']}" + (f", winner {s['winner']}" if s["winner"] else "")
            emit_result(f"turn {s['turn']} resolved ({s['events']} events){tail}", json_mode=False)
    else:
        if json_mode:
            emit_result(payload, json_mode=True)
        else:
            emit_result(
                f"would force-resolve the turn with orders from: "
                f"{', '.join(staged) or 'nobody'} — dry-run; add --apply",
                json_mode=False,
            )
    return 0


def cmd_match_score(args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json", False))
    log = _load(Store(), args.match_id)
    report = score_match(log)
    if json_mode:
        emit_result(report, json_mode=True)
        return 0
    lines = [f"{report['match_id']}: winner {report['winner'] or '—'}"]
    for team_id, outcome in report["outcome"].items():
        coop = report["cooperation"][team_id]
        lines.append(
            f"  {team_id}: outcome {outcome['total']} "
            f"(missions {outcome['missions']}, control {outcome['control']}, "
            f"resources {outcome['resources']}), cooperation {coop['score']}/100"
        )
    emit_result("\n".join(lines), json_mode=False)
    return 0


def cmd_match_replay(args: argparse.Namespace) -> int:
    log = _load(Store(), args.match_id)
    emit_result(render_html(log), json_mode=False)
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("match", help="Create and play matches (see 'league match overview').")
    p.add_argument("--json", action="store_true", help="Emit structured JSON.")
    p.set_defaults(func=cmd_match_overview, json=False)
    noun_sub = p.add_subparsers(dest="match_command", parser_class=type(p))

    ov = noun_sub.add_parser("overview", help="Describe the match noun.")
    ov.add_argument("--json", action="store_true", help="Emit structured JSON.")
    ov.set_defaults(func=cmd_match_overview)

    new = noun_sub.add_parser("new", help="Create a match (dry-run by default).")
    new.add_argument("--scenario", required=True, help="Scenario id (league arena list).")
    new.add_argument(
        "--mode",
        choices=("cooperative", "competitive"),
        default="competitive",
        help="Match mode.",
    )
    new.add_argument("--team", action="append", help="Registered team id; repeatable.")
    new.add_argument("--seed", type=int, default=1, help="Deterministic seed (default 1).")
    new.add_argument("--id", help="Match id (default: derived from scenario/mode/seed).")
    new.add_argument("--apply", action="store_true", help="Actually create (default: dry-run).")
    new.add_argument("--json", action="store_true", help="Emit structured JSON.")
    new.set_defaults(func=cmd_match_new)

    ls = noun_sub.add_parser("list", help="List matches.")
    ls.add_argument("--json", action="store_true", help="Emit structured JSON.")
    ls.set_defaults(func=cmd_match_list)

    show = noun_sub.add_parser("show", help="Show a match's current state.")
    show.add_argument("match_id", help="Match id.")
    show.add_argument("--json", action="store_true", help="Emit structured JSON.")
    show.set_defaults(func=cmd_match_show)

    act = noun_sub.add_parser(
        "act", help="Stage a team's orders for this turn (dry-run by default)."
    )
    act.add_argument("match_id", help="Match id.")
    act.add_argument("--team", required=True, help="Acting team id.")
    act.add_argument("--orders-json", help="Full orders object as JSON (wins over flags).")
    act.add_argument("--plan", help="Declared team plan for the record.")
    act.add_argument(
        "--message", action="append", metavar="FROM:TEXT", help="Team message; repeatable."
    )
    act.add_argument(
        "--action",
        action="append",
        metavar="UNIT:VERB[:X,Y]",
        help="Unit action (move/gather/deliver/hold); repeatable.",
    )
    act.add_argument("--apply", action="store_true", help="Actually stage (default: dry-run).")
    act.add_argument("--json", action="store_true", help="Emit structured JSON.")
    act.set_defaults(func=cmd_match_act)

    tick = noun_sub.add_parser(
        "tick", help="Force-resolve the turn with staged orders (dry-run by default)."
    )
    tick.add_argument("match_id", help="Match id.")
    tick.add_argument("--apply", action="store_true", help="Actually resolve (default: dry-run).")
    tick.add_argument("--json", action="store_true", help="Emit structured JSON.")
    tick.set_defaults(func=cmd_match_tick)

    score = noun_sub.add_parser("score", help="Outcome + cooperation scores from the log.")
    score.add_argument("match_id", help="Match id.")
    score.add_argument("--json", action="store_true", help="Emit structured JSON.")
    score.set_defaults(func=cmd_match_score)

    replay = noun_sub.add_parser("replay", help="Self-contained HTML replay on stdout.")
    replay.add_argument("match_id", help="Match id.")
    replay.add_argument("--json", action="store_true", help="(accepted; output is HTML)")
    replay.set_defaults(func=cmd_match_replay)
