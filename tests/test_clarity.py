"""league.clarity: replayed game moments, re-rendered prompts, mechanical checks."""

import json

from league import clarity

CASE = {
    "pos": [18, 13],
    "legal": {
        "move": [[18, 12], [17, 13], [18, 14], [19, 13], [16, 13]],
        "gather": False,
        "deliver": True,
        "hold": True,
        "can_steal": True,
        "steal": True,
    },
    "enemy_ids": ["blue-u1", "blue-u2"],
    "history": [{"turn": 3, "prompt": "P3", "reply": '{"action": {"action": "hold"}}'}],
    "prompt": "Turn 4 now",
}


def _reply(action: dict) -> str:
    return json.dumps({"action": action, "messages": ["m"]})


def test_check_reply_judges_each_verb() -> None:
    check = clarity.check_reply
    assert check(CASE, _reply({"action": "move", "to": [16, 13]})) == (True, "move")
    ok, why = check(CASE, _reply({"action": "move", "to": [16, 11]}))
    assert not ok and "distance 4" in why
    assert check(CASE, _reply({"action": "gather"}))[0] is False
    assert check(CASE, _reply({"action": "deliver"}))[0] is True
    assert check(CASE, _reply({"action": "steal", "target": "blue-u2"}))[0] is True
    assert "not an enemy" in check(CASE, _reply({"action": "steal", "target": "red-u2"}))[1]
    assert check(CASE, _reply({"action": "hold"})) == (True, "hold")
    assert check(CASE, "no json")[0] is False


def test_rerender_swaps_the_legal_line_and_drops_old_rejections() -> None:
    sent = (
        "Turn 4\n\nREJECTIONS from your last turn — x:\n- red-u1: old\n"
        "\nLegal actions right now:\n- red-u1: move to 24 cells, x in [15, 21], y in [10, 16]; "
        "gather: no\n\nCompact current state (JSON):\n{}"
    )
    out = clarity._rerender(sent, "\nLegal actions right now:\n- red-u1: NEW\n", "")
    assert "x in [" not in out and "- red-u1: NEW" in out
    assert "REJECTIONS" not in out and "Compact current state" in out


def test_message_carries_history_then_the_turn() -> None:
    text = clarity._message(CASE)
    assert text.index("turn 3: the harness said") < text.index("--- now ---\nTurn 4 now")


def test_report_counts_per_model_and_kind() -> None:
    rows = [
        {"model": "a", "kind": "rejected", "pass": True, "why": "move"},
        {"model": "a", "kind": "rejected", "pass": False, "why": "move to [1, 2] is out of range"},
    ]
    text = clarity.report(rows)
    assert "a         rejected    1/2" in text and "out of range" in text
