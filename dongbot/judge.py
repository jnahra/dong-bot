"""Would it dong? Combine a batted ball, the flight model and the park."""
from __future__ import annotations

from dataclasses import dataclass

from . import park
from .physics import Flight, solve_flight

# Empirical calibration. With the fence at its posted distance the model called
# too many real Progressive Field homers "just short"; treating the wall as 1%
# closer balances the misses in both directions (see tests/test_accuracy.py).
FENCE_CALIBRATION = 0.99

# Within this many feet of the top of the wall the model is a coin flip
# (64% right on 2026 data, vs 92%+ beyond it), so we say so.
TOO_CLOSE_FT = 2.0

# Hit coordinates that disagree with Statcast's distance by more than this are
# junk (it happens a few times a season) and can't give a trustworthy angle.
MAX_COORD_MISMATCH_FT = 75.0
MAX_ANGLE_DEG = 50.0


@dataclass(frozen=True)
class BattedBall:
    game_pk: int
    at_bat_index: int
    batter: str
    pitcher: str
    batter_is_guardian: bool
    event: str            # "Flyout", "Home Run", "Double", ...
    event_type: str       # "field_out", "home_run", ...
    exit_velo: float      # mph
    launch_angle: float   # degrees
    distance: float       # Statcast projected distance, ft
    coord_x: float
    coord_y: float
    inning: int
    is_top: bool
    away_abbr: str
    home_abbr: str
    away_score: int
    home_score: int
    venue: str
    end_time: str = ""

    @property
    def key(self) -> str:
        return f"{self.game_pk}:{self.at_bat_index}"

    @property
    def was_home_run(self) -> bool:
        return self.event_type == "home_run"


@dataclass(frozen=True)
class Verdict:
    is_dong: bool
    too_close: bool
    spray_angle: float
    zone: str
    fence_ft: float                 # posted-geometry distance to the wall
    wall_ft: float                  # wall height there
    height_at_wall: float | None    # None if the ball lands before the wall
    margin_ft: float                # + clears the top by this much / - misses by it
    short_by_ft: float              # how far in front of the wall it lands (0 if it reaches)
    flight: Flight

    @property
    def reaches_wall(self) -> bool:
        return self.height_at_wall is not None


def judge(ball: BattedBall) -> Verdict | None:
    """Return a verdict, or None when the data can't support one."""
    if ball.exit_velo <= 0 or ball.distance <= 0:
        return None
    if abs(park.coord_distance(ball.coord_x, ball.coord_y) - ball.distance) > MAX_COORD_MISMATCH_FT:
        return None
    angle = park.spray_angle(ball.coord_x, ball.coord_y)
    if abs(angle) > MAX_ANGLE_DEG:
        return None
    angle = max(-park.FOUL_LINE_DEG, min(park.FOUL_LINE_DEG, angle))

    fence = park.fence_distance(angle)
    wall = park.wall_height(angle)
    flight = solve_flight(ball.exit_velo, ball.launch_angle, ball.distance)
    effective_fence = fence * FENCE_CALIBRATION
    height = flight.height_at(effective_fence)

    if height is None:
        short_by = effective_fence - flight.landing_distance
        return Verdict(False, False, angle, park.field_zone(angle), fence, wall,
                       None, -wall, short_by, flight)
    margin = height - wall
    return Verdict(margin >= 0, abs(margin) < TOO_CLOSE_FT, angle, park.field_zone(angle),
                   fence, wall, height, margin, 0.0, flight)


def worth_posting(ball: BattedBall, verdict: Verdict, near_wall_ft: float,
                  min_launch_angle: float = 10.0) -> bool:
    """Is this ball interesting enough to post?

    Yes if it left the yard for real, would leave Progressive Field, or was
    hit to within `near_wall_ft` of where Progressive Field's wall stands.
    """
    if ball.launch_angle < min_launch_angle:
        return False
    if ball.was_home_run or verdict.is_dong:
        return True
    return ball.distance >= verdict.fence_ft * FENCE_CALIBRATION - near_wall_ft
