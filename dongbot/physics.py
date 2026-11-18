"""Batted-ball flight: how high is the ball when it reaches the wall?

Statcast gives us exit velocity, launch angle and a projected distance. Those
three numbers pin down the shape of the flight almost completely, so we:

  1. integrate a standard drag + backspin-lift trajectory, and
  2. solve for the one drag coefficient that makes the ball come down at
     exactly the projected distance Statcast reported.

Wind, air density and spin in the real park are absorbed into that fitted
coefficient. The fitted flight is then sampled at the fence distance.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

G = 32.174            # ft/s^2
MPH_TO_FPS = 5280 / 3600
K_AIR = 0.005316      # 0.5 * rho * A / m for a baseball at sea level, 1/ft
LIFT_COEF = 0.20      # typical backspin fly ball
CONTACT_HEIGHT = 3.0  # ft
DT = 0.01             # s


@dataclass(frozen=True)
class Flight:
    """A solved trajectory: sampled (distance, height) points in feet."""

    xs: tuple[float, ...]
    ys: tuple[float, ...]
    drag_coef: float

    @property
    def landing_distance(self) -> float:
        return self.xs[-1]

    @property
    def apex(self) -> float:
        return max(self.ys)

    def height_at(self, distance: float) -> float | None:
        """Ball height when it is `distance` ft from home, on the way down.

        Returns None if the ball lands before getting there.
        """
        if distance > self.xs[-1]:
            return None
        if distance <= 0:
            return self.ys[0]
        lo, hi = 0, len(self.xs) - 1
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if self.xs[mid] < distance:
                lo = mid
            else:
                hi = mid
        span = self.xs[hi] - self.xs[lo]
        t = 0.0 if span == 0 else (distance - self.xs[lo]) / span
        return self.ys[lo] + t * (self.ys[hi] - self.ys[lo])


def _simulate(ev_mph: float, la_deg: float, drag_coef: float) -> tuple[list[float], list[float]]:
    v0 = ev_mph * MPH_TO_FPS
    la = math.radians(la_deg)
    vx, vy = v0 * math.cos(la), v0 * math.sin(la)
    x, y = 0.0, CONTACT_HEIGHT
    xs, ys = [x], [y]

    def accel(vx: float, vy: float) -> tuple[float, float]:
        v = math.hypot(vx, vy)
        kd = K_AIR * drag_coef * v
        kl = K_AIR * LIFT_COEF * v
        # drag opposes velocity; lift is perpendicular to it (backspin -> up)
        return (-kd * vx - kl * vy, -G - kd * vy + kl * vx)

    for _ in range(int(15 / DT)):
        ax1, ay1 = accel(vx, vy)
        mvx, mvy = vx + ax1 * DT / 2, vy + ay1 * DT / 2
        ax2, ay2 = accel(mvx, mvy)
        nx, ny = x + mvx * DT, y + mvy * DT
        vx, vy = vx + ax2 * DT, vy + ay2 * DT
        if ny <= 0:
            t = y / (y - ny)  # interpolate the touchdown point
            xs.append(x + t * (nx - x))
            ys.append(0.0)
            break
        x, y = nx, ny
        xs.append(x)
        ys.append(y)
    return xs, ys


def solve_flight(ev_mph: float, la_deg: float, distance_ft: float) -> Flight:
    """Fit a trajectory that leaves the bat at (ev, la) and lands at distance_ft."""
    lo, hi = 0.0, 3.0  # drag coefficient bounds: vacuum-ish .. brick
    far, short = _simulate(ev_mph, la_deg, lo), _simulate(ev_mph, la_deg, hi)
    if distance_ft >= far[0][-1]:      # farther than physics allows: use least drag
        return Flight(tuple(far[0]), tuple(far[1]), lo)
    if distance_ft <= short[0][-1]:
        return Flight(tuple(short[0]), tuple(short[1]), hi)
    xs: list[float] = []
    ys: list[float] = []
    for _ in range(40):
        mid = (lo + hi) / 2
        xs, ys = _simulate(ev_mph, la_deg, mid)
        if xs[-1] > distance_ft:
            lo = mid
        else:
            hi = mid
        if abs(xs[-1] - distance_ft) < 0.05:
            break
    return Flight(tuple(xs), tuple(ys), (lo + hi) / 2)
