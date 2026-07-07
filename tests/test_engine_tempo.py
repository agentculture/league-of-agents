"""Tempo — the third scored axis, computed at read time (plan task t5, spec c4/h4).

Criteria under test (the merge gate):

* the tempo SCORE is computed at read time from the log's ``seat_latency``
  metadata against a per-substrate calibration baseline — the formula lives in
  code (``league.engine.tempo``), never in the log, so a formula change never
  invalidates a recorded match;
* substrate is CALLER-DECLARED (never guessed from timing): a known substrate
  converts against its baseline, an unknown/undeclared one degrades to an
  identity conversion with a loud caveat flag;
* missing latency (every committed season-0 log) degrades gracefully —
  ``raw`` is null-ish, ``converted`` is absent, and nothing crashes;
* every constant is pinned here (the "own the formula, pin the constant" rule).

``score_tempo`` is a pure log reader: like the rest of ``league.engine`` it
never imports ``time``/``random`` (the determinism import ban,
``tests/test_engine_state.py::test_engine_never_imports_time_or_random``, walks
this module too), so tempo scoring can never perturb ``state_hash`` or the
determinism gate.
"""

from __future__ import annotations

import pathlib

import pytest

from league.engine.events import Event, MatchLog
from league.engine.state import AgentSlot, MatchState, TeamState, Unit
from league.engine.tempo import (
    DEFAULT_CALIBRATION,
    MIN_MEASURED_MS,
    TEMPO_SCALE,
    TEMPO_VERSION,
    score_tempo,
)

_SEASON0 = pathlib.Path(__file__).resolve().parent.parent / "docs" / "playtests" / "season-0"


# --------------------------------------------------------------------------- #
# Synthetic-log builders. seat_latency is an OBSERVATION event: it folds to a
# no-op, so a hand-built log needs no real board — just teams and the events.
# --------------------------------------------------------------------------- #


def _team(tid: str, n: int) -> TeamState:
    agents = tuple(AgentSlot(id=f"{tid}-{i}", model="m", role="scout") for i in range(1, n + 1))
    return TeamState(id=tid, name=tid.title(), resources=0, agents=agents)


def _unit(tid: str, i: int) -> Unit:
    return Unit(id=f"{tid}-u{i}", team_id=tid, agent_id=f"{tid}-{i}", role="scout", pos=(0, 0))


def _state(*teams: TeamState) -> MatchState:
    units = tuple(_unit(t.id, i + 1) for t in teams for i in range(len(t.agents) or 1))
    return MatchState(
        match_id="m-tempo",
        scenario_id="skirmish-1",
        seed=0,
        mode="competitive",
        turn=1,
        turn_limit=30,
        grid_width=12,
        grid_height=10,
        status="finished",
        winner=None,
        teams=teams,
        units=units,
        control_points=(),
        missions=(),
        resource_nodes=(),
    )


def _latency(team_id: str, turn: int, elapsed_ms: int, agent_id=None, unit_id=None):
    return (
        turn,
        "seat_latency",
        {"team_id": team_id, "agent_id": agent_id, "unit_id": unit_id, "elapsed_ms": elapsed_ms},
    )


def _log(initial: MatchState, triples) -> MatchLog:
    events = tuple(
        Event(turn=turn, seq=i, kind=kind, data=data)
        for i, (turn, kind, data) in enumerate(triples)
    )
    return MatchLog(initial_state=initial, events=events)


# --------------------------------------------------------------------------- #
# 1. Constants are pinned (own the formula, pin the constant).
# --------------------------------------------------------------------------- #


def test_calibration_and_constants_are_pinned() -> None:
    assert TEMPO_VERSION == "t0"
    assert TEMPO_SCALE == 100
    assert MIN_MEASURED_MS == 1
    # Cloud is the faster substrate: its baseline is below local's. The exact
    # magnitudes are illustrative seed values (the C4-t6 methodology doc owns
    # the real numbers); what is load-bearing is the ORDER and the mechanism.
    assert DEFAULT_CALIBRATION == {"cloud": 20_000, "local": 200_000, "bot": 10}
    assert DEFAULT_CALIBRATION["cloud"] < DEFAULT_CALIBRATION["local"]


# --------------------------------------------------------------------------- #
# 2. Raw stats are computed straight from the seat_latency events.
# --------------------------------------------------------------------------- #


