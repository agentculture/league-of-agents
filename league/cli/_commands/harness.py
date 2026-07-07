"""``league harness`` — run a whole match with live agent drivers.

``run`` is a write verb (it registers teams, creates the match, and plays it
to completion), so it follows the safe-by-default contract: dry-run prints
the plan; ``--apply`` actually runs.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from league.cli._errors import EXIT_USER_ERROR, CliError
from league.cli._output import emit_diagnostic, emit_result


def cmd_harness_overview(args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json", False))
    data = {
        "noun": "harness",
        "description": (
            "Run a full match with live team drivers (deterministic bots or external "
            "agent commands), acting only through the public CLI surface."
        ),
        "verbs": {"run": "play a configured match to completion (dry-run; --apply)"},
    }
    if json_mode:
        emit_result(data, json_mode=True)
    else:
        emit_result(
            "league harness — live-agent match runner\n\n"
            "  league harness run --config <file.json> [--apply]",
            json_mode=False,
        )
    return 0


def cmd_harness_run(args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json", False))
    path = Path(args.config)
    if not path.is_file():
        raise CliError(
            code=EXIT_USER_ERROR,
            message=f"no config file at {path}",
            remediation="see 'league explain harness' for the config shape",
        )
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as err:
        raise CliError(
            code=EXIT_USER_ERROR,
            message=f"config is not valid JSON: {err}",
            remediation="see 'league explain harness' for the config shape",
        ) from err

    teams = config.get("teams", [])
    summary = {
        "config": str(path),
        "match": config.get("match", {}),
        "teams": [{"id": t.get("id"), "driver": t.get("driver", {}).get("type")} for t in teams],
        "applied": bool(args.apply),
    }
    if not args.apply:
        if json_mode:
            emit_result(summary, json_mode=True)
        else:
            drivers = ", ".join(f"{t['id']}({t['driver']})" for t in summary["teams"])
            emit_result(
                f"would run {summary['match'].get('scenario')} with {drivers} "
                "— dry-run; add --apply",
                json_mode=False,
            )
        return 0

    from league.harness import run_match

    def on_turn(resolution: dict) -> None:
        emit_diagnostic(
            f"turn {resolution['turn']} resolved ({resolution['events']} events, "
            f"{resolution['rejected']} rejected)"
        )

    try:
        result = run_match(config, on_turn=on_turn)
    except (RuntimeError, ValueError, KeyError) as err:
        raise CliError(
            code=EXIT_USER_ERROR,
            message=f"harness run failed: {err}",
            remediation="check the drivers and config; see 'league explain harness'",
        ) from err
    if json_mode:
        emit_result(result, json_mode=True)
    else:
        emit_result(
            f"{result['match_id']}: {result['status']} after {result['turns_played']} turns"
            + (f" — winner {result['winner']}" if result["winner"] else ""),
            json_mode=False,
        )
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("harness", help="Live-agent match runner (see 'league harness overview').")
    p.add_argument("--json", action="store_true", help="Emit structured JSON.")
    p.set_defaults(func=cmd_harness_overview, json=False)
    noun_sub = p.add_subparsers(dest="harness_command", parser_class=type(p))

    ov = noun_sub.add_parser("overview", help="Describe the harness noun.")
    ov.add_argument("--json", action="store_true", help="Emit structured JSON.")
    ov.set_defaults(func=cmd_harness_overview)

    run = noun_sub.add_parser("run", help="Run a configured match (dry-run by default).")
    run.add_argument("--config", required=True, help="Path to the harness config JSON.")
    run.add_argument("--apply", action="store_true", help="Actually run (default: dry-run).")
    run.add_argument("--json", action="store_true", help="Emit structured JSON.")
    run.set_defaults(func=cmd_harness_run)
