"""The mind-facing contract for the continuous lane (plan C7-t7).

Merge gate for ``league/charness.py`` — written before the implementation
(TDD). It pins the two acceptance criteria the frame's hardest parked question
(v1) demanded an answer to:

1. **The decision cadence + the briefing shape.** A mind is asked for an order
   exactly when its unit becomes idle (match start, or an action completed /
   failed / was interrupted). The briefing it receives exposes the game clock,
   its action menu WITH durations, and the visible initiative outlook (who is
   due to complete next, from the timeline) — so time budgets are plannable.

2. **Substrate independence (honesty h7).** The same continuous match log
   emerges whether a seat's driver answers in 1 millisecond or 60 seconds: game
   time comes only from role data and the timeline, never the wall clock. We
   prove it by construction — the transition stream and the final ``cstate_hash``
   are byte-identical across a fast clock and a slow clock, while the
   ``seat_latency`` observations (the tempo axis) legitimately differ.

Every driver kind gets the continuous loop (the all-backends rule): ``bot`` (an
in-harness greedy continuous policy), ``bot-file`` (a committed strategy that
sees only the briefing JSON), ``command`` / per-seat ``command`` (a subprocess,
briefing on stdin, one JSON order on stdout), and ``resident`` (one long-lived
session per seat). Command paths use stub argv scripts, the resident path a
fake session transport — no live model endpoint, no real sleep.
"""

from __future__ import annotations

import itertools
import json
import sys
import textwrap
from pathlib import Path
from typing import Any, Mapping

import pytest

import league.charness as charness
from league.charness import (
    CHarnessError,
    build_briefing,
    build_cdriver,
    cdriver_kind,
    initiative_outlook,
    make_cbot_chooser,
    run_cmatch,
)
from league.engine.continuous import (
    CAgentSlot,
    CControlPoint,
    CMatchState,
    CMission,
    CTeamState,
    CUnit,
    build_role_table,
    cstate_hash,
    from_units,
    legal_actions_continuous,
)
from league.engine.continuous.resolve import _hold_key, _Resolver

ROLE_TABLE = build_role_table()


# --------------------------------------------------------------------------- #
# Builders (mirror tests/test_continuous_resolve.py so no scenario module is
# imported — t6 runs in parallel; charness takes the initial state via a seam).
# --------------------------------------------------------------------------- #
def _slot(uid, role):
    return CAgentSlot(id=uid, model="colleague/qwen", role=role)


def _team(tid, name, roster, resources=0):
    return CTeamState(id=tid, name=name, resources=resources, agents=tuple(roster))


def _unit(uid, team, role, pos, carrying=0):
    return CUnit(id=uid, team_id=team, agent_id=uid, role=role, pos=pos, carrying=carrying)


def _state(
    *,
    mode="competitive",
    teams,
    units,
    control_points=(),
    missions=(),
    resource_nodes=(),
    time_limit=1000,
):
    return CMatchState(
        match_id="cm",
        scenario_id="charness-1",
        seed=1,
        mode=mode,
        clock=0,
        time_limit=time_limit,
        width=20000,
        height=20000,
        status="pending",
        winner=None,
        teams=tuple(teams),
        units=tuple(units),
        control_points=tuple(control_points),
        missions=tuple(missions),
        resource_nodes=tuple(resource_nodes),
    )


def _clash_state():
    """Two solo teams race for one unowned post. Blue's scout is a step out (it
    must move then take); red's defender starts one step further, so both minds
    face several decision points before the post is taken and the match ends."""
    return _state(
        teams=(
            _team("blue", "Blue", (_slot("blue-scout", "scout"),)),
            _team("red", "Red", (_slot("red-def", "defender"),)),
        ),
        units=(
            _unit("blue-scout", "blue", "scout", from_units(2, 3)),
            _unit("red-def", "red", "defender", from_units(6, 3)),
        ),
        control_points=(CControlPoint(id="cp", pos=from_units(3, 3)),),
    )


def _coop_hold_state():
    """One defender a step from an unowned post with a hold mission — the bot
    must move, take, and hold to win (exercises move + take_post + a mission)."""
    return _state(
        mode="cooperative",
        teams=(_team("blue", "Blue", (_slot("blue-def", "defender"),)),),
        units=(_unit("blue-def", "blue", "defender", from_units(1, 3)),),
        control_points=(CControlPoint(id="cp", pos=from_units(3, 3)),),
        missions=(CMission(id="hm", kind="hold", pos=from_units(3, 3), amount=4, reward=9),),
    )


