"""The continuous-lane agent-player harness — minds drive a match by *time*.

This is the sibling of ``league/harness.py`` for the continuous arena
(``league/engine/continuous/``, cycle-7). The grid harness drives a match of
uniform simultaneous turns: each turn it hands a driver the whole board and
takes back a whole-team order dict. The continuous lane replaces the turn with
an event **timeline** (``resolve.py``), so the contract changes at its root:

* **Time is the referee, not a loop this module owns.** The resolver
  (:func:`~league.engine.continuous.resolve.resolve_match`) owns the loop — it
  advances the game clock by action completion times and, whenever a unit
  becomes idle, calls a pure ``decide(unit_id, state, menu)`` callback. This
  harness is that callback: it wraps every driver kind behind one dispatcher so
  a bot, a coded strategy, a subprocess, or a resident session all answer the
  same signal the same way.
* **One action per decision point, never a whole-team order.** A driver is asked
  for exactly ONE unit's next action when that unit goes idle — the fundamental
  contract change from the grid's per-turn team order. "When does a mind get
  asked?" (the frame's hardest parked question, v1) is answered mechanically:
  *at a decision point* — match start, or the instant its unit's action
  completes / fails / is interrupted.

The mind-facing BRIEFING (pinned; see ``docs/continuous-contract.md``)
--------------------------------------------------------------------
At each decision point the harness builds a briefing — the JSON a mind receives.
:func:`build_briefing` pins its shape::

    {"game_time": <int game clock>,
     "you": {"unit_id", "agent_id", "team_id", "role", "pos", "carrying",
             "action": null},          # idle at a decision point, by definition
     "menu": [{"kind", "target", "duration", "completion_time", ...}, ...],
     "outlook": [{"unit_id", "team_id", "completion_time"}, ...],
     "board": { ...full-information state projection... },
     "messages": [{"from", "text", "game_time"}, ...],
     "clock_budget_note": "<how to read time budgets>"}

The three things a mind needs to plan *in time*: the game **clock**
(``game_time``), its action **menu with durations** (each entry also carries the
``completion_time`` it would land at — straight from
:func:`~league.engine.continuous.legal.legal_actions_continuous`), and the
initiative **outlook** — who is due to complete next
(:func:`initiative_outlook`, the same set the resolver's ``Timeline.pending()``
holds for real units). Each menu entry is directly returnable to the resolver
(it still carries its raw ``target_id`` / ``target_pos``).

Substrate independence (honesty h7) — the load-bearing property
---------------------------------------------------------------
Game time comes ONLY from role data and the timeline; a driver that answers in
1 ms and one that answers in 60 s produce the byte-identical match log. Proven
by construction: wall-clock (:data:`_monotonic`) is read ONLY to fill
``seat_latency`` observations (the out-of-game tempo axis), never fed back to
the resolver — and the resolver lives under the engine-wide AST import ban
(``tests/test_engine_state.py``), so it *cannot* read a clock. This module
records ``seat_latency`` / ``message_sent`` / ``plan_declared`` as OBSERVATION
events (fold no-ops) appended after the resolver's transition stream, so
stripping them leaves the transitions — and the final ``cstate_hash`` —
untouched. That is the h7 proof shape.

Every driver kind gets the loop (the all-backends rule)
-------------------------------------------------------
* ``bot`` — an in-harness greedy continuous policy (:func:`make_cbot_chooser`),
  reading only the briefing, stdlib only. The baseline and the test double.
* ``bot-file`` — a committed strategy under ``bots/<name>.py`` exporting
  ``decide_continuous(briefing, team_id)`` (:func:`make_cbot_file_chooser`),
  loaded by name (``validate_id`` guards path tricks) and handed ONLY the
  briefing JSON — the continuous parallel of the grid's ``bot-file`` lane
  (``bots/crusher.py`` is the reference strategy).
* ``command`` — any external agent as a subprocess: the briefing JSON on stdin,
  one JSON order (``{"action", "message"?, "plan"?}``) on stdout. ``per_seat``
  lets each seat carry its own ``argv``/``prompt`` (continuous decisions are
  already per-unit, so per-seat is the per-agent-transport axis).
* ``resident`` — one long-lived session per seat for the whole match
  (:func:`make_cresident_chooser`), reusing the grid harness's proven session
  transports (``CSESSION_TRANSPORTS``).

Config shape (mirrors ``run_match``; league-playable once the CLI + t6 scenario
registry land)::

    {"match": {"scenario": "clash-1", "id": "cm-1"},   # or "state": {...}
     "teams": [{"id": "blue", "driver": {"type": "bot"},
                "agents": [{"id": "blue-1", "role": "scout"}]},
               {"id": "red", "driver": {"type": "command", "argv": [...]}}]}

The initial :class:`~league.engine.continuous.state.CMatchState` is taken via a
clean seam (:func:`_resolve_initial`): an explicit ``initial_state`` (a state or
a builder callable), ``config["state_builder"]``, an inline
``config["match"]["state"]`` dict, or — once
``league.engine.continuous.scenario.get_cscenario`` exists (t6) — a scenario
name. The t6 wiring is a one-liner; until then a name without a registry raises
a clear :class:`CHarnessError`.
"""

