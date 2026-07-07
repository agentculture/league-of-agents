"""Tempo — the third scored axis, computed at read time (plan task t5, spec c4/h4).

Speed is a real dimension the arena did not see: in season 0 a 10-minute turn
and a 30-second turn scored identically, and the 4.5-hour opener proved tempo
matters. But raw wall-clock conflates *substrate* with *skill* — a hosted cloud
mind is inherently faster than a local one — so speed must be **converted**
before it is compared, not compared naively (spec c4/h4 boundary).

Two binding decisions shape this module (spec, "Decisions"):

* **Measurement is separated from scoring.** Latency is ALWAYS recorded, cheap
  and factual, as ``seat_latency`` OBSERVATION events on the match log (plan
  task t1, ``league.harness`` / ``league.engine.events``). The tempo *score* is
  computed HERE, at read time, from that log against a per-substrate calibration
  baseline. The formula lives in code, never in the log — so the formula can
  evolve without invalidating a single recorded match. Old logs (no
  ``seat_latency`` events) degrade gracefully: ``raw`` is ``None``, ``converted``
  is absent, nothing raises.
* **Tempo is a THIRD SCORED AXIS.** :func:`score_tempo` returns a payload
  published BESIDE outcome and cooperation (``league.engine.scoring``), never
  merged into either. Every surface that prints a converted tempo score MUST
  print raw latency beside it (the h4 honesty condition) — this module keeps
  ``raw`` and ``converted`` side by side in one payload so a caller cannot show
  one without the other.

Substrate is **caller-declared** (a config/CLI flag), never guessed from timing:
:func:`score_tempo` takes a ``{team_id: substrate_name}`` mapping and a
``{substrate_name: baseline_ms}`` calibration table (:data:`DEFAULT_CALIBRATION`
by default). A declared, known substrate converts against its baseline; an
unknown or undeclared one falls back to an **identity conversion** — baseline set
to the team's own median, score pinned at par — with a loud caveat flag, so the
payload never *pretends* to have normalized what it could not.

The calibration magnitudes here are **illustrative seed values**. The published,
contestable methodology — and any real numbers — are the C4-t6 document's job,
not this code's; what is load-bearing here is the mechanism and its honesty, not
the constants. Every constant is nonetheless a NAMED constant with a pinning
unit test (``tests/test_engine_tempo.py``).

Like the rest of ``league.engine`` this module reads the log and nothing else:
it imports no ``time``/``random``/``datetime`` (the determinism import ban,
``tests/test_engine_state.py::test_engine_never_imports_time_or_random``, walks
it), and ``seat_latency`` folds to a no-op — so tempo scoring can never perturb
``MatchState``, ``state_hash``, or the determinism gate.
"""

from __future__ import annotations

from typing import Any, Mapping

from league.engine.events import MatchLog

# The read-time formula's version tag, echoed in every payload. Bump it when the
# formula changes — recorded logs stay valid; only the derived score moves.
TEMPO_VERSION = "t0"

# The index "par": a team turning in AT its substrate's baseline scores exactly
# TEMPO_SCALE. Faster than baseline scores above it, slower below — the score is
# a normalized speed index (100 = baseline pace), not a bounded 0..100 grade, so
# being fast is rewarded rather than clipped.
TEMPO_SCALE = 100

# Measurement floor for the divide: a sub-millisecond median (a bot that decides
# instantly) is treated as at least 1 ms so the index stays finite. Never zero.
MIN_MEASURED_MS = 1

# The per-substrate calibration baseline: substrate name -> a representative
# per-turn latency in milliseconds. ILLUSTRATIVE SEED VALUES ONLY — the C4-t6
# methodology document owns the real numbers and may replace every one of these.
# The load-bearing property is the ORDER (a cloud substrate's baseline is below a
# local one's, because cloud is inherently faster) and that the table is DATA
# with a clear extension point (pass your own ``calibration=`` to override it).
DEFAULT_CALIBRATION: dict[str, int] = {
    "cloud": 20_000,  # hosted / frontier LLM: fast substrate
    "local": 200_000,  # local / on-device LLM: slow substrate (~10x cloud)
    "bot": 10,  # a coded strategy bot: effectively instantaneous
}


def _median(values: list[int]) -> int:
    """Median of a non-empty list, rounded to a whole millisecond.

    Median (not mean) drives the score: it is robust to one pathological slow
    turn, so a single stall cannot dominate a team's tempo.
    """
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2:
        return ordered[mid]
    return round((ordered[mid - 1] + ordered[mid]) / 2)


