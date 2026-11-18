"""Settings, read from the environment (and a .env file if present)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def load_dotenv(path: str | Path = ".env") -> None:
    """Minimal .env reader: KEY=value lines, existing env vars win."""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    return default if raw is None else raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    # What to post
    near_wall_ft: float = 20.0        # how close to Progressive's wall counts as "close enough"
    batters: str = "all"              # "all" or "guardians"
    max_posts_per_game: int = 12
    hashtag: str = "#GuardsBall"
    handle: str = ""                  # watermark on the image, e.g. "@WouldItDongCLE"
    game_types: tuple[str, ...] = ("R", "F", "D", "L", "W")  # regular season + postseason

    # How it runs
    dry_run: bool = True
    poll_seconds: int = 15
    backfill_minutes: int = 10        # on startup mid-game, ignore plays older than this
    give_up_minutes: int = 10         # stop waiting for missing Statcast data after this
    state_file: str = "state.json"
    out_dir: str = "out"

    # X credentials (OAuth 1.0a user context)
    x_api_key: str = ""
    x_api_secret: str = ""
    x_access_token: str = ""
    x_access_secret: str = ""

    @property
    def has_x_credentials(self) -> bool:
        return all((self.x_api_key, self.x_api_secret, self.x_access_token, self.x_access_secret))

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        env = os.environ.get
        d = cls()
        return cls(
            near_wall_ft=float(env("NEAR_WALL_FT", d.near_wall_ft)),
            batters=env("BATTERS", d.batters).lower(),
            max_posts_per_game=int(env("MAX_POSTS_PER_GAME", d.max_posts_per_game)),
            hashtag=env("HASHTAG", d.hashtag),
            handle=env("HANDLE", d.handle),
            game_types=tuple(t.strip().upper() for t in env("GAME_TYPES", ",".join(d.game_types)).split(",") if t.strip()),
            dry_run=_bool("DRY_RUN", d.dry_run),
            poll_seconds=int(env("POLL_SECONDS", d.poll_seconds)),
            backfill_minutes=int(env("BACKFILL_MINUTES", d.backfill_minutes)),
            give_up_minutes=int(env("GIVE_UP_MINUTES", d.give_up_minutes)),
            state_file=env("STATE_FILE", d.state_file),
            out_dir=env("OUT_DIR", d.out_dir),
            x_api_key=env("X_API_KEY", ""),
            x_api_secret=env("X_API_SECRET", ""),
            x_access_token=env("X_ACCESS_TOKEN", ""),
            x_access_secret=env("X_ACCESS_SECRET", ""),
        )