def _bot_config(state_factory=_clash_state):
    cfg = {
        "match": {"scenario_id": "charness-1", "id": "cm-bot"},
        "teams": [
            {"id": "blue", "driver": {"type": "bot"}},
            {"id": "red", "driver": {"type": "bot"}},
        ],
    }
    return cfg, state_factory()


def _find(state, uid):
    return next(u for u in state.units if u.id == uid)


def _transitions(log):
    """The pure transition stream — every harness OBSERVATION event stripped."""
    obs = {"decision_point", "message_sent", "plan_declared", "seat_latency"}
    return [(e.game_time, e.kind, e.data) for e in log.events if e.kind not in obs]


# --------------------------------------------------------------------------- #
# Criterion 1a — the briefing shape (pinned)
# --------------------------------------------------------------------------- #
def _briefing_state():
    """blue-scout is idle at t=0; red-def has already committed a long take
    (so it appears in the outlook with a real completion_time)."""
    state = _clash_state()
    r = _Resolver(state, ROLE_TABLE, lambda *a: None, None)
    r.emit(0, "match_started", {})
    # Give red-def a pending action so the outlook is non-trivial.
    r._start_action("red-def", {"kind": "move", "target_pos": from_units(3, 3).to_dict()}, 0)
    return r.state


def test_briefing_exposes_clock_menu_durations_and_outlook():
    state = _briefing_state()
    menu = legal_actions_continuous(state, ROLE_TABLE, "blue-scout")
    briefing = build_briefing(state, "blue-scout", menu)

    # game clock
    assert briefing["game_time"] == state.clock == 0

    # you: idle at a decision point
    you = briefing["you"]
    assert you["unit_id"] == "blue-scout"
    assert you["role"] == "scout"
    assert you["team_id"] == "blue"
    assert you["carrying"] == 0
    assert you["action"] is None
    assert you["pos"] == _find(state, "blue-scout").pos.to_dict()

    # menu: every action carries a duration AND the completion_time it lands at
    assert briefing["menu"], "the scout must have at least a move on offer"
    for entry in briefing["menu"]:
        assert entry["kind"] in {"move", "gather", "take_post", "deliver"}
        assert isinstance(entry["duration"], int) and entry["duration"] > 0
        assert entry["completion_time"] == briefing["game_time"] + entry["duration"]
        assert "target" in entry
        # directly returnable to the resolver (carries the raw target field)
        assert "target_id" in entry or "target_pos" in entry

    # outlook: red-def is due to complete next (from the timeline), canonical
    red = _find(state, "red-def")
    assert briefing["outlook"] == [
        {"unit_id": "red-def", "team_id": "red", "completion_time": red.action.completion_time}
    ]

    # board projection + budget note + messages channel
    assert {"clock", "units", "control_points"} <= set(briefing["board"])
    assert isinstance(briefing["clock_budget_note"], str) and briefing["clock_budget_note"]
    assert briefing["messages"] == []


def test_outlook_projection_equals_timeline_pending_for_real_units():
    """The initiative outlook is a pure projection of state (every unit currently
    mid-action) — provably the same set the resolver's Timeline.pending() holds
    for real units, minus the synthetic hold-expiry markers."""
    # blue-def stands ON the post so it can start a take at t=0.
    state = _state(
        mode="cooperative",
        teams=(_team("blue", "Blue", (_slot("blue-def", "defender"),)),),
        units=(_unit("blue-def", "blue", "defender", from_units(3, 3)),),
        control_points=(CControlPoint(id="cp", pos=from_units(3, 3)),),
        missions=(CMission(id="hm", kind="hold", pos=from_units(3, 3), amount=4, reward=9),),
    )
    r = _Resolver(state, ROLE_TABLE, lambda *a: None, None)
    r.emit(0, "match_started", {})
    # blue-def takes the post at t=6, which schedules a synthetic hold-expiry
    # marker on the timeline — that marker must NOT appear in a mind's outlook.
    r._start_action("blue-def", {"kind": "take_post", "target_id": "cp"}, 0)
    r.emit(6, "post_taken", {"cp_id": "cp", "team_id": "blue", "unit_id": "blue-def"})
    r._on_post_taken("cp", "blue", 6)
    assert _hold_key("cp") in r.timeline  # the synthetic marker is present

    real_unit_ids = {u.id for u in r.state.units}
    from_state = initiative_outlook(r.state)
    from_timeline = sorted(
        (
            {"unit_id": e.unit_id, "team_id": e.team_id, "completion_time": e.completion_time}
            for e in r.timeline.pending()
            if e.unit_id in real_unit_ids  # exclude the __hold__ marker
        ),
        key=lambda d: (d["completion_time"], d["team_id"], d["unit_id"]),
    )
    assert from_state == from_timeline


