"""``league play`` — one-command launch of a bundled preset game mode.

The preset registry (``league/presets.py``, plan task t2) maps a mode NAME to
a scenario, its sides, each side's driver kind, and (for a bot side) a bot
tier — resolved into the exact dict shape ``league.harness.run_match``
accepts. This noun group is the CLI surface that story promised: any
documented mode (solo-vs-bot, team-vs-bot, team-vs-team, orchestrator,
resident) launches with exactly one command —
``league play start <preset> --apply`` — instead of the multi-step
``team register`` / ``match new`` / ``harness run`` dance ``league play``
performs internally.

``start`` is a write verb and follows the SAME safe-by-default contract every
other write verb in this repo does (``match new``, ``team register``,
``harness run``): it prints what it would launch and only actually plays the
match with ``--apply``. ``--seed``/``--id`` override the preset's own
defaults (e.g. to run several matches from the same preset without a match-id
collision) without ever touching ``league/presets.py`` itself.
"""

from __future__ import annotations

import argparse
from typing import Any

from league.cli._errors import EXIT_USER_ERROR, CliError
from league.cli._output import emit_diagnostic, emit_result
from league.harness import driver_kind
from league.presets import Preset, get_preset, preset_names, resolve_preset
from league.store import validate_id


def _safe_id(value: str, what: str) -> str:
    try:
        return validate_id(value, what=what)
    except ValueError as err:
        raise CliError(
            code=EXIT_USER_ERROR,
            message=str(err),
            remediation="ids become filenames; keep them to letters, digits, '.', '_', '-'",
        ) from err


def _get_preset(name: str) -> Preset:
    try:
        return get_preset(name)
    except ValueError as err:
        raise CliError(
            code=EXIT_USER_ERROR,
            message=str(err),
            remediation="run 'league play list' to see bundled presets",
        ) from err


def _resolve(preset: Preset) -> dict[str, Any]:
    try:
        return resolve_preset(preset)
    except ValueError as err:
        raise CliError(
            code=EXIT_USER_ERROR,
            message=str(err),
            remediation="see 'league play show <preset>' for the resolved config",
        ) from err


def _preset_summary(preset: Preset) -> dict[str, Any]:
    return {
        "name": preset.name,
        "description": preset.description,
        "scenario_id": preset.scenario_id,
        "mode": preset.mode,
        "seed": preset.seed,
        "teams": [
            {"id": t.id, "name": t.name, "driver": driver_kind(t.driver), "model": t.model}
            for t in preset.teams
        ],
    }


