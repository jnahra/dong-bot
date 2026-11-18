"""The pipeline: feed parsing, filtering, dedupe, post text, and the X client."""
import copy
import dataclasses
import datetime as dt
import json
from pathlib import Path

import pytest

from dongbot import compose
from dongbot.bot import Bot
from dongbot.config import Settings
from dongbot.judge import judge
from dongbot.mlb import MLBClient, read_plays
from dongbot.state import State
from dongbot.xclient import DryRunPoster, XError, XPoster

FEED = Path(__file__).parent / "data" / "feed_824055_cle_at_kc.json"
LONG_AFTER = dt.datetime(2026, 9, 28, tzinfo=dt.timezone.utc)


@pytest.fixture
def feed():
    return json.loads(FEED.read_text())


def make_bot(tmp_path, **overrides):
    settings = dataclasses.replace(Settings(), out_dir=str(tmp_path / "out"), **overrides)
    poster = DryRunPoster(settings.out_dir)
    return Bot(settings, MLBClient(), poster, State(tmp_path / "state.json")), poster


def test_reads_real_feed(feed):
    reads = list(read_plays(feed))
    assert len(reads) == 12 and all(r.ball for r in reads)
    homer = next(r.ball for r in reads if r.key == "824055:18")
    assert (homer.batter, homer.event_type, homer.exit_velo, homer.distance) == \
        ("Daniel Schneemann", "home_run", 103.2, 380.0)
    assert homer.batter_is_guardian and homer.is_top and homer.venue == "Kauffman Stadium"
    assert (homer.away_abbr, homer.away_score, homer.home_abbr, homer.home_score) == ("CLE", 1, "KC", 1)
    royal = next(r.ball for r in reads if r.key == "824055:24")
    assert not royal.batter_is_guardian and not royal.is_top


def test_replay_posts_the_deep_ones_once(feed, tmp_path):
    bot, poster = make_bot(tmp_path)
    assert bot.process_feed(feed, backfill_all=True) == 9
    assert bot.process_feed(feed, backfill_all=True) == 0          # nothing twice
    assert len(list((tmp_path / "out").glob("*.png"))) == 9

    by_batter = {p.split(" vs ")[0] + str(i): p for i, p in enumerate(poster.posts)}
    schneemann_hr = poster.posts[0]
    assert "Daniel Schneemann vs Daniel Lynch IV" in schneemann_hr
    assert "✅ DONG at Progressive Field" in schneemann_hr and "CLE (1) @ KC (1)" in schneemann_hr
    perez = poster.posts[1]
    assert "❌ Not a dong" in perez and "🔻 3rd" in perez
    assert all(compose.weighted_length(p) <= 280 for p in by_batter.values())

    # a fresh process with the same state file still remembers
    again = Bot(bot.settings, MLBClient(), DryRunPoster(tmp_path / "out"), State(tmp_path / "state.json"))
    assert again.process_feed(feed, backfill_all=True) == 0


def test_startup_mid_game_does_not_flood(feed, tmp_path):
    bot, poster = make_bot(tmp_path)
    assert bot.process_feed(feed, now=LONG_AFTER) == 0
    assert poster.posts == []


def test_only_recent_plays_post_on_first_look(feed, tmp_path):
    bot, poster = make_bot(tmp_path)
    just_after_last = dt.datetime(2026, 9, 27, 21, 8, tzinfo=dt.timezone.utc)
    # Pasquantino HR (21:06:16) and Collins flyout (21:06:59) are inside the 10-minute window;
    # Lowe's flyout (21:01:55) is too.
    assert bot.process_feed(feed, now=just_after_last) == 3


def test_waits_for_late_statcast_data(feed, tmp_path):
    bot, _ = make_bot(tmp_path)
    late = copy.deepcopy(feed)
    late["liveData"]["plays"]["allPlays"] = [p for p in late["liveData"]["plays"]["allPlays"]
                                             if p["atBatIndex"] == 18]
    full_hit = late["liveData"]["plays"]["allPlays"][0]["playEvents"][0]["hitData"]
    distance = full_hit.pop("totalDistance")
    soon = dt.datetime(2026, 9, 27, 19, 42, 30, tzinfo=dt.timezone.utc)

    assert bot.process_feed(late, backfill_all=False, now=soon) == 0
    assert not bot.state.handled("824055:18")                       # still pending
    full_hit["totalDistance"] = distance
    assert bot.process_feed(late, now=soon + dt.timedelta(seconds=15)) == 1


