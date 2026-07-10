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
import os
import shutil
import subprocess  # nosec B404
import sys
import tempfile
from pathlib import Path
from typing import Any

from league.cli._errors import EXIT_ENV_ERROR, EXIT_USER_ERROR, CliError
from league.cli._output import emit_result
from league.engine.continuous.events import CMatchLog
from league.engine.continuous.grades import PURPOSES as CONTINUOUS_GRADE_PURPOSES
from league.engine.continuous.grades import cgrade_units
from league.engine.continuous.resolve import outcome_points as continuous_outcome_points
from league.engine.continuous.scenario import CONTINUOUS_ID_PREFIX
from league.engine.events import Event, MatchLog
from league.engine.grades import grade_units
from league.engine.knowledge import KnowledgeFrame, knowledge_by_turn, latest_knowledge
from league.engine.legal import legal_actions
from league.engine.probe import probe_match
from league.engine.scenario import Scenario, get_scenario, instantiate
from league.engine.scoring import score_match
from league.engine.state import MatchState
from league.engine.tempo import score_tempo
from league.engine.tick import resolve_turn, start_match
from league.faces import faces_app, render_brief_markdown
from league.replay import (
    DEFAULT_FPS,
    DEFAULT_SCALE,
    DEFAULT_THEME,
    DEFAULT_TWEEN,
    MAX_FPS,
    MAX_SCALE,
    MAX_TWEEN,
    MIN_FPS,
    MIN_SCALE,
    MIN_TWEEN,
    build_continuous_replay_data,
)
from league.replay import build_frames as build_video_frames
from league.replay import (
    build_replay_data,
    indices_to_rgb,
    motif_schedule,
    render_chtml,
    render_frame,
    render_gif,
    render_html,
    run_interactive_shell,
    samples_for_frames,
    synthesize_wav,
)
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


# Residency: the declared driver-kind fairness axis (spec c10/h7). Metadata
# about HOW a team's minds were invoked — never game state, so it lives in the
# match log header (league.engine.events.MatchLog.driver_kinds), not the state.
_DRIVER_KINDS = ("bot", "stateless", "resident")

# The coded-strategy bot lane (issue #30): harness configs already spell a
# bot-file team's driver as {"type": "bot-file", "strategy": "<name>"}, and
# the season-0 configs already label the SAME thing "bot-file:<name>" in a
# team's agent ``model`` field (docs/playtests/season-0/*.config.json). A
# raw `match new --driver <team>:bot-file:<name>` recognizes that existing
# convention and records the FULL string (kind + strategy) in the header —
# more specific than league.harness.driver_kind()'s own "bot" residency
# label (which only says HOW invoked, not which strategy), because a direct
# CLI call has no harness config to derive the strategy name from otherwise.
_BOT_FILE_PREFIX = "bot-file:"


def _driver_kinds_from_args(args: argparse.Namespace, team_ids: list[str]) -> dict[str, str]:
    driver_kinds: dict[str, str] = {}
    for spec in args.driver or ():
        team_id, sep, kind = spec.partition(":")
        if not sep or not team_id or not kind:
            raise CliError(
                code=EXIT_USER_ERROR,
                message=f"bad --driver {spec!r}",
                remediation="use --driver <team-id>:<bot|stateless|resident|bot-file:name>",
            )
        if team_id not in team_ids:
            raise CliError(
                code=EXIT_USER_ERROR,
                message=f"--driver references team {team_id!r}, not one of --team",
                remediation=f"teams here: {', '.join(team_ids) or 'none'}",
            )
        if kind.startswith(_BOT_FILE_PREFIX):
            strategy = kind[len(_BOT_FILE_PREFIX) :]
            try:
                validate_id(strategy, what="bot strategy name")
            except ValueError as err:
                raise CliError(
                    code=EXIT_USER_ERROR,
                    message=f"bad --driver {spec!r}: {err}",
                    remediation="use --driver <team-id>:bot-file:<strategy-name> "
                    "(bots/<strategy-name>.py)",
                ) from err
            driver_kinds[team_id] = kind  # the full "bot-file:<name>" string, verbatim
            continue
        if kind not in _DRIVER_KINDS:
            raise CliError(
                code=EXIT_USER_ERROR,
                message=f"unknown driver kind {kind!r} for team {team_id!r}",
                remediation=f"expected one of: {', '.join(_DRIVER_KINDS)}, or bot-file:<name>",
            )
        driver_kinds[team_id] = kind
    return driver_kinds


# Orchestrator mode's two declared fairness axes (plan t6, spec c4/c6/h3/h5):
# metadata about the MODE's information-asymmetry rules, never game state —
# same header-only treatment as ``_DRIVER_KINDS`` above.
_MAP_READ_KINDS = ("full", "fog")


def _map_read_from_args(args: argparse.Namespace, team_ids: list[str]) -> dict[str, str]:
    map_read: dict[str, str] = {}
    for spec in args.map_read or ():
        team_id, sep, kind = spec.partition(":")
        if not sep or not team_id or not kind:
            raise CliError(
                code=EXIT_USER_ERROR,
                message=f"bad --map-read {spec!r}",
                remediation="use --map-read <team-id>:<full|fog>",
            )
        if team_id not in team_ids:
            raise CliError(
                code=EXIT_USER_ERROR,
                message=f"--map-read references team {team_id!r}, not one of --team",
                remediation=f"teams here: {', '.join(team_ids) or 'none'}",
            )
        if kind not in _MAP_READ_KINDS:
            raise CliError(
                code=EXIT_USER_ERROR,
                message=f"unknown map-read kind {kind!r} for team {team_id!r}",
                remediation=f"expected one of: {', '.join(_MAP_READ_KINDS)}",
            )
        map_read[team_id] = kind
    return map_read


def _unit_comms_from_args(args: argparse.Namespace, team_ids: list[str]) -> dict[str, bool]:
    unit_comms: dict[str, bool] = {}
    for spec in args.unit_comms or ():
        team_id, sep, kind = spec.partition(":")
        if not sep or not team_id or not kind:
            raise CliError(
                code=EXIT_USER_ERROR,
                message=f"bad --unit-comms {spec!r}",
                remediation="use --unit-comms <team-id>:<on|off>",
            )
        if team_id not in team_ids:
            raise CliError(
                code=EXIT_USER_ERROR,
                message=f"--unit-comms references team {team_id!r}, not one of --team",
                remediation=f"teams here: {', '.join(team_ids) or 'none'}",
            )
        if kind not in ("on", "off"):
            raise CliError(
                code=EXIT_USER_ERROR,
                message=f"unknown unit-comms value {kind!r} for team {team_id!r}",
                remediation="expected 'on' or 'off'",
            )
        unit_comms[team_id] = kind == "on"
    return unit_comms


# -- mode/handicap fairness: a per-team action cap enforced at the CLI/engine
# -- boundary, not only the harness (issue #29) --------------------------
#
# The solo preset's "one action per turn" handicap used to be enforced ONLY in
# league/harness.py's command-driver wrapper (``actions[:1] if solo else
# actions``) — a raw ``match act`` call, bypassing the harness entirely,
# could stage a full-roster order set for a "solo" team with nothing to stop
# it. ``max_actions`` closes that gap the same way ``driver_kinds``/
# ``map_read``/``unit_comms`` already do: a declared mode profile, persisted
# in the match log header at ``match new`` time (never inferred from a
# driver spec the CLI has no way to see), and enforced where orders are
# staged (``cmd_match_act``, below) — never silently truncated, always a
# structured ``CliError`` plus a durable ``orders_capped`` log event when an
# ``--apply``'d attempt actually trips it. The harness's own truncation is
# unchanged and becomes redundant, not conflicting: a driver that already
# trims to the cap client-side never reaches the refusal path.


