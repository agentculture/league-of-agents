"""The compatibility sweep — proof this cycle's engine changes are additive
(cycle-6 plan task t11, spec c12/h12/c4/h4).

Every committed playtest under ``docs/playtests/`` is a permanent record: a
match that actually happened, with a report that draws conclusions from its
log. If an engine change ever silently altered how one of those logs replays,
the report's conclusions would quietly stop being true of the code — a
regression season-0/cycle-4/cycle-5/house-tiers reviewers would have no way to
notice. This module is the tripwire.

It discovers every ``*.log.jsonl`` under ``docs/playtests/`` by glob (so a
playtest added by a future cycle is automatically covered — no per-log
registration to forget), and for each one asserts:

1. ``MatchLog.from_jsonl`` parses it and ``final_state()`` folds without error
   — the log is still a valid replay of *some* match.
2. Where a committed ``*.score.json`` exists for the same ``match_id``,
   ``score_match(log)["outcome"]`` still equals the committed outcome totals
   — the fold didn't just succeed, it still reaches the *same* recorded
   end-state (outcome scoring is version-free, so this holds regardless of
   which cooperation-metric version produced the committed file).

If a future engine change breaks a committed log's fold, or drifts a
committed outcome, THIS is the test that goes red. The fix is never to edit
this module to make it pass again quietly — it is to either revert the
breaking change, or regenerate the affected playtest artifacts (log, score,
replay, report) as a deliberate, documented event called out in the PR that
made the change. A silent "regenerate and move on" defeats the entire point
of committing playtests as a historical record.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest

from league.engine.events import MatchLog
from league.engine.scoring import score_match

PLAYTESTS_DIR = Path(__file__).parent.parent / "docs" / "playtests"

# The known count as of cycle-6 t11 (11 logs across season-0, cycle-4,
# cycle-5, house-tiers). Set below that known floor so future playtests grow
# the sweep without touching this file, while an empty/broken glob (e.g. a
# typo'd pattern, or docs/playtests/ moved) still fails loudly instead of
# vacuously collecting zero tests.
_MIN_KNOWN_LOGS = 10

# The whole sweep — fold + score every committed log — must stay well inside
# this budget so it runs on every invocation without becoming the test suite's
# slow outlier.
_BUDGET_SECONDS = 10.0


def _discover_logs() -> list[Path]:
    return sorted(PLAYTESTS_DIR.glob("**/*.log.jsonl"))


def _discover_scores_by_match_id() -> dict[str, Path]:
    """Index every committed ``*.score.json`` by its own ``match_id``.

    Pairing is by ``match_id``, not filename — a score file whose match id
    doesn't correspond to any committed log (or that fails to parse) is
    simply not indexed, and the sweep skips it rather than guessing a
    filename-based pairing.
    """
    by_match_id: dict[str, Path] = {}
    for path in sorted(PLAYTESTS_DIR.glob("**/*.score.json")):
        try:
            payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        match_id = payload.get("match_id")
        if match_id:
            by_match_id[match_id] = path
    return by_match_id


LOG_PATHS = _discover_logs()
SCORE_PATHS_BY_MATCH_ID = _discover_scores_by_match_id()


def _log_id(path: Path) -> str:
    return str(path.relative_to(PLAYTESTS_DIR))


def test_the_glob_finds_every_known_committed_log() -> None:
    """Guard against the sweep going vacuous.

    An empty or broken glob would make every parametrized test below collect
    zero cases and report as trivially "passing" — this assertion is the one
    thing in this module that cannot be fooled that way.
    """
    assert LOG_PATHS, "glob found no committed logs under docs/playtests/ — the sweep is vacuous"
    assert len(LOG_PATHS) >= _MIN_KNOWN_LOGS, (
        f"expected at least {_MIN_KNOWN_LOGS} committed playtest logs, found {len(LOG_PATHS)}: "
        f"{[_log_id(p) for p in LOG_PATHS]} — logs may have been removed without updating this "
        "floor, or the glob pattern is broken"
    )


@pytest.mark.parametrize("log_path", LOG_PATHS, ids=_log_id)
def test_committed_log_still_folds_cleanly(log_path: Path) -> None:
    """``from_jsonl`` parses and ``final_state()`` computes without error."""
    payload = log_path.read_text(encoding="utf-8")
    log = MatchLog.from_jsonl(payload)
    final = log.final_state()
    assert final.match_id
    assert final.status in ("active", "finished")


@pytest.mark.parametrize("log_path", LOG_PATHS, ids=_log_id)
def test_committed_log_outcome_matches_its_committed_score(log_path: Path) -> None:
    """Where a ``*.score.json`` pairs with this log, outcome totals still agree.

    Outcome scoring is version-free (``league/engine/scoring.py``), so this
    holds regardless of which cooperation-metric version produced the
    committed file.
    """
    log = MatchLog.from_jsonl(log_path.read_text(encoding="utf-8"))
    final = log.final_state()
    score_path = SCORE_PATHS_BY_MATCH_ID.get(final.match_id)
    if score_path is None:
        pytest.skip(f"no committed score.json pairs with match_id {final.match_id!r}")
    committed = json.loads(score_path.read_text(encoding="utf-8"))
    computed = score_match(log)
    assert computed["outcome"] == committed["outcome"], (
        f"outcome drift: {_log_id(log_path)} no longer scores to the outcome committed in "
        f"{score_path.relative_to(PLAYTESTS_DIR)}"
    )


def test_at_least_one_log_paired_with_a_committed_score() -> None:
    """Guard the pairing itself against going vacuous the same way as the glob."""
    paired = sum(
        1
        for log_path in LOG_PATHS
        if MatchLog.from_jsonl(log_path.read_text(encoding="utf-8")).final_state().match_id
        in SCORE_PATHS_BY_MATCH_ID
    )
    assert paired >= _MIN_KNOWN_LOGS, (
        f"expected at least {_MIN_KNOWN_LOGS} logs to pair with a committed score.json, got "
        f"{paired} — score files may have gone missing, or match_ids drifted"
    )


def test_the_full_sweep_runs_fast() -> None:
    """Fold + score every committed log and stay well inside the time budget."""
    start = time.perf_counter()
    for log_path in LOG_PATHS:
        log = MatchLog.from_jsonl(log_path.read_text(encoding="utf-8"))
        final = log.final_state()
        score_match(log)
        assert final is not None
    elapsed = time.perf_counter() - start
    assert elapsed < _BUDGET_SECONDS, (
        f"compatibility sweep took {elapsed:.2f}s over {len(LOG_PATHS)} logs, "
        f"budget is {_BUDGET_SECONDS}s"
    )
