"""The loop: watch Guardians road games, judge deep fly balls, post the verdicts."""
from __future__ import annotations

import datetime as dt
import logging
import re
import time
import unicodedata
from pathlib import Path
from typing import Callable

from . import chart, compose
from .config import Settings
from .judge import judge, worth_posting
from .mlb import Game, MLBClient, read_plays
from .state import State
from .xclient import Poster

log = logging.getLogger(__name__)

SCHEDULE_REFRESH = dt.timedelta(minutes=5)
PREGAME_LEAD = dt.timedelta(minutes=10)
FINAL_GRACE = dt.timedelta(minutes=3)      # keep reading a finished game this long for late data
MAX_GAME_LENGTH = dt.timedelta(hours=8)
MAX_POST_ATTEMPTS = 3
SKIP_STATES = ("Postponed", "Cancelled")


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _minutes_since(iso: str, now: dt.datetime) -> float:
    try:
        then = dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    return (now - then).total_seconds() / 60


def _slug(name: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-") or "batter"


class Bot:
    def __init__(self, settings: Settings, mlb: MLBClient, poster: Poster, state: State,
                 now: Callable[[], dt.datetime] = _utcnow,
                 sleep: Callable[[float], None] = time.sleep):
        self.settings = settings
        self.mlb = mlb
        self.poster = poster
        self.state = state
        self._now = now
        self._sleep = sleep
        self._seen_this_run: set[int] = set()

    # ------------------------------------------------------------------ one game
    def process_feed(self, feed: dict, backfill_all: bool = False, now: dt.datetime | None = None) -> int:
        """Handle every new ball in play in a feed snapshot. Returns posts made."""
        s, now = self.settings, now or self._now()
        game_pk = feed["gamePk"]
        # The first time this process reads a game, plays older than the backfill
        # window are skipped, even if an earlier run already knew the game. That way
        # a lost or stale state file can never cause a burst of old posts.
        first_look = game_pk not in self._seen_this_run
        self._seen_this_run.add(game_pk)
        self.state.game(game_pk)
        made = 0

        for read in read_plays(feed):
            if self.state.handled(read.key):
                continue
            age = _minutes_since(read.end_time, now)
            if first_look and not backfill_all and age > s.backfill_minutes:
                self.state.mark(read.key, "before_startup")
                continue
            ball = read.ball
            if ball is None:  # Statcast numbers not in yet: retry next poll, within reason
                if backfill_all or age > s.give_up_minutes:
                    self.state.mark(read.key, "no_tracking_data")
                continue
            if s.batters == "guardians" and not ball.batter_is_guardian:
                self.state.mark(read.key, "other_team")
                continue
            verdict = judge(ball)
            if verdict is None:
                self.state.mark(read.key, "unjudgeable")
                continue
            if not worth_posting(ball, verdict, s.near_wall_ft):
                self.state.mark(read.key, "not_close")
                continue
            if self.state.posts_for(game_pk) >= s.max_posts_per_game:
                self.state.mark(read.key, "over_game_cap")
                continue

            text = compose.compose(ball, verdict, s.hashtag)
            try:
                image = chart.render(
                    ball, verdict,
                    Path(s.out_dir) / f"{game_pk}_{ball.at_bat_index:03d}_{_slug(ball.batter)}.png",
                    handle=s.handle,
                )
                post_id = self.poster.post(text, image, compose.alt_text(ball, verdict))
            except Exception:
                attempts = self.state.record_failure(read.key)
                log.exception("post failed for %s (attempt %d)", read.key, attempts)
                if attempts >= MAX_POST_ATTEMPTS:
                    self.state.mark(read.key, "post_failed")
                continue
            self.state.mark(read.key, "posted", post_id)
            made += 1
            log.info("posted %s: %s %s -> %s", read.key, ball.batter, ball.event,
                     "DONG" if verdict.is_dong else "no dong")

        self.state.save()
        return made

    # ------------------------------------------------------------------ scheduling
    def _wanted(self, game: Game) -> bool:
        return game.is_guardians_road_game and game.game_type in self.settings.game_types

    def _watching(self, game: Game, now: dt.datetime) -> bool:
        """Should we be reading this game's feed right now?"""
        if game.start - PREGAME_LEAD > now or now - game.start > MAX_GAME_LENGTH:
            return False
        if game.detailed_state in SKIP_STATES:
            return False
        record = self.state.games.get(str(game.game_pk))
        if game.state == "Final" and record is None:
            return False  # ended before we ever saw it
        final_seen = (record or {}).get("final_seen")
        if final_seen and now - dt.datetime.fromisoformat(final_seen) > FINAL_GRACE:
            return False
        return True

    @staticmethod
    def _starting_soon(game: Game, now: dt.datetime, lookahead: dt.timedelta) -> bool:
        return (now < game.start - PREGAME_LEAD <= now + lookahead
                and game.detailed_state not in SKIP_STATES)

    def _load_games(self, now: dt.datetime) -> list[Game]:
        today = (now - dt.timedelta(hours=5)).date()  # roughly US Eastern
        games = self.mlb.schedule(today - dt.timedelta(days=1), today + dt.timedelta(days=1))
        return [g for g in games if self._wanted(g)]

    def _poll(self, games: list[Game], now: dt.datetime) -> int:
        made = 0
        for game in games:
            try:
                feed = self.mlb.feed(game.game_pk)
                made += self.process_feed(feed, now=now)
                if feed["gameData"]["status"].get("abstractGameState") == "Final":
                    record = self.state.game(game.game_pk)
                    if "final_seen" not in record:
                        record["final_seen"] = now.isoformat()
                        self.state.save()
                        log.info("game %s is final; %d posts", game.game_pk, record.get("posts", 0))
            except Exception:
                log.exception("could not process game %s", game.game_pk)
        return made

    # ------------------------------------------------------------------ run modes
    def run_until_idle(self, max_runtime: dt.timedelta,
                       lookahead: dt.timedelta = dt.timedelta(minutes=45)) -> int:
        """For scheduled jobs (GitHub Actions).

        Watches every Guardians road game that is live or starts within
        `lookahead`, and returns once none are left or `max_runtime` is used up.
        Returns the number of posts made.
        """
        started = self._now()
        deadline = started + max_runtime
        games: list[Game] | None = None
        next_refresh = started
        made = 0
        while True:
            now = self._now()
            if now >= next_refresh:
                try:
                    games = self._load_games(now)
                    next_refresh = now + SCHEDULE_REFRESH
                except Exception:
                    if games is None:
                        raise  # can't even see the schedule: fail the job so it shows up red
                    log.exception("schedule refresh failed; using the last copy")
                    next_refresh = now + dt.timedelta(minutes=1)

            watching = [g for g in games if self._watching(g, now)]
            soon = [g for g in games if self._starting_soon(g, now, lookahead)]
            if not watching and not soon:
                log.info("no Guardians road game live or starting within %d min; done (%d posts)",
                         lookahead.total_seconds() // 60, made)
                return made
            if now >= deadline:
                log.info("hit the %d-minute limit; the next scheduled run takes over (%d posts)",
                         max_runtime.total_seconds() // 60, made)
                return made

            if watching:
                made += self._poll(watching, now)
                wait = float(self.settings.poll_seconds)
            else:
                first = min(g.start - PREGAME_LEAD for g in soon)
                log.info("next game %s; waiting until %s", soon[0].venue, first.isoformat())
                wait = (first - now).total_seconds()
            remaining = (deadline - now).total_seconds()
            self._sleep(max(1.0, min(wait, remaining, 600.0)))

    def run_forever(self) -> None:
        """For an always-on machine: watch games forever."""
        games: list[Game] = []
        next_refresh = self._now()
        log.info("watching for Guardians road games (dry_run=%s, near_wall_ft=%s, batters=%s)",
                 self.settings.dry_run, self.settings.near_wall_ft, self.settings.batters)
        while True:
            now = self._now()
            if now >= next_refresh:
                try:
                    games = self._load_games(now)
                    next_refresh = now + SCHEDULE_REFRESH
                except Exception:
                    log.exception("schedule lookup failed; retrying in a minute")
                    next_refresh = now + dt.timedelta(minutes=1)

            watching = [g for g in games if self._watching(g, now)]
            if watching:
                self._poll(watching, now)
                self._sleep(self.settings.poll_seconds)
                continue
            upcoming = [g.start - PREGAME_LEAD for g in games if g.start - PREGAME_LEAD > now]
            wait = min((min(upcoming) - now).total_seconds(), 1800) if upcoming else 1800
            self._sleep(max(30, wait))