def test_raw_block_computes_median_mean_p95_and_counts() -> None:
    initial = _state(_team("blue", 1))
    # Five turns, one team-level entry each: 100, 200, 300, 400, 500.
    triples = [_latency("blue", t, 100 * t) for t in range(1, 6)]
    payload = score_tempo(_log(initial, triples))["blue"]
    raw = payload["raw"]
    assert raw["median_ms"] == 300  # middle of 1..5 x 100
    assert raw["mean_ms"] == 300  # (100+200+300+400+500)/5
    assert raw["p95_ms"] == 500  # nearest-rank 95th percentile of 5 values -> last
    assert raw["turns_measured"] == 5
    assert raw["seats_measured"] == 1  # team-level: one seat-of-one (agent_id None)
    assert payload["version"] == "t0"


def test_seats_measured_counts_distinct_agents() -> None:
    initial = _state(_team("blue", 3))
    triples = [
        _latency("blue", 1, 100, agent_id="blue-1", unit_id="blue-u1"),
        _latency("blue", 1, 200, agent_id="blue-2", unit_id="blue-u2"),
        _latency("blue", 1, 300, agent_id="blue-3", unit_id="blue-u3"),
        _latency("blue", 2, 150, agent_id="blue-1", unit_id="blue-u1"),
    ]
    raw = score_tempo(_log(initial, triples))["blue"]["raw"]
    assert raw["seats_measured"] == 3
    assert raw["turns_measured"] == 2


def test_median_of_even_count_is_the_rounded_midpoint() -> None:
    initial = _state(_team("blue", 1))
    triples = [_latency("blue", 1, 100), _latency("blue", 2, 300)]
    raw = score_tempo(_log(initial, triples))["blue"]["raw"]
    assert raw["median_ms"] == 200  # round((100 + 300) / 2)


# --------------------------------------------------------------------------- #
# 3. Known substrate -> conversion against its calibration baseline.
# --------------------------------------------------------------------------- #


def test_known_substrate_converts_against_baseline() -> None:
    initial = _state(_team("blue", 1))
    triples = [_latency("blue", 1, 10_000), _latency("blue", 2, 10_000)]
    payload = score_tempo(_log(initial, triples), substrates={"blue": "cloud"})["blue"]
    conv = payload["converted"]
    assert conv["substrate"] == "cloud"
    assert conv["substrate_known"] is True
    assert conv["baseline_ms"] == DEFAULT_CALIBRATION["cloud"]  # 20_000
    assert conv["ratio"] == 0.5  # median 10_000 / baseline 20_000
    # Faster than baseline -> above par: 100 * 20_000 / 10_000 = 200.
    assert conv["tempo_score"] == 200
    assert "caveat" not in conv


def test_at_baseline_scores_exactly_par() -> None:
    initial = _state(_team("blue", 1))
    triples = [_latency("blue", 1, DEFAULT_CALIBRATION["local"])]
    conv = score_tempo(_log(initial, triples), substrates={"blue": "local"})["blue"]["converted"]
    assert conv["ratio"] == 1.0
    assert conv["tempo_score"] == TEMPO_SCALE  # 100 = par


def test_substrate_conversion_is_fair_across_substrates() -> None:
    """The whole point: a fast cloud mind and a slow local mind, each turning in
    AT its own substrate baseline, score the SAME tempo despite a 10x raw gap —
    conversion normalizes the substrate out (spec c4/h4 boundary)."""
    initial = _state(_team("blue", 1), _team("red", 1))
    triples = [
        _latency("blue", 1, DEFAULT_CALIBRATION["cloud"]),  # 20_000 ms
        _latency("red", 1, DEFAULT_CALIBRATION["local"]),  # 200_000 ms
    ]
    report = score_tempo(_log(initial, triples), substrates={"blue": "cloud", "red": "local"})
    assert report["blue"]["raw"]["median_ms"] != report["red"]["raw"]["median_ms"]
    assert (
        report["blue"]["converted"]["tempo_score"]
        == report["red"]["converted"]["tempo_score"]
        == TEMPO_SCALE
    )


# --------------------------------------------------------------------------- #
# 4. Unknown / undeclared substrate -> identity conversion + caveat flag.
# --------------------------------------------------------------------------- #