# --------------------------------------------------------------------------- #
# Criterion 1b — the decision cadence: one call per idle transition
# --------------------------------------------------------------------------- #
def test_decision_point_fires_when_a_unit_becomes_idle_and_at_match_start():
    cfg, state = _bot_config()
    calls: list[tuple[str, int]] = []

    base = make_cbot_chooser()

    def spy(briefing, unit_id, team_id):
        calls.append((unit_id, briefing["game_time"]))
        return base(briefing, unit_id, team_id)

    # `choosers` overrides the built driver for a team (a clean test seam); the
    # config still declares each team's driver spec for the log header.
    result = run_cmatch(cfg, initial_state=state, choosers={"blue": spy, "red": spy})

    log = result["log"]
    dps = [e for e in log.events if e.kind == "decision_point"]
    # every decision point drove exactly one chooser call
    assert len(calls) == len(dps)
    # the first decisions happen at match start (game_time 0)
    assert any(gt == 0 for _, gt in calls)
    # a unit is only ever asked while idle: its game_time equals a decision_point's
    dp_pairs = {(e.data["unit_id"], e.game_time) for e in dps}
    assert set(calls) == dp_pairs
    assert result["status"] == "finished"


# --------------------------------------------------------------------------- #
# Criterion 2 — substrate independence (honesty h7), the headline proof
# --------------------------------------------------------------------------- #
class _StepClock:
    """A deterministic fake wall-clock: every reading advances by a fixed step,
    so 'thinking time' is whatever we say it is — no real sleep, no flakiness."""

    def __init__(self, step_ms: int) -> None:
        self._t = 0.0
        self._step = step_ms / 1000.0

    def __call__(self) -> float:
        now = self._t
        self._t += self._step
        return now


def test_same_log_emerges_whether_the_driver_is_fast_or_slow(monkeypatch):
    cfg, _ = _bot_config(_coop_hold_state)
    cfg = {**cfg, "teams": [{"id": "blue", "driver": {"type": "bot"}}]}

    monkeypatch.setattr(charness, "_monotonic", _StepClock(1))  # ~1ms/think
    fast = run_cmatch(cfg, initial_state=_coop_hold_state())

    monkeypatch.setattr(charness, "_monotonic", _StepClock(60_000))  # ~60s/think
    slow = run_cmatch(cfg, initial_state=_coop_hold_state())

    # The game is byte-identical: transitions AND the final hash match exactly.
    assert _transitions(fast["log"]) == _transitions(slow["log"])
    assert cstate_hash(fast["log"].final_state()) == cstate_hash(slow["log"].final_state())
    assert fast["winner"] == slow["winner"] == "blue"

    # ...yet the tempo axis (seat_latency) legitimately differs — wall-clock is
    # observed, never fed back into game time.
    fast_ms = [e.data["elapsed_ms"] for e in fast["log"].events if e.kind == "seat_latency"]
    slow_ms = [e.data["elapsed_ms"] for e in slow["log"].events if e.kind == "seat_latency"]
    assert fast_ms and slow_ms
    assert max(fast_ms) < min(slow_ms)  # every slow think dwarfs every fast one