def test_gives_up_on_data_that_never_arrives(feed, tmp_path):
    bot, _ = make_bot(tmp_path)
    broken = copy.deepcopy(feed)
    broken["liveData"]["plays"]["allPlays"] = [p for p in broken["liveData"]["plays"]["allPlays"]
                                               if p["atBatIndex"] == 18]
    del broken["liveData"]["plays"]["allPlays"][0]["playEvents"][0]["hitData"]["totalDistance"]
    soon = dt.datetime(2026, 9, 27, 19, 42, 30, tzinfo=dt.timezone.utc)
    bot.process_feed(broken, now=soon)
    bot.process_feed(broken, now=soon + dt.timedelta(minutes=11))
    assert bot.state.plays["824055:18"]["status"] == "no_tracking_data"


def test_guardians_only_and_game_cap(feed, tmp_path):
    bot, poster = make_bot(tmp_path, batters="guardians")
    assert bot.process_feed(feed, backfill_all=True) == 4
    assert all("Lynch" in p or "Thomas" in p or "Pearson" in p for p in poster.posts)

    capped, _ = make_bot(tmp_path / "capped", max_posts_per_game=2)
    assert capped.process_feed(feed, backfill_all=True) == 2


def test_failed_posts_retry_then_stop(feed, tmp_path):
    class Flaky:
        calls = 0

        def post(self, text, image, alt_text=""):
            Flaky.calls += 1
            raise XError("boom")

    settings = dataclasses.replace(Settings(), out_dir=str(tmp_path / "out"))
    bot = Bot(settings, MLBClient(), Flaky(), State(None))
    one_play = copy.deepcopy(feed)
    one_play["liveData"]["plays"]["allPlays"] = [p for p in feed["liveData"]["plays"]["allPlays"]
                                                 if p["atBatIndex"] == 18]
    for _ in range(5):
        bot.process_feed(one_play, backfill_all=True)
    assert Flaky.calls == 3
    assert bot.state.plays["824055:18"]["status"] == "post_failed"


def test_long_names_still_fit(feed):
    ball = next(r.ball for r in read_plays(feed) if r.key == "824055:58")
    ball = dataclasses.replace(ball, batter="Christopher Featherstonehaugh-Montgomery III",
                               pitcher="Maximilian Wolfeschlegelsteinhausen Jr.")
    text = compose.compose(ball, judge(ball), "#GuardsBall")
    assert compose.weighted_length(text) <= 280
    assert "Featherstonehaugh" in text


