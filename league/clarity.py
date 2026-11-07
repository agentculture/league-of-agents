"""Instruction-clarity checks: replay recorded game moments to several models.

A *case* is one seat's turn taken from a recorded match: the seat's last few
exchanges before that turn (legal play, kept as realistic noise), then that
turn's prompt re-rendered with the CURRENT harness wording for the parts the
harness owns (the legal-actions line and the rejections/notes section). Cases
are picked where the recorded order was a mistake (a rejected order, or a
reply the old harness could not read), plus one legal control per mistake.

Running a case sends it to a model and checks the reply mechanically: is it a
readable order, is the verb one this role has, is a move target inside the
unit's Manhattan range, is a gather/deliver possible on that cell, does a
steal name an enemy unit. A pass means the instructions were clear enough for
that model to produce a legal order there; a fail carries the reason.

Every model gets the same text: the system prompt, then ONE user message that
holds the recent exchanges as a quoted transcript followed by the turn's
prompt. (A transcript, not replayed chat turns, because the Claude CLI cannot
be handed a prior conversation; doing the same for every model keeps the
comparison fair.)

    python -m league.clarity build --match <id> [--match <id> ...] --out cases.jsonl
    python -m league.clarity run --cases cases.jsonl --drivers drivers.json \\
        --model glm --model sonnet [--repeat 2] --out results.jsonl
    python -m league.clarity report results.jsonl
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import re
import subprocess  # nosec B404 - the Claude CLI is an operator-configured binary
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

from league.cli._commands.arena import _scenario_dict
from league.engine.events import fold_events
from league.engine.legal import legal_actions
from league.engine.scenario import get_scenario
from league.harness import (
    _format_legal_actions,
    _format_rejections,
    _parse_seat_reply,
    _reply_schema,
)
from league.store import Store

HISTORY_TURNS = 3
_LEGAL_BLOCK = re.compile(r"\nLegal actions right now:\n.*?\n(?=\n|[A-Z])", re.S)
_REJECT_BLOCK = re.compile(
    r"\n(?:REJECTIONS from your last turn|NOTES \(not rejections\)).*?\n(?=\n|Legal actions)", re.S
)


# -- building cases -------------------------------------------------------------


def _states_by_turn(log) -> dict[int, Any]:
    """State after each resolved turn (0 = the initial state)."""
    states = {0: log.initial_state}
    done = []
    for ev in log.events:
        done.append(ev)
        if ev.kind == "turn_resolved":
            states[ev.data["turn"]] = fold_events(log.initial_state, done)
    return states


def _rerender(sent: str, legal_line: str, rejections: str) -> str:
    """The recorded prompt with the harness-owned sections in today's wording."""
    out = _REJECT_BLOCK.sub("\n", sent)
    if _LEGAL_BLOCK.search(out):
        out = _LEGAL_BLOCK.sub(lambda _m: rejections + legal_line, out, count=1)
    return out


def build_cases(match_id: str, root: Path = Path(".")) -> list[dict[str, Any]]:
    store = Store(root)
    log = store.load_match(match_id)
    scenario = get_scenario(log.initial_state.scenario_id)
    states = _states_by_turn(log)
    rejected: dict[tuple[int, str], dict[str, Any]] = {}
    declared: dict[int, set[str]] = collections.defaultdict(set)
    for ev in log.events:
        if ev.kind == "action_rejected" and not ev.data.get("passive"):
            rejected[(ev.turn, ev.data["unit_id"])] = ev.data
        if ev.kind == "action_declared":
            declared[ev.turn].add(ev.data.get("unit_id"))
    rejections_by_turn: dict[int, list[dict[str, Any]]] = collections.defaultdict(list)
    for ev in log.events:
        if ev.kind == "action_rejected":
            rejections_by_turn[ev.turn].append(ev.data)

    cases: list[dict[str, Any]] = []
    sessions = root / ".league" / "matches" / match_id / "sessions"
    for path in sorted(sessions.glob("*.jsonl")):
        records = [json.loads(line) for line in path.read_text().splitlines()]
        ok = [r for r in records if "received" in r]
        for i, rec in enumerate(ok):
            turn, agent = rec["turn"], rec["agent_id"]
            unit_id = agent.replace("-", "-u")
            mistake = rejected.get((turn, unit_id))
            lost = unit_id not in declared[turn] and turn in states
            kind = "rejected" if mistake else ("unreadable" if lost else None)
            if kind is None:
                continue
            picks = [(rec, i, kind, mistake)]
            # One legal control: the same seat's previous accepted turn.
            prev = next(
                (
                    (r, j)
                    for j, r in reversed(list(enumerate(ok[:i])))
                    if (r["turn"], unit_id) not in rejected and unit_id in declared[r["turn"]]
                ),
                None,
            )
            if prev:
                picks.append((prev[0], prev[1], "control", None))
            for r, j, k, why in picks:
                case = _case(match_id, scenario, states, rejections_by_turn, ok, r, j, k, why)
                if case and case["id"] not in {c["id"] for c in cases}:
                    cases.append(case)
    return cases