def test_harness_never_alters_the_resolver_transition_stream():
    """The harness only APPENDS observation events (latency/messages/plans); the
    transition events it records are exactly what the pure resolver emits."""
    from league.engine.continuous import resolve_match

    cfg = {"match": {"id": "cm-x"}, "teams": [{"id": "blue", "driver": {"type": "bot"}}]}
    harness_run = run_cmatch(cfg, initial_state=_coop_hold_state())

    # Replay the SAME scripted choices straight through the resolver.
    chooser = make_cbot_chooser()

    def decide(unit_id, state, menu):
        briefing = build_briefing(state, unit_id, menu)
        return chooser(briefing, unit_id, "blue").get("action")

    pure = resolve_match(_coop_hold_state(), ROLE_TABLE, decide)
    assert _transitions(harness_run["log"]) == _transitions(pure.log)


# --------------------------------------------------------------------------- #
# All-backends rule — every driver kind gets the continuous loop
# --------------------------------------------------------------------------- #
def test_bot_driver_plays_a_full_continuous_match():
    cfg, state = _bot_config()
    result = run_cmatch(cfg, initial_state=state)
    assert result["status"] == "finished"
    assert result["winner"] in {"blue", "red", "draw"}
    # the bot actually took the post (a real transition happened)
    kinds = {e.kind for e in result["log"].events}
    assert "post_taken" in kinds
    assert "decision_point" in kinds


def test_cmatch_is_deterministic():
    cfg, _ = _bot_config()
    a = run_cmatch(cfg, initial_state=_clash_state())
    b = run_cmatch(cfg, initial_state=_clash_state())
    assert _transitions(a["log"]) == _transitions(b["log"])
    assert cstate_hash(a["log"].final_state()) == cstate_hash(b["log"].final_state())


# -- bot-file: a committed strategy that sees ONLY the briefing JSON ----------

_CSTRATEGY = textwrap.dedent('''
    """Test-only continuous strategy: take a post if offered, else rush one."""

    def decide_continuous(briefing, team_id):
        menu = briefing["menu"]
        takes = sorted(
            (m for m in menu if m["kind"] == "take_post"),
            key=lambda m: (m["completion_time"], str(m.get("target"))),
        )
        if takes:
            return {"action": takes[0], "message": "taking " + str(takes[0]["target"])}
        moves = sorted(
            (m for m in menu if m["kind"] == "move"),
            key=lambda m: (m["completion_time"], str(m.get("target"))),
        )
        return {"action": moves[0]} if moves else {"action": None}
    ''').strip()


def test_bot_file_driver_loads_a_strategy_and_plays(tmp_path, monkeypatch):
    strat_dir = tmp_path / "cbots"
    strat_dir.mkdir()
    (strat_dir / "grabber.py").write_text(_CSTRATEGY, encoding="utf-8")
    monkeypatch.setattr(charness, "_CBOTS_DIR", strat_dir)

    cfg = {
        "match": {"id": "cm-file"},
        "teams": [{"id": "blue", "driver": {"type": "bot-file", "strategy": "grabber"}}],
    }
    result = run_cmatch(cfg, initial_state=_coop_hold_state())
    assert result["status"] == "finished"
    assert result["winner"] == "blue"
    # the strategy's message rode along on its order (message_sent observation)
    msgs = [e for e in result["log"].events if e.kind == "message_sent"]
    assert any("taking" in e.data["text"] for e in msgs)


def test_bot_file_strategy_never_receives_engine_objects(tmp_path, monkeypatch):
    """Parity with the grid bot-file lane: the strategy sees the briefing dict
    and team_id, nothing else — no CMatchState, no menu object, no context."""
    seen: list[tuple[Any, ...]] = []
    spy = textwrap.dedent("""
        import json, pathlib
        _LOG = pathlib.Path(__file__).with_name("seen.jsonl")

        def decide_continuous(briefing, team_id):
            with _LOG.open("a") as fh:
                fh.write(json.dumps([sorted(briefing), team_id, str(type(briefing))]) + "\\n")
            return {"action": None}
        """).strip()
    strat_dir = tmp_path / "cbots"
    strat_dir.mkdir()
    (strat_dir / "spy.py").write_text(spy, encoding="utf-8")
    monkeypatch.setattr(charness, "_CBOTS_DIR", strat_dir)

    cfg = {
        "match": {"id": "cm-spy"},
        "teams": [{"id": "blue", "driver": {"type": "bot-file", "strategy": "spy"}}],
    }
    run_cmatch(cfg, initial_state=_coop_hold_state())
    lines = (strat_dir / "seen.jsonl").read_text(encoding="utf-8").splitlines()
    assert lines
    keys, team_id, typ = json.loads(lines[0])
    assert team_id == "blue"
    assert typ == "<class 'dict'>"
    assert {"game_time", "you", "menu", "outlook", "board"} <= set(keys)
    _ = seen  # (kept for symmetry; the subprocess writes to disk)


