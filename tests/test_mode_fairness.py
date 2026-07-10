"""Mode/handicap fairness enforced at the CLI/engine boundary (issue #29).

The solo preset's "one action per turn" handicap used to be enforced ONLY in
``league/harness.py``'s command-driver wrapper (``actions[:1] if solo else
actions``) — a raw ``match act`` call, bypassing the harness entirely, could
stage a full-roster order set for a "solo" team with nothing to stop it.

Criteria under test:

* ``match new --max-actions <team>:<n>`` persists a per-team cap in the match
  log header (``max_actions``), surfaced by ``match show --json``;
* a raw ``match act`` staging more actions than the team's cap refuses with a
  structured ``CliError`` — never a silent truncation;
* the refusal is verifiable from the log: an ``orders_capped`` event is
  appended when an ``--apply``'d attempt actually trips it;
* a team with no declared cap, or a compliant submission, is unaffected;
* the harness's own solo truncation still works unchanged (it becomes
  redundant under the new enforcement, never conflicting with it).
"""

from __future__ import annotations

import json

import pytest

from league.cli import main
from league.store import Store

_ECHO_AGENT = "import sys, json; sys.stdin.read(); print(json.dumps({'actions': []}))"


@pytest.fixture()
def arena(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _register(team: str) -> list[str]:
    return [
        "team",
        "register",
        team,
        "--name",
        f"Team {team}",
        "--agent",
        f"{team}-1:m:scout",
        "--agent",
        f"{team}-2:m:harvester",
        "--agent",
        f"{team}-3:m:defender",
    ]


def _new_solo_match(match_id: str, *, max_actions: str | None = "solo:1") -> list[str]:
    argv = [
        "match",
        "new",
        "--scenario",
        "skirmish-1",
        "--team",
        "solo",
        "--team",
        "house",
        "--seed",
        "7",
        "--id",
        match_id,
    ]
    if max_actions is not None:
        argv += ["--max-actions", max_actions]
    return argv + ["--apply"]


def test_match_new_records_max_actions_in_the_header(arena, capsys) -> None:
    assert main(_register("solo") + ["--apply"]) == 0
    assert main(_register("house") + ["--apply"]) == 0
    capsys.readouterr()

    assert main(_new_solo_match("m-cap-header") + ["--json"]) == 0
    created = json.loads(capsys.readouterr().out)
    assert created["max_actions"] == {"solo": 1}

    log = Store().load_match("m-cap-header")
    assert log.max_actions == {"solo": 1}

    assert main(["match", "show", "m-cap-header", "--json"]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["max_actions"] == {"solo": 1}


def test_match_new_max_actions_is_optional(arena, capsys) -> None:
    assert main(_register("solo") + ["--apply"]) == 0
    assert main(_register("house") + ["--apply"]) == 0
    capsys.readouterr()

    assert main(_new_solo_match("m-cap-none", max_actions=None) + ["--json"]) == 0
    capsys.readouterr()
    assert main(["match", "show", "m-cap-none", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["max_actions"] == {}


def test_match_act_refuses_a_solo_team_staging_more_than_its_cap(arena, capsys) -> None:
    """The exact bug (issue #29): a raw `match act` call, bypassing the
    harness entirely, must not be able to smuggle a full-roster order set
    past a solo team's declared one-action cap."""
    assert main(_register("solo") + ["--apply"]) == 0
    assert main(_register("house") + ["--apply"]) == 0
    capsys.readouterr()
    assert main(_new_solo_match("m-cap-refuse")) == 0
    capsys.readouterr()

    rc = main(
        [
            "match",
            "act",
            "m-cap-refuse",
            "--team",
            "solo",
            "--action",
            "solo-u1:hold",
            "--action",
            "solo-u2:hold",
            "--action",
            "solo-u3:hold",
            "--apply",
        ]
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert err.startswith("error:")
    assert "hint:" in err
    assert "solo" in err

    # Refused: nothing staged, nothing resolved.
    assert Store().pending_orders("m-cap-refuse") == {}


def test_match_act_refusal_is_verifiable_from_the_log(arena, capsys) -> None:
    """The enforcement's other half: an --apply'd violation leaves a durable
    orders_capped event behind, even though the order set itself never
    reached staging or the tick."""
    assert main(_register("solo") + ["--apply"]) == 0
    assert main(_register("house") + ["--apply"]) == 0
    capsys.readouterr()
    assert main(_new_solo_match("m-cap-log")) == 0
    capsys.readouterr()

    rc = main(
        [
            "match",
            "act",
            "m-cap-log",
            "--team",
            "solo",
            "--action",
            "solo-u1:hold",
            "--action",
            "solo-u2:hold",
            "--apply",
        ]
    )
    assert rc == 1
    capsys.readouterr()

    log = Store().load_match("m-cap-log")
    capped = [e for e in log.events if e.kind == "orders_capped"]
    assert len(capped) == 1
    assert capped[0].data == {"team_id": "solo", "declared": 2, "allowed": 1}


def test_match_act_dry_run_still_refuses_without_writing_to_the_log(arena, capsys) -> None:
    """A dry-run (no --apply) must fail fast the same way, but leaves no
    trace on disk — the safe-by-default contract every write verb here
    follows."""
    assert main(_register("solo") + ["--apply"]) == 0
    assert main(_register("house") + ["--apply"]) == 0
    capsys.readouterr()
    assert main(_new_solo_match("m-cap-dry")) == 0
    capsys.readouterr()

    before = len(Store().load_match("m-cap-dry").events)
    rc = main(
        [
            "match",
            "act",
            "m-cap-dry",
            "--team",
            "solo",
            "--action",
            "solo-u1:hold",
            "--action",
            "solo-u2:hold",
            # no --apply
        ]
    )
    assert rc == 1
    capsys.readouterr()
    assert len(Store().load_match("m-cap-dry").events) == before


def test_match_act_accepts_a_compliant_submission_within_the_cap(arena, capsys) -> None:
    assert main(_register("solo") + ["--apply"]) == 0
    assert main(_register("house") + ["--apply"]) == 0
    capsys.readouterr()
    assert main(_new_solo_match("m-cap-ok")) == 0
    capsys.readouterr()

    rc = main(
        [
            "match",
            "act",
            "m-cap-ok",
            "--team",
            "solo",
            "--action",
            "solo-u1:hold",
            "--apply",
        ]
    )
    assert rc == 0
    log = Store().load_match("m-cap-ok")
    assert not [e for e in log.events if e.kind == "orders_capped"]


def test_match_act_leaves_an_uncapped_team_unaffected(arena, capsys) -> None:
    """'house' declared no cap in this match — a full-roster order set for it
    must succeed exactly as before."""
    assert main(_register("solo") + ["--apply"]) == 0
    assert main(_register("house") + ["--apply"]) == 0
    capsys.readouterr()
    assert main(_new_solo_match("m-cap-other-team")) == 0
    capsys.readouterr()

    rc = main(
        [
            "match",
            "act",
            "m-cap-other-team",
            "--team",
            "house",
            "--action",
            "house-u1:hold",
            "--action",
            "house-u2:hold",
            "--action",
            "house-u3:hold",
            "--apply",
        ]
    )
    assert rc == 0
    log = Store().load_match("m-cap-other-team")
    assert not [e for e in log.events if e.kind == "orders_capped"]


def _new_solo_match_with_cap(match_id: str, cap_spec: str) -> list[str]:
    return [
        "match",
        "new",
        "--scenario",
        "skirmish-1",
        "--team",
        "solo",
        "--seed",
        "7",
        "--id",
        match_id,
        "--mode",
        "cooperative",
        "--max-actions",
        cap_spec,
        "--apply",
    ]


def test_match_new_rejects_bad_max_actions_flags(arena, capsys) -> None:
    assert main(_register("solo") + ["--apply"]) == 0
    capsys.readouterr()

    # Unknown team.
    rc = main(_new_solo_match_with_cap("m-cap-bad-team", "ghost:1"))
    assert rc == 1
    assert "hint:" in capsys.readouterr().err

    # Non-positive cap.
    rc = main(_new_solo_match_with_cap("m-cap-bad-n", "solo:0"))
    assert rc == 1
    assert "hint:" in capsys.readouterr().err

    # Not an int.
    rc = main(_new_solo_match_with_cap("m-cap-bad-int", "solo:many"))
    assert rc == 1
    assert "hint:" in capsys.readouterr().err

    # Bad format (no ':').
    rc = main(_new_solo_match_with_cap("m-cap-bad-format", "solo-1"))
    assert rc == 1
    assert "hint:" in capsys.readouterr().err
