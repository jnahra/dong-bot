# Would it dong at Progressive Field?

A bot for Guardians road games. Whenever a ball is hit close enough to where
Progressive Field's wall would be, it works out whether that ball would have
been a home run in Cleveland and posts the answer to X with a spray chart.

```
Daniel Schneemann vs Connor Thomas
#GuardsBall

Flyout

Exit velo: 99.2 mph
Launch angle: 26 deg
Proj. distance: 372 ft

❌ Not a dong at Progressive Field. Lands 1 ft short of the 19-ft wall in left-center.

CLE (2) @ KC (2)
🔺 7th
```

## Quick start

Needs Python 3.10+.

```bash
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt && cp .env.example .env
```

Try it on a finished game before going live. This replays Guardians at Royals,
Sept 27 2026, and writes every would-be post (text + image) to `out/`:

```bash
python -m dongbot replay 824055
```

Other commands:

```bash
python -m dongbot schedule                 # upcoming Guardians road games
python -m dongbot run                      # watch games forever; dry run until DRY_RUN=false
python -m dongbot watch                    # watch what's live or about to start, then exit
python -m dongbot check --ev 104.9 --la 29 --dist 404 --x 143.5 --y 37.4 --image card.png
python -m pytest                           # tests
```

## Going live on X

1. Create (or log into) the bot's X account, then sign up at the X developer
   console **as that account** and create an app with **Read and write** permission.
2. Generate the four OAuth 1.0a values (API key, API secret, access token,
   access token secret) and put them in `.env`.
3. X's API is pay-per-use: buy credits in the console. Each post here is one
   image upload plus one post with no link.
4. Set `DRY_RUN=false` in `.env` and start it:

```bash
python -m dongbot run
```

The bot has to be running during games. The easiest way is GitHub Actions
(free, nothing to keep switched on), below. Or use any always-on machine:

```bash
docker build -t dongbot . && docker run -d --restart unless-stopped --env-file .env -v "$PWD/data:/data" dongbot
```

Mark the account as automated in X's account settings; X's automation rules
expect that for bots.

## Running it on GitHub Actions (free)

`.github/workflows/dongbot.yml` covers the whole season by itself. Every 30
minutes from March through November it asks MLB's schedule whether a Guardians
road game is live or starts within 45 minutes. If not, it exits in under a
minute. If so, it watches the game until it's over (`python -m dongbot watch`),
then commits what it posted to `bot-state/` so the next run never reposts.

Setup, once:

1. Create a **public** GitHub repo (public repos get unlimited free Actions
   minutes; a private repo's free allowance won't cover a season) and push this
   folder to it:
   ```bash
   cd would-it-dong && git init -b main && git add . && git commit -m "Would it dong at Progressive Field" && git remote add origin https://github.com/YOU/would-it-dong.git && git push -u origin main
   ```
2. In the repo: **Settings → Secrets and variables → Actions**.
   - **Secrets** tab: add `X_API_KEY`, `X_API_SECRET`, `X_ACCESS_TOKEN`,
     `X_ACCESS_SECRET`. Secrets stay hidden even though the repo is public.
   - **Variables** tab (all optional): `HANDLE`, `NEAR_WALL_FT`, `BATTERS`,
     `HASHTAG`, `MAX_POSTS_PER_GAME`, `GAME_TYPES`. Same meanings as the table
     below.
3. Test it now: **Actions → Would it dong → Run workflow**, enter `824055` as the
   game. It replays that finished game without posting; the cards appear under
   the run's **Artifacts**.
4. To go live, add a variable `DRY_RUN` = `false`. Until then every game runs
   as a dry run, and each run's cards are kept for 14 days under Artifacts.
   Watching a few dry-run games first is a good idea.

Things to know:

- A run lasts at most 5.5 hours. If a long game or rain delay goes past that,
  the next scheduled run picks up where it stopped.
- GitHub sometimes starts scheduled runs 5 to 15 minutes late. Runs start
  30 to 45 minutes before first pitch, so that only matters if one fails. A run
  that starts mid-game posts plays from the last 20 minutes and skips older ones.
- GitHub pauses scheduled workflows in a repo with no commits for 60 days. The
  workflow makes a one-line commit to `bot-state/keepalive.txt` on the 1st of
  every month so that never happens over the winter. If it ever does pause,
  click **Enable workflow** on the Actions tab.