def test_bot_file_rejects_path_traversal_names(monkeypatch):
    cfg = {
        "match": {"id": "cm-bad"},
        "teams": [{"id": "blue", "driver": {"type": "bot-file", "strategy": "../evil"}}],
    }
    with pytest.raises(Exception):
        run_cmatch(cfg, initial_state=_coop_hold_state())


# -- command: a subprocess, briefing on stdin, one JSON order on stdout -------

# Picks a take_post if the briefing offers one, else the first move; echoes a
# message so the observation channel is exercised.
_CMD_AGENT = textwrap.dedent("""
    import json, sys
    b = json.loads(sys.stdin.read())
    menu = b["menu"]
    takes = [m for m in menu if m["kind"] == "take_post"]
    moves = [m for m in menu if m["kind"] == "move"]
    if takes:
        act = sorted(takes, key=lambda m: (m["completion_time"], str(m.get("target"))))[0]
    elif moves:
        act = sorted(moves, key=lambda m: (m["completion_time"], str(m.get("target"))))[0]
    else:
        act = None
    print(json.dumps({"action": act, "message": "on it from " + b["you"]["unit_id"]}))
    """).strip()


def test_command_driver_plays_via_subprocess():
    cfg = {
        "match": {"id": "cm-cmd"},
        "teams": [
            {
                "id": "blue",
                "driver": {"type": "command", "argv": [sys.executable, "-c", _CMD_AGENT]},
            }
        ],
    }
    result = run_cmatch(cfg, initial_state=_coop_hold_state())
    assert result["status"] == "finished"
    assert result["winner"] == "blue"
    latency = [e for e in result["log"].events if e.kind == "seat_latency"]
    assert latency and all(e.data["unit_id"] == "blue-def" for e in latency)
    assert all(e.data["agent_id"] == "blue-def" for e in latency)


def test_per_seat_command_driver_uses_each_seats_own_argv():
    """per-seat: each agent may carry its own argv/prompt (continuous decisions
    are already per-unit, so per-seat is the per-agent-transport axis)."""
    cfg = {
        "match": {"id": "cm-seat"},
        "teams": [
            {
                "id": "blue",
                "driver": {"type": "command", "per_seat": True},
                "agents": [
                    {"id": "blue-def", "argv": [sys.executable, "-c", _CMD_AGENT]},
                ],
            }
        ],
    }
    result = run_cmatch(cfg, initial_state=_coop_hold_state())
    assert result["status"] == "finished"
    assert result["winner"] == "blue"


# -- resident: one long-lived session per seat -------------------------------


class _FakeCSession:
    """A scripted continuous seat mind; records the session id serving each call
    so a wrongly re-minted session (one per decision instead of one per seat) is
    detectable."""

    def __init__(self, spec, match_id, agent_id, serial, calls):
        self.session_id = f"fake-{agent_id}-{serial}"
        self.transport = "fake"
        self._agent_id = agent_id
        self._calls = calls

    def send(self, prompt, *, timeout):
        self._calls.append({"agent_id": self._agent_id, "session_id": self.session_id})
        b = json.loads(prompt)
        takes = [m for m in b["menu"] if m["kind"] == "take_post"]
        moves = [m for m in b["menu"] if m["kind"] == "move"]
        if takes:
            act = sorted(takes, key=lambda m: (m["completion_time"], str(m.get("target"))))[0]
        elif moves:
            act = sorted(moves, key=lambda m: (m["completion_time"], str(m.get("target"))))[0]
        else:
            act = None
        return json.dumps({"action": act})


def _fake_ctransport(calls):
    serial = itertools.count(1)

    def factory(spec: Mapping[str, Any], match_id: str, agent_id: str) -> _FakeCSession:
        return _FakeCSession(spec, match_id, agent_id, next(serial), calls)

    return factory


