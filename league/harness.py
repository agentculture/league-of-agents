"""The agent-player harness — live teams drive a match through the CLI.

Every driver interacts with the arena **only** via the public CLI surface
(``league match show --json`` → orders → ``league match act --orders-json
--apply``), so whatever plays here plays exactly what any external agent
would (spec c2/h13). Four driver types ship:

* ``bot`` — a deterministic greedy policy (stdlib only). The baseline
  opponent and the harness's own test double.
* ``bot-file`` — the coded-strategy bot lane (plan task t2, spec c3/h2):
  loads a committed strategy module from ``bots/<name>.py`` (contract in
  ``bots/README.md``; reference strategy ``bots/rusher.py``) and calls its
  ``decide(show_json, team_id)`` with EXACTLY the dict ``league match show
  --json`` returns. Unlike ``bot``, the strategy never sees ``state`` or
  ``context`` directly and never imports ``league.engine``/``league.store``
  — it is honest opposition, not a hidden engine privilege.
* ``command`` — any external agent as a subprocess: the harness feeds a
  prompt (rules + full state JSON) on stdin and parses the first JSON object
  from stdout as the team's orders. A colleague-backend model, a Sonnet
  subagent, an orchestrator, or Claude itself is **a roster-config change,
  not a code change** — swap ``argv`` and the roster's ``model`` labels.
* ``resident`` — one long-lived session per seat for the whole match (plan
  task t5; per-seat by definition). Turn 1 sends the full briefing (rules +
  scenario + role); every later turn sends only a delta (new events since the
  seat last acted, compact state, teammate messages, own rejections, own
  legal actions) into the SAME session. Two transports ship, per the t3 spike
  (docs/specs/notes/cultureagent-spike.md): ``"claude"`` — the spike's proven
  zero-dep fallback, ``claude -p --session-id/--resume`` with driver-minted
  UUIDs (labeled ``claude-cli``; chosen over importing cultureagent's
  ``AgentRunner`` from the culture venv to keep league's runtime
  dependency-free) — and ``"colleague"`` — a driver-held transcript against
  the vLLM OpenAI endpoint, labeled ``colleague-direct`` because
  cultureagent's colleague backend cannot thread sessions as shipped. Every
  send/receive is appended to ``.league/matches/<id>/sessions/<agent>.jsonl``
  for audit.

Every driver also carries a declared *residency* — the fairness axis of spec
c10/h7 (see :func:`driver_kind`): ``bot`` is always ``"bot"``; a ``command``
driver is ``"stateless"`` (fresh subprocess per turn, today's default) unless
its spec sets ``"residency": "resident"``. ``run_match`` records this per team
in the match log header so teams stay comparable by more than final score.

Latency metadata (plan task t1, spec c10/h9) — every driver kind is timed the
same way: ``run_match`` threads a fresh, per-team, per-turn mutable list into
the ``context`` mapping every driver already receives
(``context["_latency_sink"]``), and each driver factory below appends one
``{"agent_id", "unit_id", "elapsed_ms"}`` record per actual driver call — a
subprocess run, a resident ``session.send``, or, for ``bot``/``bot-file``/a
non-per-seat ``command`` (which command a whole team in one call), that whole
call, with both ids ``None``. This is additive, never a new field on what a
driver *returns*: a driver exercised directly with no sink in ``context``
(every pre-existing harness test) behaves exactly as before. ``run_match``
appends the turn's records to the on-disk log as ``seat_latency``
OBSERVATION events (``league.engine.events``) straight through ``Store`` —
harness instrumentation, not a driver's declared move, so it has no reason to
detour through the CLI's orders contract, the same way resident session
transcripts already bypass it. Wall-clock capture (``time.perf_counter``)
lives ONLY in this module: the determinism import ban
(``tests/test_engine_state.py::test_engine_never_imports_time_or_random``)
covers ``league/engine/`` package-wide, and ``seat_latency`` is a fold no-op
there — MatchState/state_hash are exactly as if it were never written.

Config shape (JSON)::

    {"match": {"scenario": "skirmish-1", "mode": "competitive", "seed": 7,
               "id": "m-play-001"},
     "teams": [{"id": "blue", "name": "Blue Foundry",
                "driver": {"type": "bot"},
                "agents": [{"id": "blue-1", "model": "bot:greedy",
                            "role": "scout"}, ...]},
               {"id": "red",
                "driver": {"type": "command",
                           "argv": ["claude", "-p", "--model",
                                    "claude-sonnet-5"],
                           "timeout": 120},
                "agents": [...]}],
     "max_rounds": 40, "fog": false}

Fog of war (plan task t5, spec c5/h4) — ``"fog": true`` at the top of the
config: **fog is a harness-layer projection only**; ``league/engine`` stays
full-information and deterministic (spec c12 non-goal), the tick never
narrows what it resolves. Each turn, for every ``command``/``resident`` team,
``run_match`` fetches that team's own fogged view (``match show --team <id>
--fog --json``) instead of the shared full-board ``state``/``context`` — a
seat's briefing then contains only its unit's vision, the team's accumulated
knowledge (``league.engine.knowledge``, seen facts with staleness turns / told
facts flagged), and teammate/master messages, never the full board. The
resident driver's per-turn delta becomes newly-seen/newly-told facts since
its last successful turn (:func:`_knowledge_delta`) instead of the raw event
feed, which would otherwise leak enemy moves regardless of vision. A unit's
own legal actions are always kept (they derive from its own position, never
the board) — see :func:`_format_legal_actions`.

Orchestrator mode for real (plan task t6, spec c4/c6/h3/h5) — a per-seat
``command`` team's driver spec may add an optional ``"master"`` sub-driver:
``{"argv": [...], "id": "<agent-id>", "timeout": N, "prompt": "..."}``. The
master is invoked once per turn, BEFORE any ground seat, and commands no
unit — its only tool is guidance messages, always attributed to its declared
``id`` (default ``"<team>-master"``) regardless of what its own reply claims,
the same discipline :func:`_fold_seat_reply` already applies to every seat's
``from``. This is the mode's two declared fairness axes, echoed in the match
config and log (``league match new --map-read``/``--unit-comms``, ``match
show --json``'s ``map_read``/``unit_comms``) — never a hidden privilege:
``map_read`` — ``"full"`` gives the master the plain (unfogged) board even
though the match is fogged; ``"fog"`` (default) gives it the same fogged view
every ground seat gets; and ``unit_comms`` — ``False`` (orchestrator mode's
own default: master-mediated only) narrows what a LATER ground seat's
briefing shows to messages ``from`` the master identity, dropping teammate
chatter; ``True`` keeps today's unfiltered relay (master + teammates). Every
seat's own messages still land in the match log either way — filtering only
trims what a later seat is *shown*, never what is recorded.

**Bot drivers stay full-information under fog, by default.**
``make_bot_driver`` (the in-harness greedy bot) always reads scenario
furniture (control points, missions, resource nodes) directly out of
``state``/``match show --json`` with no vision check, and is unchanged by
this task — it stays full-information regardless of fog. The ``bot-file``
lane can still be played the same omniscient way (its default too), but a
strategy written to the fogged contract can opt in per-team with
``{"type": "bot-file", "strategy": ..., "fogged": true}`` (plan task t3,
spec c8/h4; ``make_bot_file_driver`` then calls ``match show --team <id>
--fog`` instead of the plain view — see ``bots/lampbearer.py``, an
explore-toward-unknown reference strategy). This is a **documented,
opt-in-retired asymmetry**: a fogged playtest that pairs a ``"fogged":
true`` bot-file team against a fogged agent team needs no omniscience
caveat; one that doesn't (the flag unset, or the in-harness ``bot`` driver
at all) must still declare it — fog on for every driver in the match, or
off for all of them, never a silent mix of a fogged agent team against an
omniscient bot.
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import os
import re

# Command drivers run operator-configured argv without a shell.
import subprocess  # nosec B404
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable, Mapping

from league.cli import main as cli_main
from league.engine.events import Event
from league.store import Store, validate_id

Driver = Callable[[dict[str, Any], str, int, Mapping[str, Any] | None], dict[str, Any]]


def _cli_json(argv: list[str]) -> Any:
    """Call the CLI in-process and parse its JSON result — the public surface."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cli_main([*argv, "--json"])
    if rc != 0:
        raise RuntimeError(f"league {' '.join(argv)} failed with exit {rc}")
    return json.loads(buf.getvalue())


# -- latency: wall-clock timing, harness-side only (plan t1, spec c10/h9) ---
#
# Capture lives HERE, never in league/engine: the determinism import ban
# (tests/test_engine_state.py::test_engine_never_imports_time_or_random) bans
# time/random/datetime/secrets/uuid imports package-wide over league/engine/,
# and seat_latency events fold as a no-op there regardless (an OBSERVATION
# kind, league/engine/events.py) — the ban is enforced by construction, not
# just discipline. Every driver kind is measured the SAME way: perf_counter()
# around its own actual driver call (a subprocess run, a resident
# session.send, or — bot/bot-file/a non-per-seat command, which command a
# whole team in one call — that whole call). The sink is threaded through the
# EXISTING ``context`` mapping every driver already receives, never a new
# field on what a driver *returns*: a driver exercised with no sink in
# ``context`` (every pre-existing harness test) behaves exactly as before.


def _elapsed_ms(started: float) -> int:
    """Whole milliseconds since a ``time.perf_counter()`` reading. Monotonic,
    so a wall-clock adjustment mid-match can never skew or negate a reading."""
    return int(round((time.perf_counter() - started) * 1000))


def _latency_sink(context: Mapping[str, Any] | None) -> list[dict[str, Any]] | None:
    """The mutable per-team-per-turn list ``run_match`` threads in via
    ``context["_latency_sink"]`` — ``None`` outside ``run_match`` (a driver
    exercised directly, e.g. in a unit test, simply records nothing)."""
    return (context or {}).get("_latency_sink")