- The schedule only runs March through November. To dry-run spring training
  games in February, change `3-11` to `2-11` in the workflow's first `cron`
  line and set the `GAME_TYPES` variable to `S,R,F,D,L,W`.
- Pull before pushing your own changes; the bot commits `bot-state/` after
  each game.

## Settings (`.env`, or repo variables on GitHub Actions)

| Setting | Default | What it does |
|---|---|---|
| `DRY_RUN` | `true` | Write posts to `out/` instead of sending them |
| `NEAR_WALL_FT` | `20` | "Close enough": post any ball hit to within this many feet of Progressive's wall. Real home runs and would-be dongs always post |
| `BATTERS` | `all` | `all` for both teams, `guardians` for Cleveland hitters only |
| `MAX_POSTS_PER_GAME` | `12` | Safety cap |
| `HASHTAG` | `#GuardsBall` | Leave empty for none |
| `HANDLE` | empty | Watermark on the image, e.g. `@YourBot` |
| `GAME_TYPES` | `R,F,D,L,W` | Regular season and postseason. Add `S` for spring training |
| `POLL_SECONDS` | `15` | Live feed polling interval |
| `BACKFILL_MINUTES` | `10` (`20` on Actions) | When started mid-game, ignore plays older than this |
| `GIVE_UP_MINUTES` | `10` | How long to wait for late Statcast numbers on a play |

How often it posts, measured on the 2026 season: about 4.6 posts per game at
the default 20 ft with both teams (3.3 at 5 ft, 5.5 at 30 ft), roughly half
that with `BATTERS=guardians`.

A "road game" is any Guardians game not played at Progressive Field, so
neutral-site games count too.

## How the verdict works

1. **Where it was hit.** The live feed's hit coordinates give the spray angle.
2. **Where the wall is.** Progressive Field's fence distance at every angle
   comes from the park outline in
   [GeomMLBStadiums](https://github.com/bdilday/GeomMLBStadiums) (MIT), scaled
   to the posted dimensions (325 / 370 / 410 / 405 / 375 / 325). Wall heights:
   19 ft from the left-field pole to the deep corner just left of center, 9 ft
   from center to right, 14 ft in the right-field corner.
3. **How high it was when it got there.** Exit velocity, launch angle and
   Statcast's projected distance pin down the flight. `physics.py` fits a
   drag-and-lift trajectory that leaves the bat at that speed and angle and
   lands at exactly that distance, then reads off the ball's height at the wall.
4. **Dong** if that height clears the wall. Within 2 ft of the top either way
   it is posted as "too close to call".

### How good is it?

`tests/data/progressive_2026_batted_balls.txt` holds all 697 deep fly balls
(320+ ft) actually hit at Progressive Field in 2026, with what really happened.
The model agrees with reality on 97.8% of them: of 166 real home runs it calls
158 dongs, and it calls 8 dongs on balls that stayed in. Almost all the
disagreement is in the "too close to call" band (14 of 22 right there; 98.9%
outside it).

One number was tuned on that same data (`FENCE_CALIBRATION = 0.99` in
`judge.py`), so treat the 97.8% as in-sample.

### What it doesn't know

- **Weather and altitude.** The fitted flight carries the road park's air with
  it. A ball hit at Coors is judged as if Cleveland had Denver's air that day.
- **Fielders.** A dong is a ball that clears the wall, robbed or not.
- **Odd wall details** beyond the three heights above (railings, the bullpen
  fence line, the exact end of the 14-ft corner section).
- **Bad tracking.** A few balls a season have hit coordinates that contradict
  their distance; those are skipped rather than guessed.

## Layout

```
dongbot/
  park.py      Progressive Field fence distances, wall heights, spray angle
  physics.py   trajectory fit
  judge.py     verdict + "is it worth posting" rule
  mlb.py       MLB Stats API: schedule and live feed
  compose.py   post text and alt text
  chart.py     the image
  xclient.py   X API v2 posting (and the dry-run stand-in)
  bot.py       the loop
  state.py     dedupe memory
tools/build_park_data.py   regenerates dongbot/data/progressive_field.json
tests/                     33 tests, including the 697-ball accuracy check
.github/workflows/         dongbot.yml (the season schedule), tests.yml
```

## Status

Tested by replaying finished 2026 games through the full pipeline, and by
running watch mode through a whole simulated game on a fake clock. Not yet
exercised: posting to the real X API, a live game in progress, and the workflow
running on GitHub itself (it passes `actionlint`). Steps 3 and 4 of the
GitHub Actions setup cover all three before anything gets posted.
