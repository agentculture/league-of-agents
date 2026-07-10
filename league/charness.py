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
     "board": { ...state projection, fogged to the acting team when fog is on... },
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
records ``seat_latency`` as OBSERVATION events (fold no-ops) appended after
the resolver's transition stream; ``message_sent`` / ``plan_declared`` are
recorded by the RESOLVER itself, riding the decision they were attached to
(the issue-#36 interleave convention — see
:class:`~league.engine.continuous.resolve.DecisionReply` — shared with the
``cmatch`` CLI so stepwise driving writes identical bytes). All three are
fold no-ops, so stripping them leaves the transitions — and the final
``cstate_hash`` — untouched. That is the h7 proof shape.

Continuous fog (plan C8-t5, spec c11/h2/c7/c4)
-----------------------------------------------
Fog is a **briefing-layer projection only** — the engine ticks and logs
ground truth exactly as always; ``resolve_match``, the event log, replay and
scoring never see this code. ``"fog": true`` at the top of the match config
(mirrors the grid harness's own ``config.get("fog", False)`` idiom in
``league/harness.py``; default OFF, so every existing config/fixture behaves
identically) makes :func:`build_briefing` filter its OWN ``board``/``menu``/
``outlook`` a second time, per acting team, right before handing the briefing
to a driver. An entity is visible to a team iff it sits within vision radius
of at least one of that team's own living units — the union of per-role
``vision_mu`` (:mod:`league.engine.continuous.roles`) — using the exact
integer ``space.dist_sq`` comparison the rest of the lane uses for "who is
closer," inclusive at the boundary (see :func:`_team_sees_pos`). The scout's
widest-among-executors vision (4000 mu vs 2000 for harvester/defender) is
therefore the concrete fog lever: swapping a scout in for a same-position
non-scout unit changes what its team's briefings reveal. See the "-- continuous
fog --" section below for the exact filters and the menu-honesty argument.

Every driver kind gets the loop (the all-backends rule)
-------------------------------------------------------
* ``bot`` — an in-harness greedy continuous policy (:func:`make_cbot_chooser`),
  reading only the briefing, stdlib only. The baseline and the test double.
* ``bot-file`` — a committed strategy under ``bots/<name>.py`` exporting
  ``decide_continuous(briefing, team_id)`` (:func:`make_cbot_file_chooser`),
  loaded by name (``validate_id`` guards path tricks) and handed ONLY the
  briefing JSON — the continuous parallel of the grid's ``bot-file`` lane
  (``bots/crusher.py`` is the reference strategy).
* ``command`` — any external agent as a subprocess: a TEXT prompt on stdin
  (see below), one JSON order (``{"action", "message"?, "plan"?}``) on stdout.
  ``per_seat`` lets each seat carry its own ``argv``/``prompt`` (continuous
  decisions are already per-unit, so per-seat is the per-agent-transport axis).
* ``resident`` — one long-lived session per seat for the whole match
  (:func:`make_cresident_chooser`), reusing the grid harness's proven session
  transports (``CSESSION_TRANSPORTS``).

The seat contract (plan C8-t7, spec c13/h4/c5/h18/c8/h8)
----------------------------------------------------------
``command`` and ``resident`` — the two TEXT-facing kinds — no longer receive
bare ``json.dumps(briefing)``. :func:`seat_prompt_text` wraps the FIRST
decision point a given seat is ever asked in the baked :data:`SEAT_CONTRACT`
(reply shape, time model, race semantics, menu discipline, delivery
contention, and — only when this match is fogged — the fog paragraph); every
later decision point gets the short :data:`SEAT_DELTA` instead, never a
resend. ``bot``/``bot-file`` are code, not minds, and are unaffected — they
keep reading the plain briefing dict exactly as before. This closes the
cycle-7 lane-parity finding: the contract used to live only in the operator
script ``scripts/cseat_driver.py``'s own ``_CONTRACT``, so a seat fielded
through any OTHER command driver — or through the built-in ``resident``
driver — got raw JSON with no rules at all. ``scripts/cseat_driver.py`` is
now pure transport (session management for a ``claude`` seat); see
``docs/continuous-contract.md`` for the contract text every mind actually
receives.