def cmd_play_overview(args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json", False))
    data = {
        "noun": "play",
        "description": (
            "One-command launch of a bundled preset game mode: any documented mode "
            "(solo-vs-bot, team-vs-bot, team-vs-team, orchestrator-vs-bot, "
            "resident-vs-bot) runs to completion from a single "
            "'league play start <preset> --apply' call — no hand-authored team "
            "registration or match config required."
        ),
        "verbs": {
            "list": "enumerate the bundled presets (--json for full metadata)",
            "show": "the resolved, launchable harness config for one preset (--json)",
            "start": "register teams + create + run the match end to end " "(dry-run; --apply)",
        },
    }
    if json_mode:
        emit_result(data, json_mode=True)
    else:
        lines = ["league play — one-command preset launch", ""]
        lines += [f"  league play {verb:<6} {desc}" for verb, desc in data["verbs"].items()]
        emit_result("\n".join(lines), json_mode=False)
    return 0


def cmd_play_list(args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json", False))
    presets = [_preset_summary(_get_preset(name)) for name in preset_names()]
    if json_mode:
        emit_result({"presets": presets}, json_mode=True)
    else:
        lines = []
        for p in presets:
            drivers = ", ".join(f"{t['id']}={t['driver']}" for t in p["teams"])
            lines.append(f"{p['name']}: {p['description']} [{drivers}]")
        emit_result("\n".join(lines), json_mode=False)
    return 0


def cmd_play_show(args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json", False))
    preset = _get_preset(args.preset)
    config = _resolve(preset)
    if json_mode:
        emit_result(config, json_mode=True)
    else:
        lines = [
            f"{preset.name} — {preset.description}",
            f"scenario: {preset.scenario_id} ({preset.mode}, seed {preset.seed})"
            + (", fog on" if config.get("fog") else ""),
        ]
        for team in config["teams"]:
            lines.append(
                f"  {team['id']} ({team['name']}): driver {driver_kind(team['driver'])} "
                f"— {len(team['agents'])} seats"
            )
        emit_result("\n".join(lines), json_mode=False)
    return 0


def cmd_play_start(args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json", False))
    preset = _get_preset(args.preset)
    config = _resolve(preset)

    if args.seed is not None:
        if args.seed < 0:
            raise CliError(
                code=EXIT_USER_ERROR,
                message="--seed must be a non-negative int",
                remediation="pass --seed 0 or greater",
            )
        config["match"]["seed"] = args.seed
    if args.id:
        config["match"]["id"] = _safe_id(args.id, "match id")

    match_id = config["match"]["id"]
    drivers = {t["id"]: driver_kind(t["driver"]) for t in config["teams"]}
    payload: dict[str, Any] = {
        "preset": preset.name,
        "match_id": match_id,
        "scenario": config["match"]["scenario"],
        "mode": config["match"]["mode"],
        "seed": config["match"]["seed"],
        "teams": [t["id"] for t in config["teams"]],
        "driver_kinds": drivers,
        "applied": bool(args.apply),
    }
    if not args.apply:
        if json_mode:
            emit_result(payload, json_mode=True)
        else:
            driver_str = ", ".join(f"{t}={k}" for t, k in drivers.items())
            emit_result(
                f"would launch {preset.name}: {match_id} — {payload['scenario']} "
                f"({payload['mode']}, seed {payload['seed']}, drivers: {driver_str}) "
                "— dry-run; add --apply",
                json_mode=False,
            )
        return 0

    from league.harness import run_match

    def on_turn(resolution: dict[str, Any]) -> None:
        emit_diagnostic(
            f"turn {resolution['turn']} resolved ({resolution['events']} events, "
            f"{resolution['rejected']} rejected)"
        )

    try:
        result = run_match(config, on_turn=on_turn)
    except (RuntimeError, ValueError, KeyError) as err:
        raise CliError(
            code=EXIT_USER_ERROR,
            message=f"play start failed: {err}",
            remediation="check the preset's drivers; see 'league play show <preset>'",
        ) from err
    payload["result"] = result
    if json_mode:
        emit_result(payload, json_mode=True)
    else:
        emit_result(
            f"{result['match_id']}: {result['status']} after {result['turns_played']} turns"
            + (f" — winner {result['winner']}" if result["winner"] else ""),
            json_mode=False,
        )
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("play", help="One-command preset launch (see 'league play overview').")
    p.add_argument("--json", action="store_true", help="Emit structured JSON.")
    p.set_defaults(func=cmd_play_overview, json=False)
    noun_sub = p.add_subparsers(dest="play_command", parser_class=type(p))

    ov = noun_sub.add_parser("overview", help="Describe the play noun.")
    ov.add_argument("--json", action="store_true", help="Emit structured JSON.")
    ov.set_defaults(func=cmd_play_overview)

    ls = noun_sub.add_parser("list", help="List the bundled preset game modes.")
    ls.add_argument("--json", action="store_true", help="Emit structured JSON.")
    ls.set_defaults(func=cmd_play_list)

    show = noun_sub.add_parser("show", help="Show one preset's resolved harness config.")
    show.add_argument("preset", help="Preset name (see 'league play list').")
    show.add_argument("--json", action="store_true", help="Emit structured JSON.")
    show.set_defaults(func=cmd_play_show)

    start = noun_sub.add_parser("start", help="Launch a preset end to end (dry-run by default).")
    start.add_argument("preset", help="Preset name (see 'league play list').")
    start.add_argument("--seed", type=int, help="Override the preset's declared seed.")
    start.add_argument("--id", help="Override the preset's derived match id.")
    start.add_argument("--apply", action="store_true", help="Actually run (default: dry-run).")
    start.add_argument("--json", action="store_true", help="Emit structured JSON.")
    start.set_defaults(func=cmd_play_start)