def _case(match_id, scenario, states, rejections_by_turn, ok, rec, idx, kind, why):
    turn, agent = rec["turn"], rec["agent_id"]
    unit_id = agent.replace("-", "-u")
    state = states.get(turn - 1)
    if state is None or not any(u.id == unit_id for u in state.units):
        return None
    unit = next(u for u in state.units if u.id == unit_id)
    legal = legal_actions(state, scenario, unit_id)
    legal_line = _format_legal_actions({unit_id: legal}, [unit_id], {unit_id: list(unit.pos)})
    last = [r for r in rejections_by_turn.get(turn - 1, []) if r.get("unit_id") == unit_id]
    prompt = _rerender(rec["sent"], legal_line, _format_rejections(last))
    history = [
        {"turn": r["turn"], "prompt": r["sent"], "reply": r["received"]}
        for r in ok[max(0, idx - HISTORY_TURNS) : idx]
    ]
    return {
        "id": f"{match_id}:{agent}:t{turn}:{kind}",
        "match_id": match_id,
        "scenario_id": state.scenario_id,
        "agent_id": agent,
        "unit_id": unit_id,
        "team_id": unit.team_id,
        "role": unit.role,
        "turn": turn,
        "kind": kind,
        "recorded_order": rec["received"],
        "recorded_reason": (why or {}).get("reason"),
        "legal": legal,
        "pos": list(unit.pos),
        "enemy_ids": sorted(u.id for u in state.units if u.team_id != unit.team_id),
        "history": history,
        "prompt": prompt,
    }


# -- checking a reply -----------------------------------------------------------


def check_reply(case: dict[str, Any], reply: str) -> tuple[bool, str]:
    """Is this reply a legal order for the case's unit, and if not, why not."""
    result, problem, _repair = _parse_seat_reply(reply)
    action = result.get("action")
    if not isinstance(action, dict):
        return False, f"no readable order ({problem or 'no action'})"
    verb = action.get("action")
    legal = case["legal"]
    if verb == "hold":
        return True, "hold"
    if verb == "move":
        to = action.get("to")
        if not (isinstance(to, list) and len(to) == 2):
            return False, f"move without a [x, y] target: {to!r}"
        if list(to) not in [list(m) for m in legal["move"]]:
            dist = abs(to[0] - case["pos"][0]) + abs(to[1] - case["pos"][1])
            return False, f"move to {to} is out of range (distance {dist})"
        return True, "move"
    if verb == "gather":
        return (True, "gather") if legal.get("gather") else (False, "gather not possible here")
    if verb == "deliver":
        return (True, "deliver") if legal.get("deliver") else (False, "deliver not possible here")
    if verb == "steal":
        if not legal.get("can_steal"):
            return False, "this role cannot steal"
        target = action.get("target")
        if target and target not in case["enemy_ids"]:
            return False, f"steal target {target!r} is not an enemy unit"
        return True, "steal"
    return False, f"unknown action {verb!r}"


# -- running models -------------------------------------------------------------


def _message(case: dict[str, Any]) -> str:
    parts = ["Your conversation so far in this match (most recent turns, for context):"]
    for h in case["history"]:
        parts.append(f"--- turn {h['turn']}: the harness said ---\n{h['prompt']}")
        parts.append(f"--- turn {h['turn']}: you replied ---\n{h['reply']}")
    parts.append("--- now ---\n" + case["prompt"])
    return "\n\n".join(parts)


def _ask_http(spec: dict[str, Any], system: str, text: str, schema: dict | None) -> str:
    payload: dict[str, Any] = {
        "model": spec["model"],
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": text}],
        "temperature": spec.get("temperature", 1.0),
    }
    for key in ("top_p", "max_tokens", "chat_template_kwargs"):
        if spec.get(key) is not None:
            payload[key] = spec[key]
    if schema is not None:
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "seat_reply", "schema": schema},
        }
    headers = {"Content-Type": "application/json"}
    if spec.get("api_key_env") and os.environ.get(spec["api_key_env"]):
        headers["Authorization"] = f"Bearer {os.environ[spec['api_key_env']]}"
    url = spec["base_url"].rstrip("/") + "/chat/completions"
    if not url.startswith(("http://", "https://")):
        raise RuntimeError(f"base_url must be http(s): {url!r}")
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers)
    with urllib.request.urlopen(req, timeout=spec.get("timeout", 3600)) as resp:  # nosec B310
        data = json.load(resp)
    return data["choices"][0]["message"].get("content") or ""