def _max_actions_from_args(args: argparse.Namespace, team_ids: list[str]) -> dict[str, int]:
    max_actions: dict[str, int] = {}
    for spec in args.max_actions or ():
        team_id, sep, count = spec.partition(":")
        if not sep or not team_id or not count:
            raise CliError(
                code=EXIT_USER_ERROR,
                message=f"bad --max-actions {spec!r}",
                remediation="use --max-actions <team-id>:<positive-int>",
            )
        if team_id not in team_ids:
            raise CliError(
                code=EXIT_USER_ERROR,
                message=f"--max-actions references team {team_id!r}, not one of --team",
                remediation=f"teams here: {', '.join(team_ids) or 'none'}",
            )
        try:
            n = int(count)
        except ValueError as err:
            raise CliError(
                code=EXIT_USER_ERROR,
                message=f"bad --max-actions {spec!r}: {err}",
                remediation="use --max-actions <team-id>:<positive-int>",
            ) from err
        if n < 1:
            raise CliError(
                code=EXIT_USER_ERROR,
                message=f"--max-actions {spec!r}: cap must be a positive int",
                remediation="use --max-actions <team-id>:<positive-int>",
            )
        max_actions[team_id] = n
    return max_actions


# -- fog of war: one team's briefing-safe projection (plan t5, spec c5/h4) --
#
# The engine/tick stay full-information and deterministic (spec c12
# non-goal); fog is a read-side projection layered on top, the same way
# scoring and knowledge already are — it never touches ``state``, the log,
# or ``state_hash``. ``_fogged_state`` is the substrate ``match show --team
# --fog`` and the harness's briefings share: a team's own roster in full (it
# always knows its own units — they report in), every other team's units and
# every control point / resource node only as far as the team's knowledge
# fold (``league.engine.knowledge``) has seen or been told, and a mission
# revealed only once its declared position coincides with a control point or
# resource node the team already knows about — a mission is board furniture
# the team discovers the same way as anything else, never a free hint.


def _fogged_state(
    state: MatchState, scenario: Scenario, team_id: str, frame: KnowledgeFrame
) -> dict[str, Any]:
    known_units = {u.id: u for u in frame.units}
    units: list[dict[str, Any]] = []
    for unit in state.units:
        if unit.team_id == team_id:
            units.append(unit.to_dict())  # a team always knows its own roster
        else:
            known = known_units.get(unit.id)
            if known is not None:
                units.append(known.to_dict())
    known_positions = {n.pos for n in frame.resource_nodes} | {c.pos for c in frame.control_points}
    missions = [m.to_dict() for m in scenario.missions if m.pos in known_positions]
    return {
        "match_id": state.match_id,
        "scenario_id": state.scenario_id,
        "seed": state.seed,
        "mode": state.mode,
        "turn": state.turn,
        "turn_limit": state.turn_limit,
        "grid_width": state.grid_width,
        "grid_height": state.grid_height,
        "status": state.status,
        "winner": state.winner,
        # Own economy is always known; another team's is not ours to report
        # on (nothing in the knowledge fold tracks it — a fair unknown, not a
        # bug).
        "teams": [
            {**t.to_dict(), "resources": t.resources if t.id == team_id else None}
            for t in state.teams
        ],
        "units": units,
        "control_points": [c.to_dict() for c in frame.control_points],
        "missions": missions,
        "resource_nodes": [n.to_dict() for n in frame.resource_nodes],
        "cells_seen": sorted([list(cell) for cell in frame.cells_seen]),
    }


def _load(store: Store, match_id: str) -> MatchLog:
    try:
        return store.load_match(match_id)
    except FileNotFoundError as err:
        raise CliError(
            code=EXIT_USER_ERROR,
            message=str(err),
            remediation="run 'league match list' to see matches",
        ) from err
    except ValueError as err:
        # A log is an on-disk input — hand-edited or corrupted, its parse
        # failures (``MatchLog.from_jsonl``'s ValueErrors: empty log, bad
        # log_version, invalid max_actions, ...) must land as the CLI's
        # structured error, never the dispatcher's generic "unexpected: ..."
        # wrapper (Qodo review, PR #33; mirrors _load_continuous below).
        raise CliError(
            code=EXIT_USER_ERROR,
            message=f"match {match_id!r} could not be read: {err}",
            remediation="the log file may be corrupt or hand-edited; "
            "run 'league match list' to see matches",
        ) from err


# -- continuous-lane replay routing (plan C7-t9, spec c12/c2) ----------------
#
# There is no continuous-lane store/creation path yet (persistence is a later
# task's concern) — the grid ``Store`` is engine-agnostic about WHERE a log
# lives (``.league/matches/<id>/log.jsonl``), only about how it parses one, so
# a continuous log dropped at that same path (e.g. by ``docs/playtests``
# fixtures or a future harness) is found the identical way. ``replay`` is the
# only verb extended — every other verb stays exactly grid-only, untouched.


def _sniff_continuous_log(raw: str) -> bool:
    """Peek at a match log's own header shape without fully parsing either
    engine lane's dataclasses: continuous ``CMatchState`` headers carry
    ``clock``/``width``; grid ``MatchState`` headers carry ``turn``/
    ``grid_width``. Falls back to ``False`` (grid) on any parse hiccup —
    ``_load``'s existing error path still reports a clean CliError for a
    genuinely corrupt file."""
    lines = raw.splitlines()
    if not lines:
        return False
    try:
        header = json.loads(lines[0])
        initial = header.get("initial_state", {})
    except (ValueError, AttributeError):
        return False
    return isinstance(initial, dict) and "clock" in initial and "turn" not in initial


def _load_continuous(store: Store, match_id: str) -> CMatchLog:
    path = store.log_path(match_id)
    if not path.is_file():
        raise CliError(
            code=EXIT_USER_ERROR,
            message=f"no match {match_id!r}",
            remediation="run 'league match list' to see matches",
        )
    try:
        return CMatchLog.from_jsonl(path.read_text(encoding="utf-8"))
    except (KeyError, ValueError) as err:
        raise CliError(
            code=EXIT_USER_ERROR,
            message=f"match {match_id!r} could not be read as a continuous log: {err}",
            remediation="run 'league match list' to see matches",
        ) from err


