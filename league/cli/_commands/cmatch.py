"""``league cmatch`` -- the continuous lane's external-driver CLI parity (issue #28).

The grid lane is driven externally today entirely through the public CLI loop
(``match new`` -> ``match show --json`` -> ``match act --orders-json --apply``
-> ``match tick --apply`` -> ``match score``) from a per-match working
directory -- no ``import league`` required. The continuous lane could not be
driven this way at all before this module: its only entry point was
``league.charness.run_cmatch``, an in-process, blocking library call that owns
the whole match and drives every seat synchronously in one Python process.

``cmatch`` closes that gap with five verbs mirroring the grid loop's shape,
adapted to the continuous lane's per-UNIT, per-decision-point contract
(``docs/continuous-contract.md``) rather than the grid's per-team, per-turn one:

* ``new``   -- create a continuous match, persisted to disk at clock 0 (the
  same ``.league/matches/<id>/log.jsonl`` store the grid uses).
* ``show``  -- the externally queryable "what is due right now": every
  currently-due decision point (idle unit) with its full briefing.
* ``act``   -- submit ONE unit's decision; persists it and advances the
  timeline only as far as resolution requires.
* ``tick``  -- resolve bot-driven due units via their configured drivers
  and/or park unanswered ones, advancing to the next due moment -- the verb
  an external harness calls when it has nothing to submit.
* ``run``   -- the packaged one-shot (what ``scripts/run_cmatch.py`` used to
  be the only way to reach): a real published verb now.

Determinism (the load-bearing property, ``docs/continuous-contract.md``):
state is always a pure fold of the log, and stepwise driving through
``new``/``act``/``tick`` produces logs BYTE-IDENTICAL to an equivalent single
``league.charness.run_cmatch`` call given the same decisions in the same
order -- see ``league.engine.continuous.resolve.advance_external`` (the
engine-level primitive this module is a thin CLI skin over) and
``tests/test_continuous_resolve.py``/``tests/test_cli_cmatch.py`` for the
parity proofs.

Scope this cycle: fog (``config["fog"]``) is fully supported by ``run``
(a straight pass-through to the already-fogged ``run_cmatch``) but NOT by the
stepwise ``new``/``show``/``act``/``tick`` loop -- ``new`` refuses a fogged
``--config`` with a clean, structured error naming ``run`` as the fogged
alternative. A ``command``/``resident`` (live-mind) team is driven externally
via ``act`` the same way a grid seat is; ``tick`` can only auto-resolve
``bot``/``bot-file`` teams (deterministic, in-process, no session to persist
across CLI calls) -- see ``tick``'s own docstring.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from league.charness import CHarnessError, build_briefing, make_cbot_chooser, make_cbot_file_chooser
from league.charness import run_cmatch as _run_cmatch
from league.cli._errors import EXIT_ENV_ERROR, EXIT_USER_ERROR, CliError
from league.cli._output import emit_result
from league.engine.continuous.events import CEvent, CMatchLog
from league.engine.continuous.legal import legal_actions_continuous, plan_action
from league.engine.continuous.resolve import NeedsExternalDecision, advance_external, due_decisions
from league.engine.continuous.scenario import get_cscenario, instantiate
from league.engine.continuous.state import CAgentSlot, CMatchState
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


# -- config parsing (shared by `new --config` and `run --config`) -----------
#
# Mirrors `league harness run`'s config loading, extended to accept an INLINE
# JSON string as well as a file path (`match act`'s `--orders-json` already
# sets that precedent for a flag that takes JSON directly) -- convenient for
# an external harness that builds a config in memory and would rather not
# round-trip it through a temp file.


def _parse_config_arg(value: str) -> dict[str, Any]:
    path = Path(value)
    try:
        is_file = path.is_file()
    except OSError:
        # An inline JSON blob can easily exceed a filesystem's max path/name
        # length (a long --config string is not a "path that happens not to
        # exist" -- it isn't a path at all); treat that the same as "not a
        # file" rather than letting a raw OSError escape as an opaque
        # "unexpected: ..." wrapper.
        is_file = False
    if is_file:
        raw = path.read_text(encoding="utf-8")
        source = f"config file {path}"
    else:
        raw = value
        source = "--config"
    try:
        config = json.loads(raw)
    except json.JSONDecodeError as err:
        raise CliError(
            code=EXIT_USER_ERROR,
            message=f"{source} is not valid JSON: {err}",
            remediation="see 'league explain cmatch' for the config shape",
        ) from err
    if not isinstance(config, dict):
        raise CliError(
            code=EXIT_USER_ERROR,
            message="cmatch config must be a JSON object",
            remediation='shape: {"match": {...}, "teams": [...], "fog": false}',
        )
    return config


def _cagent_from_dict(d: dict[str, Any]) -> CAgentSlot:
    return CAgentSlot(id=str(d["id"]), model=str(d.get("model", "")), role=str(d["role"]))


def _cagents_from_slots(agents: tuple) -> tuple[CAgentSlot, ...]:
    """Convert the grid's registered ``AgentSlot`` roster (``league team
    register`` is lane-agnostic -- id/model/role) into continuous
    ``CAgentSlot``s. Field-for-field identical shape; no data is lost."""
    return tuple(CAgentSlot(id=a.id, model=a.model, role=a.role) for a in agents)


# -- driver labels: self-reported header metadata, mirrors `match new`'s own
# -- `_driver_kinds_from_args` (league/cli/_commands/match.py) exactly, with
# -- one addition: `bot`/`bot-file:<name>` labels are what `cmatch tick`
# -- reconstructs an in-process chooser from later (the label IS the spec for
# -- those two kinds -- there is nothing else to store). `stateless`/
# -- `resident` stay pure self-reported metadata, precisely as in the grid: a
# -- live mind is driven externally via `act`, never invoked BY this CLI.

_CMATCH_DRIVER_KINDS = ("bot", "stateless", "resident")
_BOT_FILE_PREFIX = "bot-file:"


def _driver_label(spec: dict[str, Any]) -> str:
    kind = spec.get("type")
    if kind == "bot":
        return "bot"
    if kind == "bot-file":
        strategy = spec.get("strategy")
        if not strategy:
            raise CliError(
                code=EXIT_USER_ERROR,
                message="a 'bot-file' driver requires a 'strategy' name",
                remediation='{"type": "bot-file", "strategy": "<name>"} (bots/<name>.py)',
            )
        try:
            validate_id(str(strategy), what="bot strategy name")
        except ValueError as err:
            raise CliError(
                code=EXIT_USER_ERROR,
                message=f"bad bot-file strategy name {strategy!r}: {err}",
                remediation="strategy names become filenames under bots/",
            ) from err
        return f"{_BOT_FILE_PREFIX}{strategy}"
    if kind == "resident":
        return "resident"
    if kind == "command":
        residency = spec.get("residency", "stateless")
        if residency not in ("stateless", "resident"):
            raise CliError(
                code=EXIT_USER_ERROR,
                message=f"unknown residency {residency!r} for a command driver",
                remediation="expected 'stateless' or 'resident'",
            )
        return residency
    raise CliError(
        code=EXIT_USER_ERROR,
        message=f"unknown driver type {kind!r}",
        remediation="expected 'bot', 'bot-file', 'command' or 'resident'",
    )


def _driver_labels_from_args(args: argparse.Namespace, team_ids: list[str]) -> dict[str, str]:
    labels: dict[str, str] = {}
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
                    remediation="use --driver <team-id>:bot-file:<strategy-name>",
                ) from err
            labels[team_id] = kind
            continue
        if kind not in _CMATCH_DRIVER_KINDS:
            raise CliError(
                code=EXIT_USER_ERROR,
                message=f"unknown driver kind {kind!r} for team {team_id!r}",
                remediation=f"expected one of: {', '.join(_CMATCH_DRIVER_KINDS)}, "
                "or bot-file:<name>",
            )
        labels[team_id] = kind
    return labels


def _auto_match_id(store: Store, scenario_id: str, mode: str, seed: int) -> str:
    n = len(store.list_matches()) + 1
    return f"cm-{scenario_id}-{mode}-s{seed}-{n:03d}"


# -- reading a persisted continuous log ---------------------------------------


def _load_clog(store: Store, match_id: str) -> CMatchLog:
    path = store.log_path(match_id)
    if not path.is_file():
        raise CliError(
            code=EXIT_USER_ERROR,
            message=f"no match {match_id!r}",
            remediation="run 'league match list' to see matches, "
            "or 'league cmatch new' to create one",
        )
    try:
        return CMatchLog.from_jsonl(path.read_text(encoding="utf-8"))
    except (KeyError, ValueError) as err:
        raise CliError(
            code=EXIT_USER_ERROR,
            message=f"match {match_id!r} could not be read as a continuous (cmatch) log: {err}",
            remediation="cmatch verbs only read continuous-lane logs; use 'league match show' "
            "for a grid-lane match",
        ) from err


def _role_table_for(state: CMatchState):
    try:
        return get_cscenario(state.scenario_id).role_table
    except ValueError as err:
        raise CliError(
            code=EXIT_USER_ERROR,
            message=f"cannot resolve this match's scenario: {err}",
            remediation="the match's recorded scenario_id is not in the "
            "continuous scenario registry",
        ) from err


def _team_of(state: CMatchState, unit_id: str) -> str:
    for unit in state.units:
        if unit.id == unit_id:
            return unit.team_id
    raise CliError(
        code=EXIT_USER_ERROR,
        message=f"unknown unit {unit_id!r} in this match",
        remediation="check the unit id against 'league cmatch show <id> --json'",
    )


def _messages_from_log(clog: CMatchLog) -> list[dict[str, Any]]:
    """The running social record ``build_briefing`` expects: every
    ``message_sent`` observation in the log, in the order it was recorded.
    A cmatch-CLI-driven match never writes one this cycle (``act`` doesn't
    accept ``--message`` yet -- a documented follow-up), but a log produced by
    ``cmatch run``/``run_cmatch`` (bot or live minds) may carry plenty, and
    ``show`` must surface them exactly as a live mind would have seen them."""
    return [
        {"from": e.data["from"], "text": e.data["text"], "game_time": e.game_time}
        for e in clog.events
        if e.kind == "message_sent"
    ]


# -- overview -----------------------------------------------------------------


def cmd_cmatch_overview(args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json", False))
    data = {
        "noun": "cmatch",
        "description": (
            "The continuous lane's external-driver play loop: a mind is asked for "
            "ONE unit's action at a decision point (unit-idle), never a whole-team "
            "turn order -- see 'league explain cmatch' and docs/continuous-contract.md."
        ),
        "verbs": {
            "new": "create a continuous match from a scenario + teams/config, persisted "
            "at clock 0 (dry-run; --apply)",
            "show": "what is due right now: every idle unit's full briefing (--unit to scope)",
            "act": "submit ONE unit's decision; advances the timeline only as far as "
            "resolution requires (dry-run; --apply)",
            "tick": "resolve bot-driven due units automatically and/or park the rest "
            "(--timeout-park); the verb to call with nothing to submit (dry-run; --apply)",
            "run": "the packaged one-shot bot-vs-bot/live run (dry-run; --apply)",
        },
    }
    if json_mode:
        emit_result(data, json_mode=True)
    else:
        lines = ["league cmatch — the continuous lane's external-driver play loop", ""]
        lines += [f"  league cmatch {verb:<6} {desc}" for verb, desc in data["verbs"].items()]
        emit_result("\n".join(lines), json_mode=False)
    return 0


# -- new ------------------------------------------------------------------- #


def _teams_from_config(config: dict[str, Any]) -> tuple[list, dict[str, str]]:
    teams = []
    driver_kinds: dict[str, str] = {}
    for t in config.get("teams", []):
        if "id" not in t:
            raise CliError(
                code=EXIT_USER_ERROR,
                message="every entry in --config's 'teams' needs an 'id'",
                remediation='shape: {"id": "blue", "name": "...", "driver": {...}, '
                '"agents": [...]}',
            )
        team_id = str(t["id"])
        name = str(t.get("name", team_id))
        agents = tuple(_cagent_from_dict(a) for a in t.get("agents", []))
        teams.append((team_id, name, agents))
        driver = t.get("driver")
        if driver:
            driver_kinds[team_id] = _driver_label(driver)
    return teams, driver_kinds


def cmd_cmatch_new(args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json", False))
    store = Store()

    if args.config:
        config = _parse_config_arg(args.config)
        if config.get("fog"):
            raise CliError(
                code=EXIT_USER_ERROR,
                message="cmatch new/show/act/tick don't support fog yet (issue #28 follow-up)",
                remediation="use 'league cmatch run --config ... --apply', which delegates to "
                "the fully-featured run_cmatch harness (fog included)",
            )
        match_cfg = config.get("match", {})
        scenario_id = match_cfg.get("scenario")
        if not scenario_id:
            raise CliError(
                code=EXIT_USER_ERROR,
                message="--config's match.scenario is required",
                remediation="see 'league explain cmatch' for the config shape",
            )
        mode = str(match_cfg.get("mode", "competitive"))
        seed = int(match_cfg.get("seed", 0))
        match_id = str(match_cfg.get("id")) if match_cfg.get("id") else None
        teams, driver_kinds = _teams_from_config(config)
    else:
        if not args.scenario:
            raise CliError(
                code=EXIT_USER_ERROR,
                message="--scenario is required (or pass --config)",
                remediation="e.g. --scenario c-skirmish-1 --team blue --team red "
                "--driver blue:bot --driver red:bot --apply",
            )
        scenario_id = args.scenario
        mode = args.mode
        seed = args.seed
        match_id = args.id
        team_ids = args.team or []
        teams = []
        for team_id in team_ids:
            try:
                sid, name, agents = store.team_slots(team_id)
            except FileNotFoundError as err:
                raise CliError(
                    code=EXIT_USER_ERROR,
                    message=str(err),
                    remediation="register it first: league team register ... --apply",
                ) from err
            teams.append((sid, name, _cagents_from_slots(agents)))
        driver_kinds = _driver_labels_from_args(args, team_ids)

    if not match_id:
        match_id = _auto_match_id(store, scenario_id, mode, seed)
    _safe_id(match_id, "match id")

    try:
        scenario = get_cscenario(scenario_id)
    except ValueError as err:
        raise CliError(
            code=EXIT_USER_ERROR,
            message=str(err),
            remediation="see docs/features/continuous-lane.md for the scenario catalog",
        ) from err
    try:
        state = instantiate(scenario, match_id=match_id, seed=seed, mode=mode, teams=teams)
    except ValueError as err:
        raise CliError(
            code=EXIT_USER_ERROR,
            message=str(err),
            remediation="check team rosters/mode against the scenario's requirements",
        ) from err

    payload: dict[str, Any] = {
        "match_id": match_id,
        "scenario": scenario_id,
        "mode": mode,
        "seed": seed,
        "teams": [t[0] for t in teams],
        "driver_kinds": driver_kinds,
        "time_limit": state.time_limit,
        "applied": bool(args.apply),
    }
    if args.apply:
        clog = CMatchLog(
            initial_state=state,
            events=(CEvent(game_time=0, seq=0, kind="match_started", data={}),),
            driver_kinds=driver_kinds,
        )
        try:
            path = store.create_match(clog)
        except FileExistsError as err:
            raise CliError(
                code=EXIT_USER_ERROR,
                message=str(err),
                remediation="pass a fresh --id (or match.id in --config)",
            ) from err
        payload["log"] = str(path)
        payload["due"] = due_decisions(clog)
    if json_mode:
        emit_result(payload, json_mode=True)
    else:
        verb = "created" if args.apply else "would create (dry-run; add --apply)"
        emit_result(
            f"{verb}: {match_id} — {scenario_id} ({mode}, seed {seed}, "
            f"teams: {', '.join(payload['teams']) or 'none'})",
            json_mode=False,
        )
    return 0


# -- show -------------------------------------------------------------------- #


def cmd_cmatch_show(args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json", False))
    store = Store()
    clog = _load_clog(store, args.match_id)
    state = clog.final_state()
    role_table = _role_table_for(state)
    due = due_decisions(clog)

    unit = getattr(args, "unit", None)
    if unit is not None and unit not in due:
        raise CliError(
            code=EXIT_USER_ERROR,
            message=f"unit {unit!r} is not currently due in match {args.match_id!r}",
            remediation=f"due units: {', '.join(due) or 'none'}",
        )
    target_units = [unit] if unit else due
    messages = _messages_from_log(clog)

    decisions = []
    for uid in target_units:
        menu = legal_actions_continuous(state, role_table, uid)
        briefing = build_briefing(
            state, uid, menu, messages=messages, fog=False, role_table=role_table
        )
        decisions.append({"unit_id": uid, "briefing": briefing})

    payload = {
        "match_id": args.match_id,
        "game_time": state.clock,
        "status": state.status,
        "winner": state.winner,
        "due": due,
        "decisions": decisions,
    }
    if json_mode:
        emit_result(payload, json_mode=True)
    else:
        lines = [
            f"{args.match_id}: {state.status} — t={state.clock}"
            + (f", winner {state.winner}" if state.winner else "")
        ]
        if not decisions:
            lines.append(
                "  no unit is currently due"
                + ("" if state.status == "active" else f" (match {state.status})")
            )
        for entry in decisions:
            uid = entry["unit_id"]
            menu_entries = entry["briefing"]["menu"]
            options = (
                ", ".join(
                    f"{m['kind']}→{m.get('target')}@{m['completion_time']}" for m in menu_entries
                )
                or "(no legal actions — park)"
            )
            lines.append(f"  {uid} due at t={entry['briefing']['game_time']}: {options}")
        emit_result("\n".join(lines), json_mode=False)
    return 0


# -- act ----------------------------------------------------------------------- #


def _action_from_args(args: argparse.Namespace) -> dict[str, Any] | None:
    raw = getattr(args, "action_json", None)
    if raw is None:
        return None
    try:
        action = json.loads(raw)
    except json.JSONDecodeError as err:
        raise CliError(
            code=EXIT_USER_ERROR,
            message=f"--action-json is not valid JSON: {err}",
            remediation="pass a menu entry verbatim, or 'null' to park",
        ) from err
    if action is None:
        return None
    if not isinstance(action, dict) or "kind" not in action:
        raise CliError(
            code=EXIT_USER_ERROR,
            message="--action-json must be a JSON object with a 'kind', or null",
            remediation="copy an entry verbatim from "
            "'league cmatch show <id> --unit <uid> --json'",
        )
    return action


def cmd_cmatch_act(args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json", False))
    store = Store()
    clog = _load_clog(store, args.match_id)
    state = clog.final_state()
    if state.status != "active":
        raise CliError(
            code=EXIT_USER_ERROR,
            message=f"match {args.match_id!r} is {state.status}, not active",
            remediation="start a new match with 'league cmatch new'",
        )
    role_table = _role_table_for(state)
    due = due_decisions(clog)
    if not due:
        raise CliError(
            code=EXIT_USER_ERROR,
            message=f"no unit is currently due in match {args.match_id!r}",
            remediation="call 'league cmatch tick --apply' to advance the timeline",
        )
    if args.unit not in due:
        raise CliError(
            code=EXIT_USER_ERROR,
            message=f"unit {args.unit!r} is not currently due",
            remediation=f"due units: {', '.join(due)}",
        )
    if args.unit != due[0]:
        raise CliError(
            code=EXIT_USER_ERROR,
            message=f"unit {due[0]!r} must be answered first (canonical order)",
            remediation=f"due units, in the order they must be answered: {', '.join(due)}",
        )

    action = _action_from_args(args)
    if action is not None and plan_action(state, role_table, args.unit, action) is None:
        raise CliError(
            code=EXIT_USER_ERROR,
            message=f"action {action!r} is not legal for unit {args.unit!r} right now",
            remediation=f"see 'league cmatch show {args.match_id} --unit {args.unit} --json' "
            "for the legal menu",
        )

    payload: dict[str, Any] = {
        "match_id": args.match_id,
        "unit": args.unit,
        "action": action,
        "applied": bool(args.apply),
    }
    if args.apply:
        answered = False

        def decide_external(unit_id: str, s: CMatchState, menu: dict) -> dict | None:
            nonlocal answered
            if unit_id == args.unit and not answered:
                answered = True
                return action
            raise NeedsExternalDecision(unit_id)

        new_log, finished = advance_external(clog, role_table, decide_external)
        new_events = new_log.events[len(clog.events) :]
        store.append_events(args.match_id, new_events)
        new_state = new_log.final_state()
        payload["events_appended"] = len(new_events)
        payload["finished"] = finished
        payload["status"] = new_state.status
        payload["winner"] = new_state.winner
        payload["due"] = due_decisions(new_log)
    if json_mode:
        emit_result(payload, json_mode=True)
    else:
        label = action["kind"] if action else "park"
        if not args.apply:
            emit_result(
                f"would submit {args.unit}: {label} on {args.match_id} — dry-run; add --apply",
                json_mode=False,
            )
        else:
            tail = f" — {payload['status']}" + (
                f", winner {payload['winner']}" if payload["winner"] else ""
            )
            emit_result(
                f"{args.unit} answered ({label}); {payload['events_appended']} event(s){tail}; "
                f"due next: {', '.join(payload['due']) or 'none'}",
                json_mode=False,
            )
    return 0


# -- tick ---------------------------------------------------------------------- #
#
# Auto-resolves whatever DUE units this match's log header declares a `bot`/
# `bot-file:<name>` driver for (the label IS the reconstructable spec -- no
# separate config file needed, see the module docstring's driver-label
# section), and/or parks the rest when `--timeout-park` is passed. A
# `stateless`/`resident` (live-mind) team's due units are neither -- they stay
# due, waiting for an external `cmatch act` call, exactly mirroring the grid
# lane's own `match tick` (which force-resolves with whatever orders are
# ALREADY staged; it never invokes a live mind itself either).


def _bot_choosers(driver_kinds: dict[str, str]) -> dict[str, Any]:
    choosers: dict[str, Any] = {}
    for team_id, label in driver_kinds.items():
        if label == "bot":
            choosers[team_id] = make_cbot_chooser()
        elif label.startswith(_BOT_FILE_PREFIX):
            strategy = label[len(_BOT_FILE_PREFIX) :]
            try:
                choosers[team_id] = make_cbot_file_chooser({"strategy": strategy})
            except CHarnessError as err:
                raise CliError(
                    code=EXIT_ENV_ERROR,
                    message=f"cannot load bot strategy for team {team_id!r}: {err}",
                    remediation="check bots/<name>.py exists and exports decide_continuous",
                ) from err
    return choosers


def cmd_cmatch_tick(args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json", False))
    store = Store()
    clog = _load_clog(store, args.match_id)
    state = clog.final_state()
    if state.status != "active":
        raise CliError(
            code=EXIT_USER_ERROR,
            message=f"match {args.match_id!r} is {state.status}, not active",
            remediation="only active matches tick",
        )
    role_table = _role_table_for(state)
    choosers = _bot_choosers(clog.driver_kinds)
    due_before = due_decisions(clog)

    if not args.apply:
        would_resolve = [u for u in due_before if _team_of(state, u) in choosers]
        would_park = [u for u in due_before if u not in would_resolve] if args.timeout_park else []
        pending = [u for u in due_before if u not in would_resolve and u not in would_park]
        payload = {
            "match_id": args.match_id,
            "due": due_before,
            "would_resolve": would_resolve,
            "would_park": would_park,
            "applied": False,
        }
        if json_mode:
            emit_result(payload, json_mode=True)
        else:
            emit_result(
                f"would resolve {', '.join(would_resolve) or 'none'}; "
                f"park {', '.join(would_park) or 'none'}; "
                f"leave pending {', '.join(pending) or 'none'} — dry-run; add --apply",
                json_mode=False,
            )
        return 0

    resolved: list[str] = []
    parked: list[str] = []

    def decide_external(unit_id: str, s: CMatchState, menu: dict) -> dict | None:
        team_id = _team_of(s, unit_id)
        chooser = choosers.get(team_id)
        if chooser is not None:
            briefing = build_briefing(s, unit_id, menu, role_table=role_table)
            reply = chooser(briefing, unit_id, team_id)
            action = reply.get("action") if isinstance(reply, dict) else None
            if action is not None and plan_action(s, role_table, unit_id, dict(action)) is None:
                action = None  # a bot's illegal pick safely parks (mirrors league.charness)
            resolved.append(unit_id)
            return action
        if args.timeout_park:
            parked.append(unit_id)
            return None
        raise NeedsExternalDecision(unit_id)

    new_log, finished = advance_external(clog, role_table, decide_external)
    new_events = new_log.events[len(clog.events) :]
    store.append_events(args.match_id, new_events)
    new_state = new_log.final_state()
    payload = {
        "match_id": args.match_id,
        "due": due_before,
        "resolved": resolved,
        "parked": parked,
        "events_appended": len(new_events),
        "finished": finished,
        "status": new_state.status,
        "winner": new_state.winner,
        "applied": True,
        "due_now": due_decisions(new_log),
    }
    if json_mode:
        emit_result(payload, json_mode=True)
    else:
        tail = f" — {payload['status']}" + (
            f", winner {payload['winner']}" if payload["winner"] else ""
        )
        emit_result(
            f"tick: resolved {len(resolved)}, parked {len(parked)}, "
            f"{payload['events_appended']} event(s){tail}; "
            f"due next: {', '.join(payload['due_now']) or 'none'}",
            json_mode=False,
        )
    return 0


# -- run ------------------------------------------------------------------- #


def cmd_cmatch_run(args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json", False))
    config = _parse_config_arg(args.config)
    match_cfg = config.get("match", {})
    teams_cfg = config.get("teams", [])
    summary = {
        "config": args.config,
        "match": match_cfg,
        "teams": [
            {"id": t.get("id"), "driver": (t.get("driver") or {}).get("type")} for t in teams_cfg
        ],
        "applied": bool(args.apply),
    }
    if not args.apply:
        if json_mode:
            emit_result(summary, json_mode=True)
        else:
            drivers = ", ".join(f"{t['id']}({t['driver']})" for t in summary["teams"])
            emit_result(
                f"would run {match_cfg.get('scenario')} with {drivers} — dry-run; add --apply",
                json_mode=False,
            )
        return 0

    try:
        result = _run_cmatch(config)
    except (CHarnessError, ValueError, KeyError) as err:
        raise CliError(
            code=EXIT_USER_ERROR,
            message=f"cmatch run failed: {err}",
            remediation="check the config against 'league explain cmatch'",
        ) from err

    log = result["log"]
    store = Store()
    log_path = store.log_path(result["match_id"])
    if log_path.is_file():
        raise CliError(
            code=EXIT_USER_ERROR,
            message=f"match {result['match_id']!r} already exists",
            remediation="pass a fresh match id in the config (match.id)",
        )
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(log.to_jsonl(), encoding="utf-8")

    payload = {
        "match_id": result["match_id"],
        "status": result["status"],
        "game_time": result["game_time"],
        "winner": result["winner"],
        "outcome_points": result["outcome_points"],
        "events": len(log.events),
        "log": str(log_path),
    }
    if json_mode:
        emit_result(payload, json_mode=True)
    else:
        tail = f", winner {payload['winner']}" if payload["winner"] else ""
        emit_result(
            f"{payload['match_id']}: {payload['status']} at t={payload['game_time']}{tail} "
            f"({payload['events']} events) — {payload['log']}",
            json_mode=False,
        )
    return 0


# -- registration ------------------------------------------------------------ #


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "cmatch", help="Continuous-lane external-driver play loop (see 'league cmatch overview')."
    )
    p.add_argument("--json", action="store_true", help="Emit structured JSON.")
    p.set_defaults(func=cmd_cmatch_overview, json=False)
    noun_sub = p.add_subparsers(dest="cmatch_command", parser_class=type(p))

    ov = noun_sub.add_parser("overview", help="Describe the cmatch noun.")
    ov.add_argument("--json", action="store_true", help="Emit structured JSON.")
    ov.set_defaults(func=cmd_cmatch_overview)

    new = noun_sub.add_parser("new", help="Create a continuous match (dry-run by default).")
    new.add_argument("--config", help="Path to (or inline JSON of) a match+teams config.")
    new.add_argument("--scenario", help="Continuous scenario id, e.g. c-skirmish-1.")
    new.add_argument(
        "--mode", choices=("competitive", "cooperative"), default="competitive", help="Match mode."
    )
    new.add_argument("--seed", type=int, default=0, help="Deterministic seed (metadata only).")
    new.add_argument("--id", help="Match id (default: auto-generated).")
    new.add_argument(
        "--team", action="append", metavar="TEAM_ID", help="A registered team id; repeatable."
    )
    new.add_argument(
        "--driver",
        action="append",
        metavar="TEAM_ID:KIND",
        help="Driver label for a --team: bot|stateless|resident|bot-file:<name>; repeatable.",
    )
    new.add_argument("--apply", action="store_true", help="Actually create (default: dry-run).")
    new.add_argument("--json", action="store_true", help="Emit structured JSON.")
    new.set_defaults(func=cmd_cmatch_new)

    show = noun_sub.add_parser("show", help="What is due right now: every idle unit's briefing.")
    show.add_argument("match_id", help="Match id.")
    show.add_argument("--unit", help="Scope to one due unit (default: every due unit).")
    show.add_argument("--json", action="store_true", help="Emit structured JSON.")
    show.set_defaults(func=cmd_cmatch_show)

    act = noun_sub.add_parser("act", help="Submit one unit's decision (dry-run by default).")
    act.add_argument("match_id", help="Match id.")
    act.add_argument("--unit", required=True, help="The due unit this decision is for.")
    act.add_argument(
        "--action-json",
        help="A menu entry verbatim (JSON object), or omit/pass 'null' to park.",
    )
    act.add_argument("--apply", action="store_true", help="Actually submit (default: dry-run).")
    act.add_argument("--json", action="store_true", help="Emit structured JSON.")
    act.set_defaults(func=cmd_cmatch_act)

    tick = noun_sub.add_parser(
        "tick", help="Resolve bot-driven due units and/or park the rest (dry-run by default)."
    )
    tick.add_argument("match_id", help="Match id.")
    tick.add_argument(
        "--timeout-park",
        action="store_true",
        help="Park any due unit with no bot/bot-file driver configured "
        "(default: leave it pending).",
    )
    tick.add_argument("--apply", action="store_true", help="Actually resolve (default: dry-run).")
    tick.add_argument("--json", action="store_true", help="Emit structured JSON.")
    tick.set_defaults(func=cmd_cmatch_tick)

    run = noun_sub.add_parser(
        "run", help="Play a configured continuous match to completion (dry-run by default)."
    )
    run.add_argument("--config", required=True, help="Path to (or inline JSON of) the config.")
    run.add_argument("--apply", action="store_true", help="Actually run (default: dry-run).")
    run.add_argument("--json", action="store_true", help="Emit structured JSON.")
    run.set_defaults(func=cmd_cmatch_run)