from __future__ import annotations

import importlib.util
import json

# Command drivers run operator-configured argv without a shell.
import subprocess  # nosec B404
import sys
import time
from pathlib import Path
from typing import Any, Callable, Mapping

from league.engine.continuous.events import CEvent, CMatchLog
from league.engine.continuous.legal import plan_action
from league.engine.continuous.resolve import outcome_points, resolve_match
from league.engine.continuous.roles import CRoleStats, build_role_table
from league.engine.continuous.state import CMatchState
from league.harness import ClaudeCliSession, ColleagueDirectSession
from league.store import validate_id

#: A chooser answers one decision point: ``(briefing, unit_id, team_id) ->
#: {"action": <menu entry|None>, "message"?/"messages"?, "plan"?}``.
CChooser = Callable[[dict[str, Any], str, str], Mapping[str, Any]]

RoleTable = tuple[tuple[str, CRoleStats], ...]


class CHarnessError(Exception):
    """A continuous-harness configuration or wiring error — raised loudly rather
    than degrading a match silently (mirrors the grid harness's ``ValueError``
    discipline, but a distinct type so callers can catch harness faults apart
    from engine ``ValueError``s)."""


# -- wall-clock: harness-side only, the tempo axis (honesty h7) --------------
#
# ``_monotonic`` is the ONLY clock this module reads, and it feeds ONLY
# ``seat_latency`` observations — never the resolver. It is a module global so a
# test can substitute a deterministic fake (proving 1 ms vs 60 s answers yield
# the identical match log). The resolver itself lives under the engine-wide AST
# import ban, so it cannot import ``time`` at all — the h7 property is enforced
# by construction, not discipline.
_monotonic = time.perf_counter


def _elapsed_ms(started: float) -> int:
    return int(round((_monotonic() - started) * 1000))


CLOCK_BUDGET_NOTE = (
    "Game time is {game_time} (integer game-time units — never wall-clock; your "
    "thinking time never advances it). Each menu action lists its in-game "
    "'duration' and the 'completion_time' it would finish at. 'outlook' lists "
    "which units finish their current action next (soonest first) — plan your "
    "timing around who frees up when; a faster role acts again sooner."
)


# -- the briefing: what a mind receives at a decision point ------------------


def _find_unit(state: CMatchState, unit_id: str):
    for unit in state.units:
        if unit.id == unit_id:
            return unit
    raise CHarnessError(f"unknown unit {unit_id!r}")


def initiative_outlook(state: CMatchState) -> list[dict[str, Any]]:
    """Who is due to complete their current action next — the visible initiative
    outlook, canonical ``(completion_time, team_id, unit_id)`` order.

    A pure projection of ``state``: every unit currently mid-action (``action``
    is not ``None``). This is exactly the set the resolver's
    ``Timeline.pending()`` holds for real units — the synthetic hold-expiry
    markers the timeline also carries are resolver-internal scheduling, not
    decision points, so they are correctly absent from a mind's outlook.
    """
    busy = [
        {"unit_id": u.id, "team_id": u.team_id, "completion_time": u.action.completion_time}
        for u in state.units
        if u.action is not None
    ]
    busy.sort(key=lambda d: (d["completion_time"], d["team_id"], d["unit_id"]))
    return busy