# -- the deterministic greedy bot ------------------------------------------
#
# NOTE — fog asymmetry (plan t5, spec c5/h4), loud on purpose: this policy
# reads ``state["missions"]``/``state["control_points"]``/
# ``state["resource_nodes"]`` directly with no vision check, so it stays
# FULL-INFORMATION even in a fog match — ``run_match`` deliberately never
# fogs the ``state`` a ``bot``/``bot-file`` driver receives (see the module
# docstring's "Fog of war" section). Making this greedy policy fog-honest
# would mean it has to explore toward unknown ground instead of beelining
# the nearest declared objective — a real redesign, not a trivial change —
# so it is left omniscient for now. A fogged match pitting this bot against
# a fogged agent team is NOT a fair comparison; playtests must record fog as
# "on for everyone" or "off for everyone", never mixed.


def _clamp_step(pos: list[int], target: list[int], move: int, grid: dict[str, int]) -> list[int]:
    x, y = pos
    budget = move
    dx = target[0] - x
    step = max(-budget, min(budget, dx))
    x += step
    budget -= abs(step)
    dy = target[1] - y
    step = max(-budget, min(budget, dy))
    y += step
    return [max(0, min(grid["width"] - 1, x)), max(0, min(grid["height"] - 1, y))]


def _manhattan(a: list[int], b: list[int]) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def make_bot_driver(scenario: dict[str, Any]) -> Driver:
    """Greedy but honest teamwork: harvesters run the economy, others take points."""
    roles = scenario["roles"]
    grid = scenario["grid"]

    def orders(
        state: dict[str, Any],
        team_id: str,
        turn: int,
        context: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        t0 = time.perf_counter()
        my_units = [u for u in state["units"] if u["team_id"] == team_id and u["alive"]]
        deliver = next(
            (
                m
                for m in state["missions"]
                if m["kind"] == "deliver" and m.get("team_id") in (None, team_id)
            ),
            None,
        )
        nodes = [n for n in state["resource_nodes"] if n["remaining"] > 0]
        cps = state["control_points"]
        actions: list[dict[str, Any]] = []
        messages: list[dict[str, Any]] = []

        taken: set[str] = set()
        for unit in sorted(my_units, key=lambda u: u["id"]):
            stats = roles[unit["role"]]
            pos = list(unit["pos"])
            if unit["role"] == "harvester" and deliver is not None:
                if unit["carrying"] >= stats["carry"] or (unit["carrying"] > 0 and not nodes):
                    if pos == list(deliver["pos"]):
                        actions.append({"unit_id": unit["id"], "action": "deliver"})
                        messages.append(
                            {"from": unit["agent_id"], "text": f"delivered {unit['carrying']}"}
                        )
                    else:
                        to = _clamp_step(pos, list(deliver["pos"]), stats["move"], grid)
                        actions.append({"unit_id": unit["id"], "action": "move", "to": to})
                    continue
                on_node = next((n for n in nodes if list(n["pos"]) == pos), None)
                if on_node is not None:
                    actions.append({"unit_id": unit["id"], "action": "gather"})
                    continue
                if nodes:
                    nearest = min(nodes, key=lambda n: (_manhattan(pos, list(n["pos"])), n["id"]))
                    to = _clamp_step(pos, list(nearest["pos"]), stats["move"], grid)
                    actions.append({"unit_id": unit["id"], "action": "move", "to": to})
                    continue
                actions.append({"unit_id": unit["id"], "action": "hold"})
                continue

            # Scouts and defenders split the control points between them.
            wanted = [c for c in cps if c["owner"] != team_id and c["id"] not in taken]
            if not wanted:
                wanted = [c for c in cps if c["id"] not in taken] or cps
            key = (
                (lambda c: (-_manhattan(pos, list(c["pos"])), c["id"]))
                if unit["role"] == "scout"
                else (lambda c: (_manhattan(pos, list(c["pos"])), c["id"]))
            )
            target = sorted(wanted, key=key)[0]
            taken.add(target["id"])
            if pos == list(target["pos"]):
                actions.append({"unit_id": unit["id"], "action": "hold"})
            else:
                to = _clamp_step(pos, list(target["pos"]), stats["move"], grid)
                actions.append({"unit_id": unit["id"], "action": "move", "to": to})

        result: dict[str, Any] = {"actions": actions}
        if turn == 1:
            result["plan"] = (
                "greedy split: harvester runs node-to-target relay; "
                "scout takes the far point, defender the near one"
            )
        if messages:
            result["messages"] = messages
        sink = _latency_sink(context)
        if sink is not None:
            # No per-unit granularity: one greedy call commands the whole
            # team's roster at once (a "seat" of one, team-wide).
            sink.append({"agent_id": None, "unit_id": None, "elapsed_ms": _elapsed_ms(t0)})
        return result

    return orders


# -- coded-strategy bots: bots/<name>.py, loaded as trusted repo source -----
#
# The "bot-file" lane (plan task t2, spec c3/h2) is deliberately NOT another
# in-harness policy function like ``make_bot_driver`` above. A strategy is a
# committed, readable file under ``bots/`` (contract: ``bots/README.md``);
# the driver's job is only to load it and hand it the exact JSON dict any
# external bot process would get from ``league match show --json`` — never
# the engine's own objects, never anything the CLI itself doesn't expose.

_BOTS_DIR = Path(__file__).resolve().parent.parent / "bots"


def _load_bot_strategy(name: str) -> Callable[[dict[str, Any], str], dict[str, Any]]:
    """Load ``bots/<name>.py``'s ``decide(show_json, team_id)`` function.

    ``validate_id`` — the store's own path-traversal defense — rejects any
    name that could escape ``bots/`` (``..``, path separators, a leading
    dot) before it ever reaches the filesystem: strategies are trusted repo
    code, but only from this one directory, by this one name pattern.
    """
    validate_id(name, what="bot strategy name")
    path = _BOTS_DIR / f"{name}.py"
    if not path.is_file():
        raise ValueError(f"unknown bot strategy {name!r}: no such file {path}")
    spec = importlib.util.spec_from_file_location(f"league_bots_{name}", path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise ValueError(f"could not load bot strategy {name!r} from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    decide = getattr(module, "decide", None)
    if not callable(decide):
        raise ValueError(f"bots/{name}.py has no callable decide(show_json, team_id)")
    return decide


def make_bot_file_driver(spec: Mapping[str, Any]) -> Driver:
    """A coded strategy played through the public JSON surface only.

    The returned ``orders`` closure ignores the ``state``/``context`` the run
    loop hands every driver AS INPUT TO THE STRATEGY — it calls ``match show
    --json`` itself (the same ``_cli_json`` path every other driver uses,
    exactly what a subprocess bot would have to do) and passes ONLY that
    parsed dict (plus ``team_id``) to ``decide``. No scenario, no engine
    dataclass, ever crosses into strategy code. ``context`` is still read for
    harness-internal bookkeeping (the latency sink, plan t1) — never handed
    to the strategy.

    NOTE — fog asymmetry, opt-in escape hatch (plan t3/t5, spec c5/c8/h4): by
    default (``spec`` has no ``"fogged"``, or it's falsy) this driver still
    calls the plain ``match show --json``, so a bot-file strategy stays
    full-information under fog — unchanged, same documented asymmetry as
    :func:`make_bot_driver` (see the module docstring). A strategy written
    to the fogged contract instead (e.g. ``bots/lampbearer.py``) opts in
    per-team with ``{"type": "bot-file", "strategy": ..., "fogged": true}``:
    this driver then calls ``match show --team <team_id> --fog`` instead, so
    the strategy sees EXACTLY the projection an agent team's own briefing is
    built from. The standing omniscience-asymmetry warning applies only when
    a bot-file team's spec omits (or sets false) ``"fogged"``.
    """
    name = spec.get("strategy")
    if not name:
        raise ValueError("bot-file driver requires a 'strategy' name (bots/<name>.py)")
    decide = _load_bot_strategy(str(name))
    fogged = bool(spec.get("fogged", False))

    def orders(
        state: dict[str, Any],
        team_id: str,
        turn: int,
        context: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        t0 = time.perf_counter()
        match_id = str(state.get("match_id") or "")
        argv = (
            ["match", "show", match_id, "--team", team_id, "--fog"]
            if fogged
            else ["match", "show", match_id]
        )
        show_json = _cli_json(argv)
        result = decide(show_json, team_id)
        sink = _latency_sink(context)
        if sink is not None:
            # One call decides for the whole roster — same team-wide "seat
            # of one" as make_bot_driver above.
            sink.append({"agent_id": None, "unit_id": None, "elapsed_ms": _elapsed_ms(t0)})
        return result

    return orders


# -- external agents as subprocesses ---------------------------------------

_RULES = """Rules (complete — nothing else applies):
- Turns and timing. Orders are simultaneous: every unit's order for a turn
  resolves together, and submission order never matters. The state's "turn"
  field counts turns ALREADY resolved, so the order you send now is for turn
  state.turn + 1. The match ends after the scenario's turn_limit turns, or
  earlier once every mission is resolved. Thinking time is not scored.
- One action per unit per turn:
  * move: to=[x, y] with Manhattan distance |dx|+|dy| from the unit's CURRENT
    position <= its role's move stat, and on the grid. The legal_actions list
    shows every legal move target; anything else is rejected.
  * gather: only on a resource-node square, only for a role with
    can_gather=true; fills the unit up to its carry capacity (limited by what
    the node has left).
  * deliver: only on the deliver-mission square while carrying; unloads all
    cargo into the team's resources.
  * hold: stay put.
  A rejected order does nothing; the unit simply loses that turn.
- Squares can be shared by any number of units. There is no combat, no
  blocking and no damage: units never push, stop or remove each other.
- Control points. ONLY units whose role has can_capture=true count on a
  control point. A unit with can_capture=false (for example the scout) counts
  for NOTHING there: it neither builds a streak nor contests or blocks the
  other team's. Each turn exactly one team has capture-capable units on a
  point, that team's streak on it grows by 1; if both teams do, or nobody
  does, the streak resets to 0. A streak of {capture} captures the point.
  Ownership stays with a team after its units leave, until the other team
  captures it.
- Hold mission of amount N: completes when its point is owned by a team that
  keeps an unbroken capture-capable streak on it of {capture}+N turns (the
  capture turns plus N more). Leaving or being contested resets the streak.
- Deliver mission: completes when a team's resources reach its amount; if
  both teams reach it on the same turn, both get it.
- Score (competitive): mission rewards + 2 points per control point owned at
  the end + delivered resources. Higher total wins; equal totals draw.
- Team play. Each unit is controlled by its own agent. Teammates see your
  messages and declared plan; the other team does not. Declared plans and
  team messages are free and are scored for cooperation quality."""

_FOG_RULES = """
- Fog of war is ON. Each unit sees every cell within Manhattan distance of its
  role's vision stat; your team sees the union of its units' views. You always
  know your own units. Enemy units, resource nodes and control points are
  known only once seen (a sighting is remembered, but may be stale) or once a
  teammate's message names them by their exact id (for example "rn-1a" or
  "red-u2"); a description like "the western node" teaches nothing. A mission
  is listed once your team has seen its cell or knows the control point or
  resource node it sits on, and a listed mission always shows its current
  status. The other team cannot see your messages."""


_CP_VISION_RULES = """
- Control points watch. A control point your team owns also sees every cell
  within Manhattan distance {radius} of it, for your team, from the turn your
  team captures it until the turn the other team captures it. Arriving on a
  point grants nothing; the view comes with the capture. While enemy units
  build a capture streak on your point you see them there, and the turn the
  point is captured your team learns it (its owner changes in your view) and
  loses that point's view."""


_CROWN_RULES = """
- The Crown. It sits on the center cell {pos}{shared}. The first team to have
  capture-capable units on it, with no capture-capable enemy there, for
  {turns} consecutive turns takes it, once and for good, for {value} points.
  Like a control point, both teams present resets the streak to 0, and a
  can_capture=false unit counts for nothing.{delivering} It is scored exactly
  as stated here; whether it is worth the units and turns it ties up is your
  call."""

_HOME_DELIVERY_RULES = """
- Home delivery. Each team has its own deliver mission on its own spawn
  corner (the mission carries that team's team_id). A unit can deliver only
  on its own team's delivery square, and only that team can complete its
  deliver mission; both teams can complete their own."""


_THIEF_RULES = """
- The thief. A role with can_steal=true has one more action:
  * steal: {{"unit_id": "<thief>", "action": "steal", "target": "<enemy unit id>"}}
    ("target" is optional). It resolves AFTER every unit has moved, gathered
    and delivered this turn, on the cell where the thief stands, and takes
    exactly 1 cargo from an enemy unit carrying cargo on that cell (harvesters
    included; without a target, the first such unit by id). It fails if an
    enemy defender stands on that cell at that moment, if the thief is
    already full (thief carry 1), or if no enemy unit with cargo is there (one
    that moved away or delivered this turn is gone). A named target must be
    that unit: if it is not on the cell the steal fails, even when another
    enemy carrier is. A failed steal costs nothing more: the thief stays where
    it is, as with hold. Stolen cargo is carried
    like gathered cargo and counts only once delivered. A thief cannot gather
    or capture. Moving cargo this way is the only interaction between units;
    otherwise the rule above stands."""


_EARLY_END_RULES = """
- Early end. Besides turn {limit}, the match ends (and the leader wins) when
  the leader's lead can no longer be overcome, or when the lead is at least
  {pct}% of "max_swing" for {turns} turns in a row, counting from turn {start}.
  max_swing is the most the gap could still close by: everything the trailing
  team could still win in the turns left (each open mission, each control
  point it does not own, the Crown, every resource still on the board or in
  cargo, counting only what a unit could still reach in time) plus every
  control point the leader could still lose. The state's "standing" block
  shows points, leader, lead, max_swing and the leader's current run
  ("lead_hold") every turn, so both teams see exactly where this stands."""


def _has_thief(scenario: Mapping[str, Any]) -> bool:
    return any(r.get("can_steal") for r in scenario.get("roles", {}).values())


def _verbs(scenario: Mapping[str, Any]) -> str:
    """The action-verb hint in the reply format: steal appears only on a board
    that fields a thief, so thief-free prompts are unchanged."""
    return "move|gather|deliver|steal|hold" if _has_thief(scenario) else "move|gather|deliver|hold"


def _reply_schema(scenario: Mapping[str, Any]) -> dict[str, Any]:
    """The seat reply format as a JSON schema, for drivers that opt into
    structured output (``"structured_output": true``): the serving side then
    constrains the reply to it, so a JSON slip cannot happen. Same schema for
    every seat on the board; it encodes the format the prompt already asks
    for, nothing more."""
    return {
        "type": "object",
        "properties": {
            "action": {
                "type": "object",
                "properties": {
                    "unit_id": {"type": "string"},
                    "action": {"type": "string", "enum": _verbs(scenario).split("|")},
                    "to": {"type": "array", "items": {"type": "integer"}},
                    "target": {"type": "string"},
                },
                "required": ["action"],
                "additionalProperties": False,
            },
            "messages": {"type": "array", "items": {"type": "string"}},
            "plan": {"type": "string"},
        },
        "required": ["action"],
        "additionalProperties": False,
    }


def _rules_text(scenario: Mapping[str, Any], fog: bool) -> str:
    """The rules block for a seat: the complete rules, plus the crown, thief
    and fog paragraphs only when they apply."""
    text = _RULES.format(capture=scenario["capture_hold_turns"])
    crown = scenario.get("crown")
    if crown:
        shared = any(
            m.get("kind") == "deliver" and list(m.get("pos", ())) == list(crown["pos"])
            for m in scenario.get("missions", [])
        )
        text += _CROWN_RULES.format(
            pos=list(crown["pos"]),
            turns=crown["hold_turns"],
            value=crown["value"],
            shared=" (the same cell as the deliver mission)" if shared else "",
            delivering=(
                " Enemy units delivering resources stand on this same cell." if shared else ""
            ),
        )
    if any(m.get("side") is not None for m in scenario.get("missions", [])):
        text += _HOME_DELIVERY_RULES
    if _has_thief(scenario):
        text += _THIEF_RULES.format()
    early = scenario.get("early_end")
    if early:
        text += _EARLY_END_RULES.format(
            limit=scenario.get("turn_limit"),
            pct=early["ratio_pct"],
            turns=early["turns"],
            start=early["from_turn"],
        )
    if fog and scenario.get("cp_vision"):
        text += _FOG_RULES + _CP_VISION_RULES.format(radius=scenario["cp_vision"])
        return text
    return text + _FOG_RULES if fog else text


_PROMPT = """You are the {team_id} team commander in a League of Agents match.
{rules}
{extra}
Scenario: {scenario}
{rejections}{legal_actions}
Current match state (JSON):
{state}

You command team {team_id}. Reply with ONLY one JSON object, no prose:
{{"plan": "<optional standing plan>",
  "messages": [{{"from": "<agent-id>", "text": "..."}}],
  "actions": [{{"unit_id": "...", "action": "{verbs}",
               "to": [x, y]}}]}}
"""

_SOLO_NOTE = """
IMPORTANT HANDICAP: you are playing solo. You may issue an action for at most
ONE unit this turn (any extra actions will be discarded). Your other units can
only stand where they are. Choose the single action that matters most.
"""

_SEAT_PROMPT = """You are agent {agent_id}, one member of team {team_id} in a
League of Agents match. You control ONLY unit {unit_id} (role: {role}).
{rules}
{extra}
Scenario: {scenario}
{rejections}{legal_actions}
Current match state (JSON):
{state}

Messages your teammates already sent this turn:
{team_messages}

Coordinate through messages; you cannot command other units. Reply with ONLY
one JSON object, no prose:
{{"action": {{"unit_id": "{unit_id}", "action": "{verbs}",
             "to": [x, y]}},
  "messages": ["<optional message to your team>", "..."],
  "plan": "<optional; only if proposing/refreshing the team plan>"}}
Each message is a plain string; it is signed as {agent_id} for you.
"""

_MASTER_PROMPT = """You are {master_id}, the {team_id} team's ORCHESTRATOR/MASTER. This is a
DECLARED capability of orchestrator mode (spec c4/h3), never a hidden
privilege — it is recorded in the match config and log. You command no unit
directly: your only tool is guidance messages relayed to your ground units.
{rules}
{extra}
Scenario: {scenario}
Current match state (JSON):
{state}

{comms_note}
Reply with ONLY one JSON object, no prose:
{{"messages": [{{"from": "{master_id}", "text": "..."}}],
  "plan": "<optional standing plan>"}}
"""


# -- rejection feedback + legal-actions citation (spec c8/h5) ---------------
#
# Without this, a seat whose order is rejected never learns why: the engine
# emits an ``action_rejected`` event with a plain-English ``reason``, but that
# reason never made it into the next briefing — a weak model just repeats the
# same illegal move for the whole match (19 of 53 orders in the season-0
# coordination playtest). ``run_match`` reads ``last_turn_rejections`` and
# ``legal_actions`` off ``match show --json`` (league/engine/legal.py, wired
# in ``match show`` by task t1) each turn and hands both to every driver as a
# ``context`` mapping, so a seat can both see *why* its last order failed and
# check what is legal *before* declaring the next one.


def _rejections_for(
    rejections: list[Mapping[str, Any]],
    *,
    team_id: str | None = None,
    unit_id: str | None = None,
) -> list[Mapping[str, Any]]:
    """Narrow last-turn ``action_rejected`` rows to one team and/or unit."""
    return [
        r
        for r in rejections
        if (team_id is None or r.get("team_id") == team_id)
        and (unit_id is None or r.get("unit_id") == unit_id)
    ]


def _format_rejections(rejections: list[Mapping[str, Any]]) -> str:
    """A REJECTIONS section citing the engine's own reason text verbatim."""
    # A passive row is not a rejected order: the engine notes that a unit
    # whose role cannot capture is standing on a control point (its move or
    # hold succeeded). Telling the seat its order was rejected would be false.
    real = [r for r in rejections if not r.get("passive")]
    notes = [r for r in rejections if r.get("passive")]
    out = ""
    if real:
        lines = "\n".join(f"- {r.get('unit_id')}: {r.get('reason')}" for r in real)
        out += (
            "\nREJECTIONS from your last turn — the engine's own reason, so you "
            f"don't repeat it:\n{lines}\n"
        )
    if notes:
        lines = "\n".join(
            f"- {r.get('unit_id')} stands on a control point, but {r.get('reason')}: "
            "its order was carried out; it just does not count toward capture"
            for r in notes
        )
        out += f"\nNOTES (not rejections) from your last turn:\n{lines}\n"
    return out


def _unit_positions(state: Mapping[str, Any]) -> dict[str, list[int]]:
    return {u["id"]: list(u["pos"]) for u in state.get("units", []) if u.get("pos")}


def _format_move_targets(moves: list[Any], pos: list[int] | None = None) -> str:
    """The legal move targets, exactly. A short list is printed as is; a long
    one as the Manhattan rule from the unit's cell, which is exact (a bounding
    box was not: it invited diagonal targets the engine rejects)."""
    if len(moves) <= 8:
        return json.dumps(moves)
    if pos is None:
        return json.dumps(moves)
    ux, uy = pos
    reach = max(abs(x - ux) + abs(y - uy) for x, y in moves)
    return (
        f"{len(moves)} cells: any on-grid [x, y] with |x-{ux}| + |y-{uy}| <= {reach} "
        f"(steps add up: 2 across and 2 up is 4, not 2)"
    )


def _format_legal_actions(
    legal_actions: Mapping[str, Any],
    unit_ids: list[str],
    positions: Mapping[str, list[int]] | None = None,
) -> str:
    """A compact 'legal now' line per unit — checkable before declaring, not
    just discovered after the engine rejects it."""
    lines = []
    for unit_id in unit_ids:
        legal = legal_actions.get(unit_id)
        if legal is None:
            continue
        steal = ""
        if legal.get("can_steal"):
            steal = f"; steal: {'yes' if legal.get('steal') else 'no (full)'}"
        lines.append(
            f"- {unit_id}: move to "
            f"{_format_move_targets(legal.get('move', []), (positions or {}).get(unit_id))}; "
            f"gather: {'yes' if legal.get('gather') else 'no'}; "
            f"deliver: {'yes' if legal.get('deliver') else 'no'}{steal}; hold: yes"
        )
    if not lines:
        return ""
    return "\nLegal actions right now:\n" + "\n".join(lines) + "\n"


# -- fog of war: briefing-boundary enforcement (plan t5, spec c5/h4) --------
#
# Fog is a HARNESS-layer projection only: league/engine (the tick, vision,
# knowledge fold) stays full-information and deterministic — see the module
# docstring's "Fog of war" section for the whole picture. The two pieces
# below are what a `command`/`resident` driver's PROMPT TEXT must never leak
# once fog is on: the once-per-match "Scenario:" block (which otherwise
# dumps every control point / mission / resource node position up front,
# regardless of vision) and the resident driver's per-turn delta (which
# otherwise reads the raw event log — every team's moves, regardless of
# vision). `run_match` separately swaps the "state" argument itself for the
# team's fogged view via `match show --team <id> --fog --json`
# (league/cli/_commands/match.py's `_fogged_state`) before ever calling a
# driver — these two helpers close the two OTHER leaks that live in this
# module's own prompt-building code.


def _fogged_scenario(scenario: Mapping[str, Any]) -> dict[str, Any]:
    """The once-per-match rules block under fog: drop map furniture positions
    (control points, missions, resource nodes) so a fresh seat starts knowing
    only the universal rules — grid size, role stats, capture/turn limits —
    never the board. Furniture and objectives are learned the same way live
    state is: a unit's own sightings and named teammate/master messages
    (``league.engine.knowledge``), surfaced turn to turn in the fogged
    ``state``/delta blocks around this one.
    """
    _redacted = ("control_points", "missions", "resource_nodes")
    fogged = {k: v for k, v in scenario.items() if k not in _redacted}
    fogged["fog_of_war"] = (
        "on — control points, missions, and resource nodes are not listed here; "
        "you learn them only when your own units see them or a teammate/master "
        "message names them (watch your state/knowledge as the match unfolds)."
    )
    return fogged


def _knowledge_delta(
    prev: Mapping[str, Any] | None, current: Mapping[str, Any]
) -> dict[str, list[Any]]:
    """Facts a team's knowledge fold added or refreshed since ``prev`` — the
    resident driver's fog delta (spec c5/h4): everything newly seen or told
    since this seat's last successful turn, nothing it already had. Both
    arguments are ``KnowledgeFrame.to_dict()`` shapes (or ``None`` for "never
    briefed before"), fetched off the public CLI surface
    (``match show --team <id> --fog --json``)'s ``"knowledge"`` key — this
    module never imports ``league.engine.knowledge`` directly.
    """

    def _changed(key: str) -> list[Any]:
        before = {fact["id"]: fact for fact in (prev or {}).get(key, [])}
        return [fact for fact in current.get(key, []) if before.get(fact["id"]) != fact]

    return {
        "units": _changed("units"),
        "resource_nodes": _changed("resource_nodes"),
        "control_points": _changed("control_points"),
    }


def _as_list(value: Any) -> list[Any]:
    """A driver's JSON is untrusted input: a field declared as a list in the
    protocol may come back as a dict, string, or number. Coerce to an empty
    list rather than let a type mismatch raise downstream — malformed driver
    output should idle the team, not crash the match loop."""
    return value if isinstance(value, list) else []


def _extract_json(text: str) -> dict[str, Any]:
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


_JSON_STR = r'"(?:[^"\\]|\\.)*"'
_PLAN_RE = re.compile(r'"plan"\s*:\s*(' + _JSON_STR + ")")
# A message as seats write it, even when its object is missing a brace.
_MESSAGE_RE = re.compile(
    r'"from"\s*:\s*(' + _JSON_STR + r')\s*,\s*"text"\s*:\s*(' + _JSON_STR + ")"
)


def _messages_array_strings(text: str, decoder: json.JSONDecoder) -> list[str]:
    """The plain-string items of a reply's ``"messages": [...]`` array, read
    one by one so a missing or trailing comma does not lose them."""
    head = re.search(r'"messages"\s*:\s*\[', text)
    if not head:
        return []
    out: list[str] = []
    i = head.end()
    while i < len(text):
        while i < len(text) and text[i] in " \t\r\n,":
            i += 1
        if i >= len(text) or text[i] != '"':
            break
        try:
            item, i = decoder.raw_decode(text, i)
        except json.JSONDecodeError:
            break
        out.append(item)
    return out


def _parse_seat_reply(text: str) -> tuple[dict[str, Any], str | None, str | None]:
    """A resident seat's reply as orders, plus two notes: what the seat must be
    told (something was lost), and what the audit record keeps (any repair).

    A reply the harness can still read is the harness's job to read: a JSON
    slip such as a message object missing its closing brace must not cost the
    seat its order. On a parse failure the reply's parts are recovered one by
    one: the action object, every message object, and the plan string. Only
    when no action can be read is the seat told, and its unit idles.
    """
    decoder = json.JSONDecoder()
    start = text.find("{")
    if start < 0:
        note = "your reply contained no JSON object, so your unit idled"
        return {}, note, note
    try:
        obj, _ = decoder.raw_decode(text[start:])
    except json.JSONDecodeError as err:
        error = f"{err.msg} at line {err.lineno} column {err.colno}"
    else:
        if isinstance(obj, dict):
            action = obj.get("action")
            if action is None or isinstance(action, dict):
                return obj, None, None
            if isinstance(action, str):  # a flat action: {"action": "move", "to": [...]}
                flat = {k: v for k, v in obj.items() if k not in ("messages", "plan")}
                rest = {k: obj[k] for k in ("messages", "plan") if k in obj}
                return {"action": flat, **rest}, None, "read a flat action object"
        error = "the reply is not a JSON object"
    action: dict[str, Any] | None = None
    messages: list[Any] = []
    for i in range(start + 1, len(text)):
        if text[i] != "{":
            continue
        try:
            inner, _ = decoder.raw_decode(text[i:])
        except json.JSONDecodeError:
            continue
        if not isinstance(inner, dict):
            continue
        if action is None and isinstance(inner.get("action"), str):
            action = inner
        elif inner.get("text") and inner not in messages:
            messages.append(inner)
    found: list[Any] = [
        {"from": json.loads(m.group(1)), "text": json.loads(m.group(2))}
        for m in _MESSAGE_RE.finditer(text)
    ]
    if len(found) > len(messages):
        messages = found
    strings = _messages_array_strings(text, decoder)
    if len(strings) > len(messages):
        messages = strings
    result: dict[str, Any] = {}
    if messages:
        result["messages"] = messages
    plan = _PLAN_RE.search(text)
    if plan:
        result["plan"] = json.loads(plan.group(1))
    if action is None:
        note = (
            f"your reply was not valid JSON ({error}) and no action could be read, "
            "so your unit idled"
        )
        return result, note, note
    result["action"] = action
    parts = ", ".join(
        ["action"]
        + (["%d message(s)" % len(messages)] if messages else [])
        + (["plan"] if plan else [])
    )
    return result, None, f"repaired invalid JSON ({error}); recovered {parts}"


def _run_command(argv: list[str], prompt: str, timeout: float, who: str) -> dict[str, Any]:
    """One driver call, retried once — live seats flake; matches must not die.

    A second consecutive failure raises; the caller decides whether that seat
    simply idles this turn (per-seat/commander loops) or the run aborts.
    """
    last_error: Exception | None = None
    for _ in range(2):
        try:
            # Operator-configured argv, shell=False, bounded by timeout.
            proc = subprocess.run(  # nosec B603
                argv,
                input=prompt,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            if proc.returncode != 0:
                raise RuntimeError(
                    f"driver {argv[0]} for {who} failed (exit {proc.returncode}): "
                    f"{proc.stderr.strip()[:300]}"
                )
            return _extract_json(proc.stdout)
        except (RuntimeError, ValueError, subprocess.TimeoutExpired) as err:
            last_error = err
    raise RuntimeError(f"driver for {who} failed twice: {last_error}")


def make_command_driver(
    spec: Mapping[str, Any], scenario: dict[str, Any], *, fog: bool = False, map_read: str = "fog"
) -> Driver:
    argv = list(spec["argv"])
    timeout = float(spec.get("timeout", 300))
    solo = bool(spec.get("solo", False))
    extra = str(spec.get("prompt", ""))
    rules = _rules_text(scenario, fog)
    # The commander's whole team shares one fogged view (spec c5/h4): under
    # fog the once-per-turn "Scenario:" block drops map furniture too — see
    # _fogged_scenario. `state` itself is already the team's fogged
    # projection by the time it reaches here (run_match swaps it in per team
    # via `match show --team <id> --fog --json` before calling this driver).
    scenario_for_prompt = _fogged_scenario(scenario) if fog else scenario

    def orders(
        state: dict[str, Any],
        team_id: str,
        turn: int,
        context: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        context = context or {}
        my_unit_ids = [u["id"] for u in state.get("units", []) if u.get("team_id") == team_id]
        briefing_state, briefing_scenario = state, scenario_for_prompt
        if fog and map_read == "full":
            # Orchestrator mode's declared capability (plan t6, spec c4/h3):
            # this team's single commander mind reads the whole board even
            # though the match is fogged — a recorded exception (the match
            # log's `map_read`), never a silent one.
            match_id = str(state.get("match_id") or "")
            if match_id:
                briefing_state = _cli_json(["match", "show", match_id])["state"]
            briefing_scenario = scenario
        prompt = _PROMPT.format(
            team_id=team_id,
            rules=rules,
            extra=(_SOLO_NOTE if solo else "") + (f"\n{extra}\n" if extra else ""),
            scenario=json.dumps(briefing_scenario, sort_keys=True),
            rejections=_format_rejections(
                _rejections_for(context.get("rejections", []), team_id=team_id)
            ),
            legal_actions=_format_legal_actions(
                context.get("legal_actions", {}), my_unit_ids, _unit_positions(state)
            ),
            state=json.dumps(briefing_state, sort_keys=True),
            verbs=_verbs(scenario),
        )
        sink = _latency_sink(context)
        t0 = time.perf_counter()
        try:
            result = _run_command(argv, prompt, timeout, team_id)
        except RuntimeError as err:
            print(f"[harness] {team_id} commander idles this turn: {err}", file=sys.stderr)
            if sink is not None:
                # A failed/timed-out call still burned wall-clock time —
                # real tempo data, not something to drop on the idle path.
                sink.append({"agent_id": None, "unit_id": None, "elapsed_ms": _elapsed_ms(t0)})
            return {"actions": []}
        if sink is not None:
            # One commander mind for the whole team, whether or not `solo`
            # is set — team-wide "seat of one", same as bot/bot-file.
            sink.append({"agent_id": None, "unit_id": None, "elapsed_ms": _elapsed_ms(t0)})
        actions = _as_list(result.get("actions"))
        result["actions"] = actions[:1] if solo else actions  # solo: handicap enforced, not asked
        if "messages" in result:
            result["messages"] = _as_list(result["messages"])
        return result

    return orders


def _fold_seat_reply(
    combined: dict[str, Any], result: Mapping[str, Any], unit_id: str, agent_id: str
) -> None:
    """Fold one seat's reply into the team's orders — shared by every per-seat
    driver (command and resident): a seat commands its own unit only, its
    messages are attributed to it, and the first offered plan wins."""
    action = result.get("action")
    if isinstance(action, dict):
        action["unit_id"] = unit_id  # a seat commands its own unit, only
        combined["actions"].append(action)
    for message in _as_list(result.get("messages")):
        # A message is a plain string; the older {"from", "text"} object form
        # is still read. Either way the seat signs as itself.
        text = message.get("text") if isinstance(message, dict) else message
        if isinstance(text, str) and text.strip():
            combined["messages"].append({"from": agent_id, "text": text})
    if result.get("plan") and "plan" not in combined:
        combined["plan"] = str(result["plan"])


def make_per_seat_driver(
    spec: Mapping[str, Any],
    scenario: dict[str, Any],
    agents: list[dict[str, Any]],
    *,
    fog: bool = False,
    map_read: str = "fog",
    unit_comms: bool = True,
) -> Driver:
    """One independent mind per seat, coordinating only through messages.

    Seats are consulted in roster order each turn; every seat sees the shared
    state plus the messages teammates have queued so far this turn (its own
    channel to influence later seats). Each seat may command only its unit.
    Under fog the "shared state" every seat on this team sees is the TEAM's
    fogged view (run_match already swapped ``state`` for it per team), and
    the once-per-turn scenario block drops map furniture too — see
    :func:`_fogged_scenario`. Per-unit legal actions are unaffected: they
    always derive from that unit's own position, fog or not.

    Orchestrator mode for real (plan t6, spec c4/c6/h3/h5): an optional
    ``spec["master"]`` — ``{"argv": [...], "id": "<agent-id>", "timeout": N,
    "prompt": "..."}`` — runs once per turn, BEFORE any ground seat, and
    commands no unit; its messages are always attributed to its declared
    ``id`` (default ``f"{team_id}-master"``) regardless of what its own reply
    claims, mirroring :func:`_fold_seat_reply`'s discipline for every other
    seat's ``from``. Its briefing is this team's usual view UNLESS
    ``map_read`` is ``"full"`` *and* the match is fogged, in which case it
    fetches the plain (unfogged) board itself — a declared exception (spec
    c4/h3), never a silent one. ``unit_comms`` decides what a LATER ground
    seat's "teammates already sent" block is filtered to: ``False``
    (orchestrator mode's own default) keeps only messages ``from`` the master
    identity, dropping teammate chatter; ``True`` keeps today's unfiltered
    relay. Every seat's own messages still land in the match log either way —
    filtering only trims what a later seat is *shown*.
    """
    argv = list(spec["argv"])
    timeout = float(spec.get("timeout", 300))
    extra = str(spec.get("prompt", ""))
    rules = _rules_text(scenario, fog)
    scenario_for_prompt = _fogged_scenario(scenario) if fog else scenario
    seat_prompts = {a["id"]: str(a.get("prompt", "")) for a in agents}

    master_spec = spec.get("master")
    master_argv = list(master_spec["argv"]) if master_spec else None
    master_timeout = float(master_spec.get("timeout", timeout)) if master_spec else timeout
    master_extra = str(master_spec.get("prompt", "")) if master_spec else ""
    _comms_note = (
        "Unit-to-unit messaging is OFF this match — you are their only channel."
        if not unit_comms
        else "Units can also message each other directly this match."
    )

    def orders(
        state: dict[str, Any],
        team_id: str,
        turn: int,
        context: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        context = context or {}
        sink = _latency_sink(context)
        legal_actions = context.get("legal_actions", {})
        rejections = context.get("rejections", [])
        my_units = {
            u["agent_id"]: u for u in state["units"] if u["team_id"] == team_id and u["alive"]
        }
        combined: dict[str, Any] = {"actions": [], "messages": []}

        master_id = None
        if master_argv is not None:
            master_id = str(master_spec.get("id") or f"{team_id}-master")
            master_state, master_scenario = state, scenario_for_prompt
            if fog and map_read == "full":
                match_id = str(state.get("match_id") or "")
                if match_id:
                    master_state = _cli_json(["match", "show", match_id])["state"]
                master_scenario = scenario
            master_prompt = _MASTER_PROMPT.format(
                master_id=master_id,
                team_id=team_id,
                rules=rules,
                extra=f"\n{master_extra}\n" if master_extra else "",
                scenario=json.dumps(master_scenario, sort_keys=True),
                state=json.dumps(master_state, sort_keys=True),
                comms_note=_comms_note,
            )
            t0 = time.perf_counter()
            try:
                result = _run_command(master_argv, master_prompt, master_timeout, master_id)
            except RuntimeError as err:
                print(f"[harness] master {master_id} idles this turn: {err}", file=sys.stderr)
            else:
                for message in _as_list(result.get("messages")):
                    if isinstance(message, dict) and message.get("text"):
                        combined["messages"].append(
                            {"from": master_id, "text": str(message["text"])}
                        )
            if sink is not None:
                # The master commands no unit (its only tool is guidance
                # messages) — no unit_id, but its own agent identity.
                sink.append({"agent_id": master_id, "unit_id": None, "elapsed_ms": _elapsed_ms(t0)})

        for agent in agents:
            unit = my_units.get(agent["id"])
            if unit is None:
                continue
            seat_extra = "\n".join(part for part in (extra, seat_prompts[agent["id"]]) if part)
            visible_messages = (
                combined["messages"]
                if unit_comms
                else [m for m in combined["messages"] if m.get("from") == master_id]
            )
            prompt = _SEAT_PROMPT.format(
                agent_id=agent["id"],
                team_id=team_id,
                unit_id=unit["id"],
                role=unit["role"],
                rules=rules,
                extra=f"\n{seat_extra}\n" if seat_extra else "",
                scenario=json.dumps(scenario_for_prompt, sort_keys=True),
                rejections=_format_rejections(_rejections_for(rejections, unit_id=unit["id"])),
                legal_actions=_format_legal_actions(
                    legal_actions, [unit["id"]], _unit_positions(state)
                ),
                state=json.dumps(state, sort_keys=True),
                team_messages=json.dumps(visible_messages, sort_keys=True) or "[]",
                verbs=_verbs(scenario),
            )
            t0 = time.perf_counter()
            try:
                result = _run_command(argv, prompt, timeout, agent["id"])
            except RuntimeError as err:
                print(f"[harness] seat {agent['id']} idles this turn: {err}", file=sys.stderr)
                if sink is not None:
                    sink.append(
                        {
                            "agent_id": agent["id"],
                            "unit_id": unit["id"],
                            "elapsed_ms": _elapsed_ms(t0),
                        }
                    )
                continue
            if sink is not None:
                sink.append(
                    {"agent_id": agent["id"], "unit_id": unit["id"], "elapsed_ms": _elapsed_ms(t0)}
                )
            _fold_seat_reply(combined, result, unit["id"], agent["id"])
        if not combined["messages"]:
            combined.pop("messages")
        return combined

    return orders


# -- resident minds: one long-lived session per seat (plan task t5) ---------
#
# The session transport is abstracted behind SESSION_TRANSPORTS so tests
# inject a fake session and no test ever needs a live model endpoint; the
# real adapters below are thin shells over the exact invocations the t3 spike
# proved live (docs/specs/notes/cultureagent-spike.md).


def _mint_session_id(match_id: str, agent_id: str) -> str:
    """A deterministic, UUID-shaped session id from (match, seat).

    Deterministic on purpose: a crashed harness re-mints the same id for the
    same seat, so ``claude -p --resume`` picks the conversation back up
    mid-match (the spike's crash-resume property). ``hashlib`` keeps the
    engine-wide no-``uuid``/no-``random`` determinism rule intact.
    """
    digest = hashlib.sha256(f"{match_id}/{agent_id}".encode("utf-8")).hexdigest()
    return f"{digest[:8]}-{digest[8:12]}-4{digest[13:16]}-8{digest[17:20]}-{digest[20:32]}"


class ClaudeCliSession:
    """A claude seat: the spike's proven zero-dependency fallback transport.

    ``claude -p --session-id <minted>`` on the first send, ``--resume`` on
    every later one — mechanically the same session loop cultureagent's
    ``AgentRunner`` runs internally, but owned by this driver so league's
    runtime never imports the culture venv (the spike's recorded trade-off).
    """

    transport = "claude-cli"

    def __init__(self, spec: Mapping[str, Any], match_id: str, agent_id: str) -> None:
        self._command = str(spec.get("command", "claude"))
        self._model = spec.get("model")
        # Extra CLI flags (e.g. --effort, --tools "") and a system prompt that
        # REPLACES the CLI's own, so a claude seat and an HTTP seat can be
        # handed the identical system prompt (fairness across transports).
        self._args = [str(a) for a in spec.get("args", [])]
        self._system_prompt = spec.get("system_prompt")
        self.session_id = _mint_session_id(match_id, agent_id)
        self._started = False
        # Set by the resident driver when the spec opts into structured output.
        self.reply_schema: dict[str, Any] | None = None

    def _argv(self, flag: str) -> list[str]:
        argv = [self._command, "-p", flag, self.session_id]
        if self.reply_schema is not None:
            argv += ["--json-schema", json.dumps(self.reply_schema, separators=(",", ":"))]
        if self._model:
            argv += ["--model", str(self._model)]
        if self._system_prompt:
            argv += ["--system-prompt", str(self._system_prompt)]
        return argv + self._args

    def _run(self, argv: list[str], prompt: str, timeout: float) -> subprocess.CompletedProcess:
        try:
            # Operator-configured command, shell=False, bounded by timeout.
            return subprocess.run(  # nosec B603
                argv, input=prompt, capture_output=True, text=True, timeout=timeout, check=False
            )
        except subprocess.TimeoutExpired as err:
            raise RuntimeError(
                f"claude-cli session {self.session_id} timed out after {timeout}s"
            ) from err

    def send(self, prompt: str, *, timeout: float) -> str:
        proc = self._run(
            self._argv("--resume" if self._started else "--session-id"), prompt, timeout
        )
        if proc.returncode != 0 and not self._started:
            # The deterministic id may already exist on disk (crashed match):
            # resume it instead of failing the seat.
            proc = self._run(self._argv("--resume"), prompt, timeout)
        if proc.returncode != 0:
            raise RuntimeError(
                f"claude-cli session {self.session_id} failed (exit {proc.returncode}): "
                f"{proc.stderr.strip()[:300]}"
            )
        self._started = True
        return proc.stdout


_DEFAULT_COLLEAGUE_BASE_URL = "http://localhost:8001/v1"


def _http_post_json(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    if not url.startswith(("http://", "https://")):
        raise RuntimeError(f"colleague-direct base_url must be http(s), got {url!r}")
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # nosec B310
        return json.load(response)


class ColleagueDirectSession:
    """A colleague seat: the driver-held transcript IS the session.

    Labeled ``colleague-direct`` everywhere it surfaces, never "cultureagent":
    the spike proved cultureagent's colleague backend mints a fresh task per
    message (no cross-message memory as shipped), so continuity lives in this
    ``messages`` list POSTed to the vLLM OpenAI endpoint — stdlib ``urllib``,
    zero dependencies, trivially auditable.
    """

    transport = "colleague-direct"

    def __init__(self, spec: Mapping[str, Any], match_id: str, agent_id: str) -> None:
        model = spec.get("model")
        if not model:
            raise ValueError("a 'colleague' resident transport needs a 'model' in the driver spec")
        self._model = str(model)
        self._base_url = str(
            spec.get("base_url")
            or os.environ.get("COLLEAGUE_BASE_URL", _DEFAULT_COLLEAGUE_BASE_URL)
        ).rstrip("/")
        self._temperature = float(spec.get("temperature", 0.6))
        self._top_p = spec.get("top_p")
        # "max_tokens": null in the spec means no cap: the field is omitted and
        # the server's own context window is the only limit.
        max_tokens = spec.get("max_tokens", 4096)
        self._max_tokens = None if max_tokens is None else int(max_tokens)
        self._chat_template_kwargs = spec.get("chat_template_kwargs")
        self._reasoning_fallback = bool(spec.get("reasoning_fallback", True))
        self.last_finish_reason: str | None = None
        self.last_usage: Any = None
        # The model's thinking for the last reply, kept for the audit record
        # only: it is never fed back into the transcript.
        self.last_reasoning: str | None = None
        # Set by the resident driver when the spec opts into structured output.
        self.reply_schema: dict[str, Any] | None = None
        self._history: list[dict[str, str]] = []
        if spec.get("system_prompt"):
            self._history.append({"role": "system", "content": str(spec["system_prompt"])})
        self.session_id = f"colleague-direct-{_mint_session_id(match_id, agent_id)}"

    def send(self, prompt: str, *, timeout: float) -> str:
        self.last_reasoning = None
        self._history.append({"role": "user", "content": prompt})
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": list(self._history),
            "temperature": self._temperature,
        }
        if self._max_tokens is not None:
            payload["max_tokens"] = self._max_tokens
        if self._top_p is not None:
            payload["top_p"] = float(self._top_p)
        if self._chat_template_kwargs:
            payload["chat_template_kwargs"] = dict(self._chat_template_kwargs)
        if self.reply_schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "seat_reply", "schema": self.reply_schema},
            }
        try:
            data = _http_post_json(f"{self._base_url}/chat/completions", payload, timeout)
        except OSError as err:
            # The model never saw this message — keep the transcript honest
            # so the next attempt isn't preceded by a phantom user turn.
            self._history.pop()
            raise RuntimeError(f"colleague-direct session {self.session_id}: {err}") from err
        choice = data["choices"][0]
        message = choice["message"]
        # The Qwen gotcha (spike, scripts/openai_driver.py): thinking models
        # may return content=None with the answer in reasoning_content. That
        # fallback is opt-in now: with "reasoning_fallback": false, a reply
        # that ran out of budget mid-thought stays empty (the seat idles and
        # the failure is visible) instead of feeding the raw reasoning back
        # into the transcript as if it were the answer.
        content = message.get("content") or ""
        inline = re.findall(r"<think>(.*?)</think>", content, flags=re.S)
        reasoning = message.get("reasoning_content") or "\n".join(t.strip() for t in inline)
        self.last_reasoning = reasoning or None
        if not content and self._reasoning_fallback:
            content = message.get("reasoning_content") or ""
        content = re.sub(r"<think>.*?</think>", "", content, flags=re.S).strip()
        self.last_finish_reason = choice.get("finish_reason")
        self.last_usage = data.get("usage")
        self._history.append({"role": "assistant", "content": content})
        if not content:
            raise RuntimeError(
                f"colleague-direct session {self.session_id}: empty answer "
                f"(finish_reason={self.last_finish_reason}, usage={self.last_usage})"
            )
        return content


# name -> factory(spec, match_id, agent_id). Tests register a fake here so no
# suite run ever touches a live endpoint; operators pick by spec["transport"].
SESSION_TRANSPORTS: dict[str, Callable[[Mapping[str, Any], str, str], Any]] = {
    "claude": ClaudeCliSession,
    "colleague": ColleagueDirectSession,
}

_RESIDENT_NOTE = """This is a resident session: it lasts the whole match. This turn-1 briefing is
the ONLY time you will see the rules and the scenario — remember them. Every
later turn sends only a delta: new events, your own rejections, your legal
actions, a compact state, and teammate messages.
If a reply has a JSON slip, the harness still reads whatever it can (your
action, messages and plan). Only if no action can be read does your unit
idle, and you are told so on your next turn."""

_RESIDENT_DELTA_PROMPT = """Turn {turn} — delta briefing (rules, scenario and role are unchanged
from turn 1; you still control ONLY unit {unit_id}).
New events since your last turn (JSON):
{events}
{rejections}{legal_actions}
Compact current state (JSON):
{state}

Messages your teammates already sent this turn:
{team_messages}

Reply as before: ONLY one JSON object — your single action for unit
{unit_id}, plus optional messages/plan.
"""


def _compact_state(state: Mapping[str, Any]) -> dict[str, Any]:
    """The delta's state snapshot: what changes turn to turn, nothing that was
    already taught (grid, roles, scenario constants stay in turn 1).

    Under fog, ``state["units"]`` mixes two shapes: this team's own units, in
    full, and a fog-of-war-known enemy unit (``KnowledgeFrame``'s
    ``KnownUnit.to_dict()``), whose ``carrying`` is its cargo as last seen and
    is absent for a told-only unit — genuinely unknown, not zero — hence
    ``.get`` here, never ``[...]``.
    """
    return {
        "turn": state.get("turn"),
        "status": state.get("status"),
        "winner": state.get("winner"),
        "teams": {t["id"]: {"resources": t["resources"]} for t in state.get("teams", [])},
        "units": [
            {
                "id": u["id"],
                "team_id": u["team_id"],
                "role": u["role"],
                "pos": u["pos"],
                "carrying": u.get("carrying"),
                "alive": u["alive"],
            }
            for u in state.get("units", [])
        ],
        "control_points": [
            {"id": c["id"], "pos": c["pos"], "owner": c.get("owner")}
            for c in state.get("control_points", [])
        ],
        "missions": [
            {
                "id": m["id"],
                "kind": m.get("kind"),
                "pos": m.get("pos"),
                "amount": m.get("amount"),
                "status": m.get("status"),
                **({"team_id": m["team_id"]} if m.get("team_id") else {}),
            }
            for m in state.get("missions", [])
        ],
        "resource_nodes": [
            {"id": n["id"], "pos": n["pos"], "remaining": n["remaining"]}
            for n in state.get("resource_nodes", [])
        ],
        **({"crown": state["crown"]} if state.get("crown") is not None else {}),
        **({"standing": state["standing"]} if state.get("standing") is not None else {}),
    }


_TEAM_PRIVATE_EVENTS = frozenset({"message_sent", "plan_declared"})


def _events_since(
    match_id: str, since_turn: int, upto_turn: int, team_id: str | None = None
) -> list[dict[str, Any]]:
    """Events a seat hasn't seen yet, read off the log via the public CLI
    (``match replay --json``) — the harness never opens the log file itself.

    With ``team_id``, the other team's messages and declared plans are
    dropped: they are team-private, and a resident seat must not read the
    opponent's coordination off the shared log."""
    if not match_id:
        return []
    events_by_turn = _cli_json(["match", "replay", match_id]).get("events_by_turn", {})
    return [
        {"turn": int(turn), **event}
        for turn in sorted(events_by_turn, key=int)
        if since_turn < int(turn) <= upto_turn
        for event in events_by_turn[turn]
        if team_id is None
        or event.get("kind") not in _TEAM_PRIVATE_EVENTS
        or (event.get("data") or {}).get("team_id") == team_id
    ]


_SEAT_META = (
    ("finish_reason", "last_finish_reason"),
    ("usage", "last_usage"),
    ("reasoning", "last_reasoning"),
)


def _seat_meta(session: Any) -> dict[str, Any]:
    """What the session knows about its last reply, for the audit record:
    finish reason, token usage and, when the model exposes it, its thinking.
    Absent fields are left out, so records from sessions that expose nothing
    (the Claude CLI) keep their old shape."""
    return {k: getattr(session, a) for k, a in _SEAT_META if getattr(session, a, None) is not None}


def make_resident_driver(
    spec: Mapping[str, Any],
    scenario: dict[str, Any],
    agents: list[dict[str, Any]],
    *,
    fog: bool = False,
) -> Driver:
    """One long-lived session per seat for the whole match (per-seat by
    definition). Turn 1 = full briefing into a fresh session; turn N>1 = delta
    only, into the SAME session. Every exchange (and every failure) is
    appended to ``.league/matches/<id>/sessions/<agent-id>.jsonl`` for audit.

    Under fog (spec c5/h4): the once-per-match scenario block drops map
    furniture (:func:`_fogged_scenario`), ``state`` itself is already this
    team's fogged view (``run_match`` swaps it in before calling this
    driver), and the delta's "new events" section becomes newly-seen/
    newly-told facts since this seat's last successful turn
    (:func:`_knowledge_delta`) instead of the raw log — the raw log would
    otherwise show every team's moves regardless of vision. Legal actions are
    unaffected: a unit always knows its own, fog or not.
    """
    transport = spec.get("transport")
    if transport not in SESSION_TRANSPORTS:
        raise ValueError(
            f"unknown resident transport {transport!r}; "
            f"expected one of {sorted(SESSION_TRANSPORTS)}"
        )
    timeout = float(spec.get("timeout", 300))
    extra = str(spec.get("prompt", ""))
    rules = _rules_text(scenario, fog)
    scenario_for_prompt = _fogged_scenario(scenario) if fog else scenario
    seat_prompts = {a["id"]: str(a.get("prompt", "")) for a in agents}
    sessions: dict[str, Any] = {}
    briefed: set[str] = set()  # seats whose session has actually seen the rules
    reply_notes: dict[str, str] = {}  # a seat's last reply problem, told once on its next turn
    structured = spec.get("structured_output", False)
    if not isinstance(structured, bool):
        raise ValueError(f"structured_output must be true or false, got {structured!r}")
    reply_schema = _reply_schema(scenario)
    last_seen: dict[str, int] = {}  # state turn at the seat's last successful briefing
    last_known: dict[str, Mapping[str, Any]] = {}  # fog only: last knowledge snapshot per seat

    def _full_briefing(agent: dict[str, Any], unit: dict[str, Any], **fields: Any) -> str:
        seat_extra = "\n".join(
            part for part in (_RESIDENT_NOTE, extra, seat_prompts[agent["id"]]) if part
        )
        return _SEAT_PROMPT.format(
            agent_id=agent["id"],
            team_id=unit["team_id"],
            unit_id=unit["id"],
            role=unit["role"],
            rules=rules,
            extra=f"\n{seat_extra}\n",
            scenario=json.dumps(scenario_for_prompt, sort_keys=True),
            verbs=_verbs(scenario),
            **fields,
        )

    def orders(
        state: dict[str, Any],
        team_id: str,
        turn: int,
        context: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        context = context or {}
        sink = _latency_sink(context)
        legal_actions = context.get("legal_actions", {})
        rejections = context.get("rejections", [])
        match_id = str(state.get("match_id") or "")
        store = Store()
        my_units = {
            u["agent_id"]: u for u in state["units"] if u["team_id"] == team_id and u["alive"]
        }
        new_events: dict[str, list[dict[str, Any]]] = {}  # per since-turn, fetched lazily
        # One team-wide knowledge snapshot per turn (every seat on a team
        # shares the same fold; league/engine/knowledge.py is team-scoped).
        current_knowledge: Mapping[str, Any] | None = None
        if fog and match_id:
            current_knowledge = _cli_json(["match", "show", match_id, "--team", team_id, "--fog"])[
                "knowledge"
            ]
        combined: dict[str, Any] = {"actions": [], "messages": []}
        for agent in agents:
            unit = my_units.get(agent["id"])
            if unit is None:
                continue
            session = sessions.get(agent["id"])
            if session is None:
                session = SESSION_TRANSPORTS[transport](spec, match_id, agent["id"])
                if structured and hasattr(session, "reply_schema"):
                    session.reply_schema = reply_schema
                sessions[agent["id"]] = session
            note = reply_notes.get(agent["id"])
            shared = {
                "rejections": (f"About your previous reply: {note}.\n" if note else "")
                + _format_rejections(_rejections_for(rejections, unit_id=unit["id"])),
                "legal_actions": _format_legal_actions(
                    legal_actions, [unit["id"]], _unit_positions(state)
                ),
                "team_messages": json.dumps(combined["messages"], sort_keys=True),
            }
            if agent["id"] not in briefed:
                # First contact (or every prior attempt failed): the seat has
                # never seen the rules, so it gets the full briefing — never a
                # delta it can't ground.
                prompt = _full_briefing(
                    agent, unit, state=json.dumps(state, sort_keys=True), **shared
                )
            elif fog:
                delta = _knowledge_delta(last_known.get(agent["id"]), current_knowledge or {})
                prompt = _RESIDENT_DELTA_PROMPT.format(
                    turn=turn,
                    unit_id=unit["id"],
                    events=json.dumps(delta, sort_keys=True),
                    state=json.dumps(_compact_state(state), sort_keys=True),
                    **shared,
                )
            else:
                since = last_seen.get(agent["id"], 0)
                if str(since) not in new_events:
                    new_events[str(since)] = _events_since(match_id, since, state["turn"], team_id)
                prompt = _RESIDENT_DELTA_PROMPT.format(
                    turn=turn,
                    unit_id=unit["id"],
                    events=json.dumps(new_events[str(since)], sort_keys=True),
                    state=json.dumps(_compact_state(state), sort_keys=True),
                    **shared,
                )
            record = {
                "turn": turn,
                "agent_id": agent["id"],
                "session_id": session.session_id,
                "transport": session.transport,
                "sent": prompt,
            }
            t0 = time.perf_counter()
            try:
                reply = session.send(prompt, timeout=timeout)
            except RuntimeError as err:
                if match_id:
                    store.append_session_record(
                        match_id, agent["id"], {**record, "error": str(err), **_seat_meta(session)}
                    )
                print(f"[harness] seat {agent['id']} idles this turn: {err}", file=sys.stderr)
                if sink is not None:
                    sink.append(
                        {
                            "agent_id": agent["id"],
                            "unit_id": unit["id"],
                            "elapsed_ms": _elapsed_ms(t0),
                        }
                    )
                continue
            if sink is not None:
                sink.append(
                    {"agent_id": agent["id"], "unit_id": unit["id"], "elapsed_ms": _elapsed_ms(t0)}
                )
            reply_notes.pop(agent["id"], None)  # the seat saw it in this prompt
            result, problem, repair = _parse_seat_reply(reply)
            if match_id:
                extra = {"reply_problem": repair} if repair else {}
                store.append_session_record(
                    match_id,
                    agent["id"],
                    {**record, "received": reply, **_seat_meta(session), **extra},
                )
            briefed.add(agent["id"])
            last_seen[agent["id"]] = state["turn"]
            if fog and current_knowledge is not None:
                last_known[agent["id"]] = current_knowledge
            if problem:
                reply_notes[agent["id"]] = problem
            if repair:
                print(f"[harness] seat {agent['id']}: {repair}", file=sys.stderr)
            _fold_seat_reply(combined, result, unit["id"], agent["id"])
        if not combined["messages"]:
            combined.pop("messages")
        return combined

    return orders


def build_driver(
    spec: Mapping[str, Any],
    scenario: dict[str, Any],
    agents: list[dict[str, Any]] | None = None,
    *,
    fog: bool = False,
    map_read: str = "fog",
    unit_comms: bool = True,
) -> Driver:
    """``fog`` only reaches the ``command``/``resident`` factories — bot and
    bot-file drivers stay full-information regardless (documented asymmetry,
    see the module docstring's "Fog of war" section). ``map_read``/
    ``unit_comms`` are orchestrator mode's declared fairness axes (plan t6,
    spec c4/c6/h3/h5) and only reach a ``command`` driver (plain or
    per-seat) — see :func:`make_command_driver`/:func:`make_per_seat_driver`.
    """
    kind = spec.get("type")
    if spec.get("per_seat") and kind not in ("command", "resident"):
        raise ValueError("per_seat is only supported for 'command' and 'resident' drivers")
    if kind == "bot":
        return make_bot_driver(scenario)
    if kind == "bot-file":
        return make_bot_file_driver(spec)
    if kind == "resident":  # per-seat by definition
        return make_resident_driver(spec, scenario, agents or [], fog=fog)
    if kind == "command" and spec.get("per_seat"):
        return make_per_seat_driver(
            spec, scenario, agents or [], fog=fog, map_read=map_read, unit_comms=unit_comms
        )
    if kind == "command":
        return make_command_driver(spec, scenario, fog=fog, map_read=map_read)
    raise ValueError(
        f"unknown driver type {kind!r}; expected 'bot', 'bot-file', 'command' or 'resident'"
    )


# -- residency: the declared fairness axis (spec c10/h7) --------------------

DRIVER_KINDS = ("bot", "stateless", "resident")


def driver_kind(spec: Mapping[str, Any]) -> str:
    """The residency label recorded for a team's driver — metadata about HOW its
    minds were invoked, never game state (it never touches ``MatchState``).

    ``bot`` drivers are always ``"bot"``; ``bot-file`` drivers (coded
    strategies loaded from ``bots/``) are ALSO ``"bot"`` — same fairness
    axis, just a different, committed-source policy instead of the in-harness
    greedy one. ``resident`` drivers are always ``"resident"`` — one
    persistent session per seat for the whole match
    (:func:`make_resident_driver`). ``command`` drivers default to
    ``"stateless"`` (fresh subprocess per turn) unless the spec declares
    ``"residency": "resident"`` — e.g. a command whose own process holds
    per-seat sessions.
    """
    kind = spec.get("type")
    if kind in ("bot", "bot-file"):
        return "bot"
    if kind == "resident":
        return "resident"
    if kind == "command":
        residency = spec.get("residency", "stateless")
        if residency not in ("stateless", "resident"):
            raise ValueError(
                f"unknown residency {residency!r} for a command driver; "
                "expected 'stateless' or 'resident'"
            )
        return residency
    raise ValueError(
        f"unknown driver type {kind!r}; expected 'bot', 'bot-file', 'command' or 'resident'"
    )


# -- the run loop -----------------------------------------------------------


def _append_seat_latency(match_id: str, records: list[dict[str, Any]]) -> None:
    """Append one turn's per-seat/per-team wall-clock timings as
    ``seat_latency`` OBSERVATION events (``league.engine.events`` — a fold
    no-op by construction, so MatchState/state_hash are exactly as if they
    were never written; spec c10/h9).

    Appended straight to the store, never through the CLI's ``--orders-json``
    contract: this is harness-owned instrumentation, not a driver's declared
    move, the same reasoning that already lets the resident driver append
    session transcripts directly (``Store.append_session_record``). ``seq``
    continues from the log's current length so it never collides with the
    seq range the tick just assigned this same turn's real events.
    """
    if not records:
        return
    store = Store()
    log = store.load_match(match_id)
    seq = len(log.events)
    events = tuple(
        Event(
            turn=int(record["turn"]),
            seq=seq + i,
            kind="seat_latency",
            data={
                "team_id": record["team_id"],
                "agent_id": record.get("agent_id"),
                "unit_id": record.get("unit_id"),
                "elapsed_ms": int(record["elapsed_ms"]),
            },
        )
        for i, record in enumerate(records)
    )
    store.append_events(match_id, events)


def run_match(config: Mapping[str, Any], *, on_turn: Callable[[dict], None] | None = None) -> dict:
    """Register teams, create the match, and drive it to completion via the CLI.

    Resumable: if the configured match id already exists on disk, the loop
    picks up from its current turn instead of failing — live matches can
    outlast a shell window, and a crashed run must not orphan the game.
    """
    match_cfg = config["match"]
    scenario = _cli_json(["arena", "show", match_cfg["scenario"]])
    # Fog of war (plan t5, spec c5/h4) — see the module docstring's "Fog of
    # war" section for the whole picture: a harness-layer-only projection,
    # never touching league/engine.
    fog = bool(config.get("fog", False))

    existing = {row["match_id"] for row in _cli_json(["match", "list"])["matches"]}
    if match_cfg.get("id") in existing:
        match_id = match_cfg["id"]
    else:
        for team in config["teams"]:
            argv = ["team", "register", team["id"], "--name", team.get("name", team["id"])]
            for agent in team["agents"]:
                argv += ["--agent", f"{agent['id']}:{agent['model']}:{agent['role']}"]
            _cli_json(argv + ["--apply"])

        new_argv = [
            "match",
            "new",
            "--scenario",
            match_cfg["scenario"],
            "--mode",
            match_cfg.get("mode", "competitive"),
            "--seed",
            str(match_cfg.get("seed", 1)),
        ]
        for team in config["teams"]:
            new_argv += ["--team", team["id"]]
        if match_cfg.get("id"):
            new_argv += ["--id", match_cfg["id"]]
        for team in config["teams"]:
            new_argv += ["--driver", f"{team['id']}:{driver_kind(team['driver'])}"]
            # Orchestrator mode's two declared fairness axes (plan t6, spec
            # c4/c6/h3/h5): only echoed when a team's config actually opts
            # in — same "omit it and it's simply unrecorded" contract
            # ``--driver`` already has.
            if "map_read" in team:
                new_argv += ["--map-read", f"{team['id']}:{team['map_read']}"]
            if "unit_comms" in team:
                comms = "on" if team["unit_comms"] else "off"
                new_argv += ["--unit-comms", f"{team['id']}:{comms}"]
            # Mode/handicap fairness (issue #29): a DECLARED profile — same
            # opt-in contract as map_read/unit_comms above — persisted as a
            # match log header field so a raw `match act` against this same
            # match is held to it too, not only this driver's own client-side
            # truncation (e.g. the solo preset's "solo": True handicap).
            if "max_actions" in team:
                new_argv += ["--max-actions", f"{team['id']}:{team['max_actions']}"]
        created = _cli_json(new_argv + ["--apply"])
        match_id = created["match_id"]

    drivers = {
        t["id"]: build_driver(
            t["driver"],
            scenario,
            t.get("agents"),
            fog=fog,
            map_read=t.get("map_read", "fog"),
            unit_comms=t.get("unit_comms", True),
        )
        for t in config["teams"]
    }
    driver_types = {t["id"]: t["driver"].get("type") for t in config["teams"]}
    max_rounds = int(config.get("max_rounds", scenario["turn_limit"] + 2))

    for _ in range(max_rounds):
        shown = _cli_json(["match", "show", match_id])
        state = shown["state"]
        if state["status"] != "active":
            break
        turn = state["turn"] + 1
        # Rejection feedback + legal-actions citation (spec c8/h5): every
        # driver gets the prior turn's rejections and the current legal-move
        # surface, straight off the public `match show --json` projection —
        # no bypassing the CLI to read the log directly.
        context = {
            "legal_actions": shown.get("legal_actions", {}),
            "rejections": shown.get("last_turn_rejections", []),
        }
        # Latency metadata (plan t1, spec c10/h9): a fresh sink per team this
        # turn, threaded in via `context["_latency_sink"]` — never a new
        # field on what a driver returns (see the "latency" section above
        # make_bot_driver). Appended to the on-disk log below, once this
        # turn's real events are already written, so seq numbers never
        # collide with the tick's own.
        turn_latency: list[dict[str, Any]] = []
        for team in config["teams"]:
            team_id = team["id"]
            # Fog boundary (spec c5/h4): a command/resident seat is fed that
            # team's own fogged view — its vision + accumulated knowledge,
            # never the shared full-board `state`/`context` above. Bot/
            # bot-file drivers are handed the shared full state here
            # regardless (documented asymmetry, module docstring) — a
            # bot-file spec with "fogged": true (plan t3) ignores it anyway
            # and fetches its own team-scoped fog view internally
            # (make_bot_file_driver), so this loop needs no branch for it.
            if fog and driver_types[team_id] in ("command", "resident"):
                team_shown = _cli_json(["match", "show", match_id, "--team", team_id, "--fog"])
                team_state = team_shown["state"]
                team_context = {
                    "legal_actions": team_shown.get("legal_actions", {}),
                    "rejections": team_shown.get("last_turn_rejections", []),
                }
            else:
                team_state, team_context = state, dict(context)
            latency_sink: list[dict[str, Any]] = []
            team_context["_latency_sink"] = latency_sink
            orders = drivers[team_id](team_state, team_id, turn, team_context)
            acted = _cli_json(
                [
                    "match",
                    "act",
                    match_id,
                    "--team",
                    team_id,
                    "--orders-json",
                    json.dumps(orders),
                    "--apply",
                ]
            )
            for record in latency_sink:
                turn_latency.append({"team_id": team_id, "turn": turn, **record})
            if acted.get("resolution") and on_turn is not None:
                on_turn(acted["resolution"])
        if turn_latency:
            _append_seat_latency(match_id, turn_latency)

    final = _cli_json(["match", "show", match_id])["state"]
    score = _cli_json(["match", "score", match_id])
    return {
        "match_id": match_id,
        "status": final["status"],
        "turns_played": final["turn"],
        "winner": final["winner"],
        "score": score,
    }