def test_ordinals():
    assert [compose.ordinal(n) for n in (1, 2, 3, 4, 11, 12, 13, 21)] == \
        ["1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "21st"]


class FakeResponse:
    def __init__(self, status, payload):
        self.status_code, self._payload, self.text = status, payload, json.dumps(payload)

    def json(self):
        return self._payload

    def raise_for_status(self):
        assert self.status_code < 300


class FakeXSession:
    def __init__(self, fail_alt=False):
        self.calls, self.fail_alt = [], fail_alt

    def post(self, url, **kw):
        self.calls.append((url, kw))
        if url.endswith("/media/upload"):
            assert kw["data"] == {"media_category": "tweet_image"} and "media" in kw["files"]
            return FakeResponse(200, {"data": {"id": "111"}})
        if url.endswith("/media/metadata"):
            return FakeResponse(400 if self.fail_alt else 200, {"data": {"id": "111"}})
        return FakeResponse(201, {"data": {"id": "999", "text": kw["json"]["text"]}})


@pytest.mark.parametrize("fail_alt", [False, True])
def test_x_poster_uploads_then_posts(tmp_path, fail_alt):
    image = tmp_path / "card.png"
    image.write_bytes(b"\x89PNG fake")
    session = FakeXSession(fail_alt)
    post_id = XPoster("k", "s", "t", "ts", session=session).post("hello", image, "alt words")
    assert post_id == "999"
    assert [url.rsplit("/2/", 1)[1] for url, _ in session.calls] == ["media/upload", "media/metadata", "tweets"]
    assert session.calls[1][1]["json"] == {"id": "111", "metadata": {"alt_text": {"text": "alt words"}}}
    assert session.calls[2][1]["json"] == {"text": "hello", "media": {"media_ids": ["111"]}}


def test_x_poster_surfaces_errors(tmp_path):
    class Rejecting(FakeXSession):
        def post(self, url, **kw):
            return FakeResponse(403, {"detail": "no credits"})

    with pytest.raises(XError, match="403"):
        XPoster("k", "s", "t", "ts", session=Rejecting()).post("hello", None)


def test_schedule_finds_road_games():
    def game(pk, away, home, venue, state="Preview", detailed="Scheduled"):
        return {"gamePk": pk, "gameDate": "2027-04-02T23:10:00Z", "gameType": "R",
                "status": {"abstractGameState": state, "detailedState": detailed},
                "teams": {"away": {"team": {"id": away}}, "home": {"team": {"id": home}}},
                "venue": {"id": venue, "name": f"Venue {venue}"}}

    payload = {"dates": [
        {"games": [game(1, 114, 118, 7), game(2, 145, 114, 5)]},
        {"games": [game(3, 139, 114, 2523),                       # "home" game at a neutral site
                   game(1, 114, 118, 7, "Final", "Final")]},      # same gamePk listed twice
    ]}

    class Session:
        headers: dict = {}

        def get(self, url, params=None, timeout=None):
            assert params["teamId"] == 114
            return FakeResponse(200, payload)

    games = MLBClient(session=Session()).schedule(dt.date(2027, 4, 2), dt.date(2027, 4, 3))
    assert [g.game_pk for g in games] == [1, 2, 3]
    assert [g.is_guardians_road_game for g in games] == [True, False, True]
    assert games[0].state == "Final"


def test_ignores_plays_without_a_ball_in_play(feed):
    plays = feed["liveData"]["plays"]["allPlays"]
    strikeout = copy.deepcopy(plays[0])
    strikeout["playEvents"] = [{"playId": "x", "type": "pitch"}]
    strikeout["about"]["atBatIndex"] = 70
    in_progress = copy.deepcopy(plays[3])
    in_progress["about"].update(atBatIndex=71, isComplete=False)
    plays += [strikeout, in_progress]
    assert {r.key for r in read_plays(feed)}.isdisjoint({"824055:70", "824055:71"})


def test_knows_when_to_watch_a_game(tmp_path):
    from dongbot.mlb import Game

    bot, _ = make_bot(tmp_path)
    start = dt.datetime(2027, 3, 25, 18, 20, tzinfo=dt.timezone.utc)
    game = Game(900, start, "Preview", "Scheduled", "R", 114, 112, 17, "Wrigley Field")
    minutes = lambda m: start + dt.timedelta(minutes=m)  # noqa: E731

    assert not bot._watching(game, minutes(-30))
    assert bot._watching(game, minutes(-5))
    assert bot._watching(game, minutes(150))
    assert not bot._watching(game, minutes(9 * 60))
    assert not bot._watching(dataclasses.replace(game, detailed_state="Postponed"), minutes(5))

    bot.state.game(900)["final_seen"] = minutes(170).isoformat()
    assert bot._watching(game, minutes(172))          # grace period for late data
    assert not bot._watching(game, minutes(175))

    home = dataclasses.replace(game, away_id=112, home_id=114, venue_id=5)
    spring = dataclasses.replace(game, game_type="S")
    assert bot._wanted(game) and not bot._wanted(home) and not bot._wanted(spring)


# ---------------------------------------------------------------- watch mode (GitHub Actions)

class FakeClock:
    def __init__(self, start):
        self.t = start
        self.sleeps = []

    def now(self):
        return self.t

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.t += dt.timedelta(seconds=seconds)


class FakeMLB:
    """Serves one game: the fixture's plays, Final once `final_at` passes."""

    def __init__(self, feed, game, clock, final_at):
        self._feed, self.game, self.clock, self.final_at = feed, game, clock, final_at
        self.feed_calls = 0

    def schedule(self, start, end):
        return [self.game] if self.game else []

    def feed(self, game_pk):
        self.feed_calls += 1
        snapshot = copy.deepcopy(self._feed)
        final = self.clock.now() >= self.final_at
        snapshot["gameData"]["status"]["abstractGameState"] = "Final" if final else "Live"
        return snapshot


def road_game(start, **kw):
    from dongbot.mlb import Game

    fields = dict(game_pk=824055, start=start, state="Live", detailed_state="In Progress",
                  game_type="R", away_id=114, home_id=118, venue_id=7, venue="Kauffman Stadium")
    fields.update(kw)
    return Game(**fields)


FIRST_PITCH = dt.datetime(2026, 9, 27, 19, 10, tzinfo=dt.timezone.utc)
LAST_OUT = dt.datetime(2026, 9, 27, 21, 18, tzinfo=dt.timezone.utc)


def watch_bot(tmp_path, feed, start_at, game=..., **settings):
    clock = FakeClock(start_at)
    game = road_game(FIRST_PITCH) if game is ... else game
    mlb = FakeMLB(feed, game, clock, LAST_OUT)
    s = dataclasses.replace(Settings(), out_dir=str(tmp_path / "out"), **settings)
    poster = DryRunPoster(s.out_dir)
    bot = Bot(s, mlb, poster, State(tmp_path / "state.json"), now=clock.now, sleep=clock.sleep)
    return bot, clock, mlb, poster


def test_watch_exits_at_once_with_no_game(feed, tmp_path):
    bot, clock, mlb, _ = watch_bot(tmp_path, feed, FIRST_PITCH, game=None)
    assert bot.run_until_idle(dt.timedelta(minutes=330)) == 0
    assert mlb.feed_calls == 0 and clock.sleeps == []


def test_watch_ignores_a_game_hours_away(feed, tmp_path):
    bot, clock, mlb, _ = watch_bot(tmp_path, feed, FIRST_PITCH - dt.timedelta(hours=3))
    bot.run_until_idle(dt.timedelta(minutes=330))
    assert mlb.feed_calls == 0 and clock.sleeps == []


def test_watch_covers_a_whole_game_then_exits(feed, tmp_path):
    bot, clock, mlb, poster = watch_bot(tmp_path, feed, FIRST_PITCH - dt.timedelta(minutes=35))
    made = bot.run_until_idle(dt.timedelta(minutes=330))
    assert made == 9 and len(poster.posts) == 9
    # waited for pregame, then polled every 15 s until 3 minutes after the final out
    assert clock.sleeps[:3] == [600, 600, 300] and set(clock.sleeps[3:]) == {15.0}
    assert LAST_OUT + dt.timedelta(minutes=3) <= clock.t <= LAST_OUT + dt.timedelta(minutes=4)
    assert State(tmp_path / "state.json").games["824055"]["final_seen"]


def test_watch_hands_off_at_the_time_limit_without_reposting(feed, tmp_path):
    bot, clock, _, poster = watch_bot(tmp_path, feed, FIRST_PITCH - dt.timedelta(minutes=5))
    bot.run_until_idle(dt.timedelta(minutes=60))
    assert clock.t <= FIRST_PITCH + dt.timedelta(minutes=56)
    assert len(poster.posts) == 9          # the fixture feed shows every play at once

    # next scheduled run: new process, same committed state file
    nxt, _, _, poster2 = watch_bot(tmp_path, feed, clock.t + dt.timedelta(minutes=10))
    nxt.run_until_idle(dt.timedelta(minutes=330))
    assert poster2.posts == []


def test_watch_skips_a_game_that_ended_before_it_started(feed, tmp_path):
    over = road_game(FIRST_PITCH, state="Final", detailed_state="Final")
    bot, _, mlb, poster = watch_bot(tmp_path, feed, LAST_OUT + dt.timedelta(minutes=40), game=over)
    bot.run_until_idle(dt.timedelta(minutes=330))
    assert mlb.feed_calls == 0 and poster.posts == []


def test_lost_state_never_floods_old_plays(feed, tmp_path):
    # The state file knows the game but none of its plays (e.g. a commit was lost).
    state = State(tmp_path / "state.json")
    state.game(824055)
    state.save()
    bot, _, _, poster = watch_bot(tmp_path, feed, LAST_OUT - dt.timedelta(minutes=1))
    bot.run_until_idle(dt.timedelta(minutes=330))
    assert len(poster.posts) == 0          # every play is older than the backfill window


def test_watch_fails_loudly_if_schedule_unreachable(feed, tmp_path):
    bot, _, mlb, _ = watch_bot(tmp_path, feed, FIRST_PITCH)

    def boom(*a):
        raise ConnectionError("MLB down")

    mlb.schedule = boom
    with pytest.raises(ConnectionError):
        bot.run_until_idle(dt.timedelta(minutes=330))
