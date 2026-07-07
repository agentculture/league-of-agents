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
import hashlib
import importlib.util
import io
import json
import os
import re

# Command drivers run operator-configured argv without a shell.
import subprocess  # nosec B404
import sys
import urllib.request
from pathlib import Path
from typing import Any, Callable, Mapping

from league.cli import main as cli_main
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

    def orders(
        state: dict[str, Any],
        team_id: str,
        turn: int,
        context: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
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

    The returned ``orders`` closure ignores the ``state``/``context`` the
    run loop hands every driver and instead calls ``match show --json``
    itself (the same ``_cli_json`` path every other driver uses) — exactly
    what a subprocess bot would have to do — then passes ONLY that parsed
    dict (plus ``team_id``) to the strategy's ``decide``. No scenario, no
    engine dataclass, ever crosses into strategy code.
    """
    name = spec.get("strategy")
    if not name:
        raise ValueError("bot-file driver requires a 'strategy' name (bots/<name>.py)")
    decide = _load_bot_strategy(str(name))

    def orders(
        state: dict[str, Any],
        team_id: str,
        turn: int,
        context: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        match_id = str(state.get("match_id") or "")
        show_json = _cli_json(["match", "show", match_id])
        return decide(show_json, team_id)

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
{rejections}{legal_actions}
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
{rejections}{legal_actions}
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
    if not rejections:
        return ""
    lines = "\n".join(f"- {r.get('unit_id')}: {r.get('reason')}" for r in rejections)
    return (
        "\nREJECTIONS from your last turn — the engine's own reason, so you "
        f"don't repeat it:\n{lines}\n"
    )


def _format_move_targets(moves: list[Any]) -> str:
    """Keep the legal-actions line short even for a wide-ranging role."""
    if len(moves) <= 8:
        return json.dumps(moves)
    xs = [m[0] for m in moves]
    ys = [m[1] for m in moves]
    return f"{len(moves)} cells, x in [{min(xs)}, {max(xs)}], y in [{min(ys)}, {max(ys)}]"


def _format_legal_actions(legal_actions: Mapping[str, Any], unit_ids: list[str]) -> str:
    """A compact 'legal now' line per unit — checkable before declaring, not
    just discovered after the engine rejects it."""
    lines = []
    for unit_id in unit_ids:
        legal = legal_actions.get(unit_id)
        if legal is None:
            continue
        lines.append(
            f"- {unit_id}: move to {_format_move_targets(legal.get('move', []))}; "
            f"gather: {'yes' if legal.get('gather') else 'no'}; "
            f"deliver: {'yes' if legal.get('deliver') else 'no'}; hold: yes"
        )
    if not lines:
        return ""
    return "\nLegal actions right now:\n" + "\n".join(lines) + "\n"


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

    def orders(
        state: dict[str, Any],
        team_id: str,
        turn: int,
        context: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        context = context or {}
        my_unit_ids = [u["id"] for u in state.get("units", []) if u.get("team_id") == team_id]
        prompt = _PROMPT.format(
            team_id=team_id,
            rules=rules,
            extra=(_SOLO_NOTE if solo else "") + (f"\n{extra}\n" if extra else ""),
            scenario=json.dumps(scenario, sort_keys=True),
            rejections=_format_rejections(
                _rejections_for(context.get("rejections", []), team_id=team_id)
            ),
            legal_actions=_format_legal_actions(context.get("legal_actions", {}), my_unit_ids),
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
    for message in result.get("messages", []) or []:
        if isinstance(message, dict) and message.get("text"):
            combined["messages"].append({"from": agent_id, "text": str(message["text"])})
    if result.get("plan") and "plan" not in combined:
        combined["plan"] = str(result["plan"])


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

    def orders(
        state: dict[str, Any],
        team_id: str,
        turn: int,
        context: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        context = context or {}
        legal_actions = context.get("legal_actions", {})
        rejections = context.get("rejections", [])
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
                rejections=_format_rejections(_rejections_for(rejections, unit_id=unit["id"])),
                legal_actions=_format_legal_actions(legal_actions, [unit["id"]]),
                state=json.dumps(state, sort_keys=True),
                team_messages=json.dumps(combined["messages"], sort_keys=True) or "[]",
            )
            try:
                result = _run_command(argv, prompt, timeout, agent["id"])
            except RuntimeError as err:
                print(f"[harness] seat {agent['id']} idles this turn: {err}", file=sys.stderr)
                continue
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
        self.session_id = _mint_session_id(match_id, agent_id)
        self._started = False

    def _argv(self, flag: str) -> list[str]:
        argv = [self._command, "-p", flag, self.session_id]
        if self._model:
            argv += ["--model", str(self._model)]
        return argv

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
        self._max_tokens = int(spec.get("max_tokens", 4096))
        self._chat_template_kwargs = spec.get("chat_template_kwargs")
        self._history: list[dict[str, str]] = []
        self.session_id = f"colleague-direct-{_mint_session_id(match_id, agent_id)}"

    def send(self, prompt: str, *, timeout: float) -> str:
        self._history.append({"role": "user", "content": prompt})
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": list(self._history),
            "max_tokens": self._max_tokens,
            "temperature": self._temperature,
        }
        if self._chat_template_kwargs:
            payload["chat_template_kwargs"] = dict(self._chat_template_kwargs)
        try:
            data = _http_post_json(f"{self._base_url}/chat/completions", payload, timeout)
        except OSError as err:
            # The model never saw this message — keep the transcript honest
            # so the next attempt isn't preceded by a phantom user turn.
            self._history.pop()
            raise RuntimeError(f"colleague-direct session {self.session_id}: {err}") from err
        message = data["choices"][0]["message"]
        # The Qwen gotcha (spike, scripts/openai_driver.py): thinking models
        # may return content=None with the answer in reasoning_content.
        content = message.get("content") or message.get("reasoning_content") or ""
        content = re.sub(r"<think>.*?</think>", "", content, flags=re.S).strip()
        self._history.append({"role": "assistant", "content": content})
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
actions, a compact state, and teammate messages."""

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
    already taught (grid, roles, scenario constants stay in turn 1)."""
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
                "carrying": u["carrying"],
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
            }
            for m in state.get("missions", [])
        ],
        "resource_nodes": [
            {"id": n["id"], "pos": n["pos"], "remaining": n["remaining"]}
            for n in state.get("resource_nodes", [])
        ],
    }


def _events_since(match_id: str, since_turn: int, upto_turn: int) -> list[dict[str, Any]]:
    """Events a seat hasn't seen yet, read off the log via the public CLI
    (``match replay --json``) — the harness never opens the log file itself."""
    if not match_id:
        return []
    events_by_turn = _cli_json(["match", "replay", match_id]).get("events_by_turn", {})
    return [
        {"turn": int(turn), **event}
        for turn in sorted(events_by_turn, key=int)
        if since_turn < int(turn) <= upto_turn
        for event in events_by_turn[turn]
    ]


def make_resident_driver(
    spec: Mapping[str, Any], scenario: dict[str, Any], agents: list[dict[str, Any]]
) -> Driver:
    """One long-lived session per seat for the whole match (per-seat by
    definition). Turn 1 = full briefing into a fresh session; turn N>1 = delta
    only, into the SAME session. Every exchange (and every failure) is
    appended to ``.league/matches/<id>/sessions/<agent-id>.jsonl`` for audit.
    """
    transport = spec.get("transport")
    if transport not in SESSION_TRANSPORTS:
        raise ValueError(
            f"unknown resident transport {transport!r}; "
            f"expected one of {sorted(SESSION_TRANSPORTS)}"
        )
    timeout = float(spec.get("timeout", 300))
    extra = str(spec.get("prompt", ""))
    rules = _RULES.format(capture=scenario["capture_hold_turns"])
    seat_prompts = {a["id"]: str(a.get("prompt", "")) for a in agents}
    sessions: dict[str, Any] = {}
    briefed: set[str] = set()  # seats whose session has actually seen the rules
    last_seen: dict[str, int] = {}  # state turn at the seat's last successful briefing

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
            scenario=json.dumps(scenario, sort_keys=True),
            **fields,
        )

    def orders(
        state: dict[str, Any],
        team_id: str,
        turn: int,
        context: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        context = context or {}
        legal_actions = context.get("legal_actions", {})
        rejections = context.get("rejections", [])
        match_id = str(state.get("match_id") or "")
        store = Store()
        my_units = {
            u["agent_id"]: u for u in state["units"] if u["team_id"] == team_id and u["alive"]
        }
        new_events: dict[str, list[dict[str, Any]]] = {}  # per since-turn, fetched lazily
        combined: dict[str, Any] = {"actions": [], "messages": []}
        for agent in agents:
            unit = my_units.get(agent["id"])
            if unit is None:
                continue
            session = sessions.get(agent["id"])
            if session is None:
                session = SESSION_TRANSPORTS[transport](spec, match_id, agent["id"])
                sessions[agent["id"]] = session
            shared = {
                "rejections": _format_rejections(_rejections_for(rejections, unit_id=unit["id"])),
                "legal_actions": _format_legal_actions(legal_actions, [unit["id"]]),
                "team_messages": json.dumps(combined["messages"], sort_keys=True),
            }
            if agent["id"] not in briefed:
                # First contact (or every prior attempt failed): the seat has
                # never seen the rules, so it gets the full briefing — never a
                # delta it can't ground.
                prompt = _full_briefing(
                    agent, unit, state=json.dumps(state, sort_keys=True), **shared
                )
            else:
                since = last_seen.get(agent["id"], 0)
                if str(since) not in new_events:
                    new_events[str(since)] = _events_since(match_id, since, state["turn"])
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
            try:
                reply = session.send(prompt, timeout=timeout)
            except RuntimeError as err:
                if match_id:
                    store.append_session_record(
                        match_id, agent["id"], {**record, "error": str(err)}
                    )
                print(f"[harness] seat {agent['id']} idles this turn: {err}", file=sys.stderr)
                continue
            if match_id:
                store.append_session_record(match_id, agent["id"], {**record, "received": reply})
            briefed.add(agent["id"])
            last_seen[agent["id"]] = state["turn"]
            try:
                result = _extract_json(reply)
            except ValueError as err:
                print(f"[harness] seat {agent['id']} idles this turn: {err}", file=sys.stderr)
                continue
            _fold_seat_reply(combined, result, unit["id"], agent["id"])
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
    if spec.get("per_seat") and kind not in ("command", "resident"):
        raise ValueError("per_seat is only supported for 'command' and 'resident' drivers")
    if kind == "bot":
        return make_bot_driver(scenario)
    if kind == "bot-file":
        return make_bot_file_driver(spec)
    if kind == "resident":  # per-seat by definition
        return make_resident_driver(spec, scenario, agents or [])
    if kind == "command" and spec.get("per_seat"):
        return make_per_seat_driver(spec, scenario, agents or [])
    if kind == "command":
        return make_command_driver(spec, scenario)
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
        for team in config["teams"]:
            new_argv += ["--driver", f"{team['id']}:{driver_kind(team['driver'])}"]
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
        # Rejection feedback + legal-actions citation (spec c8/h5): every
        # driver gets the prior turn's rejections and the current legal-move
        # surface, straight off the public `match show --json` projection —
        # no bypassing the CLI to read the log directly.
        context = {
            "legal_actions": shown.get("legal_actions", {}),
            "rejections": shown.get("last_turn_rejections", []),
        }
        for team in config["teams"]:
            team_id = team["id"]
            orders = drivers[team_id](state, team_id, turn, context)
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
