"""The agent-player harness — live teams drive a match through the CLI.

Every driver interacts with the arena **only** via the public CLI surface
(``league match show --json`` → orders → ``league match act --orders-json
--apply``), so whatever plays here plays exactly what any external agent
would (spec c2/h13). Two driver types ship:

* ``bot`` — a deterministic greedy policy (stdlib only). The baseline
  opponent and the harness's own test double.
* ``command`` — any external agent as a subprocess: the harness feeds a
  prompt (rules + full state JSON) on stdin and parses the first JSON object
  from stdout as the team's orders. A colleague-backend model, a Sonnet
  subagent, an orchestrator, or Claude itself is **a roster-config change,
  not a code change** — swap ``argv`` and the roster's ``model`` labels.

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
     "max_rounds": 40}
"""

from __future__ import annotations

import contextlib
import io
import json

# Command drivers run operator-configured argv without a shell.
import subprocess  # nosec B404
import sys
from typing import Any, Callable, Mapping

from league.cli import main as cli_main

Driver = Callable[[dict[str, Any], str, int], dict[str, Any]]


def _cli_json(argv: list[str]) -> Any:
    """Call the CLI in-process and parse its JSON result — the public surface."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cli_main([*argv, "--json"])
    if rc != 0:
        raise RuntimeError(f"league {' '.join(argv)} failed with exit {rc}")
    return json.loads(buf.getvalue())


# -- the deterministic greedy bot ------------------------------------------


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

    def orders(state: dict[str, Any], team_id: str, turn: int) -> dict[str, Any]:
        my_units = [u for u in state["units"] if u["team_id"] == team_id and u["alive"]]
        deliver = next((m for m in state["missions"] if m["kind"] == "deliver"), None)
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
        return result

    return orders


# -- external agents as subprocesses ---------------------------------------

_RULES = """Rules, briefly: turn-based, simultaneous orders. Each unit does ONE action per
turn: move (Manhattan distance <= its role's move stat), gather (on a resource
node square, fills to carry capacity), deliver (on the deliver-mission square,
unloads into team resources), or hold (stay; builds control-point streaks).
Sole occupancy of a control point for {capture} consecutive turns captures it;
holding it {capture}+N turns completes a hold mission of amount N. The deliver
mission completes when team resources reach its amount. Declared plans and
team messages are free and are scored for cooperation quality."""

_PROMPT = """You are the {team_id} team commander in a League of Agents match.
{rules}
{extra}
Scenario: {scenario}

Current match state (JSON):
{state}