def _ask_claude(spec: dict[str, Any], system: str, text: str, schema: dict | None) -> str:
    argv = [
        spec.get("command", "claude"),
        "-p",
        "--model",
        spec["model"],
        "--system-prompt",
        system,
    ]
    argv += [str(a) for a in spec.get("args", [])]
    if schema is not None:
        argv += ["--json-schema", json.dumps(schema, separators=(",", ":"))]
    proc = subprocess.run(  # nosec B603 - operator-configured argv, no shell
        argv, input=text, capture_output=True, text=True, timeout=spec.get("timeout", 3600)
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip()[:300])
    return proc.stdout


def run_cases(cases, drivers, models, repeat=1, structured=True, out=None):
    rows = []
    for name in models:
        spec = drivers[name]
        ask = _ask_claude if spec.get("transport") == "claude" else _ask_http
        for case in cases:
            schema = _reply_schema(_scenario_dict(get_scenario(case["scenario_id"])))
            for n in range(repeat):
                t0 = time.time()
                try:
                    reply = ask(
                        spec,
                        spec.get("system_prompt", ""),
                        _message(case),
                        schema if structured else None,
                    )
                    ok, why = check_reply(case, reply)
                except Exception as err:  # a failed call is reported, not fatal
                    reply, ok, why = "", False, f"call failed: {err}"
                row = {
                    "model": name,
                    "case": case["id"],
                    "kind": case["kind"],
                    "role": case["role"],
                    "try": n + 1,
                    "pass": ok,
                    "why": why,
                    "seconds": round(time.time() - t0, 1),
                    "reply": reply,
                }
                rows.append(row)
                if out:
                    with open(out, "a") as fh:
                        fh.write(json.dumps(row) + "\n")
                print(f"{name:8} {'PASS' if ok else 'FAIL'} {case['id']}  {why}", file=sys.stderr)
    return rows


def report(rows: list[dict[str, Any]]) -> str:
    by = collections.defaultdict(lambda: [0, 0])
    fails = collections.defaultdict(collections.Counter)
    for r in rows:
        key = (r["model"], r["kind"])
        by[key][0] += r["pass"]
        by[key][1] += 1
        if not r["pass"]:
            fails[r["model"]][re.sub(r"\d+", "N", r["why"])] += 1
    lines = ["model     kind        pass/total"]
    for (model, kind), (p, t) in sorted(by.items()):
        lines.append(f"{model:9} {kind:11} {p}/{t}")
    for model, counter in sorted(fails.items()):
        lines.append(
            f"{model} failures: " + "; ".join(f"{k} x{v}" for k, v in counter.most_common())
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m league.clarity")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--match", action="append", required=True)
    b.add_argument("--root", default=".")
    b.add_argument("--out", required=True)
    r = sub.add_parser("run")
    r.add_argument("--cases", required=True)
    r.add_argument("--drivers", required=True)
    r.add_argument("--model", action="append", required=True)
    r.add_argument("--repeat", type=int, default=1)
    r.add_argument("--kind", action="append", help="only these case kinds")
    r.add_argument("--no-structured", action="store_true")
    r.add_argument("--out")
    p = sub.add_parser("report")
    p.add_argument("results")
    args = ap.parse_args(argv)
    if args.cmd == "build":
        cases = [c for m in args.match for c in build_cases(m, Path(args.root))]
        Path(args.out).write_text("".join(json.dumps(c) + "\n" for c in cases))
        print(f"{len(cases)} cases: {dict(collections.Counter(c['kind'] for c in cases))}")
    elif args.cmd == "run":
        cases = [json.loads(line) for line in Path(args.cases).read_text().splitlines()]
        if args.kind:
            cases = [c for c in cases if c["kind"] in args.kind]
        drivers = json.loads(Path(args.drivers).read_text())
        rows = run_cases(cases, drivers, args.model, args.repeat, not args.no_structured, args.out)
        print(report(rows))
    else:
        rows = [json.loads(line) for line in Path(args.results).read_text().splitlines()]
        print(report(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