Config shape (mirrors ``run_match``; league-playable once the CLI + t6 scenario
registry land)::

    {"match": {"scenario": "clash-1", "id": "cm-1"},   # or "state": {...}
     "teams": [{"id": "blue", "driver": {"type": "bot"},
                "agents": [{"id": "blue-1", "role": "scout"}]},
               {"id": "red", "driver": {"type": "command", "argv": [...]}}],
     "fog": false}

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
from league.engine.continuous.resolve import DecisionReply, outcome_points, resolve_match
from league.engine.continuous.roles import CRoleStats, build_role_table, stats_for
from league.engine.continuous.space import Pos, dist_sq
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
    reasons over. Compact but complete; deterministic (mirrors state ordering).

    This is always the FOGLESS base projection — ground truth, exactly as the
    engine holds it. :func:`build_briefing` applies fog (if any) as a second,
    separate pass over this dict's output (:func:`_fog_filter_board`); this
    function itself never changes behavior based on fog. Keeping the two
    passes distinct is what makes "fog is a projection, never a mutation"
    checkable by reading the code, not just by testing it.
    """
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


# -- continuous fog: a briefing-layer projection, never an engine mutation ---
#
# Plan C8-t5 (spec c11/h2/c7/c4). The engine ticks and logs ground truth
# exactly as before fog existed at all — ``resolve_match``, the event log,
# replay and scoring never import or call anything below. Fog only narrows
# what :func:`build_briefing` hands back to a mind: a SECOND pass over this
# module's own (fogless) projections of ``state``, gated by a per-match
# ``"fog": true`` flag (mirrors the grid harness's ``config.get("fog",
# False)`` idiom in ``league/harness.py`` — default OFF, so every existing
# config/fixture/committed log is untouched).
#
# Visibility rule (pinned): an entity is visible to a team iff it is within
# vision radius of AT LEAST ONE of that team's own living units — the union
# of per-role vision radii (``CRoleStats.vision_mu``) — compared with the
# SAME exact integer milliunit primitive the rest of the continuous lane uses
# for "who is closer" (``space.dist_sq``; never a float, never the floored
# root ``space.dist`` returns). The boundary is INCLUSIVE: an entity sitting
# EXACTLY at the vision radius counts as visible (``dist_sq <= vision_mu **
# 2``, not ``<``) — the same ``<=`` convention ``space.arrived`` already pins
# for "reached the target", and the same inclusive convention the grid
# lane's ``league/engine/vision.py`` uses for its Manhattan ball. A team's
# own units are always fully visible to it regardless of distance (mirrors
# the grid's ``vision.visible_units``: "a team always knows its own units,
# they report in") — this falls out of the radius rule for free for a unit's
# own position (distance 0 to itself) but is applied explicitly below so a
# scattered roster (teammates far apart) never loses track of each other.
#
# What gets filtered: ``board["units"]`` (enemy units only — a team's own
# units are always kept), ``board["control_points"]``, ``board
# ["resource_nodes"]`` and ``board["missions"]`` — the four spatial entity
# lists the board projection carries (spec c7 leaves "which entity kinds" to
# this task; these four are exactly the lists with a ``pos``). ``board
# ["teams"]`` (name/aggregate resources) is deliberately NOT filtered: it
# carries no position, so it is not a spatial "entity" fog governs — it reads
# like a scoreboard, not the map, and nothing in this cycle's contract asks
# fog to hide it.
#
# Menu honesty (the spec's own ask: "menu entries must never reference
# entities the team cannot see"): the ONLY menu entries that can name a
# still-undiscovered entity are ``move`` entries toward a point of interest
# (``legal_actions_continuous`` enumerates every control point / resource
# node / mission location as a move target, visible or not — see
# ``legal.py``'s ``_points_of_interest``). ``gather`` / ``take_post`` /
# ``deliver`` entries always target an entity the acting unit is already
# ARRIVED at (``space.arrived``, within ``ARRIVAL_TOLERANCE_MU`` == 1 mu) —
# every role's ``vision_mu`` is at least 2000 mu, so the unit standing there
# always sees it trivially; those three menu kinds need no filtering at all,
# by construction, not by a separate check. ``move`` entries are filtered by
# their own ``target_pos`` directly (the same visibility test applied to the
# destination — no entity-id lookup needed, so it is correct even when two
# entities share a position).
#
# The ``outlook`` gets the same treatment: an enemy unit's completion time is
# ground truth about a unit the team may not currently see, so an entry is
# kept only if it names the team's own unit or a currently visible enemy one.


def _team_sees_pos(state: CMatchState, table: RoleTable, team_id: str, pos: Pos) -> bool:
    """True iff ``pos`` sits within vision radius of at least one of
    ``team_id``'s own living units — the union-of-vision-radii fog rule,
    inclusive at the boundary. See the "continuous fog" section above."""
    for unit in state.units:
        if unit.team_id != team_id or not unit.alive:
            continue
        radius = stats_for(table, unit.role).vision_mu
        if dist_sq(unit.pos, pos) <= radius * radius:
            return True
    return False


def _fog_filter_board(
    board: Mapping[str, Any], state: CMatchState, table: RoleTable, team_id: str
) -> dict[str, Any]:
    """Narrow a fogless :func:`_board_projection` to what ``team_id`` can
    currently see: its own units always, everything else only within vision."""
    fogged = dict(board)
    fogged["units"] = [
        u
        for u in board["units"]
        if u["team_id"] == team_id or _team_sees_pos(state, table, team_id, Pos.from_dict(u["pos"]))
    ]
    for key in ("control_points", "resource_nodes", "missions"):
        fogged[key] = [
            entry
            for entry in board[key]
            if _team_sees_pos(state, table, team_id, Pos.from_dict(entry["pos"]))
        ]
    return fogged


def _fog_filter_menu(
    entries: list[dict[str, Any]], state: CMatchState, table: RoleTable, team_id: str
) -> list[dict[str, Any]]:
    """Drop a ``move`` entry aimed at a point of interest the team cannot see
    yet — the only menu-honesty gap (see the "continuous fog" section)."""
    out: list[dict[str, Any]] = []
    for entry in entries:
        if entry["kind"] == "move":
            target = Pos.from_dict(entry["target_pos"])
            if not _team_sees_pos(state, table, team_id, target):
                continue
        out.append(entry)
    return out


def _fog_filter_outlook(
    outlook: list[dict[str, Any]], state: CMatchState, table: RoleTable, team_id: str
) -> list[dict[str, Any]]:
    """Drop an enemy unit's outlook entry unless it is currently visible; a
    team's own units' entries are always kept."""
    out: list[dict[str, Any]] = []
    for entry in outlook:
        if entry["team_id"] == team_id:
            out.append(entry)
            continue
        unit = _find_unit(state, entry["unit_id"])
        if _team_sees_pos(state, table, team_id, unit.pos):
            out.append(entry)
    return out


def build_briefing(
    state: CMatchState,
    unit_id: str,
    menu: Mapping[str, Any],
    messages: "list[dict[str, Any]] | tuple[()]" = (),
    *,
    fog: bool = False,
    role_table: RoleTable | None = None,
) -> dict[str, Any]:
    """The JSON a mind receives at a decision point (the pinned contract shape).

    ``menu`` is exactly what
    :func:`~league.engine.continuous.legal.legal_actions_continuous` returns for
    ``unit_id`` in ``state``; ``messages`` is the running social record (each
    other seat's messages so far). See the module docstring / the
    ``docs/continuous-contract.md`` for the field-by-field contract.

    ``fog`` (default ``False``, so every pre-fog caller/test is unaffected)
    applies the acting unit's team's union-of-vision-radii filter to
    ``menu``/``outlook``/``board`` — see the "continuous fog" section above
    for the exact rule. ``role_table`` supplies each role's ``vision_mu``;
    it defaults to :func:`~league.engine.continuous.roles.build_role_table`'s
    stock table when fog is on and none is given, so a caller need not thread
    one through just to exercise the default roster.
    """
    unit = _find_unit(state, unit_id)
    game_time = state.clock
    menu_entries = _menu_entries(menu, game_time)
    outlook = initiative_outlook(state)
    board = _board_projection(state)
    if fog:
        table = role_table or build_role_table()
        team_id = unit.team_id
        menu_entries = _fog_filter_menu(menu_entries, state, table, team_id)
        outlook = _fog_filter_outlook(outlook, state, table, team_id)
        board = _fog_filter_board(board, state, table, team_id)
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
        "menu": menu_entries,
        "outlook": outlook,
        "board": board,
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


# -- the mind-facing seat contract: baked into first contact (plan C8-t7) ----
#
# Cycle 7's live match found a lane-parity gap (spec c13/h4/c5/h18/c8/h8,
# recorded in the cycle-7 live report): a grid mind always got a spoken seat
# prompt baked into ``league/harness.py`` (``_SEAT_PROMPT``), but a continuous
# mind got raw briefing JSON — the reply-shape/time-model/race-semantics/
# menu-discipline prose lived only in the OPERATOR script
# ``scripts/cseat_driver.py``'s own ``_CONTRACT``, so only a seat fielded
# through that one script ever heard the rules. This section closes the gap:
# the contract is now baked in HERE, for every text-facing driver kind, and
# ``scripts/cseat_driver.py`` carries none of it any more (pure transport).
#
# "Text-facing" means ``command`` (plain or ``per_seat``) and the built-in
# ``resident`` driver — the two kinds that serialize the briefing to a STRING
# a live mind reads. ``bot``/``bot-file`` read the briefing dict directly (they
# are code, not minds) and are unaffected — exactly the grid's own
# bot/bot-file lane, which never saw ``_SEAT_PROMPT`` either.
#
# First contact vs. delta (mirrors ``league.harness.make_resident_driver``'s
# own turn-1-vs-delta idiom, generalized to every text-facing kind here,
# including ``command`` — unlike the grid, where only ``resident`` gets this
# treatment and a plain ``command`` driver is retaught the rules every turn.
# The continuous ``command`` lane earns the same treatment because cycle 7's
# own operator script (``cseat_driver.py``) already assumed persistent,
# resident-style seats even under a ``"type": "command"`` declaration — this
# module now owns that assumption explicitly instead of leaving it to the
# operator script to get right): the FIRST decision point a given agent id is
# ever asked answers with the full baked contract; every later one gets a
# short delta note. Tracking is per ``agent_id``, held in the chooser's own
# closure so it lives exactly as long as the match (the same shape as the
# resident chooser's pre-existing ``briefed`` set below).
#
# Leakage (the honesty condition): the contract text is static prose plus the
# same JSON the briefing already carries — it never repeats a concrete number
# the briefing withholds. The fog paragraph names the RULE (vision is your
# team's living units' union, the scout usually sees widest) without quoting
# an actual vision-radius value, and it is only ever included when the match
# config actually has fog on (``no overclaiming when fog is off`` — the spec's
# own phrase); see ``tests/test_charness_contract.py`` for the boundary proof,
# mirroring ``tests/test_harness_fog.py``'s own leakage checks for the grid's
# ``_SEAT_PROMPT``/scenario block.

_FOG_NOTE = (
    "- Fog is on: your board shows only what your team currently sees — the union of "
    "every living unit on your team's own vision radius. Something outside that union "
    "is simply absent from your board and menu; it may still exist, you have just not "
    "seen it yet. Your scout sees widest among your executors, so where it stands "
    "changes what your whole team can see — it is your team's eyes.\n"
)

_BOARD_LINE_FULL = (
    "full ground truth: teams, units, control_points (with live takers), missions, "
    "resource_nodes"
)

_BOARD_LINE_FOGGED = (
    "your team's currently visible view, not full ground truth: teams (unfiltered), "
    "plus units/control_points/missions/resource_nodes narrowed to what your team's "
    "vision reaches right now (see the fog note above) — ground truth is still logged "
    "for scoring/replay, you are just not shown all of it live"
)

#: The baked seat contract — first contact only. Adapted from cycle 7's
#: ``scripts/cseat_driver.py`` ``_CONTRACT`` (the text a mind actually received
#: in the cycle-7 live match), plus delivery contention (t3) and conditional
#: fog wording (t5). ``{fog_note}``/``{board_line}`` are filled per-match by
#: :func:`seat_prompt_text`; ``{briefing}`` is the exact JSON the briefing
#: pins (see ``docs/continuous-contract.md``) — nothing added, nothing hidden.
SEAT_CONTRACT = """You are {agent_id}, a live mind playing ONE unit ({unit_id}, role {role}) \
for team {team_id} in a continuous-time League of Agents arena match.

How this arena works — read carefully, it is NOT turn-based:
- Time is INTEGER GAME-TIME, never wall-clock: your thinking time never advances the \
clock. Every action has an in-game duration; while your unit executes one, the rest of \
the world keeps moving on its own timeline. You are consulted again exactly when your \
unit becomes idle (its action completed, failed, or was interrupted).
- Positions are fixed-point ("mu" = milliunits; 1000 mu = 1 distance unit). Roles move \
at different speeds and act at different durations — the role table is lopsided on \
purpose.
- Control points RACE: several units (even from both teams) can be mid-take on the same \
post at once, and the FIRST to complete wins it — everyone else's attempt fails with \
"post taken by a faster agent". Starting first does not mean finishing first: a faster \
role that starts later can still beat you. Check "takers" on each control point and the \
menu's completion_time before committing.
- Deliveries can be DENIED: if an enemy unit is standing at the delivery site the \
instant your delivery would complete, it fails instead of banking (an action_failed \
event, reason "delivery denied by enemy presence at the site") — nothing is lost, you \
keep carrying, and you get a fresh decision point. Only an enemy presence denies; two \
teammates delivering at the same instant both succeed. A defended site is a real \
tradeoff: wait it out, deliver elsewhere, or bring a teammate to clear it first.
- Scoring is outcome points: held control points plus mission rewards for delivered \
resources. No single unit can win the race AND run the economy inside the time limit — \
split the labor with your teammate and say what you are doing.
{fog_note}
Each decision point you receive ONE JSON briefing:
- game_time — the integer clock right now.
- you — your unit: position, carrying, role, current action (null = idle).
- menu — the ONLY actions legal for you right now; each entry carries kind, duration, \
completion_time (absolute), and target/target_id. Menu discipline: your reply's \
"action" must be copied verbatim from one of these entries — nothing invented, nothing \
paraphrased.
- outlook — which units finish their current action soonest; plan your timing around \
who frees up when.
- board — {board_line}.
- messages — every broadcast so far; your teammates see yours at their next decision.

Reply with EXACTLY ONE JSON object and nothing else — no prose, no code fences:
{{"action": <ONE entry copied verbatim from menu>, "message": "<optional short \
broadcast to your team>", "plan": "<optional: declare your team's plan, once>"}}
An action copied from outside the menu parks your unit for this decision (wasted time). \
To deliberately wait instead, set your reply's action to JSON null rather than omitting \
it.

Your first briefing follows.

{briefing}"""

#: The delta — every decision point after the first for a given seat. No
#: rules re-teach (mirrors ``league.harness``'s own resident-delta idiom).
SEAT_DELTA = """Decision point at game_time {game_time} — same match, same rules, same \
reply contract (exactly one JSON object, action copied verbatim from menu or null).

{briefing}"""


def seat_prompt_text(briefing: Mapping[str, Any], *, fog: bool, first_contact: bool) -> str:
    """The exact string a text-facing driver (``command``/``resident``) receives:
    the baked :data:`SEAT_CONTRACT` on ``first_contact``, else the short
    :data:`SEAT_DELTA`. ``fog`` gates the one conditional paragraph (the fog
    note/board line) so an unfogged match's contract never claims fog exists —
    the "no overclaiming when fog is off" honesty condition. The embedded
    ``{briefing}`` is ``json.dumps(briefing)`` verbatim: this function adds
    prose around the pinned briefing, never a byte of engine data beyond it.
    """
    you = briefing["you"]
    briefing_json = json.dumps(briefing)
    if first_contact:
        return SEAT_CONTRACT.format(
            agent_id=you["agent_id"],
            unit_id=you["unit_id"],
            role=you["role"],
            team_id=you["team_id"],
            fog_note=_FOG_NOTE if fog else "",
            board_line=_BOARD_LINE_FOGGED if fog else _BOARD_LINE_FULL,
            briefing=briefing_json,
        )
    return SEAT_DELTA.format(game_time=briefing["game_time"], briefing=briefing_json)


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
    spec: Mapping[str, Any],
    agents: list[dict[str, Any]],
    *,
    per_seat: bool = False,
    fog: bool = False,
) -> CChooser:
    """A ``command`` driver: one subprocess call per decision point.

    ``fog`` (default ``False``, so every pre-t7 caller/config is unaffected)
    reaches :func:`seat_prompt_text` so the baked contract's fog paragraph is
    only ever present when this match is actually fogged. ``contacted`` tracks
    which agent ids have already been sent the full contract — per this
    chooser's own closure, so it lives exactly as long as this team's driver
    (the same shape as :func:`make_cresident_chooser`'s ``briefed`` set): the
    FIRST decision point a given seat is ever asked carries
    :data:`SEAT_CONTRACT`; every later one gets the short :data:`SEAT_DELTA` —
    even though a plain ``command`` subprocess is otherwise stateless, so an
    operator script (e.g. ``scripts/cseat_driver.py``) that manages its own
    resident session no longer has to re-derive "have I taught this seat the
    rules yet" itself; the harness already answers it before the seat ever
    sees the prompt.
    """
    team_argv = list(spec["argv"]) if spec.get("argv") else None
    team_timeout = float(spec.get("timeout", 300))
    by_agent = {a["id"]: a for a in (agents or [])}
    contacted: set[str] = set()

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
        first_contact = agent_id not in contacted
        contacted.add(agent_id)
        prompt = seat_prompt_text(briefing, fog=fog, first_contact=first_contact)
        return _run_command(argv, prompt, timeout, agent_id)

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


def make_cresident_chooser(
    spec: Mapping[str, Any], agents: list[dict[str, Any]], *, fog: bool = False
) -> CChooser:
    """The built-in ``resident`` driver: one long-lived session per seat.

    First contact into a fresh session carries the full :data:`SEAT_CONTRACT`;
    every later decision point into the SAME session gets the short
    :data:`SEAT_DELTA` (the resident property — session persistence — is what
    makes a delta safe to send at all). ``fog`` gates the contract's one
    conditional paragraph, same as :func:`make_ccommand_chooser`.
    """
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
        first_contact = agent_id not in briefed
        prompt = seat_prompt_text(briefing, fog=fog, first_contact=first_contact)
        reply_text = session.send(prompt, timeout=timeout)
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


def build_cdriver(
    spec: Mapping[str, Any], agents: list[dict[str, Any]] | None, *, fog: bool = False
) -> CChooser:
    """Construct the chooser for one team's driver spec (the continuous analog
    of ``league.harness.build_driver``). ``fog`` only reaches the text-facing
    ``command``/``resident`` factories — it gates the baked contract's one
    conditional paragraph (see ``seat_prompt_text``); ``bot``/``bot-file``
    never see prose at all, so ``fog`` does not reach them here (the briefing
    DICT they read is already fog-filtered upstream, uniformly, by
    :func:`run_cmatch`'s own ``build_briefing`` call — a separate mechanism
    from this module's seat-contract prose)."""
    kind = spec.get("type")
    if spec.get("per_seat") and kind not in ("command", "resident"):
        raise CHarnessError("per_seat is only supported for 'command' and 'resident' drivers")
    if kind == "bot":
        return make_cbot_chooser()
    if kind == "bot-file":
        return make_cbot_file_chooser(spec)
    if kind == "resident":  # per-seat by definition
        return make_cresident_chooser(spec, agents or [], fog=fog)
    if kind == "command":
        return make_ccommand_chooser(
            spec, agents or [], per_seat=bool(spec.get("per_seat")), fog=fog
        )
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


def _instantiate_from_registry(
    get: Callable[[str], Any], name: str, config: Mapping[str, Any]
) -> CMatchState:
    """The t6 wiring: resolve a registered continuous scenario and instantiate
    it from the config's match/team declarations. Registry misses and roster
    mismatches surface as :class:`CHarnessError` — the harness's one error
    vocabulary — never a bare registry exception."""
    from league.engine.continuous.scenario import instantiate as cinstantiate
    from league.engine.continuous.state import CAgentSlot

    try:
        scenario = get(name)
    except (KeyError, ValueError) as exc:
        raise CHarnessError(f"unknown continuous scenario {name!r}: {exc}") from exc
    match = config.get("match", {})
    teams = []
    for team in config.get("teams", []):
        agents = tuple(
            CAgentSlot(id=str(a["id"]), model=str(a.get("model", "")), role=str(a["role"]))
            for a in team.get("agents", [])
        )
        teams.append((str(team["id"]), str(team.get("name", team["id"])), agents))
    try:
        return cinstantiate(
            scenario,
            match_id=str(match.get("id") or f"cm-{name}"),
            seed=int(match.get("seed", 0)),
            mode=str(match.get("mode", "competitive")),
            teams=teams,
        )
    except (KeyError, ValueError) as exc:
        raise CHarnessError(
            f"cannot instantiate continuous scenario {name!r} from this config: {exc}"
        ) from exc


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
            return _instantiate_from_registry(get, str(name), config)  # t6 seam
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


def normalize_messages(reply: Mapping[str, Any]) -> list[str]:
    """A driver may attach a message to its order as ``"message"`` (a string or
    ``{"text": ...}``) or ``"messages"`` (a list of either). Normalize to plain
    text strings; the ``from`` is always forced to the seat's own agent id
    downstream (by the resolver's ``_record_social``), never trusted from the
    reply (spoof-proof, like the grid). Public because ``cmatch tick`` applies
    the identical normalization to a bot/bot-file reply (issue #37) — one
    rule, both driving paths."""
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
    :class:`~league.engine.continuous.events.CMatchLog`: the resolver's own
    stream (message/plan observations riding their decisions, per
    :class:`~league.engine.continuous.resolve.DecisionReply`) plus the
    harness's ``seat_latency`` observations appended at the tail — all fold
    no-ops, so ``log.final_state()`` is exactly the resolver's final state.
    The log's ``fog`` header field records this match's briefing projection.

    ``config["fog"]`` (default ``False``) turns on the continuous fog mode —
    see the "continuous fog" section of the module docstring. It is read the
    same way the grid harness reads its own top-level ``"fog"`` flag; fog is
    strictly a briefing-layer projection, so this flag never reaches the
    resolver and never changes the log (:func:`build_briefing` is the only
    thing that sees it).
    """
    state = _resolve_initial(config, initial_state)
    table: RoleTable = role_table or build_role_table()
    fog = bool(config.get("fog", False))
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
        built[tid] = build_cdriver(tcfg["driver"], tcfg.get("agents"), fog=fog)
        driver_kinds[tid] = cdriver_kind(tcfg["driver"])

    match_id = str((config.get("match", {}) or {}).get("id") or state.match_id)

    messages: list[dict[str, Any]] = []  # running social record, shown in later briefings
    observations: list[tuple[int, str, dict[str, Any]]] = []  # (game_time, kind, data)

    def chooser_for(team_id: str) -> CChooser:
        return override.get(team_id) or built[team_id]

    def decide(unit_id: str, cstate: CMatchState, menu: Mapping[str, Any]) -> DecisionReply | None:
        unit = _find_unit(cstate, unit_id)
        team_id = unit.team_id
        agent_id = unit.agent_id
        game_time = cstate.clock
        briefing = build_briefing(
            cstate, unit_id, menu, messages=messages, fog=fog, role_table=table
        )

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

        # The social record: normalized here, recorded by the RESOLVER as
        # message_sent/plan_declared events riding this decision (the issue
        # #36 interleave convention `DecisionReply` pins — shared with the
        # `cmatch` CLI so both driving paths write identical bytes). The
        # resolver also owns the from-is-the-seat's-own-agent rule and the
        # once-per-agent plan dedup.
        texts = normalize_messages(reply)
        for text in texts:
            messages.append({"from": agent_id, "text": text, "game_time": game_time})
        plan = reply.get("plan")

        action = reply.get("action")
        # Legality gate (the legal<->resolver agreement, harness side): a live
        # mind's illegal action safely parks the seat, never raises through the
        # resolver — the continuous analog of the grid's reject-and-idle.
        if action is not None and plan_action(cstate, table, unit_id, dict(action)) is None:
            print(f"[charness] seat {agent_id} chose an illegal action; idling", file=sys.stderr)
            action = None
        return DecisionReply(
            action=dict(action) if action is not None else None,
            messages=tuple(texts),
            plan=str(plan) if plan else None,
        )

    result = resolve_match(state, table, decide, driver_kinds=driver_kinds)

    events = list(result.log.events)
    seq = len(events)
    for offset, (game_time, kind, data) in enumerate(observations):
        events.append(CEvent(game_time=game_time, seq=seq + offset, kind=kind, data=data))
    log = CMatchLog(
        initial_state=result.log.initial_state,
        events=tuple(events),
        driver_kinds=driver_kinds,
        fog=fog,
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