def _reject_continuous_log(store: Store, match_id: str, verb: str) -> None:
    """``show``/``probe`` are grid-lane-only today (issue #28 item f — full
    continuous-lane support for these verbs, e.g. new ``cmatch`` verbs, is a
    separate PR). Without this check, ``_load``'s ``MatchLog.from_jsonl``
    tried to read a continuous header's ``initial_state`` (``clock``/
    ``width``, no ``turn``) as a grid ``MatchState`` and blew up with an
    opaque ``unexpected: KeyError: 'turn'`` — the CLI's own error contract
    promises no Python traceback ever leaks. This uses the SAME lane-sniff
    ``score``/``replay`` already route on (``_sniff_continuous_log``) so
    detection is consistent everywhere, and fails with a clean, dedicated,
    structured ``CliError`` naming the limitation instead.

    Only the HEADER LINE is read from disk (Qodo review, PR #33): the lane
    signal lives entirely in line 1, and ``show`` sits on the harness's hot
    path (``match show --json`` is called repeatedly during live play) —
    reading the whole log here just to sniff, then letting ``_load`` read it
    all again, doubled the log I/O per call for no extra information. A read
    hiccup simply falls through to ``_load``, whose error path already
    reports a clean CliError for an unreadable/corrupt file.
    """
    path = store.log_path(match_id)
    if not path.is_file():
        return  # _load's not-found path owns this report
    try:
        with path.open(encoding="utf-8") as fh:
            header_line = fh.readline()
    except (OSError, UnicodeDecodeError):
        return  # _load's error path owns the unreadable/undecodable-file report
    if _sniff_continuous_log(header_line):
        raise CliError(
            code=EXIT_USER_ERROR,
            message=f"match {match_id!r} is a continuous-lane log; 'match {verb}' "
            "doesn't support the continuous lane yet",
            remediation="use 'league match replay' or 'league match score' (both "
            "auto-detect the continuous lane); continuous-lane-native verbs are "
            "tracked separately (issue #28)",
        )


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
            "score": "outcome + cooperation + tempo scores from the log, plus a "
            "per-unit role-purpose scorecard naming MVP/LVP (grid or continuous, "
            "detected automatically; --substrate <team>=<name> to convert tempo)",
            "probe": "span-of-control probe: subagents fielded, per-seat realization, "
            "guidance linkage, from the log alone",
            "brief": "markdown briefing from the faces registry (--team for the fogged view)",
            "replay": "self-contained HTML replay on stdout (grid or continuous, "
            "detected automatically)",
            "record": "render the match log to a shareable GIF (or --format mp4 with "
            "ffmpeg on PATH — MP4 carries the match's seeded ambient soundtrack), "
            "offline, to --out <file> (--theme light|dark, --tween N)",
            "tui": "replay-stepping terminal view: ground truth or --team fog "
            "(--frame N for non-interactive; --no-color)",
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
    _safe_id(match_id, "match id")
    driver_kinds = _driver_kinds_from_args(args, team_ids)
    map_read = _map_read_from_args(args, team_ids)
    unit_comms = _unit_comms_from_args(args, team_ids)
    max_actions = _max_actions_from_args(args, team_ids)
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
        "driver_kinds": driver_kinds,
        "map_read": map_read,
        "unit_comms": unit_comms,
        "max_actions": max_actions,
        "turn_limit": state.turn_limit,
        "applied": bool(args.apply),
    }
    if args.apply:
        initial = instantiate(
            scenario, match_id=match_id, seed=args.seed, mode=args.mode, teams=teams
        )
        log = MatchLog(
            initial_state=initial,
            events=events,
            driver_kinds=driver_kinds,
            map_read=map_read,
            unit_comms=unit_comms,
            max_actions=max_actions,
        )
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
        drivers = (
            f", drivers: {', '.join(f'{t}={k}' for t, k in sorted(driver_kinds.items()))}"
            if driver_kinds
            else ""
        )
        emit_result(
            f"{verb}: {match_id} — {args.scenario} ({args.mode}, seed {args.seed}, "
            f"teams: {', '.join(payload['teams']) or 'none'}{drivers})",
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
    _reject_continuous_log(store, args.match_id, "show")
    log = _load(store, args.match_id)
    state = log.final_state()
    pending = sorted(store.pending_orders(args.match_id))
    team_id = getattr(args, "team", None)
    fog = bool(getattr(args, "fog", False))
    if fog and not team_id:
        raise CliError(
            code=EXIT_USER_ERROR,
            message="--fog requires --team",
            remediation="pass --team <team-id> --fog for that team's fogged view",
        )
    if team_id is not None and team_id not in {t.id for t in state.teams}:
        raise CliError(
            code=EXIT_USER_ERROR,
            message=f"team {team_id!r} is not in this match",
            remediation=f"teams here: {', '.join(t.id for t in state.teams)}",
        )
    if json_mode:
        scenario = get_scenario(state.scenario_id)
        living_actions = {
            unit.id: legal_actions(state, scenario, unit.id)
            for unit in state.units
            if unit.alive and (team_id is None or unit.team_id == team_id)
        }
        # The rejections from the most recently resolved turn — the harness's
        # rejection-feedback loop (spec c8/h5): a seat that never learns why an
        # order was rejected repeats it for the whole match (season-0
        # coordination playtest: 19 of 53 orders). ``event.turn`` on an
        # ``action_rejected`` is the turn it was rejected in; that equals
        # ``state.turn`` right after the fold, so this is exactly "last turn",
        # never a history dump. ``passive`` rejections (issue #31) are excluded
        # here too: a capture-incapable unit standing on a point fires one every
        # turn from mere occupancy, regardless of whether its own declared order
        # succeeded — surfacing it here would have the harness re-explain the
        # same non-mistake to a seat that did nothing wrong, every turn.
        last_turn_rejections = [
            {
                "team_id": event.data.get("team_id"),
                "unit_id": event.data.get("unit_id"),
                "reason": event.data.get("reason"),
            }
            for event in log.events
            if event.kind == "action_rejected"
            and not event.data.get("passive")
            and event.turn == state.turn
            and (team_id is None or event.data.get("team_id") == team_id)
        ]
        payload: dict[str, Any] = {
            "state": state.to_dict(),
            "staged_teams": pending,
            "legal_actions": living_actions,
            "last_turn_rejections": last_turn_rejections,
            "driver_kinds": log.driver_kinds,
            "map_read": log.map_read,
            "unit_comms": log.unit_comms,
            "max_actions": log.max_actions,
        }
        if fog:
            # Additive and read-only: swaps only this response's "state" for
            # the team's fog-of-war projection and adds "knowledge" (the raw
            # fold) — the plain (no --team/--fog) response above is untouched.
            frame = latest_knowledge(log, scenario)[team_id]
            payload["knowledge"] = frame.to_dict()
            payload["state"] = _fogged_state(state, scenario, team_id, frame)
        emit_result(payload, json_mode=True)
        return 0
    lines = [
        f"{state.match_id}: {state.status} — turn {state.turn}/{state.turn_limit} "
        f"({state.mode}, seed {state.seed})",
    ]
    if state.winner:
        lines.append(f"winner: {state.winner}")
    for team in state.teams:
        units = [u for u in state.units if u.team_id == team.id and u.alive]
        driver = log.driver_kinds.get(team.id)
        lines.append(
            f"  {team.id}: resources {team.resources}"
            + (f", driver {driver}" if driver else "")
            + ", units "
            + ", ".join(f"{u.id}@{u.pos[0]},{u.pos[1]}" for u in units)
        )
    for cp in state.control_points:
        hold = f", streak {cp.hold[0][1]} ({cp.hold[0][0]})" if cp.hold else ""
        lines.append(f"  {cp.id}: owner {cp.owner or '—'}{hold}")
    for mission in state.missions:
        who = f" by {', '.join(mission.completed_by)}" if mission.completed_by else ""
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


def _reject_excess_actions(
    store: Store,
    match_id: str,
    log: MatchLog,
    team_id: str,
    turn: int,
    declared: int,
    allowed: int,
) -> None:
    """The durable, log-verifiable half of the mode/handicap enforcement
    (issue #29): an ``orders_capped`` OBSERVATION event appended straight to
    the store, bypassing ``resolve_turn`` entirely — a refused order set
    never reaches staging or the tick, so there is nothing for the engine to
    fold. Same bypass pattern as ``league.harness``'s own ``seat_latency``
    events: harness/CLI-side instrumentation, not a declared move."""
    event = Event(
        turn=turn,
        seq=len(log.events),
        kind="orders_capped",
        data={"team_id": team_id, "declared": declared, "allowed": allowed},
    )
    store.append_events(match_id, (event,))


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
    # Mode/handicap fairness (issue #29): a solo/handicapped team's declared
    # action cap is enforced HERE, at the CLI/engine boundary where orders are
    # staged — not only in the harness's command-driver wrapper, which a raw
    # `match act` call bypasses entirely. Refuse loudly (never silently
    # truncate) so a caller learns immediately, and record the refusal
    # durably in the log whenever an --apply'd attempt actually trips it.
    cap = log.max_actions.get(args.team)
    declared_actions = orders.get("actions") or []
    if cap is not None and len(declared_actions) > cap:
        if args.apply:
            _reject_excess_actions(
                store, args.match_id, log, args.team, state.turn + 1, len(declared_actions), cap
            )
        raise CliError(
            code=EXIT_USER_ERROR,
            message=(
                f"team {args.team!r} declared {len(declared_actions)} action(s) but this "
                f"match caps it to {cap} (mode/handicap profile)"
            ),
            remediation=(
                f"resubmit with at most {cap} action(s); see 'league match show "
                f"{args.match_id} --json' for the recorded max_actions profile"
            ),
        )
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


# Tempo: the third scored axis (plan task t5, spec c4/h4). Substrate is
# CALLER-DECLARED (a config/CLI flag), never guessed from timing —
# ``--substrate <team>=<name>`` maps a team to a calibration substrate so the
# read-time conversion (league.engine.tempo.score_tempo) can normalize its raw
# wall-clock against that substrate's baseline. Omit it and a team's tempo falls
# back to an identity conversion with a loud caveat — never a silent claim.


def _substrates_from_args(args: argparse.Namespace, team_ids: list[str]) -> dict[str, str]:
    substrates: dict[str, str] = {}
    for spec in getattr(args, "substrate", None) or ():
        team_id, sep, name = spec.partition("=")
        if not sep or not team_id or not name:
            raise CliError(
                code=EXIT_USER_ERROR,
                message=f"bad --substrate {spec!r}",
                remediation="use --substrate <team-id>=<substrate-name> (e.g. blue=cloud)",
            )
        if team_id not in team_ids:
            raise CliError(
                code=EXIT_USER_ERROR,
                message=f"--substrate references team {team_id!r}, not one of this match's teams",
                remediation=f"teams here: {', '.join(team_ids) or 'none'}",
            )
        substrates[team_id] = name
    return substrates


def _tempo_line(payload: dict[str, Any]) -> str:
    """One team's tempo, RAW ALWAYS BESIDE CONVERTED (the h4 honesty condition).

    A converted tempo score is never printed without the raw median next to it;
    a team with no latency data says so instead of inventing a number.
    """
    raw = payload.get("raw")
    if raw is None:
        return "tempo — (no latency data)"
    converted = payload["converted"]
    raw_str = f"median {raw['median_ms']}ms, p95 {raw['p95_ms']}ms"
    if converted["substrate_known"]:
        return (
            f"tempo {converted['tempo_score']} "
            f"[{raw_str}; {converted['substrate']} baseline "
            f"{converted['baseline_ms']}ms, ratio {converted['ratio']}]"
        )
    return (
        f"tempo {converted['tempo_score']} "
        f"[unnormalized — {raw_str}; substrate undeclared/unknown, not substrate-fair]"
    )


# Per-unit role-purpose scorecards (plan task t6, spec c6/c10/c15/h13): a NEW
# axis beside the team-level outcome/cooperation/tempo, never merged into any
# of them. ``grade_units``/``cgrade_units`` (plan tasks t1/t2) each return
# their own lane-native shape — the two shapes below normalize BOTH into one
# common presentation shape (same keys, same MVP/LVP flag convention) so a
# caller reading ``report["units"]`` never has to branch on which lane a match
# came from. Only the *names* of the purposes differ per lane (grid: economy/
# control/recon/coordination; continuous: race_hold/economy/eyes) — the
# engine's per-unit grade/breakdown math is untouched, this is presentation
# only. Boundary (spec: no ranking/ELO surface anywhere): this section names a
# MATCH's MVP/LVP only; nothing here reads or writes another match's data, and
# no aggregation across the ``units`` dicts of different matches ever happens.


def _units_section(
    *,
    match_id: str,
    purposes: tuple[str, ...],
    units: dict[str, dict[str, Any]],
    mvp: dict[str, Any] | None,
    lvp: dict[str, Any] | None,
) -> dict[str, Any]:
    mvp_id = mvp["unit_id"] if mvp else None
    lvp_id = lvp["unit_id"] if lvp else None
    return {
        "match_id": match_id,
        "purposes": list(purposes),
        "units": {
            unit_id: {**entry, "mvp": unit_id == mvp_id, "lvp": unit_id == lvp_id}
            for unit_id, entry in units.items()
        },
        "mvp": mvp,
        "lvp": lvp,
    }


def _grid_units_section(log: MatchLog) -> dict[str, Any]:
    """The grid lane's units section — ``grade_units`` (league.engine.grades,
    plan t1) verbatim, normalized to the shared presentation shape."""
    report = grade_units(log)
    units = {
        unit_id: {
            "team_id": entry["team_id"],
            "role": entry["role"],
            "home_purpose": entry["home_purpose"],
            "grade": entry["grade"],
            "breakdown": dict(entry["breakdown"]),
        }
        for unit_id, entry in report["units"].items()
    }
    return _units_section(
        match_id=report["match_id"],
        purposes=tuple(report["purposes"]),
        units=units,
        mvp=report["mvp"],
        lvp=report["lvp"],
    )


def _continuous_units_section(clog: CMatchLog) -> dict[str, Any]:
    """The continuous lane's units section — ``cgrade_units`` (league.engine.
    continuous.grades, plan t2) verbatim, normalized to the shared shape.

    ``cgrade_units`` raises ``ValueError`` for a match with no units at all
    (a malformed/empty roster) — turned into a clean ``CliError`` here rather
    than let it become the top-level dispatcher's generic "unexpected: ..."
    wrapper, per the CLI's own error contract.
    """
    try:
        report = cgrade_units(clog)
    except ValueError as err:
        raise CliError(
            code=EXIT_USER_ERROR,
            message=f"cannot grade match {clog.initial_state.match_id!r}: {err}",
            remediation="a match needs at least one unit on its roster to be graded",
        ) from err
    units: dict[str, dict[str, Any]] = {}
    for unit in report["units"]:
        home_purpose = next(
            (purpose for purpose, entry in unit["purposes"].items() if entry["on_role"]), None
        )
        units[unit["unit_id"]] = {
            "team_id": unit["team_id"],
            "role": unit["role"],
            "home_purpose": home_purpose,
            "grade": unit["grade"],
            "breakdown": {purpose: entry["points"] for purpose, entry in unit["purposes"].items()},
        }
    return _units_section(
        match_id=report["match_id"],
        purposes=CONTINUOUS_GRADE_PURPOSES,
        units=units,
        mvp=report["mvp"],
        lvp=report["lvp"],
    )


def _render_units_lines(units_section: dict[str, Any]) -> list[str]:
    """A readable scorecard: units ranked by grade (ties broken the same
    canonical ``(team_id, unit_id)`` way ``grade_units``/``cgrade_units`` break
    their own MVP/LVP ties), MVP/LVP marked, every purpose's contribution
    shown."""
    lines = ["units (role-purpose scorecard):"]
    ordered = sorted(
        units_section["units"].items(),
        key=lambda kv: (-kv[1]["grade"], kv[1]["team_id"], kv[0]),
    )
    if not ordered:
        lines.append("  (no units to grade)")
        return lines
    for unit_id, entry in ordered:
        tag = " [MVP]" if entry["mvp"] else " [LVP]" if entry["lvp"] else ""
        breakdown = ", ".join(
            f"{purpose} {points}" for purpose, points in entry["breakdown"].items()
        )
        lines.append(
            f"  {unit_id} ({entry['team_id']}, {entry['role']}) grade {entry['grade']}{tag}"
            f" — {breakdown}"
        )
    return lines


def cmd_match_score(args: argparse.Namespace) -> int:
    """Outcome + cooperation + tempo (grid) or outcome (continuous), plus the
    per-unit role-purpose scorecard both lanes share (plan task t6).

    Routing mirrors ``cmd_match_replay`` exactly (plan C7-t9's sniff-first
    discipline, spec c12): the log's OWN header shape is authoritative
    (``clock``/no ``grid_width`` -> continuous); the ``CONTINUOUS_ID_PREFIX``
    naming convention only picks the error voice when there is no log on disk
    to sniff. A grid match is byte-identical to before this task except for
    the additive ``units`` key — team axes (outcome/cooperation/tempo) are
    computed by the same untouched calls they always were.
    """
    json_mode = bool(getattr(args, "json", False))
    store = Store()
    path = store.log_path(args.match_id)
    if path.is_file():
        route_continuous = _sniff_continuous_log(path.read_text(encoding="utf-8"))
    else:
        route_continuous = args.match_id.startswith(CONTINUOUS_ID_PREFIX)

    if route_continuous:
        return _cmd_match_score_continuous(args, json_mode)

    log = _load(store, args.match_id)
    report = score_match(log, version=getattr(args, "cooperation_version", "v0"))
    # Tempo is a THIRD axis, computed at read time and published BESIDE outcome
    # and cooperation — never merged into either (spec c4/h4).
    substrates = _substrates_from_args(args, list(report["outcome"]))
    report["tempo"] = score_tempo(log, substrates=substrates)
    # The per-unit scorecard is a FOURTH axis, beside — never inside — the
    # three above: it is computed independently, from the same log, by a
    # module that never imports scoring.py/tempo.py (AST-enforced in
    # tests/test_grades.py), so it can only ever sit next to team scores.
    report["units"] = _grid_units_section(log)
    if json_mode:
        emit_result(report, json_mode=True)
        return 0
    lines = [f"{report['match_id']}: winner {report['winner'] or '—'}"]
    for team_id, outcome in report["outcome"].items():
        coop = report["cooperation"][team_id]
        lines.append(
            f"  {team_id}: outcome {outcome['total']} "
            f"(missions {outcome['missions']}, control {outcome['control']}, "
            f"resources {outcome['resources']}), cooperation {coop['score']}/100, "
            f"{_tempo_line(report['tempo'][team_id])}"
        )
    lines.append("")
    lines.extend(_render_units_lines(report["units"]))
    emit_result("\n".join(lines), json_mode=False)
    return 0


def _cmd_match_score_continuous(args: argparse.Namespace, json_mode: bool) -> int:
    """The continuous lane's score path (plan task t6): outcome facts exactly
    as the continuous engine already computes them today (``outcome_points``,
    ``status``, ``winner`` — the same facts ``build_continuous_replay_data``'s
    own ``outcome`` block surfaces), plus the same-shaped ``units`` scorecard
    the grid lane carries. There is no continuous cooperation/tempo axis yet
    (out of this task's scope) — only outcome + units.
    """
    clog = _load_continuous(Store(), args.match_id)
    initial = clog.initial_state
    final = clog.final_state()
    report: dict[str, Any] = {
        "match_id": initial.match_id,
        "scenario_id": initial.scenario_id,
        "mode": initial.mode,
        "status": final.status,
        "winner": final.winner,
        "outcome": continuous_outcome_points(final),
    }
    report["units"] = _continuous_units_section(clog)
    if json_mode:
        emit_result(report, json_mode=True)
        return 0
    lines = [
        f"{report['match_id']}: winner {report['winner'] or '—'} ({report['status']})",
    ]
    for team_id, points in report["outcome"].items():
        lines.append(f"  {team_id}: outcome {points}")
    lines.append("")
    lines.extend(_render_units_lines(report["units"]))
    emit_result("\n".join(lines), json_mode=False)
    return 0


def cmd_match_probe(args: argparse.Namespace) -> int:
    """Span-of-control: how many subagents a team's mind actually fielded, how
    well their orders landed, and whether guidance steered behavior — computed
    from the log alone (``league.engine.probe``, plan task t7). See ``league
    explain match probe`` for the evidence hierarchy and formula.
    """
    json_mode = bool(getattr(args, "json", False))
    store = Store()
    _reject_continuous_log(store, args.match_id, "probe")
    log = _load(store, args.match_id)
    report = probe_match(log)
    if json_mode:
        emit_result(report, json_mode=True)
        return 0
    lines = [f"{report['match_id']}: span-of-control probe ({report['version']})"]
    for team_id, team in report["teams"].items():
        commanders = f", commanders {', '.join(team['commanders'])}" if team["commanders"] else ""
        lines.append(
            f"  {team_id}: span {team['span']}/{team['roster_size']} ({team['evidence']} evidence)"
            f"{commanders}, score {team['score']}/100 "
            f"(span_coverage {team['signals']['span_coverage']}, "
            f"realization {team['signals']['realization_rate']}, "
            f"guidance {team['signals']['guidance_linkage']})"
        )
    emit_result("\n".join(lines), json_mode=False)
    return 0


def cmd_match_brief(args: argparse.Namespace) -> int:
    """The agents' face: markdown (or facts JSON) served from the faces registry.

    The verb is a thin adapter — it resolves the ``("match", "brief")`` tool in
    the agentfront registry (``league.faces.faces_app``) and renders whatever
    that one declaration returns, so the markdown and JSON projections cannot
    drift (face-agreement tests in ``tests/test_faces.py`` prove it).
    """
    json_mode = bool(getattr(args, "json", False))
    entry = faces_app().get_by_path(("match", "brief"))
    try:
        facts = entry.func(args.match_id, args.team or "")
    except FileNotFoundError as err:
        raise CliError(
            code=EXIT_USER_ERROR,
            message=str(err),
            remediation="run 'league match list' to see matches",
        ) from err
    except ValueError as err:
        raise CliError(
            code=EXIT_USER_ERROR,
            message=str(err),
            remediation="pass --team <id> for a team in this match, or omit --team",
        ) from err
    if json_mode:
        emit_result(facts, json_mode=True)
    else:
        emit_result(render_brief_markdown(facts), json_mode=False)
    return 0


def cmd_match_replay(args: argparse.Namespace) -> int:
    """Self-contained HTML replay — routed to the right engine lane.

    Detection (plan C7-t9): the log's OWN header shape is the authoritative
    signal (``clock``/``width`` for
    :class:`~league.engine.continuous.state.CMatchState` vs ``turn``/
    ``grid_width`` for the grid's ``MatchState``) — a grid match that merely
    NAMED itself ``c-…`` still replays as grid. The
    :data:`CONTINUOUS_ID_PREFIX` naming discipline only chooses which lane's
    not-found error speaks when there is no log on disk to sniff. No new verb:
    a grid log falls through to the untouched grid path below, byte-identical
    to before this routing existed.
    """
    match_id = args.match_id
    json_mode = bool(getattr(args, "json", False))

    path = Store().log_path(match_id)
    if path.is_file():
        route_continuous = _sniff_continuous_log(path.read_text(encoding="utf-8"))
    else:
        route_continuous = match_id.startswith(CONTINUOUS_ID_PREFIX)

    if route_continuous:
        clog = _load_continuous(Store(), match_id)
        if json_mode:
            emit_result(build_continuous_replay_data(clog), json_mode=True)
        else:
            emit_result(render_chtml(clog), json_mode=False)
        return 0

    log = _load(Store(), match_id)
    if json_mode:
        emit_result(build_replay_data(log), json_mode=True)
    else:
        emit_result(render_html(log), json_mode=False)
    return 0


# -- video export: one command, offline, from the log alone (plan task t6, --
# -- spec c7/h7). The primary path is a pure-stdlib animated GIF (never --
# -- installs anything, always works); ffmpeg for --format mp4 is optional --
# -- and lives ENTIRELY in this CLI function — league/replay/video.py never --
# -- shells out, so the toolchain risk (parked r1) stays isolated here. --


def _record_provenance(args: argparse.Namespace) -> str:
    """The exact command, reconstructed canonically from parsed args (not raw
    ``sys.argv``) so two equivalent invocations embed identical provenance —
    load-bearing for the reproducibility merge gate."""
    return (
        f"league match record {args.match_id} --out {args.out} "
        f"--format {args.format} --theme {args.theme} --scale {args.scale} "
        f"--fps {args.fps} --tween {args.tween}"
    )


def _frame_delay_cs(fps: int) -> int:
    return max(2, round(100 / fps))


def _repeat_count(delay_cs: int, output_fps: int) -> int:
    """How many constant-rate output frames reproduce one GIF-style hold time."""
    return max(1, round(delay_cs * output_fps / 100))


def _mp4_turn_samples(
    video, data, *, output_fps: int, tween: int
) -> tuple[dict[int, tuple[int, int]], int]:
    """Map every played turn to ``(start_sample, interval_samples)`` on the
    MP4's own timeline, plus the total held-frame count.

    Derived from the exact held-frame counts the raw video pipe carries — the
    frame sequence is the title card, then per turn one board frame followed
    by its ``tween`` sub-frames (the final turn has none), then the closing
    card — so an event motif lands at the sample where its turn's frame
    appears on screen, to the same rounding ``samples_for_frames`` uses."""
    cum = [0]
    for frame in video.frames:
        cum.append(cum[-1] + _repeat_count(frame.delay_cs, output_fps))
    turns = [f["turn"] for f in data["frames"][1:]]
    out: dict[int, tuple[int, int]] = {}
    last = len(turns) - 1
    for i, turn in enumerate(turns):
        idx = 1 + i * (tween + 1)
        nxt = idx + (tween + 1) if i < last else idx + 1
        start = samples_for_frames(cum[idx], output_fps)
        out[turn] = (start, samples_for_frames(cum[nxt], output_fps) - start)
    return out, cum[-1]


def _soundtrack_wav(video, data, *, fps: int, tween: int) -> bytes:
    """The exact WAV the MP4 carries: the match's seeded ambient bed plus the
    event-sound layer (cycle-8 audio-events amendment) — every notable event's
    motif rendered at its turn's video time, from the same canonical table the
    HTML replay plays live (``league.replay.audio.EVENT_SOUND``). Same log +
    same settings -> byte-identical output."""
    output_fps = fps * (tween + 1)
    turn_samples, held_frames = _mp4_turn_samples(video, data, output_fps=output_fps, tween=tween)
    schedule = motif_schedule(
        data["events_by_turn"],
        [t["id"] for t in data["teams"]],
        {u["id"]: u["team"] for u in data["frames"][0]["units"]},
        turn_samples,
    )
    return synthesize_wav(
        data["match_id"],
        data["seed"],
        num_samples=samples_for_frames(held_frames, output_fps),
        motifs=schedule,
    )


def _render_mp4(video, data, *, fps: int, tween: int, out_path: Path, provenance: str) -> None:
    """Pipe the same raw frames ffmpeg's way. The only subprocess call in the
    whole video-export feature — deliberately kept out of league/replay/video.py
    (library code stays subprocess-free and trivially testable).

    The container runs at ``fps * (tween + 1)`` so each tween sub-frame maps to
    ~one output frame and a full turn still spans 1/fps seconds — at plain
    ``fps``, every sub-frame would expand to a whole turn interval and the video
    would play ``tween + 1`` times slower than asked.

    The MP4 also carries the match's soundtrack (cycle-8 t9 + the audio-events
    amendment): a WAV synthesized offline from the same ``match_id|seed``
    identity the HTML replay's live score derives its seed from — the same
    piece of music — with the event-sound layer's motifs rendered at each
    event's video time, sized to the video's exact held-frame duration and
    muxed as a second input (``-c:a aac -shortest``). The GIF path never comes
    here: GIF89a has no audio channel, so its silence is format truth, not a
    missing feature."""
    output_fps = fps * (tween + 1)
    raw = bytearray()
    for frame in video.frames:
        rgb = indices_to_rgb(frame.indices, video.palette)
        raw += rgb * _repeat_count(frame.delay_cs, output_fps)
    wav_bytes = _soundtrack_wav(video, data, fps=fps, tween=tween)
    with tempfile.TemporaryDirectory(prefix="league-record-") as tmp_dir:
        wav_path = Path(tmp_dir) / "soundtrack.wav"
        wav_path.write_bytes(wav_bytes)
        try:
            subprocess.run(  # nosec B603 B607
                [
                    "ffmpeg",
                    "-y",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-f",
                    "rawvideo",
                    "-pixel_format",
                    "rgb24",
                    "-video_size",
                    f"{video.width}x{video.height}",
                    "-framerate",
                    str(output_fps),
                    "-i",
                    "-",
                    "-i",
                    str(wav_path),
                    "-pix_fmt",
                    "yuv420p",
                    "-c:a",
                    "aac",
                    "-shortest",
                    "-metadata",
                    f"comment={provenance}",
                    str(out_path),
                ],
                input=bytes(raw),
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError as err:
            raise CliError(
                code=EXIT_ENV_ERROR,
                message=f"ffmpeg failed: {err.stderr.decode(errors='replace')[:300]}",
                remediation="drop --format (defaults to gif, the always-works path)",
            ) from err


def cmd_match_record(args: argparse.Namespace) -> int:
    """Render a committed match log into a shareable video artifact, offline —
    no screen capture, no live session, no network (spec c7/h7)."""
    json_mode = bool(getattr(args, "json", False))
    if not MIN_SCALE <= args.scale <= MAX_SCALE:
        raise CliError(
            code=EXIT_USER_ERROR,
            message=f"--scale {args.scale} out of range",
            remediation=f"pick a cell size in {MIN_SCALE}..{MAX_SCALE} (pixels per grid cell)",
        )
    if not MIN_FPS <= args.fps <= MAX_FPS:
        raise CliError(
            code=EXIT_USER_ERROR,
            message=f"--fps {args.fps} out of range",
            remediation=f"pick a frame rate in {MIN_FPS}..{MAX_FPS}",
        )
    if not MIN_TWEEN <= args.tween <= MAX_TWEEN:
        raise CliError(
            code=EXIT_USER_ERROR,
            message=f"--tween {args.tween} out of range",
            remediation=(
                f"pick a tween count in {MIN_TWEEN}..{MAX_TWEEN} "
                "(interpolated frames inserted between turns; 0 disables)"
            ),
        )
    turn_delay_cs = _frame_delay_cs(args.fps)
    if turn_delay_cs < 2 * (args.tween + 1):
        raise CliError(
            code=EXIT_USER_ERROR,
            message=(
                f"--tween {args.tween} is too high for --fps {args.fps}: a turn holds "
                f"{turn_delay_cs}cs but its {args.tween + 1} sub-frames need >= 2cs each"
            ),
            remediation=(
                f"lower --tween to <= {turn_delay_cs // 2 - 1} at this frame rate, "
                "or lower --fps to give each turn a longer hold"
            ),
        )
    log = _load(Store(), args.match_id)
    provenance = _record_provenance(args)
    data = build_replay_data(log)
    video = build_video_frames(
        data,
        cell_px=args.scale,
        turn_delay_cs=turn_delay_cs,
        theme=args.theme,
        tween=args.tween,
    )
    out_path = Path(args.out)

    if args.format == "mp4":
        if shutil.which("ffmpeg") is None:
            raise CliError(
                code=EXIT_ENV_ERROR,
                message="--format mp4 requires ffmpeg on PATH, and none was found",
                remediation=(
                    "install ffmpeg, or drop --format to use the always-works GIF fallback "
                    "(the default)"
                ),
            )
        _render_mp4(
            video,
            data,
            fps=args.fps,
            tween=args.tween,
            out_path=out_path,
            provenance=provenance,
        )
        size = out_path.stat().st_size
    else:
        gif_bytes = render_gif(
            log,
            scale=args.scale,
            fps=args.fps,
            theme=args.theme,
            tween=args.tween,
            provenance=provenance,
        )
        out_path.write_bytes(gif_bytes)
        size = len(gif_bytes)

    payload = {
        "match_id": args.match_id,
        "out": str(out_path),
        "format": args.format,
        "theme": args.theme,
        "scale": args.scale,
        "fps": args.fps,
        "tween": args.tween,
        "frames": len(video.frames),
        "bytes": size,
        "provenance": provenance,
    }
    if json_mode:
        emit_result(payload, json_mode=True)
    else:
        emit_result(
            f"wrote {out_path} ({args.format}, {len(video.frames)} frames, {size} bytes) "
            f"from {args.match_id} — provenance embedded",
            json_mode=False,
        )
    return 0


def _color_enabled(args: argparse.Namespace) -> bool:
    """``--no-color`` and the ``NO_COLOR`` convention both disable ANSI color."""
    if getattr(args, "no_color", False):
        return False
    if os.environ.get("NO_COLOR"):
        return False
    return True


def cmd_match_tui(args: argparse.Namespace) -> int:
    """Replay-stepping terminal view: ground truth, or a team's fogged knowledge.

    ``--frame N`` (or a non-tty stdin/stdout) renders one frame to stdout and
    exits — the path the tests and pipes drive. With both stdin and stdout as
    ttys and no ``--frame``, it launches the curses shell instead (arrow keys
    step frames, Tab toggles the team).
    """
    store = Store()
    log = _load(store, args.match_id)
    data = build_replay_data(log)
    team_ids = {t.id for t in log.initial_state.teams}

    knowledge = None
    if args.team is not None:
        if args.team not in team_ids:
            raise CliError(
                code=EXIT_USER_ERROR,
                message=f"team {args.team!r} is not in match {args.match_id!r}",
                remediation=f"teams here: {', '.join(sorted(team_ids)) or 'none'}",
            )
        scenario = get_scenario(log.initial_state.scenario_id)
        knowledge = knowledge_by_turn(log, scenario)

    if args.frame is None and sys.stdin.isatty() and sys.stdout.isatty():
        run_interactive_shell(data, knowledge, initial_team=args.team)
        return 0

    total = len(data["frames"])
    frame_index = args.frame if args.frame is not None else total - 1
    resolved = frame_index + total if frame_index < 0 else frame_index
    if not 0 <= resolved < total:
        raise CliError(
            code=EXIT_USER_ERROR,
            message=f"--frame {frame_index} out of range for {args.match_id!r} (0..{total - 1})",
            remediation=f"pick a frame in 0..{total - 1} (or omit --frame for the last one)",
        )
    lines = render_frame(
        data, resolved, team=args.team, knowledge=knowledge, color=_color_enabled(args)
    )
    emit_result("\n".join(lines), json_mode=False)
    return 0


def cmd_match_rematch(args: argparse.Namespace) -> int:
    """Fair comparison by construction: identical scenario + seed, new roster."""
    json_mode = bool(getattr(args, "json", False))
    store = Store()
    log = _load(store, args.match_id)
    original = log.initial_state
    scenario = get_scenario(original.scenario_id)

    if args.team:
        teams = []
        for team_id in args.team:
            try:
                teams.append(store.team_slots(team_id))
            except FileNotFoundError as err:
                raise CliError(
                    code=EXIT_USER_ERROR,
                    message=str(err),
                    remediation="register it first: league team register ... --apply",
                ) from err
    elif args.swap:
        teams = [(t.id, t.name, t.agents) for t in reversed(original.teams)]
    else:
        raise CliError(
            code=EXIT_USER_ERROR,
            message="rematch needs --swap or an explicit --team roster",
            remediation="--swap flips sides; --team <id> (repeatable) fields new rosters",
        )

    match_id = _safe_id(
        args.id or f"{args.match_id}-r{len(store.list_matches()) + 1:02d}", "match id"
    )
    try:
        initial = instantiate(
            scenario,
            match_id=match_id,
            seed=original.seed,
            mode=original.mode,
            teams=teams,
        )
    except ValueError as err:
        raise CliError(
            code=EXIT_USER_ERROR,
            message=str(err),
            remediation="rosters must match the scenario's roles",
        ) from err
    _, events = start_match(initial)

    payload = {
        "match_id": match_id,
        "rematch_of": args.match_id,
        "scenario": original.scenario_id,
        "mode": original.mode,
        "seed": original.seed,
        "teams": [t[0] for t in teams],
        "applied": bool(args.apply),
    }
    if args.apply:
        log_new = MatchLog(initial_state=initial, events=events)
        try:
            path = store.create_match(log_new)
        except FileExistsError as err:
            raise CliError(
                code=EXIT_USER_ERROR, message=str(err), remediation="pass a fresh --id"
            ) from err
        payload["log"] = str(path)
    if json_mode:
        emit_result(payload, json_mode=True)
    else:
        verb = "created rematch" if args.apply else "would create rematch (dry-run; add --apply)"
        emit_result(
            f"{verb}: {match_id} of {args.match_id} — same scenario+seed "
            f"({original.scenario_id}, seed {original.seed}), teams: "
            f"{', '.join(payload['teams'])}",
            json_mode=False,
        )
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
    new.add_argument(
        "--driver",
        action="append",
        metavar="TEAM:KIND",
        help="Declared driver residency for a team — bot/stateless/resident, or "
        "bot-file:<strategy-name> to record which committed bots/<name>.py "
        "strategy plays it (fairness metadata only, recorded in the match log; "
        "repeatable).",
    )
    new.add_argument(
        "--map-read",
        action="append",
        metavar="TEAM:full|fog",
        help="Orchestrator mode's declared map-read capability for a team under "
        "fog — 'full' (its master reads the whole board) or 'fog' (default: "
        "same fogged view as everyone) — a declared information-asymmetry "
        "rule, never a hidden privilege (spec c4/h3; repeatable).",
    )
    new.add_argument(
        "--unit-comms",
        action="append",
        metavar="TEAM:on|off",
        help="Orchestrator mode's declared unit-to-unit comms flag for a team — "
        "'on' lets ground units message each other directly; 'off' (the "
        "mode's default) means master-mediated only — a recorded fairness "
        "axis (spec c6/h5; repeatable).",
    )
    new.add_argument(
        "--max-actions",
        action="append",
        metavar="TEAM:N",
        help="Mode/handicap profile (issue #29): cap how many unit actions a "
        "team may stage in one 'match act' call — e.g. the solo preset's "
        "one-action-per-turn handicap. Recorded in the match log header and "
        "enforced by 'match act' with a structured error; a team absent from "
        "this map is uncapped (repeatable).",
    )
    new.add_argument("--apply", action="store_true", help="Actually create (default: dry-run).")
    new.add_argument("--json", action="store_true", help="Emit structured JSON.")
    new.set_defaults(func=cmd_match_new)

    ls = noun_sub.add_parser("list", help="List matches.")
    ls.add_argument("--json", action="store_true", help="Emit structured JSON.")
    ls.set_defaults(func=cmd_match_list)

    show = noun_sub.add_parser("show", help="Show a match's current state.")
    show.add_argument("match_id", help="Match id.")
    show.add_argument(
        "--team", help="Scope legal_actions/last_turn_rejections (and, with --fog) to this team."
    )
    show.add_argument(
        "--fog",
        action="store_true",
        help="Requires --team: replace 'state' with that team's fog-of-war "
        "knowledge projection and add 'knowledge' (spec c5/h4).",
    )
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

    score = noun_sub.add_parser(
        "score",
        help="Outcome + cooperation + tempo scores, plus a per-unit MVP/LVP scorecard, "
        "from the log (grid or continuous, detected automatically).",
    )
    score.add_argument("match_id", help="Match id.")
    score.add_argument("--json", action="store_true", help="Emit structured JSON.")
    score.add_argument(
        "--cooperation-version",
        choices=("v0", "v1"),
        default="v0",
        help="Cooperation metric: v0 (cadence, default) or v1 (content-aware).",
    )
    score.add_argument(
        "--substrate",
        action="append",
        metavar="TEAM=NAME",
        help="Declare a team's substrate for tempo conversion — e.g. --substrate "
        "blue=cloud (known: cloud/local/bot; unknown/undeclared falls back to an "
        "identity conversion, raw latency shown, not substrate-normalized; "
        "repeatable). Raw latency is ALWAYS printed beside the converted score. "
        "See docs/tempo-methodology.md for the calibration/conversion methodology "
        "and its own limits.",
    )
    score.set_defaults(func=cmd_match_score)

    probe = noun_sub.add_parser(
        "probe", help="Span-of-control probe: subagents fielded + command quality from the log."
    )
    probe.add_argument("match_id", help="Match id.")
    probe.add_argument("--json", action="store_true", help="Emit structured JSON.")
    probe.set_defaults(func=cmd_match_probe)

    brief = noun_sub.add_parser(
        "brief", help="Markdown briefing of the match — the agents' face (--team for fog)."
    )
    brief.add_argument("match_id", help="Match id.")
    brief.add_argument("--team", help="Render the fogged view: only what this team knows.")
    brief.add_argument(
        "--json", action="store_true", help="The same facts as JSON instead of markdown."
    )
    brief.set_defaults(func=cmd_match_brief)

    replay = noun_sub.add_parser("replay", help="Self-contained HTML replay on stdout.")
    replay.add_argument("match_id", help="Match id.")
    replay.add_argument("--json", action="store_true", help="Replay data as JSON instead of HTML.")
    replay.set_defaults(func=cmd_match_replay)

    record = noun_sub.add_parser(
        "record",
        help="Render the match log to a shareable GIF/MP4 video file, offline.",
    )
    record.add_argument("match_id", help="Match id.")
    record.add_argument("--out", required=True, help="Output file path (e.g. match.gif).")
    record.add_argument(
        "--format",
        choices=("gif", "mp4"),
        default="gif",
        help="gif (default): pure-stdlib, always works, no install — and silent, because "
        "GIF has no audio channel. mp4: pipes the same frames through ffmpeg plus the "
        "match's deterministic ambient soundtrack (the HTML replay's own seeded score, "
        "synthesized offline) — requires ffmpeg on PATH, else errors naming the gif "
        "fallback.",
    )
    record.add_argument(
        "--theme",
        choices=("light", "dark"),
        default=DEFAULT_THEME,
        help="Color theme, sharing the HTML replay's validated palette: light "
        f"(default {DEFAULT_THEME}, Anthropic cream) or dark (Culture black-green).",
    )
    record.add_argument(
        "--scale",
        type=int,
        default=DEFAULT_SCALE,
        help=f"Pixels per grid cell ({MIN_SCALE}..{MAX_SCALE}, default {DEFAULT_SCALE}).",
    )
    record.add_argument(
        "--fps",
        type=int,
        default=DEFAULT_FPS,
        help=f"Turn frames per second ({MIN_FPS}..{MAX_FPS}, default {DEFAULT_FPS}); the "
        "opening/closing cards hold several times longer, automatically.",
    )
    record.add_argument(
        "--tween",
        type=int,
        default=DEFAULT_TWEEN,
        help=f"Interpolated frames inserted between each pair of turns so movement "
        f"flows instead of teleporting ({MIN_TWEEN}..{MAX_TWEEN}, default {DEFAULT_TWEEN}; "
        "0 disables). Each sub-frame holds >= 2cs, so a high --fps caps how many fit "
        "one turn.",
    )
    record.add_argument("--json", action="store_true", help="Emit structured JSON.")
    record.set_defaults(func=cmd_match_record)

    tui = noun_sub.add_parser(
        "tui", help="Replay-stepping terminal view (ground truth or --team fog)."
    )
    tui.add_argument("match_id", help="Match id.")
    tui.add_argument(
        "--frame",
        type=int,
        help="Frame index to render non-interactively (default: last frame; "
        "negative counts from the end).",
    )
    tui.add_argument("--team", help="Render this team's knowledge instead of ground truth.")
    tui.add_argument(
        "--no-color", action="store_true", help="Disable ANSI color (also honors NO_COLOR)."
    )
    tui.set_defaults(func=cmd_match_tui)

    rematch = noun_sub.add_parser(
        "rematch", help="Same scenario + seed with a new roster (dry-run by default)."
    )
    rematch.add_argument("match_id", help="Match id to rematch.")
    rematch.add_argument("--swap", action="store_true", help="Flip the original sides.")
    rematch.add_argument("--team", action="append", help="Registered team id; repeatable.")
    rematch.add_argument("--id", help="New match id (default: <original>-rNN).")
    rematch.add_argument("--apply", action="store_true", help="Actually create.")
    rematch.add_argument("--json", action="store_true", help="Emit structured JSON.")
    rematch.set_defaults(func=cmd_match_rematch)
