"""The continuous determinism CI gate (plan task C7-t6, spec c10/h3).

The continuous-lane sibling of ``tests/test_determinism_gate.py``: a canonical
scripted match — fixed scenario (``c-skirmish-1``), fixed seed, deterministic
scripted decision callbacks — is replayed through the real continuous resolver
(``resolve_match``) on every CI run. The resulting final ``cstate_hash`` must
equal the committed fixture. If a continuous engine rule changes on purpose,
regenerate the fixture and justify it in the PR:

    uv run python -c "from tests.test_determinism_gate_continuous import \\
        compute_final_hash; print(compute_final_hash())" \\
        > tests/fixtures/determinism_continuous.hash

Any *unintentional* drift — platform, ordering, refactor side effects — fails
here before it can corrupt fairness (same actions + same seed must mean same
outcome, or continuous matches stop being comparable), exactly the same
determinism claim the grid gate has always made. The grid's own fixture
(``tests/fixtures/determinism.hash``) and gate are untouched by this file —
the two lanes each earn determinism on their own committed artifact (spec
c10: "two engine lanes, both honest").

The scripted match is deliberately rich: it is the exact race the spec names
(a slower unit starts taking the post FIRST, a faster unit starts LATER and
still completes first — the loser's attempt is a first-class ``action_failed``
event), running IN PARALLEL with a full gather -> deliver economy and a hold-
mission completion, so the committed hash — and the event-kind coverage
asserted below — pins the whole continuous event vocabulary, not just the
race in isolation.
"""

from __future__ import annotations

from pathlib import Path

from league.engine.continuous.events import EVENT_KINDS, TRANSITION_KINDS
from league.engine.continuous.resolve import ResolveResult, resolve_match
from league.engine.continuous.scenario import get_cscenario, instantiate
from league.engine.continuous.state import CAgentSlot, cstate_hash

FIXTURE = Path(__file__).parent / "fixtures" / "determinism_continuous.hash"


def _slot(uid: str, role: str, model: str) -> CAgentSlot:
    return CAgentSlot(id=uid, model=model, role=role)


def _roster(team: str, model: str) -> tuple[CAgentSlot, ...]:
    return (_slot(f"{team}-scout", "scout", model), _slot(f"{team}-harvester", "harvester", model))


def _pick(menu: dict, kind: str):
    for entry in menu["actions"]:
        if entry["kind"] == kind:
            return entry
    return None


def _pick_move_to(menu: dict, ref: str):
    for entry in menu["actions"]:
        if entry["kind"] == "move" and entry.get("target_ref") == ref:
            return entry
    return None


def _scripted_decider(unit_id: str, state, menu: dict):
    """The canonical scripted match's deciders — dict-driven per unit id, the
    same pattern ``tests/test_continuous_resolve.py`` uses for its scripted
    races. Four units, four distinct jobs:

    * ``blue-u1`` (scout) — travels one unit to ``cp-crossing`` then takes it.
      Starts its take LATER than ``red-u2`` but is the faster role, so it
      completes FIRST: THE race.
    * ``blue-u2`` (harvester) — gathers from the co-located resource node to
      capacity, then delivers — the gather -> deliver economy, running in
      parallel with the race on its own timeline entry.
    * ``red-u2`` (harvester) — already camped on the post; starts taking it at
      ``t=0`` (the slower attempt that starts first and still loses).
    * ``red-u1`` (scout) — parked in a far corner all match; contributes only
      its opening ``decision_point`` (proves an idle unit is inert, not a bug).
    """
    if unit_id == "blue-u1":
        take = _pick(menu, "take_post")
        if take is not None:
            return take
        return _pick_move_to(menu, "cp-crossing")
    if unit_id == "blue-u2":
        unit = next(u for u in state.units if u.id == "blue-u2")
        if unit.carrying < 3:
            gather = _pick(menu, "gather")
            if gather is not None:
                return gather
        return _pick(menu, "deliver")
    if unit_id == "red-u2":
        cp = next(c for c in state.control_points if c.id == "cp-crossing")
        return _pick(menu, "take_post") if cp.owner is None else None
    return None  # red-u1 parks for the whole match


def play_canonical_match() -> ResolveResult:
    scenario = get_cscenario("c-skirmish-1")
    initial = instantiate(
        scenario,
        match_id="cm-determinism-gate",
        seed=2026,
        mode="competitive",
        teams=(
            ("blue", "Blue Foundry", _roster("blue", "claude-sonnet-5")),
            ("red", "Red Relay", _roster("red", "colleague/qwen")),
        ),
    )
    return resolve_match(initial, scenario.role_table, _scripted_decider)


def compute_final_hash() -> str:
    return cstate_hash(play_canonical_match().final_state)


def test_committed_hash_matches_replay() -> None:
    assert FIXTURE.is_file(), (
        "fixture missing — generate it with the command in this module's docstring; "
        f"current computed hash: {compute_final_hash()}"
    )
    committed = FIXTURE.read_text(encoding="utf-8").strip()
    assert compute_final_hash() == committed, (
        "continuous engine determinism drift: the canonical match no longer replays to "
        "the committed end state. If a rule change is intentional, regenerate the fixture "
        "(see module docstring) and call the change out in the PR."
    )


def test_two_fresh_replays_agree_and_fold_matches_resolve() -> None:
    a = play_canonical_match()
    b = play_canonical_match()
    assert a.log.events == b.log.events
    assert a.log.to_jsonl() == b.log.to_jsonl()
    assert cstate_hash(a.final_state) == cstate_hash(b.final_state)
    assert cstate_hash(a.log.final_state()) == cstate_hash(a.final_state)


def test_the_scripted_match_actually_exercises_the_rules() -> None:
    """Guard against the gate going vacuous: the script must hit every
    transition kind, and — the spec's own demand — a REAL race with a
    first-class failed attempt."""
    res = play_canonical_match()
    kinds = {e.kind for e in res.log.events}
    assert set(TRANSITION_KINDS) <= kinds
    assert "decision_point" in kinds
    assert kinds <= set(EVENT_KINDS)

    taken = [e for e in res.log.events if e.kind == "post_taken"]
    assert len(taken) == 1
    assert taken[0].data == {"cp_id": "cp-crossing", "team_id": "blue", "unit_id": "blue-u1"}

    failed = [e for e in res.log.events if e.kind == "action_failed"]
    assert len(failed) == 1
    assert failed[0].data == {"unit_id": "red-u2", "reason": "post taken by a faster agent"}
    # red-u2's OWN take started at t=0 (would complete at t=10); it fails at
    # t=7 — the winner's completion instant, strictly before its own would-be
    # completion — the loser really is caught mid-take, not merely outraced.
    assert failed[0].game_time == 7

    final = res.final_state
    cp = next(c for c in final.control_points if c.id == "cp-crossing")
    assert cp.owner == "blue" and cp.takers == ()

    scenario = get_cscenario("c-skirmish-1")
    assert final.status == "finished"
    assert final.clock <= scenario.time_limit
    assert all(m.status == "completed" for m in final.missions)
    hold = next(m for m in final.missions if m.id == "ms-hold")
    supply = next(m for m in final.missions if m.id == "ms-supply")
    assert hold.completed_by == ("blue",)
    assert supply.completed_by == ("blue",)
    assert final.winner == "blue"

    # red-u1 (parked the whole match) never started an action.
    assert not any(
        e.kind == "action_started" and e.data.get("unit_id") == "red-u1" for e in res.log.events
    )