def _menu_entries(menu: Mapping[str, Any], game_time: int) -> list[dict[str, Any]]:
    """Enrich each ``legal_actions_continuous`` action with the absolute
    ``completion_time`` it would land at and a friendly ``target`` label, while
    keeping the raw ``target_id``/``target_pos`` so the entry is directly
    returnable to the resolver."""
    out: list[dict[str, Any]] = []
    for entry in menu.get("actions", []):
        enriched = dict(entry)
        enriched["completion_time"] = game_time + int(entry["duration"])
        target = entry.get("target_id")
        if target is None:
            target = entry.get("target_ref")
        enriched["target"] = target
        out.append(enriched)
    return out


def _board_projection(state: CMatchState) -> dict[str, Any]:
    """A full-information (fogless) projection of the board — the state a mind
    reasons over. Compact but complete; deterministic (mirrors state ordering)."""
    return {
        "match_id": state.match_id,
        "clock": state.clock,
        "time_limit": state.time_limit,
        "width": state.width,
        "height": state.height,
        "mode": state.mode,
        "teams": [{"id": t.id, "name": t.name, "resources": t.resources} for t in state.teams],
        "units": [
            {
                "id": u.id,
                "team_id": u.team_id,
                "agent_id": u.agent_id,
                "role": u.role,
                "pos": u.pos.to_dict(),
                "carrying": u.carrying,
                "alive": u.alive,
                "action": u.action.to_dict() if u.action is not None else None,
            }
            for u in state.units
        ],
        "control_points": [
            {
                "id": c.id,
                "pos": c.pos.to_dict(),
                "owner": c.owner,
                "takers": [t.to_dict() for t in c.takers],
            }
            for c in state.control_points
        ],
        "missions": [
            {
                "id": m.id,
                "kind": m.kind,
                "pos": m.pos.to_dict(),
                "amount": m.amount,
                "reward": m.reward,
                "status": m.status,
                "completed_by": list(m.completed_by),
            }
            for m in state.missions
        ],
        "resource_nodes": [
            {"id": n.id, "pos": n.pos.to_dict(), "remaining": n.remaining}
            for n in state.resource_nodes
        ],
    }


def build_briefing(
    state: CMatchState,
    unit_id: str,
    menu: Mapping[str, Any],
    messages: "list[dict[str, Any]] | tuple[()]" = (),
) -> dict[str, Any]:
    """The JSON a mind receives at a decision point (the pinned contract shape).

    ``menu`` is exactly what
    :func:`~league.engine.continuous.legal.legal_actions_continuous` returns for
    ``unit_id`` in ``state``; ``messages`` is the running social record (each
    other seat's messages so far). See the module docstring / the
    ``docs/continuous-contract.md`` for the field-by-field contract.
    """
    unit = _find_unit(state, unit_id)
    game_time = state.clock
    return {
        "game_time": game_time,
        "you": {
            "unit_id": unit.id,
            "agent_id": unit.agent_id,
            "team_id": unit.team_id,
            "role": unit.role,
            "pos": unit.pos.to_dict(),
            "carrying": unit.carrying,
            "action": unit.action.to_dict() if unit.action is not None else None,
        },
        "menu": _menu_entries(menu, game_time),
        "outlook": initiative_outlook(state),
        "board": _board_projection(state),
        "messages": [dict(m) for m in messages],
        "clock_budget_note": CLOCK_BUDGET_NOTE.format(game_time=game_time),
    }


# -- the in-harness greedy continuous policy (the ``bot`` driver) ------------


def make_cbot_chooser() -> CChooser:
    """A deterministic greedy continuous policy, reading ONLY the briefing.

    Priority: take a post if one is on offer; else deliver a full/partial load;
    else gather; else move toward the most useful point of interest (an
    un-owned control point first). Ties break on ``(completion_time, target)``
    so two runs choose identically. Full-information by default, exactly like
    the grid's ``make_bot_driver`` (a fair-comparison caveat, not a hidden
    engine privilege)."""

    def choose(briefing: dict[str, Any], unit_id: str, team_id: str) -> dict[str, Any]:
        menu = briefing["menu"]
        you = briefing["you"]
        board = briefing.get("board", {})

        def of(kind: str) -> list[dict[str, Any]]:
            return sorted(
                (m for m in menu if m["kind"] == kind),
                key=lambda m: (m["completion_time"], str(m.get("target"))),
            )

        takes = of("take_post")
        if takes:
            return {"action": takes[0]}
        if you["carrying"] > 0:
            delivers = of("deliver")
            if delivers:
                return {"action": delivers[0]}
        gathers = of("gather")
        if gathers:
            return {"action": gathers[0]}
        moves = of("move")
        if moves:
            cp_ids = {cp["id"] for cp in board.get("control_points", [])}
            owned = {
                cp["id"] for cp in board.get("control_points", []) if cp.get("owner") == team_id
            }

            def rank(m: dict[str, Any]) -> tuple[int, int, str]:
                ref = m.get("target")
                wants_cp = ref in cp_ids and ref not in owned
                return (0 if wants_cp else 1, m["completion_time"], str(ref))

            return {"action": sorted(moves, key=rank)[0]}
        return {"action": None}

    return choose


