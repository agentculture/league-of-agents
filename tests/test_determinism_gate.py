"""The determinism CI gate (plan task t6, spec h2).

A canonical scripted match — fixed scenario, seed, and per-turn orders — is
replayed through the real tick engine on every CI run. The resulting final
state hash must equal the committed fixture. If engine rules change on
purpose, regenerate the fixture and justify it in the PR:

    uv run python -c "from tests.test_determinism_gate import compute_final_hash; \\
        print(compute_final_hash())" > tests/fixtures/determinism.hash

Any *unintentional* drift — platform, ordering, refactor side effects — fails
here before it can corrupt fairness (same actions + same seed must mean same
outcome, or matches stop being comparable).

Cycle-8 t10 deliberate regeneration (documented, pre-authorized, see
docs/roles.md's "Decision: the scout is eyes-only" section): flipping the
grid scout's ``can_capture`` to ``False`` changes this exact script's outcome
— blue's scout (``blue-u1``) still walks to and parks on ``cp-east`` at turn
4 (the script is otherwise untouched), but no longer counts as an occupant,
so ``cp-east`` is never captured and ``ms-outpost`` never completes. A second,
knock-on effect: red's scout (``red-u1``) no longer contests ``cp-center``
either (it also can't capture), so blue's defender (``blue-u3``), which
arrives at ``cp-center`` on turn 5, captures it outright on turn 6 instead of
the two of them contesting it forever. The fixture below was regenerated from
this same script under the new rule; see this task's commit for the old/new
hash pair.
"""

from __future__ import annotations

from pathlib import Path

from league.engine.events import MatchLog
from league.engine.scenario import get_scenario, instantiate
from league.engine.state import AgentSlot, state_hash
from league.engine.tick import resolve_turn, start_match

FIXTURE = Path(__file__).parent / "fixtures" / "determinism.hash"

# Every move below respects role ranges (scout 3, harvester 2, defender 2)
# from the skirmish-1 spawns: blue (0,0)/(1,0)/(0,1), red (11,9)/(10,9)/(11,8).
_SCRIPT = [
    {  # turn 1 — both sides fan out
        "blue": {
            "plan": "harvester to west node; defender screens; scout takes east point",
            "messages": [{"from": "blue-1", "text": "opening relay"}],
            "actions": [
                {"unit_id": "blue-u1", "action": "move", "to": [3, 0]},
                {"unit_id": "blue-u2", "action": "move", "to": [1, 2]},
                {"unit_id": "blue-u3", "action": "move", "to": [0, 3]},
            ],
        },
        "red": {
            "actions": [
                {"unit_id": "red-u1", "action": "move", "to": [9, 8]},
                {"unit_id": "red-u2", "action": "move", "to": [10, 7]},
            ]
        },
    },
    {  # turn 2 — advance
        "blue": {
            "actions": [
                {"unit_id": "blue-u1", "action": "move", "to": [6, 0]},
                {"unit_id": "blue-u2", "action": "move", "to": [1, 4]},
                {"unit_id": "blue-u3", "action": "move", "to": [1, 4]},
            ]
        },
        "red": {
            "actions": [
                {"unit_id": "red-u1", "action": "move", "to": [9, 5]},
                {"unit_id": "red-u2", "action": "move", "to": [10, 5]},
            ]
        },
    },
    {  # turn 3 — blue reaches the west node; red heads for center + east node
        "blue": {
            "actions": [
                {"unit_id": "blue-u1", "action": "move", "to": [8, 1]},
                {"unit_id": "blue-u2", "action": "move", "to": [0, 5]},
                {"unit_id": "blue-u3", "action": "move", "to": [2, 5]},
            ]
        },
        "red": {
            "actions": [
                {"unit_id": "red-u1", "action": "move", "to": [8, 4]},
                {"unit_id": "red-u2", "action": "move", "to": [11, 4]},
            ]
        },
    },
    {  # turn 4 — blue scout lands on cp-east (eyes-only: it will never count
        # as an occupant there — cycle-8 t10); both harvesters gather; red's
        # scout reaches cp-center alone (it won't count there either).
        "blue": {
            "actions": [
                {"unit_id": "blue-u1", "action": "move", "to": [9, 2]},
                {"unit_id": "blue-u2", "action": "gather"},
                {"unit_id": "blue-u3", "action": "move", "to": [4, 5]},
            ]
        },
        "red": {
            "actions": [
                {"unit_id": "red-u1", "action": "move", "to": [6, 5]},
                {"unit_id": "red-u2", "action": "gather"},
            ]
        },
    },
    {  # turn 5 — cp-east stays uncaptured (blue's sole occupant is its
        # eyes-only scout); blue's defender arrives at cp-center where red's
        # scout already sits — but the scout doesn't count as an occupant, so
        # blue starts an UNCONTESTED streak there instead of a real contest.
        "blue": {
            "messages": [{"from": "blue-3", "text": "contesting center, keep east"}],
            "actions": [
                {"unit_id": "blue-u1", "action": "hold"},
                {"unit_id": "blue-u2", "action": "move", "to": [2, 5]},
                {"unit_id": "blue-u3", "action": "move", "to": [6, 5]},
            ],
        },
        "red": {
            "actions": [
                {"unit_id": "red-u1", "action": "hold"},
                {"unit_id": "red-u2", "action": "move", "to": [11, 6]},
            ]
        },
    },
    {  # turn 6 — blue's center streak (started turn 5) completes: blue
        # captures cp-center outright, since red's scout was never a real
        # contester. cp-east still sits uncaptured under blue's parked scout.
        "blue": {
            "actions": [
                {"unit_id": "blue-u1", "action": "hold"},
                {"unit_id": "blue-u2", "action": "move", "to": [4, 5]},
                {"unit_id": "blue-u3", "action": "hold"},
            ]
        },
        "red": {
            "actions": [
                {"unit_id": "red-u1", "action": "hold"},
                {"unit_id": "red-u2", "action": "move", "to": [11, 8]},
            ]
        },
    },
    {  # turn 7 — blue harvester arrives at the delivery square
        "blue": {
            "actions": [
                {"unit_id": "blue-u1", "action": "hold"},
                {"unit_id": "blue-u2", "action": "move", "to": [6, 5]},
                {"unit_id": "blue-u3", "action": "hold"},
            ]
        },
        "red": {
            "actions": [
                {"unit_id": "red-u1", "action": "hold"},
                {"unit_id": "red-u2", "action": "hold"},
            ]
        },
    },
    {  # turn 8 — delivery lands (blue banks 3 resources; ms-supply needs 6,
        # so it stays open); blue's cp-center hold keeps extending (streak 4,
        # already captured turn 6); cp-east remains uncaptured throughout —
        # ms-outpost never opens a hold window, by design of this cycle's rule.
        "blue": {
            "actions": [
                {"unit_id": "blue-u1", "action": "hold"},
                {"unit_id": "blue-u2", "action": "deliver"},
                {"unit_id": "blue-u3", "action": "hold"},
            ]
        },
        "red": {
            "actions": [
                {"unit_id": "red-u1", "action": "hold"},
                {"unit_id": "red-u2", "action": "hold"},
            ]
        },
    },
]


