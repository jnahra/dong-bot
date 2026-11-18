"""Tiny JSON-backed memory so a restart never double-posts."""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path

KEEP_DAYS = 10


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class State:
    def __init__(self, path: str | Path | None):
        self.path = Path(path) if path else None
        self.plays: dict[str, dict] = {}     # "gamePk:atBatIndex" -> {status, post_id, at}
        self.games: dict[str, dict] = {}     # gamePk -> {first_seen, posts, final_seen}
        self.failures: dict[str, int] = {}
        if self.path and self.path.exists():
            data = json.loads(self.path.read_text())
            self.plays = data.get("plays", {})
            self.games = data.get("games", {})
            self.failures = data.get("failures", {})

    # ----- games -----
    def knows_game(self, game_pk: int) -> bool:
        return str(game_pk) in self.games

    def game(self, game_pk: int) -> dict:
        return self.games.setdefault(str(game_pk), {"first_seen": _now().isoformat(), "posts": 0})

    def posts_for(self, game_pk: int) -> int:
        return self.games.get(str(game_pk), {}).get("posts", 0)

    # ----- plays -----
    def handled(self, key: str) -> bool:
        return key in self.plays

    def mark(self, key: str, status: str, post_id: str = "") -> None:
        self.plays[key] = {"status": status, "post_id": post_id, "at": _now().isoformat()}
        self.failures.pop(key, None)
        if status == "posted":
            game = self.game(int(key.split(":")[0]))
            game["posts"] = game.get("posts", 0) + 1

    def record_failure(self, key: str) -> int:
        self.failures[key] = self.failures.get(key, 0) + 1
        return self.failures[key]

    # ----- persistence -----
    def save(self) -> None:
        if not self.path:
            return
        cutoff = (_now() - dt.timedelta(days=KEEP_DAYS)).isoformat()
        old = {pk for pk, g in self.games.items() if g.get("first_seen", "") < cutoff}
        if old:
            self.games = {pk: g for pk, g in self.games.items() if pk not in old}
            self.plays = {k: v for k, v in self.plays.items() if k.split(":")[0] not in old}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps({"plays": self.plays, "games": self.games, "failures": self.failures}, indent=1))
        os.replace(tmp, self.path)