def test_resident_driver_uses_one_session_per_seat(monkeypatch):
    calls: list[dict[str, Any]] = []
    monkeypatch.setitem(charness.CSESSION_TRANSPORTS, "fake", _fake_ctransport(calls))
    cfg = {
        "match": {"id": "cm-res"},
        "teams": [
            {
                "id": "blue",
                "driver": {"type": "resident", "transport": "fake"},
                "agents": [{"id": "blue-def", "role": "defender"}],
            }
        ],
    }
    result = run_cmatch(cfg, initial_state=_coop_hold_state())
    assert result["status"] == "finished"
    assert result["winner"] == "blue"
    # every call to this seat used the SAME session id (resident, not re-minted)
    assert calls
    assert len({c["session_id"] for c in calls if c["agent_id"] == "blue-def"}) == 1


# --------------------------------------------------------------------------- #
# The t6 seam — initial state via callable / inline dict / (absent) registry
# --------------------------------------------------------------------------- #
def test_seam_accepts_a_state_builder_callable():
    cfg = {"match": {"id": "cm-cb"}, "teams": [{"id": "blue", "driver": {"type": "bot"}}]}
    result = run_cmatch(cfg, initial_state=_coop_hold_state)  # a callable
    assert result["status"] == "finished"


def test_seam_accepts_an_inline_state_dict():
    cfg = {
        "match": {"id": "cm-inline", "state": _coop_hold_state().to_dict()},
        "teams": [{"id": "blue", "driver": {"type": "bot"}}],
    }
    result = run_cmatch(cfg)
    assert result["status"] == "finished"


def test_seam_missing_scenario_registry_raises_a_clear_error():
    cfg = {
        "match": {"id": "cm-nostate", "scenario": "clash-1"},
        "teams": [{"id": "blue", "driver": {"type": "bot"}}],
    }
    with pytest.raises(CHarnessError) as exc:
        run_cmatch(cfg)
    assert "scenario" in str(exc.value).lower() or "state" in str(exc.value).lower()


def test_every_team_in_the_state_needs_a_driver():
    cfg = {"match": {"id": "cm-nodrv"}, "teams": [{"id": "blue", "driver": {"type": "bot"}}]}
    with pytest.raises(CHarnessError):
        run_cmatch(cfg, initial_state=_clash_state())  # red has no driver


# --------------------------------------------------------------------------- #
# Residency labels + the committed reference strategy
# --------------------------------------------------------------------------- #
def test_cdriver_kind_labels_match_the_grid_vocabulary():
    assert cdriver_kind({"type": "bot"}) == "bot"
    assert cdriver_kind({"type": "bot-file", "strategy": "crusher"}) == "bot"
    assert cdriver_kind({"type": "resident", "transport": "fake"}) == "resident"
    assert cdriver_kind({"type": "command", "argv": []}) == "stateless"
    assert cdriver_kind({"type": "command", "argv": [], "residency": "resident"}) == "resident"


def test_run_cmatch_records_driver_kinds_in_the_log_header():
    cfg, state = _bot_config()
    result = run_cmatch(cfg, initial_state=state)
    assert result["log"].driver_kinds == {"blue": "bot", "red": "bot"}


def test_build_cdriver_rejects_unknown_type():
    with pytest.raises(CHarnessError):
        build_cdriver({"type": "telepathy"}, None)


def test_committed_crusher_reference_strategy():
    """bots/crusher.py is the continuous lane's readable reference strategy —
    parallel to bots/rusher.py, sees only the briefing JSON."""
    path = Path(__file__).resolve().parent.parent / "bots" / "crusher.py"
    assert path.is_file()
    import bots.crusher as crusher

    # take_post wins if offered
    briefing = {
        "menu": [
            {"kind": "move", "target": "cp", "completion_time": 5, "target_pos": {"x": 1, "y": 1}},
            {"kind": "take_post", "target": "cp", "completion_time": 6, "target_id": "cp"},
        ],
        "board": {"control_points": [{"id": "cp", "owner": None}]},
    }
    assert crusher.decide_continuous(briefing, "blue")["action"]["kind"] == "take_post"
    # else it rushes a control point
    briefing["menu"] = [briefing["menu"][0]]
    assert crusher.decide_continuous(briefing, "blue")["action"]["kind"] == "move"