# -- coded-strategy continuous bots: bots/<name>.py, briefing-JSON-only -------
#
# The continuous parallel of the grid's ``bot-file`` lane
# (``league.harness.make_bot_file_driver``): a committed, readable strategy file
# under ``bots/`` handed ONLY the briefing dict — never an engine object, never
# anything the mind-facing contract doesn't expose. The entry point is
# ``decide_continuous(briefing, team_id)`` (distinct from the grid's
# ``decide(show_json, team_id)`` so a file can never be called with the wrong
# contract shape). ``_CBOTS_DIR`` is a module global so tests can point it at a
# scratch directory without writing into the committed ``bots/``.
_CBOTS_DIR = Path(__file__).resolve().parent.parent / "bots"


def _load_cstrategy(name: str) -> Callable[[dict[str, Any], str], Mapping[str, Any]]:
    """Load ``bots/<name>.py``'s ``decide_continuous(briefing, team_id)``.

    ``validate_id`` (the store's path-traversal defense) rejects any name that
    could escape ``bots/`` before it reaches the filesystem — strategies are
    trusted repo code, but only from this one directory, by this one name rule.
    """
    validate_id(name, what="continuous bot strategy name")
    path = _CBOTS_DIR / f"{name}.py"
    if not path.is_file():
        raise CHarnessError(f"unknown continuous bot strategy {name!r}: no such file {path}")
    spec = importlib.util.spec_from_file_location(f"league_cbots_{name}", path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise CHarnessError(f"could not load continuous bot strategy {name!r} from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    decide = getattr(module, "decide_continuous", None)
    if not callable(decide):
        raise CHarnessError(f"bots/{name}.py has no callable decide_continuous(briefing, team_id)")
    return decide


def make_cbot_file_chooser(spec: Mapping[str, Any]) -> CChooser:
    name = spec.get("strategy")
    if not name:
        raise CHarnessError("bot-file driver requires a 'strategy' name (bots/<name>.py)")
    decide = _load_cstrategy(str(name))

    def choose(briefing: dict[str, Any], unit_id: str, team_id: str) -> Mapping[str, Any]:
        return decide(briefing, team_id)

    return choose


# -- external agents as subprocesses (the ``command`` driver) ----------------


def _first_json_object(text: str) -> dict[str, Any]:
    decoder = json.JSONDecoder()
    for start in range(len(text)):
        if text[start] != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    raise ValueError("no JSON object found in driver output")


def _run_command(argv: list[str], prompt: str, timeout: float, who: str) -> dict[str, Any]:
    """One subprocess driver call, retried once — live seats flake; a match
    must not die on a single hiccup. A second consecutive failure raises; the
    dispatcher then parks that seat for this decision point."""
    last_error: Exception | None = None
    for _ in range(2):
        try:
            # Operator-configured argv, shell=False, bounded by timeout.
            proc = subprocess.run(  # nosec B603
                argv, input=prompt, capture_output=True, text=True, timeout=timeout, check=False
            )
            if proc.returncode != 0:
                raise RuntimeError(
                    f"driver {argv[0]} for {who} failed (exit {proc.returncode}): "
                    f"{proc.stderr.strip()[:300]}"
                )
            return _first_json_object(proc.stdout)
        except (RuntimeError, ValueError, subprocess.TimeoutExpired) as err:
            last_error = err
    raise RuntimeError(f"driver for {who} failed twice: {last_error}")


def make_ccommand_chooser(
    spec: Mapping[str, Any], agents: list[dict[str, Any]], *, per_seat: bool = False
) -> CChooser:
    team_argv = list(spec["argv"]) if spec.get("argv") else None
    team_timeout = float(spec.get("timeout", 300))
    by_agent = {a["id"]: a for a in (agents or [])}

    def choose(briefing: dict[str, Any], unit_id: str, team_id: str) -> Mapping[str, Any]:
        agent_id = briefing["you"]["agent_id"]
        if per_seat:
            seat = by_agent.get(agent_id, {})
            argv = list(seat.get("argv") or team_argv or [])
            timeout = float(seat.get("timeout", team_timeout))
            if not argv:
                raise CHarnessError(f"per-seat command seat {agent_id!r} has no 'argv'")
        else:
            argv = list(team_argv or [])
            timeout = team_timeout
            if not argv:
                raise CHarnessError("command driver requires an 'argv'")
        return _run_command(argv, json.dumps(briefing), timeout, agent_id)

    return choose


# -- resident minds: one long-lived session per seat -------------------------
#
# Reuses the grid harness's proven session transports (the t3 spike's
# claude-cli / colleague-direct shells) — a resident seat is the same idea in
# either lane: one persistent session threads every decision point. Tests
# register a fake here so no suite run ever touches a live endpoint.
CSESSION_TRANSPORTS: dict[str, Callable[[Mapping[str, Any], str, str], Any]] = {
    "claude": ClaudeCliSession,
    "colleague": ColleagueDirectSession,
}


def make_cresident_chooser(spec: Mapping[str, Any], agents: list[dict[str, Any]]) -> CChooser:
    transport = spec.get("transport")
    if transport not in CSESSION_TRANSPORTS:
        raise CHarnessError(
            f"unknown resident transport {transport!r}; "
            f"expected one of {sorted(CSESSION_TRANSPORTS)}"
        )
    timeout = float(spec.get("timeout", 300))
    sessions: dict[str, Any] = {}
    briefed: set[str] = set()

    def choose(briefing: dict[str, Any], unit_id: str, team_id: str) -> dict[str, Any]:
        agent_id = briefing["you"]["agent_id"]
        match_id = str(briefing.get("board", {}).get("match_id") or "")
        session = sessions.get(agent_id)
        if session is None:
            session = CSESSION_TRANSPORTS[transport](spec, match_id, agent_id)
            sessions[agent_id] = session
        payload = dict(briefing)
        # First contact carries the intro; later decision points are deltas into
        # the SAME session (the resident property — session persistence).
        payload["resident_intro"] = agent_id not in briefed
        reply_text = session.send(json.dumps(payload), timeout=timeout)
        briefed.add(agent_id)
        return _first_json_object(reply_text)

    return choose


# -- residency label + driver construction (mirror the grid harness) ---------

CDRIVER_KINDS = ("bot", "stateless", "resident")


def cdriver_kind(spec: Mapping[str, Any]) -> str:
    """The per-team residency label recorded in the match-log header (spec
    c10/h7 parity) — metadata about HOW a team's minds were invoked, never game
    state. ``bot``/``bot-file`` -> ``"bot"``; ``resident`` -> ``"resident"``; a
    ``command`` defaults to ``"stateless"`` unless it declares
    ``"residency": "resident"``."""
    kind = spec.get("type")
    if kind in ("bot", "bot-file"):
        return "bot"
    if kind == "resident":
        return "resident"
    if kind == "command":
        residency = spec.get("residency", "stateless")
        if residency not in ("stateless", "resident"):
            raise CHarnessError(
                f"unknown residency {residency!r} for a command driver; "
                "expected 'stateless' or 'resident'"
            )
        return residency
    raise CHarnessError(
        f"unknown driver type {kind!r}; expected 'bot', 'bot-file', 'command' or 'resident'"
    )


def build_cdriver(spec: Mapping[str, Any], agents: list[dict[str, Any]] | None) -> CChooser:
    """Construct the chooser for one team's driver spec (the continuous analog
    of ``league.harness.build_driver``)."""
    kind = spec.get("type")
    if spec.get("per_seat") and kind not in ("command", "resident"):
        raise CHarnessError("per_seat is only supported for 'command' and 'resident' drivers")
    if kind == "bot":
        return make_cbot_chooser()
    if kind == "bot-file":
        return make_cbot_file_chooser(spec)
    if kind == "resident":  # per-seat by definition
        return make_cresident_chooser(spec, agents or [])
    if kind == "command":
        return make_ccommand_chooser(spec, agents or [], per_seat=bool(spec.get("per_seat")))
    raise CHarnessError(
        f"unknown driver type {kind!r}; expected 'bot', 'bot-file', 'command' or 'resident'"
    )


# -- the initial-state seam (t6 scenario registry wires in as a one-liner) ---


def _try_get_cscenario() -> Callable[[str], Any] | None:
    """Return ``league.engine.continuous.scenario.get_cscenario`` if it exists
    (t6), else ``None``. The one place the t6 registry wires in — the whole
    seam is this lazy import, so t7 never hard-depends on a module that is being
    built in parallel."""
    try:
        from league.engine.continuous import scenario as cscenario  # type: ignore
    except ImportError:
        return None
    return getattr(cscenario, "get_cscenario", None)


def _ensure_cstate(value: Any) -> CMatchState:
    if isinstance(value, CMatchState):
        return value
    if isinstance(value, Mapping):
        return CMatchState.from_dict(dict(value))
    raise CHarnessError(
        f"expected a CMatchState or its to_dict() mapping, got {type(value).__name__}"
    )


def _resolve_initial(config: Mapping[str, Any], initial_state: Any) -> CMatchState:
    if initial_state is not None:
        return _ensure_cstate(initial_state() if callable(initial_state) else initial_state)
    builder = config.get("state_builder")
    if callable(builder):
        return _ensure_cstate(builder())
    match = config.get("match", {})
    if isinstance(match.get("state"), Mapping):
        return CMatchState.from_dict(dict(match["state"]))
    name = match.get("scenario") or match.get("scenario_id")
    if name:
        get = _try_get_cscenario()
        if get is not None:
            return _ensure_cstate(get(str(name)))  # t6 seam
        raise CHarnessError(
            f"no continuous scenario registry yet to resolve {name!r}: pass initial_state=, "
            "config['state_builder'], or an inline config['match']['state'] dict "
            "(the t6 registry wires in at _try_get_cscenario as a one-liner)"
        )
    raise CHarnessError(
        "run_cmatch needs an initial CMatchState: pass initial_state=, "
        "config['state_builder'], config['match']['state'], or a scenario name "
        "once league.engine.continuous.scenario.get_cscenario lands (t6)"
    )


# -- message/plan normalization (the social OBSERVATION record) --------------


def _normalize_messages(reply: Mapping[str, Any]) -> list[str]:
    """A driver may attach a message to its order as ``"message"`` (a string or
    ``{"text": ...}``) or ``"messages"`` (a list of either). Normalize to plain
    text strings; the ``from`` is always forced to the seat's own agent id by
    the caller, never trusted from the reply (spoof-proof, like the grid)."""
    out: list[str] = []
    single = reply.get("message")
    if isinstance(single, str) and single.strip():
        out.append(single.strip())
    elif isinstance(single, Mapping) and single.get("text"):
        out.append(str(single["text"]))
    for message in reply.get("messages", []) or []:
        if isinstance(message, Mapping) and message.get("text"):
            out.append(str(message["text"]))
        elif isinstance(message, str) and message.strip():
            out.append(message.strip())
    return out


# -- the run loop: the harness IS the resolver's decision callback -----------


def run_cmatch(
    config: Mapping[str, Any],
    *,
    initial_state: Any = None,
    role_table: RoleTable | None = None,
    choosers: Mapping[str, CChooser] | None = None,
) -> dict[str, Any]:
    """Resolve a continuous match, driving every seat through the mind-facing
    contract.

    Builds one dispatching ``decide(unit_id, state, menu)`` callback that, for
    each decision point, builds the briefing, times the team's driver call
    (wall-clock -> ``seat_latency``), records any message/plan, gates the chosen
    action through the legality oracle (an illegal choice safely parks the seat
    rather than crashing the match), and hands the action back to the resolver.

    ``choosers`` optionally overrides the built driver for named teams (a test
    seam). Returns ``{"match_id", "status", "game_time", "winner",
    "outcome_points", "log"}`` where ``log`` is the full
    :class:`~league.engine.continuous.events.CMatchLog` with the harness's
    OBSERVATION events appended (fold no-ops, so ``log.final_state()`` is
    exactly the resolver's final state).
    """
    state = _resolve_initial(config, initial_state)
    table: RoleTable = role_table or build_role_table()
    team_specs = {t["id"]: t for t in config.get("teams", [])}
    override = dict(choosers or {})

    built: dict[str, CChooser] = {}
    driver_kinds: dict[str, str] = {}
    for team in state.teams:
        tid = team.id
        if tid in override:
            spec = (team_specs.get(tid) or {}).get("driver") or {"type": "bot"}
            driver_kinds[tid] = cdriver_kind(spec)
            continue
        tcfg = team_specs.get(tid)
        if tcfg is None or "driver" not in tcfg:
            raise CHarnessError(f"team {tid!r} in the state has no driver in the config")
        built[tid] = build_cdriver(tcfg["driver"], tcfg.get("agents"))
        driver_kinds[tid] = cdriver_kind(tcfg["driver"])

    match_id = str((config.get("match", {}) or {}).get("id") or state.match_id)

    messages: list[dict[str, Any]] = []  # running social record, shown in later briefings
    observations: list[tuple[int, str, dict[str, Any]]] = []  # (game_time, kind, data)
    plans_declared: set[str] = set()

    def chooser_for(team_id: str) -> CChooser:
        return override.get(team_id) or built[team_id]

    def decide(unit_id: str, cstate: CMatchState, menu: Mapping[str, Any]) -> dict[str, Any] | None:
        unit = _find_unit(cstate, unit_id)
        team_id = unit.team_id
        agent_id = unit.agent_id
        game_time = cstate.clock
        briefing = build_briefing(cstate, unit_id, menu, messages=messages)

        started = _monotonic()
        try:
            reply: Mapping[str, Any] = chooser_for(team_id)(briefing, unit_id, team_id)
        except Exception as err:  # a live driver crashed → park this seat, keep the match alive
            print(f"[charness] seat {agent_id} idles: {err}", file=sys.stderr)
            observations.append(
                (game_time, "seat_latency", _latency(team_id, agent_id, unit_id, started))
            )
            return None
        observations.append(
            (game_time, "seat_latency", _latency(team_id, agent_id, unit_id, started))
        )

        for text in _normalize_messages(reply):
            messages.append({"from": agent_id, "text": text, "game_time": game_time})
            observations.append(
                (
                    game_time,
                    "message_sent",
                    {"team_id": team_id, "from": agent_id, "unit_id": unit_id, "text": text},
                )
            )
        plan = reply.get("plan")
        if plan and agent_id not in plans_declared:
            plans_declared.add(agent_id)
            observations.append(
                (
                    game_time,
                    "plan_declared",
                    {"team_id": team_id, "from": agent_id, "text": str(plan)},
                )
            )

        action = reply.get("action")
        if action is None:
            return None
        # Legality gate (the legal<->resolver agreement, harness side): a live
        # mind's illegal action safely parks the seat, never raises through the
        # resolver — the continuous analog of the grid's reject-and-idle.
        if plan_action(cstate, table, unit_id, dict(action)) is None:
            print(f"[charness] seat {agent_id} chose an illegal action; idling", file=sys.stderr)
            return None
        return dict(action)

    result = resolve_match(state, table, decide, driver_kinds=driver_kinds)

    events = list(result.log.events)
    seq = len(events)
    for offset, (game_time, kind, data) in enumerate(observations):
        events.append(CEvent(game_time=game_time, seq=seq + offset, kind=kind, data=data))
    log = CMatchLog(
        initial_state=result.log.initial_state,
        events=tuple(events),
        driver_kinds=driver_kinds,
    )

    final = result.final_state
    return {
        "match_id": match_id,
        "status": final.status,
        "game_time": final.clock,
        "winner": final.winner,
        "outcome_points": outcome_points(final),
        "log": log,
    }


def _latency(team_id: str, agent_id: str, unit_id: str, started: float) -> dict[str, Any]:
    """One ``seat_latency`` observation payload — every continuous decision is
    per-unit, so both ``agent_id`` and ``unit_id`` are always present (unlike a
    grid team-wide bot call). Wall-clock lives only here."""
    return {
        "team_id": team_id,
        "agent_id": agent_id,
        "unit_id": unit_id,
        "elapsed_ms": _elapsed_ms(started),
    }