def _nearest_rank(values: list[int], numerator: int, denominator: int) -> int:
    """The ``numerator/denominator`` percentile by the nearest-rank method.

    Integer-only (``rank = ceil(q * n)``, no ``math`` import): deterministic and
    dependency-free, matching the engine's no-float-surprises discipline.
    """
    ordered = sorted(values)
    n = len(ordered)
    rank = -(-(numerator * n) // denominator)  # ceil(numerator*n / denominator)
    index = min(max(rank, 1), n) - 1
    return ordered[index]


def _raw_block(events_data: list[Mapping[str, Any]], turns: set[int]) -> dict[str, Any]:
    """The always-published raw latency facts for one team.

    ``median_ms`` drives the converted score; ``p95_ms`` exposes the tail; the
    counts say how much of the match was actually measured.
    """
    elapsed = [int(d["elapsed_ms"]) for d in events_data]
    seats = {d.get("agent_id") for d in events_data}  # None counts as one team-wide seat
    return {
        "median_ms": _median(elapsed),
        "mean_ms": round(sum(elapsed) / len(elapsed)),
        "p95_ms": _nearest_rank(elapsed, 95, 100),
        "turns_measured": len(turns),
        "seats_measured": len(seats),
    }


def _converted_block(
    median_ms: int, substrate: str | None, calibration: Mapping[str, int]
) -> dict[str, Any]:
    """Convert one team's median against its declared substrate baseline.

    Known substrate: normalize against ``calibration[substrate]`` —
    ``ratio = median / baseline`` (<1 faster than baseline, >1 slower) and
    ``tempo_score = round(TEMPO_SCALE * baseline / max(median, MIN_MEASURED_MS))``.
    Unknown / undeclared: an **identity conversion** — baseline is the team's own
    median, ratio is 1.0, score is par — carrying a caveat flag so the payload
    never claims a normalization it did not perform.
    """
    if substrate is not None and substrate in calibration:
        baseline = int(calibration[substrate])
        ratio = round(median_ms / baseline, 4) if baseline else 0.0
        tempo_score = round(TEMPO_SCALE * baseline / max(median_ms, MIN_MEASURED_MS))
        return {
            "tempo_score": tempo_score,
            "baseline_ms": baseline,
            "ratio": ratio,
            "substrate": substrate,
            "substrate_known": True,
        }
    if substrate is None:
        caveat = (
            "no substrate declared for this team; identity conversion applied — "
            "the tempo score is NOT substrate-normalized (raw latency is shown "
            "beside it). Declare a substrate to normalize."
        )
    else:
        caveat = (
            f"unknown substrate {substrate!r} (not in the calibration table "
            f"{sorted(calibration)}); identity conversion applied — the tempo score "
            "is NOT substrate-normalized (raw latency is shown beside it)."
        )
    return {
        "tempo_score": TEMPO_SCALE,  # par: a neutral, non-normalized placeholder
        "baseline_ms": median_ms,  # identity: baseline == the team's own median
        "ratio": 1.0,
        "substrate": substrate,
        "substrate_known": False,
        "caveat": caveat,
    }


def score_tempo(
    log: MatchLog,
    *,
    substrates: Mapping[str, str] | None = None,
    calibration: Mapping[str, int] | None = None,
) -> dict[str, dict[str, Any]]:
    """Tempo per team, from the log's ``seat_latency`` metadata and nothing else.

    Returns ``{team_id: {"raw": ..., "converted": ..., "version": "t0"}}`` — a
    third axis to publish BESIDE ``score_match``'s outcome and cooperation, never
    merged into either. ``raw`` (``median_ms``/``mean_ms``/``p95_ms``/
    ``turns_measured``/``seats_measured``) is ALWAYS present so a caller can never
    show ``converted`` without it (the h4 honesty condition). A team with no
    ``seat_latency`` events (every committed season-0 log) gets ``raw = None`` and
    no ``converted`` key — graceful, never a crash.

    ``substrates`` is the caller-declared ``{team_id: substrate_name}`` map
    (config/CLI flag, never guessed from timing); ``calibration`` overrides
    :data:`DEFAULT_CALIBRATION`.
    """
    substrates = substrates or {}
    table: Mapping[str, int] = DEFAULT_CALIBRATION if calibration is None else calibration

    by_team_data: dict[str, list[Mapping[str, Any]]] = {}
    by_team_turns: dict[str, set[int]] = {}
    for event in log.events:
        if event.kind != "seat_latency":
            continue
        team_id = event.data.get("team_id")
        if team_id is None:
            continue
        by_team_data.setdefault(team_id, []).append(event.data)
        by_team_turns.setdefault(team_id, set()).add(event.turn)

    report: dict[str, dict[str, Any]] = {}
    for team in log.final_state().teams:
        data = by_team_data.get(team.id)
        if not data:
            # Missing latency (old logs): raw null-ish, converted absent.
            report[team.id] = {"raw": None, "version": TEMPO_VERSION}
            continue
        raw = _raw_block(data, by_team_turns[team.id])
        converted = _converted_block(raw["median_ms"], substrates.get(team.id), table)
        report[team.id] = {"raw": raw, "converted": converted, "version": TEMPO_VERSION}
    return report