def test_undeclared_substrate_uses_identity_conversion() -> None:
    initial = _state(_team("blue", 1))
    triples = [_latency("blue", 1, 7_000), _latency("blue", 2, 9_000)]
    conv = score_tempo(_log(initial, triples))["blue"]["converted"]  # no substrates arg
    assert conv["substrate"] is None
    assert conv["substrate_known"] is False
    assert conv["baseline_ms"] == 8_000  # identity: baseline == the team's own median
    assert conv["ratio"] == 1.0
    assert conv["tempo_score"] == TEMPO_SCALE  # neutral par, NOT a normalized claim
    assert "caveat" in conv and conv["caveat"]


def test_unknown_substrate_name_uses_identity_conversion() -> None:
    initial = _state(_team("blue", 1))
    triples = [_latency("blue", 1, 5_000)]
    conv = score_tempo(_log(initial, triples), substrates={"blue": "quantum"})["blue"]["converted"]
    assert conv["substrate"] == "quantum"  # the declared name is preserved, honestly
    assert conv["substrate_known"] is False
    assert conv["tempo_score"] == TEMPO_SCALE
    assert "caveat" in conv


# --------------------------------------------------------------------------- #
# 5. Missing latency (old logs) degrades gracefully — never a crash.
# --------------------------------------------------------------------------- #


def test_missing_latency_degrades_to_null_raw_and_absent_converted() -> None:
    initial = _state(_team("blue", 1), _team("red", 1))
    log = _log(initial, [])  # no seat_latency events at all
    report = score_tempo(log, substrates={"blue": "cloud"})
    assert set(report) == {"blue", "red"}
    for team_id in ("blue", "red"):
        payload = report[team_id]
        assert payload["raw"] is None
        assert "converted" not in payload  # no raw -> nothing to convert
        assert payload["version"] == "t0"


@pytest.mark.parametrize("name", ["opener", "coordination", "orchestrator"])
def test_committed_season0_logs_have_no_latency_and_do_not_crash(name: str) -> None:
    """The committed season-0 logs predate C4-t1 — they carry NO seat_latency
    events. Reading tempo off them must degrade, never raise."""
    log = MatchLog.from_jsonl((_SEASON0 / f"{name}.log.jsonl").read_text())
    assert not any(e.kind == "seat_latency" for e in log.events)
    report = score_tempo(log)
    assert report  # one payload per team
    for payload in report.values():
        assert payload["raw"] is None
        assert "converted" not in payload
        assert payload["version"] == "t0"


# --------------------------------------------------------------------------- #
# 6. Edge cases: zero-latency seats never divide by zero; every team covered.
# --------------------------------------------------------------------------- #


def test_zero_latency_with_known_substrate_never_divides_by_zero() -> None:
    initial = _state(_team("blue", 1))
    triples = [_latency("blue", 1, 0), _latency("blue", 2, 0)]
    conv = score_tempo(_log(initial, triples), substrates={"blue": "bot"})["blue"]["converted"]
    # median 0 is floored to MIN_MEASURED_MS for the divide — finite, not a crash.
    assert conv["baseline_ms"] == DEFAULT_CALIBRATION["bot"]
    assert conv["ratio"] == 0.0
    assert isinstance(conv["tempo_score"], int)
    assert conv["tempo_score"] == TEMPO_SCALE * DEFAULT_CALIBRATION["bot"] // MIN_MEASURED_MS


def test_every_team_gets_a_payload_even_with_partial_latency() -> None:
    initial = _state(_team("blue", 1), _team("red", 1))
    triples = [_latency("blue", 1, 1_000)]  # only blue is measured
    report = score_tempo(_log(initial, triples))
    assert set(report) == {"blue", "red"}
    assert report["blue"]["raw"] is not None
    assert report["red"]["raw"] is None


def test_explicit_calibration_overrides_the_default_table() -> None:
    initial = _state(_team("blue", 1))
    triples = [_latency("blue", 1, 1_000)]
    conv = score_tempo(
        _log(initial, triples), substrates={"blue": "edge"}, calibration={"edge": 500}
    )["blue"]["converted"]
    assert conv["substrate_known"] is True
    assert conv["baseline_ms"] == 500
    assert conv["ratio"] == 2.0  # median 1000 / baseline 500 -> slower than baseline
    assert conv["tempo_score"] == 50  # 100 * 500 / 1000
