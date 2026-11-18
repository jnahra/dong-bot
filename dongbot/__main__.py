"""Command line: python -m dongbot {run,replay,check,schedule}"""
from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import json
import logging
import sys
from pathlib import Path

from . import chart, compose
from .bot import Bot
from .config import Settings
from .judge import BattedBall, judge
from .mlb import MLBClient
from .state import State
from .xclient import DryRunPoster, Poster, XPoster


def _poster(settings: Settings, live: bool) -> Poster:
    if not live:
        return DryRunPoster(settings.out_dir)
    if not settings.has_x_credentials:
        sys.exit("DRY_RUN is off but X credentials are missing. Fill in X_API_KEY, X_API_SECRET, "
                 "X_ACCESS_TOKEN and X_ACCESS_SECRET in .env (see README).")
    return XPoster(settings.x_api_key, settings.x_api_secret, settings.x_access_token, settings.x_access_secret)


def cmd_run(args: argparse.Namespace, settings: Settings) -> None:
    live = not settings.dry_run and not args.dry_run
    settings = dataclasses.replace(settings, dry_run=not live)
    Bot(settings, MLBClient(), _poster(settings, live), State(settings.state_file)).run_forever()


def cmd_watch(args: argparse.Namespace, settings: Settings) -> None:
    """For scheduled jobs: watch whatever is live or about to start, then exit."""
    live = not settings.dry_run
    bot = Bot(settings, MLBClient(), _poster(settings, live), State(settings.state_file))
    bot.run_until_idle(dt.timedelta(minutes=args.max_minutes),
                       lookahead=dt.timedelta(minutes=args.lookahead_minutes))


def cmd_replay(args: argparse.Namespace, settings: Settings) -> None:
    """Run a finished game through the bot. Dry run unless --post is given."""
    if args.feed_file:
        feed = json.loads(Path(args.feed_file).read_text())
    else:
        feed = MLBClient().feed(int(args.game))
    settings = dataclasses.replace(settings, dry_run=not args.post, max_posts_per_game=10_000)
    poster = _poster(settings, live=args.post)
    made = Bot(settings, MLBClient(), poster, State(None)).process_feed(feed, backfill_all=True)
    where = "posted to X" if args.post else f"written to {settings.out_dir}/"
    print(f"{made} posts {where}")


def cmd_check(args: argparse.Namespace, settings: Settings) -> None:
    """Judge one batted ball from raw numbers."""
    ball = BattedBall(0, 0, args.batter, args.pitcher, True, args.event,
                      "home_run" if args.event.lower() == "home run" else "field_out",
                      args.ev, args.la, args.dist, args.x, args.y, 1, True, "CLE", "OPP", 0, 0, "")
    verdict = judge(ball)
    if verdict is None:
        sys.exit("Can't judge that ball: the hit coordinates don't agree with the distance.")
    print(compose.compose(ball, verdict, settings.hashtag))
    if args.image:
        print("\nimage:", chart.render(ball, verdict, args.image, handle=settings.handle))


def cmd_schedule(args: argparse.Namespace, settings: Settings) -> None:
    today = dt.date.today()
    games = MLBClient().schedule(today, today + dt.timedelta(days=args.days))
    road = [g for g in games if g.is_guardians_road_game and g.game_type in settings.game_types]
    if not road:
        print(f"No Guardians road games in the next {args.days} days.")
    for g in road:
        print(f"{g.start:%a %b %d %H:%M} UTC  gamePk {g.game_pk}  at {g.venue}  [{g.detailed_state}]")


def main() -> None:
    parser = argparse.ArgumentParser(prog="dongbot", description="Would it dong at Progressive Field?")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="watch Guardians road games and post")
    run.add_argument("--dry-run", action="store_true", help="never post, whatever .env says")
    run.set_defaults(func=cmd_run)

    watch = sub.add_parser("watch", help="for scheduled jobs (GitHub Actions): watch any game that is "
                                         "live or about to start, then exit")
    watch.add_argument("--max-minutes", type=float, default=330,
                       help="exit after this long so the next scheduled run can take over (default 330)")
    watch.add_argument("--lookahead-minutes", type=float, default=45,
                       help="also wait for a game starting within this many minutes (default 45)")
    watch.set_defaults(func=cmd_watch)

    replay = sub.add_parser("replay", help="run a finished game through the bot")
    replay.add_argument("game", nargs="?", help="gamePk, e.g. 824055")
    replay.add_argument("--feed-file", help="read a saved feed JSON instead of calling MLB")
    replay.add_argument("--post", action="store_true", help="actually post to X")
    replay.set_defaults(func=cmd_replay)

    check = sub.add_parser("check", help="judge one batted ball from raw numbers")
    check.add_argument("--ev", type=float, required=True, help="exit velocity, mph")
    check.add_argument("--la", type=float, required=True, help="launch angle, degrees")
    check.add_argument("--dist", type=float, required=True, help="projected distance, ft")
    check.add_argument("--x", type=float, required=True, help="hitData coordX")
    check.add_argument("--y", type=float, required=True, help="hitData coordY")
    check.add_argument("--batter", default="Batter")
    check.add_argument("--pitcher", default="Pitcher")
    check.add_argument("--event", default="Flyout")
    check.add_argument("--image", help="also write the card to this PNG path")
    check.set_defaults(func=cmd_check)

    sched = sub.add_parser("schedule", help="list upcoming Guardians road games")
    sched.add_argument("--days", type=int, default=14)
    sched.set_defaults(func=cmd_schedule)

    args = parser.parse_args()
    if args.command == "replay" and not (args.game or args.feed_file):
        parser.error("replay needs a gamePk or --feed-file")
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    args.func(args, Settings.from_env())


if __name__ == "__main__":
    main()