You command team {team_id}. Reply with ONLY one JSON object, no prose:
{{"plan": "<optional standing plan>",
  "messages": [{{"from": "<agent-id>", "text": "..."}}],
  "actions": [{{"unit_id": "...", "action": "move|gather|deliver|hold",
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

Current match state (JSON):
{state}

Messages your teammates already sent this turn:
{team_messages}

Coordinate through messages; you cannot command other units. Reply with ONLY
one JSON object, no prose:
{{"action": {{"unit_id": "{unit_id}", "action": "move|gather|deliver|hold",
             "to": [x, y]}},
  "messages": [{{"from": "{agent_id}", "text": "..."}}],
  "plan": "<optional; only if proposing/refreshing the team plan>"}}
"""


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


def make_command_driver(spec: Mapping[str, Any], scenario: dict[str, Any]) -> Driver:
    argv = list(spec["argv"])
    timeout = float(spec.get("timeout", 300))
    solo = bool(spec.get("solo", False))
    extra = str(spec.get("prompt", ""))
    rules = _RULES.format(capture=scenario["capture_hold_turns"])

    def orders(state: dict[str, Any], team_id: str, turn: int) -> dict[str, Any]:
        prompt = _PROMPT.format(
            team_id=team_id,
            rules=rules,
            extra=(_SOLO_NOTE if solo else "") + (f"\n{extra}\n" if extra else ""),
            scenario=json.dumps(scenario, sort_keys=True),
            state=json.dumps(state, sort_keys=True),
        )
        try:
            result = _run_command(argv, prompt, timeout, team_id)
        except RuntimeError as err:
            print(f"[harness] {team_id} commander idles this turn: {err}", file=sys.stderr)
            return {"actions": []}
        if solo:
            actions = result.get("actions") or []
            result["actions"] = actions[:1]  # the handicap is enforced, not just asked
        return result

    return orders


def make_per_seat_driver(
    spec: Mapping[str, Any], scenario: dict[str, Any], agents: list[dict[str, Any]]
) -> Driver:
    """One independent mind per seat, coordinating only through messages.

    Seats are consulted in roster order each turn; every seat sees the shared
    state plus the messages teammates have queued so far this turn (its own
    channel to influence later seats). Each seat may command only its unit.
    """
    argv = list(spec["argv"])
    timeout = float(spec.get("timeout", 300))
    extra = str(spec.get("prompt", ""))
    rules = _RULES.format(capture=scenario["capture_hold_turns"])
    seat_prompts = {a["id"]: str(a.get("prompt", "")) for a in agents}

    def orders(state: dict[str, Any], team_id: str, turn: int) -> dict[str, Any]:
        my_units = {
            u["agent_id"]: u for u in state["units"] if u["team_id"] == team_id and u["alive"]
        }
        combined: dict[str, Any] = {"actions": [], "messages": []}
        for agent in agents:
            unit = my_units.get(agent["id"])
            if unit is None:
                continue
            seat_extra = "\n".join(part for part in (extra, seat_prompts[agent["id"]]) if part)
            prompt = _SEAT_PROMPT.format(
                agent_id=agent["id"],
                team_id=team_id,
                unit_id=unit["id"],
                role=unit["role"],
                rules=rules,
                extra=f"\n{seat_extra}\n" if seat_extra else "",
                scenario=json.dumps(scenario, sort_keys=True),
                state=json.dumps(state, sort_keys=True),
                team_messages=json.dumps(combined["messages"], sort_keys=True) or "[]",
            )
            try:
                result = _run_command(argv, prompt, timeout, agent["id"])
            except RuntimeError as err:
                print(f"[harness] seat {agent['id']} idles this turn: {err}", file=sys.stderr)
                continue
            action = result.get("action")
            if isinstance(action, dict):
                action["unit_id"] = unit["id"]  # a seat commands its own unit, only
                combined["actions"].append(action)
            for message in result.get("messages", []) or []:
                if isinstance(message, dict) and message.get("text"):
                    combined["messages"].append({"from": agent["id"], "text": str(message["text"])})
            if result.get("plan") and "plan" not in combined:
                combined["plan"] = str(result["plan"])
        if not combined["messages"]:
            combined.pop("messages")
        return combined

    return orders


def build_driver(
    spec: Mapping[str, Any],
    scenario: dict[str, Any],
    agents: list[dict[str, Any]] | None = None,
) -> Driver:
    kind = spec.get("type")
    if spec.get("per_seat") and kind != "command":
        raise ValueError("per_seat is only supported for 'command' drivers")
    if kind == "bot":
        return make_bot_driver(scenario)
    if kind == "command" and spec.get("per_seat"):
        return make_per_seat_driver(spec, scenario, agents or [])
    if kind == "command":
        return make_command_driver(spec, scenario)
    raise ValueError(f"unknown driver type {kind!r}; expected 'bot' or 'command'")


# -- the run loop -----------------------------------------------------------


def run_match(config: Mapping[str, Any], *, on_turn: Callable[[dict], None] | None = None) -> dict:
    """Register teams, create the match, and drive it to completion via the CLI.

    Resumable: if the configured match id already exists on disk, the loop
    picks up from its current turn instead of failing — live matches can
    outlast a shell window, and a crashed run must not orphan the game.
    """
    match_cfg = config["match"]
    scenario = _cli_json(["arena", "show", match_cfg["scenario"]])

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
        created = _cli_json(new_argv + ["--apply"])
        match_id = created["match_id"]

    drivers = {
        t["id"]: build_driver(t["driver"], scenario, t.get("agents")) for t in config["teams"]
    }
    max_rounds = int(config.get("max_rounds", scenario["turn_limit"] + 2))

    for _ in range(max_rounds):
        shown = _cli_json(["match", "show", match_id])
        state = shown["state"]
        if state["status"] != "active":
            break
        turn = state["turn"] + 1
        for team in config["teams"]:
            team_id = team["id"]
            orders = drivers[team_id](state, team_id, turn)
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
            if acted.get("resolution") and on_turn is not None:
                on_turn(acted["resolution"])

    final = _cli_json(["match", "show", match_id])["state"]
    score = _cli_json(["match", "score", match_id])
    return {
        "match_id": match_id,
        "status": final["status"],
        "turns_played": final["turn"],
        "winner": final["winner"],
        "score": score,
    }
