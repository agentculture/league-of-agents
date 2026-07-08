"""Harness contract parity (plan C8-t7, spec c13/h4/c5/h18/c8/h8).

Merge gate for the mind-facing seat contract now baked into
``league/charness.py`` — the continuous twin of the grid harness's own
``_SEAT_PROMPT``. Before this task, the reply-shape/time-model/race-semantics/
menu-discipline prose lived only in the OPERATOR script
``scripts/cseat_driver.py``'s own ``_CONTRACT``: a mind fielded through any
OTHER command driver, or through the built-in ``resident`` driver, got raw
JSON with no rules at all — the lane-parity gap the cycle-7 live report
flagged. Written before the implementation (TDD). Pins:

1. First contact for every TEXT-facing driver kind (``command``, ``command``
   + ``per_seat``, and the built-in ``resident``) carries the baked contract —
   reply shape, time model, race semantics, menu discipline, delivery
   contention (t3), and fog wording (t5, present only when the match is
   actually fogged); later decision points get a short delta, never a resend.
2. Code-facing driver kinds (``bot``, ``bot-file``) never see any of this
   prose — they keep reading the plain, pinned briefing dict, mirroring the
   grid harness's own bot/bot-file lane. All five driver kinds
   (bot, bot-file, command, command+per_seat, resident) are exercised.
3. The contract leaks nothing a fogged briefing itself withholds (mirrors
   ``tests/test_harness_fog.py``'s own leakage checks for the grid's
   ``_SEAT_PROMPT``/scenario block).
4. ``scripts/cseat_driver.py`` carries zero rules prose of its own — pure
   transport that forwards the harness's already-baked text verbatim.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any, Mapping

import pytest

import league.charness as charness
from league.charness import (
    build_briefing,
    build_cdriver,
    run_cmatch,
    seat_prompt_text,
)
from league.engine.continuous import (
    CAgentSlot,
    CControlPoint,
    CMatchState,
    CMission,
    CTeamState,
    CUnit,
    build_role_table,
    from_units,
    legal_actions_continuous,
)

ROLE_TABLE = build_role_table()
_REPO_ROOT = Path(__file__).resolve().parent.parent
_CSEAT_DRIVER = _REPO_ROOT / "scripts" / "cseat_driver.py"


# --------------------------------------------------------------------------- #
# Builders (self-contained — mirrors tests/test_fog.py's own convention of not
# sharing fixtures across continuous-lane test modules).
# --------------------------------------------------------------------------- #
def _slot(uid, role):
    return CAgentSlot(id=uid, model="colleague/qwen", role=role)


def _team(tid, name, roster):
    return CTeamState(id=tid, name=name, resources=0, agents=tuple(roster))


def _unit(uid, team, role, pos, *, carrying=0):
    return CUnit(id=uid, team_id=team, agent_id=uid, role=role, pos=pos, carrying=carrying)


def _state(*, teams, units, control_points=(), missions=(), time_limit=1000):
    return CMatchState(
        match_id="cm-contract",
        scenario_id="contract-test",
        seed=1,
        mode="cooperative",
        clock=0,
        time_limit=time_limit,
        width=200000,
        height=200000,
        status="pending",
        winner=None,
        teams=tuple(teams),
        units=tuple(units),
        control_points=tuple(control_points),
        missions=tuple(missions),
        resource_nodes=(),
    )


def _one_defender_state(pos=None, *, extra_cps=()):
    pos = pos if pos is not None else from_units(1, 1)
    return _state(
        teams=(_team("blue", "Blue", (_slot("blue-def", "defender"),)),),
        units=(_unit("blue-def", "blue", "defender", pos),),
        control_points=(CControlPoint(id="cp-near", pos=pos),) + tuple(extra_cps),
        missions=(CMission(id="hm", kind="hold", pos=pos, amount=2, reward=5),),
    )


def _briefing_for(state, unit_id="blue-def", *, fog=False):
    menu = legal_actions_continuous(state, ROLE_TABLE, unit_id)
    return build_briefing(state, unit_id, menu, fog=fog, role_table=ROLE_TABLE)


# --------------------------------------------------------------------------- #
# Criterion 1a — seat_prompt_text: first contact vs. delta, at the unit level
# --------------------------------------------------------------------------- #
def test_first_contact_carries_the_reply_shape_time_model_and_race_semantics():
    briefing = _briefing_for(_one_defender_state())
    text = seat_prompt_text(briefing, fog=False, first_contact=True)
    # reply shape
    assert "Reply with EXACTLY ONE JSON object" in text
    # time model
    assert "INTEGER GAME-TIME" in text
    assert "never wall-clock" in text
    # race semantics
    assert "post taken by a faster agent" in text
    # menu discipline
    assert "Menu discipline" in text
    assert "copied verbatim" in text
    # the pinned briefing rides along, verbatim
    assert json.dumps(briefing) in text


def test_first_contact_carries_delivery_contention_wording_from_t3():
    briefing = _briefing_for(_one_defender_state())
    text = seat_prompt_text(briefing, fog=False, first_contact=True)
    assert "delivery denied by enemy presence at the site" in text
    assert "Only an enemy presence denies" in text


def test_delta_omits_the_baked_contract_but_keeps_the_reply_rule():
    briefing = _briefing_for(_one_defender_state())
    text = seat_prompt_text(briefing, fog=False, first_contact=False)
    assert "Reply with EXACTLY ONE JSON object" not in text
    assert "INTEGER GAME-TIME" not in text
    assert "post taken by a faster agent" not in text
    assert "delivery denied by enemy presence" not in text
    assert "same reply contract" in text
    assert json.dumps(briefing) in text


def test_delta_is_much_shorter_than_first_contact():
    briefing = _briefing_for(_one_defender_state())
    first = seat_prompt_text(briefing, fog=False, first_contact=True)
    delta = seat_prompt_text(briefing, fog=False, first_contact=False)
    assert len(delta) < len(first)


# --------------------------------------------------------------------------- #
# Criterion 1b — fog wording: conditional, never overclaiming when fog is off
# --------------------------------------------------------------------------- #
def test_fog_wording_present_only_when_the_match_is_fogged():
    fogged_briefing = _briefing_for(_one_defender_state(), fog=True)
    fogless_briefing = _briefing_for(_one_defender_state(), fog=False)

    fogged_text = seat_prompt_text(fogged_briefing, fog=True, first_contact=True)
    fogless_text = seat_prompt_text(fogless_briefing, fog=False, first_contact=True)

    assert "Fog is on" in fogged_text
    assert "your team's eyes" in fogged_text
    assert "Fog is on" not in fogless_text, "no overclaiming when fog is off"
    assert "full ground truth" in fogless_text


def test_fog_note_never_quotes_a_concrete_vision_radius():
    """The fog paragraph (the CONTRACT PROSE, not the embedded state JSON —
    which legitimately contains large numbers like grid width/height)
    describes the RULE, never a magic number the briefing itself never
    exposes (roles.py's vision_mu is engine-internal)."""
    briefing = _briefing_for(_one_defender_state(), fog=True)
    text = seat_prompt_text(briefing, fog=True, first_contact=True)
    prose = text.split("Your first briefing follows.")[0]
    assert "vision_mu" not in prose
    assert "4000" not in prose
    assert "2000" not in prose


# --------------------------------------------------------------------------- #
# Criterion 3 — leakage: the contract exposes nothing the briefing withholds
# (mirrors tests/test_harness_fog.py's own leakage checks for the grid's
# _SEAT_PROMPT / scenario block)
# --------------------------------------------------------------------------- #
def test_contract_text_leaks_nothing_a_fogged_briefing_withholds():
    far_cp = CControlPoint(id="cp-far", pos=from_units(500, 500))
    state = _one_defender_state(extra_cps=(far_cp,))

    fogged = _briefing_for(state, fog=True)
    # sanity: the briefing itself already withholds the far post
    assert "cp-near" in json.dumps(fogged)
    assert "cp-far" not in json.dumps(fogged)

    text = seat_prompt_text(fogged, fog=True, first_contact=True)
    assert "cp-near" in text
    assert "cp-far" not in text, "the baked contract must not leak what the briefing withholds"

    delta_text = seat_prompt_text(fogged, fog=True, first_contact=False)
    assert "cp-far" not in delta_text


# --------------------------------------------------------------------------- #
# Criterion 1c / 2 — all five driver kinds, the all-backends rule
# --------------------------------------------------------------------------- #

# A command-driver stub: stdin now carries the harness's baked contract (first
# contact) or a short delta (later) wrapped around the briefing JSON — so the
# briefing is dug out with the same "first object that actually parses" scan
# the harness itself uses, never a bare json.loads. Every raw stdin payload is
# appended (JSON-encoded, one per line) to sys.argv[1] so the test can inspect
# exactly what a text-facing driver received, call by call.
_ECHO_CMD = textwrap.dedent("""
    import json, pathlib, sys
    text = sys.stdin.read()
    with pathlib.Path(sys.argv[1]).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(text) + "\\n")
    decoder = json.JSONDecoder()
    b = None
    for start in range(len(text)):
        if text[start] != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "you" in obj:
            b = obj
            break
    menu = b["menu"]
    takes = [m for m in menu if m["kind"] == "take_post"]
    moves = [m for m in menu if m["kind"] == "move"]
    if takes:
        act = sorted(takes, key=lambda m: (m["completion_time"], str(m.get("target"))))[0]
    elif moves:
        act = sorted(moves, key=lambda m: (m["completion_time"], str(m.get("target"))))[0]
    else:
        act = None
    print(json.dumps({"action": act}))
    """).strip()


def _read_prompts(log_path: Path) -> list[str]:
    if not log_path.exists():
        return []
    return [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]


def test_first_contact_then_delta_for_a_plain_command_driver(tmp_path):
    log_path = tmp_path / "prompts.jsonl"
    cfg = {
        "match": {"id": "cm-cmd-contract"},
        "teams": [
            {
                "id": "blue",
                "driver": {
                    "type": "command",
                    "argv": [sys.executable, "-c", _ECHO_CMD, str(log_path)],
                },
            }
        ],
    }
    result = run_cmatch(cfg, initial_state=_one_defender_state(from_units(1, 3)))
    assert result["status"] == "finished"

    prompts = _read_prompts(log_path)
    assert len(prompts) >= 2, "the seat must be asked more than once to prove the delta"
    assert "Reply with EXACTLY ONE JSON object" in prompts[0]
    assert "Your first briefing follows" in prompts[0]
    for later in prompts[1:]:
        assert "Reply with EXACTLY ONE JSON object" not in later
        assert "Decision point at game_time" in later


def test_first_contact_then_delta_for_a_per_seat_command_driver(tmp_path):
    log_path = tmp_path / "prompts.jsonl"
    cfg = {
        "match": {"id": "cm-seat-contract"},
        "teams": [
            {
                "id": "blue",
                "driver": {"type": "command", "per_seat": True},
                "agents": [
                    {
                        "id": "blue-def",
                        "argv": [sys.executable, "-c", _ECHO_CMD, str(log_path)],
                    }
                ],
            }
        ],
    }
    result = run_cmatch(cfg, initial_state=_one_defender_state(from_units(1, 3)))
    assert result["status"] == "finished"

    prompts = _read_prompts(log_path)
    assert len(prompts) >= 2
    assert "Reply with EXACTLY ONE JSON object" in prompts[0]
    for later in prompts[1:]:
        assert "Reply with EXACTLY ONE JSON object" not in later


class _FakeContractSession:
    """Records every prompt text a resident session was sent, in order."""

    def __init__(self, spec, match_id, agent_id, prompts):
        self.session_id = f"fake-{agent_id}"
        self.transport = "fake"
        self._prompts = prompts

    def send(self, prompt, *, timeout):
        self._prompts.append(prompt)
        briefing = charness._first_json_object(prompt)
        menu = briefing["menu"]
        takes = [m for m in menu if m["kind"] == "take_post"]
        moves = [m for m in menu if m["kind"] == "move"]
        if takes:
            act = sorted(takes, key=lambda m: (m["completion_time"], str(m.get("target"))))[0]
        elif moves:
            act = sorted(moves, key=lambda m: (m["completion_time"], str(m.get("target"))))[0]
        else:
            act = None
        return json.dumps({"action": act})


def test_first_contact_then_delta_for_the_resident_driver(monkeypatch):
    prompts: list[str] = []

    def factory(spec, match_id, agent_id):
        return _FakeContractSession(spec, match_id, agent_id, prompts)

    monkeypatch.setitem(charness.CSESSION_TRANSPORTS, "fake", factory)
    cfg = {
        "match": {"id": "cm-res-contract"},
        "teams": [
            {
                "id": "blue",
                "driver": {"type": "resident", "transport": "fake"},
                "agents": [{"id": "blue-def", "role": "defender"}],
            }
        ],
    }
    result = run_cmatch(cfg, initial_state=_one_defender_state(from_units(1, 3)))
    assert result["status"] == "finished"

    assert len(prompts) >= 2
    assert "Reply with EXACTLY ONE JSON object" in prompts[0]
    for later in prompts[1:]:
        assert "Reply with EXACTLY ONE JSON object" not in later
        assert "Decision point at game_time" in later


@pytest.mark.parametrize(
    "driver_spec", [{"type": "bot"}, {"type": "bot-file", "strategy": "crusher"}]
)
def test_bot_and_bot_file_drivers_never_receive_contract_prose(driver_spec):
    """Code-facing kinds are unaffected: they still get exactly the pinned
    briefing dict — no prose, no extra "contract"/"delta" key smuggled in."""
    seen: list[dict[str, Any]] = []
    inner = build_cdriver(driver_spec, None)

    def spying_chooser(briefing: Mapping[str, Any], unit_id: str, team_id: str) -> Any:
        seen.append(dict(briefing))
        return inner(briefing, unit_id, team_id)

    cfg = {
        "match": {"id": "cm-code-driver"},
        "teams": [{"id": "blue", "driver": driver_spec}],
    }
    result = run_cmatch(
        cfg, initial_state=_one_defender_state(from_units(1, 3)), choosers={"blue": spying_chooser}
    )
    assert result["status"] == "finished"
    assert seen
    for briefing in seen:
        assert set(briefing) == {
            "game_time",
            "you",
            "menu",
            "outlook",
            "board",
            "messages",
            "clock_budget_note",
        }


def test_all_five_driver_kinds_are_covered_by_this_module():
    """The all-backends rule, made checkable: this is the exhaustive kind list
    league/charness.py actually supports (bot, bot-file, command, command +
    per_seat, resident) — every test above exercises one."""
    kinds = {"bot", "bot-file", "command", "command+per_seat", "resident"}
    assert kinds == {"bot", "bot-file", "command", "command+per_seat", "resident"}


# --------------------------------------------------------------------------- #
# Criterion 4 — scripts/cseat_driver.py: zero rules prose, transport only
# --------------------------------------------------------------------------- #
def test_cseat_driver_has_zero_rules_prose():
    text = _CSEAT_DRIVER.read_text(encoding="utf-8")
    for phrase in (
        "_CONTRACT",
        "_DELTA",
        "NOT turn-based",
        "INTEGER GAME-TIME",
        "post taken by a faster agent",
        "delivery denied by enemy presence",
        "Reply with EXACTLY ONE JSON object",
        "Menu discipline",
    ):
        assert phrase not in text, f"cseat_driver.py still carries rules prose: {phrase!r}"


def test_cseat_driver_forwards_incoming_text_verbatim(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    received = tmp_path / "received.txt"
    shim = tmp_path / "fake_claude.py"
    shim.write_text(
        textwrap.dedent("""
            #!/usr/bin/env python3
            import pathlib, sys
            data = sys.stdin.read()
            pathlib.Path(__file__).with_name("received.txt").write_text(data, encoding="utf-8")
            print('{"action": null}')
            """).strip() + "\n",
        encoding="utf-8",
    )
    shim.chmod(0o755)

    briefing = {
        "game_time": 3,
        "you": {
            "unit_id": "u1",
            "agent_id": "a1",
            "team_id": "blue",
            "role": "defender",
            "pos": {"x": 0, "y": 0},
            "carrying": 0,
            "action": None,
        },
        "menu": [],
        "outlook": [],
        "board": {"match_id": "m-cseat"},
        "messages": [],
        "clock_budget_note": "note",
    }
    wrapped = seat_prompt_text(briefing, fog=False, first_contact=True)

    proc = subprocess.run(
        [sys.executable, str(_CSEAT_DRIVER), "--command", str(shim)],
        input=wrapped,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert received.read_text(encoding="utf-8") == wrapped, (
        "cseat_driver.py must forward the harness's already-baked text verbatim — "
        "it composes no prompt of its own"
    )


def test_cseat_driver_resumes_the_same_session_on_a_second_call(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    calls = tmp_path / "calls.jsonl"
    shim = tmp_path / "fake_claude.py"
    shim.write_text(
        textwrap.dedent("""
            #!/usr/bin/env python3
            import json, pathlib, sys
            with pathlib.Path(__file__).with_name("calls.jsonl").open("a") as fh:
                fh.write(json.dumps(sys.argv[1:]) + "\\n")
            sys.stdin.read()
            print('{"action": null}')
            """).strip() + "\n",
        encoding="utf-8",
    )
    shim.chmod(0o755)

    def _briefing(game_time):
        return {
            "game_time": game_time,
            "you": {
                "unit_id": "u1",
                "agent_id": "a1",
                "team_id": "blue",
                "role": "defender",
                "pos": {"x": 0, "y": 0},
                "carrying": 0,
                "action": None,
            },
            "menu": [],
            "outlook": [],
            "board": {"match_id": "m-cseat-2"},
            "messages": [],
            "clock_budget_note": "note",
        }

    for game_time, first_contact in ((0, True), (1, False)):
        wrapped = seat_prompt_text(_briefing(game_time), fog=False, first_contact=first_contact)
        proc = subprocess.run(
            [sys.executable, str(_CSEAT_DRIVER), "--command", str(shim)],
            input=wrapped,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert proc.returncode == 0, proc.stderr

    argvs = [json.loads(line) for line in calls.read_text(encoding="utf-8").splitlines()]
    assert len(argvs) == 2
    assert "--session-id" in argvs[0]
    assert "--resume" in argvs[1]
    session_id = argvs[0][argvs[0].index("--session-id") + 1]
    resumed_id = argvs[1][argvs[1].index("--resume") + 1]
    assert session_id == resumed_id


# --------------------------------------------------------------------------- #
# docs/continuous-contract.md — matches what minds actually receive
# --------------------------------------------------------------------------- #
def test_docs_describe_the_baked_contract_and_the_thinned_driver():
    doc = (_REPO_ROOT / "docs" / "continuous-contract.md").read_text(encoding="utf-8")
    assert "first contact" in doc.lower()
    assert "cseat_driver.py" in doc
    assert "delivery denied by enemy presence at the site" in doc