def _roster(team: str, model: str) -> tuple[AgentSlot, ...]:
    return (
        AgentSlot(id=f"{team}-1", model=model, role="scout"),
        AgentSlot(id=f"{team}-2", model=model, role="harvester"),
        AgentSlot(id=f"{team}-3", model=model, role="defender"),
    )


def play_canonical_match() -> MatchLog:
    scenario = get_scenario("skirmish-1")
    initial = instantiate(
        scenario,
        match_id="m-determinism-gate",
        seed=2026,
        mode="competitive",
        teams=(
            ("blue", "Blue Foundry", _roster("blue", "claude-sonnet-5")),
            ("red", "Red Relay", _roster("red", "colleague/qwen")),
        ),
    )
    state, events = start_match(initial)
    all_events = list(events)
    for orders in _SCRIPT:
        state, events = resolve_turn(state, scenario, orders, seq_start=len(all_events))
        all_events.extend(events)
    return MatchLog(initial_state=initial, events=tuple(all_events))


def compute_final_hash() -> str:
    return state_hash(play_canonical_match().final_state())


def test_committed_hash_matches_replay() -> None:
    assert FIXTURE.is_file(), (
        "fixture missing — generate it with the command in this module's docstring; "
        f"current computed hash: {compute_final_hash()}"
    )
    committed = FIXTURE.read_text(encoding="utf-8").strip()
    assert compute_final_hash() == committed, (
        "engine determinism drift: the canonical match no longer replays to the "
        "committed end state. If a rule change is intentional, regenerate the fixture "
        "(see module docstring) and call the change out in the PR."
    )


def test_two_fresh_replays_agree_and_fold_matches_tick() -> None:
    a = play_canonical_match()
    b = play_canonical_match()
    assert a.to_jsonl() == b.to_jsonl()
    assert state_hash(a.final_state()) == state_hash(b.final_state())


def test_the_scripted_match_actually_exercises_the_rules() -> None:
    """Guard against the gate going vacuous: the script must hit real mechanics."""
    log = play_canonical_match()
    kinds = {e.kind for e in log.events}
    assert {
        "unit_moved",
        "resource_gathered",
        "resource_delivered",
        "control_point_captured",
        "control_point_held",
        "message_sent",
        "plan_declared",
    } <= kinds
    final = log.final_state()
    assert any(t.resources > 0 for t in final.teams)
    assert any(c.owner for c in final.control_points)
