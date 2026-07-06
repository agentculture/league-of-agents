"""On-disk arena state — teams and match logs under ``.league/`` in the CWD.

The store is deliberately dumb: JSON files for teams, the JSONL match log as
the only match artifact (spec: the log is the single source of truth), plus a
``pending/`` staging area for declared-but-unresolved orders. No third-party
dependencies, no timestamps, no randomness — ids and content come from the
caller, so everything stays reproducible.

Layout::

    .league/
      teams/<team-id>.json
      matches/<match-id>/log.jsonl
      matches/<match-id>/pending/<team-id>.json
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from league.engine.events import Event, MatchLog
from league.engine.state import AgentSlot


def _canon(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class Store:
    """File-backed arena store rooted at ``<root>/.league``."""

    def __init__(self, root: Path | None = None) -> None:
        base = root if root is not None else Path.cwd()
        self.root = base / ".league"

    # -- teams ------------------------------------------------------------

    @property
    def _teams_dir(self) -> Path:
        return self.root / "teams"

    def team_path(self, team_id: str) -> Path:
        return self._teams_dir / f"{team_id}.json"

    def save_team(self, team_id: str, name: str, agents: tuple[AgentSlot, ...]) -> Path:
        path = self.team_path(team_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"id": team_id, "name": name, "agents": [a.to_dict() for a in agents]}
        path.write_text(_canon(payload) + "\n", encoding="utf-8")
        return path

    def load_team(self, team_id: str) -> dict[str, Any]:
        path = self.team_path(team_id)
        if not path.is_file():
            raise FileNotFoundError(f"no registered team {team_id!r}")
        return json.loads(path.read_text(encoding="utf-8"))

    def team_slots(self, team_id: str) -> tuple[str, str, tuple[AgentSlot, ...]]:
        data = self.load_team(team_id)
        agents = tuple(AgentSlot.from_dict(a) for a in data["agents"])
        return data["id"], data["name"], agents

    def list_teams(self) -> list[dict[str, Any]]:
        if not self._teams_dir.is_dir():
            return []
        return [
            json.loads(p.read_text(encoding="utf-8"))
            for p in sorted(self._teams_dir.glob("*.json"))
        ]

    # -- matches ----------------------------------------------------------

    @property
    def _matches_dir(self) -> Path:
        return self.root / "matches"

    def match_dir(self, match_id: str) -> Path:
        return self._matches_dir / match_id

    def log_path(self, match_id: str) -> Path:
        return self.match_dir(match_id) / "log.jsonl"

    def list_matches(self) -> list[str]:
        if not self._matches_dir.is_dir():
            return []
        return sorted(p.parent.name for p in self._matches_dir.glob("*/log.jsonl"))

    def create_match(self, log: MatchLog) -> Path:
        path = self.log_path(log.initial_state.match_id)
        if path.exists():
            raise FileExistsError(f"match {log.initial_state.match_id!r} already exists")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(log.to_jsonl(), encoding="utf-8")
        return path

    def load_match(self, match_id: str) -> MatchLog:
        path = self.log_path(match_id)
        if not path.is_file():
            raise FileNotFoundError(f"no match {match_id!r}")
        return MatchLog.from_jsonl(path.read_text(encoding="utf-8"))

    def append_events(self, match_id: str, events: tuple[Event, ...]) -> None:
        path = self.log_path(match_id)
        if not path.is_file():
            raise FileNotFoundError(f"no match {match_id!r}")
        with path.open("a", encoding="utf-8") as fh:
            for event in events:
                fh.write(_canon(event.to_dict()) + "\n")

    # -- pending orders (staged by `match act`, consumed by resolution) ----

    def _pending_dir(self, match_id: str) -> Path:
        return self.match_dir(match_id) / "pending"

    def stage_orders(self, match_id: str, team_id: str, orders: dict[str, Any]) -> Path:
        path = self._pending_dir(match_id) / f"{team_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_canon(orders) + "\n", encoding="utf-8")
        return path

    def pending_orders(self, match_id: str) -> dict[str, dict[str, Any]]:
        pending = self._pending_dir(match_id)
        if not pending.is_dir():
            return {}
        return {
            p.stem: json.loads(p.read_text(encoding="utf-8"))
            for p in sorted(pending.glob("*.json"))
        }

    def clear_pending(self, match_id: str) -> None:
        pending = self._pending_dir(match_id)
        if pending.is_dir():
            for p in pending.glob("*.json"):
                p.unlink()
