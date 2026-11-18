"""MLB Stats API: find Guardians road games and read batted balls off the live feed."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any, Iterator

import requests

from .judge import BattedBall

BASE = "https://statsapi.mlb.com/api"
GUARDIANS_ID = 114
PROGRESSIVE_FIELD_ID = 5

# Ask the feed for only what we read: ~70 KB per poll instead of ~800 KB.
FEED_FIELDS = ",".join([
    "gamePk", "gameData", "status", "abstractGameState", "detailedState",
    "teams", "away", "home", "id", "name", "abbreviation", "teamName", "venue",
    "liveData", "plays", "allPlays", "result", "type", "event", "eventType",
    "description", "awayScore", "homeScore", "about", "atBatIndex", "halfInning",
    "inning", "isTopInning", "isComplete", "endTime", "matchup", "batter",
    "pitcher", "fullName", "playEvents", "hitData", "launchSpeed", "launchAngle",
    "totalDistance", "trajectory", "coordinates", "coordX", "coordY", "playId",
])


@dataclass(frozen=True)
class Game:
    game_pk: int
    start: dt.datetime        # UTC
    state: str                # "Preview" | "Live" | "Final"
    detailed_state: str
    game_type: str            # R regular, F/D/L/W postseason, S spring
    away_id: int
    home_id: int
    venue_id: int
    venue: str

    @property
    def is_guardians_road_game(self) -> bool:
        """Any Guardians game not played at Progressive Field (covers neutral sites)."""
        return GUARDIANS_ID in (self.away_id, self.home_id) and self.venue_id != PROGRESSIVE_FIELD_ID


class MLBClient:
    def __init__(self, session: requests.Session | None = None, timeout: float = 15.0):
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", "would-it-dong-progressive/1.0")
        self.timeout = timeout

    def _get(self, path: str, **params: Any) -> dict:
        resp = self.session.get(f"{BASE}{path}", params=params, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def schedule(self, start: dt.date, end: dt.date) -> list[Game]:
        data = self._get("/v1/schedule", sportId=1, teamId=GUARDIANS_ID,
                         startDate=start.isoformat(), endDate=end.isoformat())
        games: dict[int, Game] = {}
        for day in data.get("dates", []):
            for g in day.get("games", []):
                game = Game(
                    game_pk=g["gamePk"],
                    start=dt.datetime.fromisoformat(g["gameDate"].replace("Z", "+00:00")),
                    state=g["status"]["abstractGameState"],
                    detailed_state=g["status"].get("detailedState", ""),
                    game_type=g.get("gameType", "R"),
                    away_id=g["teams"]["away"]["team"]["id"],
                    home_id=g["teams"]["home"]["team"]["id"],
                    venue_id=g.get("venue", {}).get("id", 0),
                    venue=g.get("venue", {}).get("name", ""),
                )
                # A postponed game is listed twice under one gamePk; keep the latest.
                games[game.game_pk] = game
        return sorted(games.values(), key=lambda g: g.start)

    def feed(self, game_pk: int) -> dict:
        return self._get(f"/v1.1/game/{game_pk}/feed/live", fields=FEED_FIELDS)


@dataclass(frozen=True)
class PlayRead:
    """One completed ball in play. `ball` is None while Statcast data is still missing."""

    key: str
    end_time: str
    ball: BattedBall | None


def read_plays(feed: dict) -> Iterator[PlayRead]:
    """Yield every completed play that put a ball in play."""
    game_pk = feed["gamePk"]
    teams = feed["gameData"]["teams"]
    venue = feed["gameData"].get("venue", {}).get("name", "")
    for play in feed["liveData"]["plays"]["allPlays"]:
        about, result = play.get("about", {}), play.get("result", {})
        if not about.get("isComplete") or result.get("type") != "atBat":
            continue
        hit = next((e["hitData"] for e in reversed(play.get("playEvents", [])) if e.get("hitData")), None)
        if hit is None:
            continue  # strikeout, walk, ... (or tracking that never arrives)
        key = f"{game_pk}:{about['atBatIndex']}"
        end_time = about.get("endTime", "")
        coords = hit.get("coordinates") or {}
        values = (hit.get("launchSpeed"), hit.get("launchAngle"), hit.get("totalDistance"),
                  coords.get("coordX"), coords.get("coordY"))
        if any(v is None for v in values):
            yield PlayRead(key, end_time, None)
            continue
        is_top = bool(about.get("isTopInning"))
        batting = teams["away"] if is_top else teams["home"]
        yield PlayRead(key, end_time, BattedBall(
            game_pk=game_pk,
            at_bat_index=about["atBatIndex"],
            batter=play["matchup"]["batter"]["fullName"],
            pitcher=play["matchup"]["pitcher"]["fullName"],
            batter_is_guardian=batting["id"] == GUARDIANS_ID,
            event=result.get("event", ""),
            event_type=result.get("eventType", ""),
            exit_velo=float(values[0]),
            launch_angle=float(values[1]),
            distance=float(values[2]),
            coord_x=float(values[3]),
            coord_y=float(values[4]),
            inning=int(about.get("inning", 0)),
            is_top=is_top,
            away_abbr=teams["away"].get("abbreviation", "AWAY"),
            home_abbr=teams["home"].get("abbreviation", "HOME"),
            away_score=int(result.get("awayScore", 0)),
            home_score=int(result.get("homeScore", 0)),
            venue=venue,
            end_time=end_time,
        ))
