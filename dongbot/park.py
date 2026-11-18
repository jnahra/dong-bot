"""Progressive Field geometry: where the wall is and how tall it is."""
from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

_DATA = Path(__file__).parent / "data" / "progressive_field.json"

# MLB hit coordinates (hitData.coordinates) -> spray angle. Home plate sits at
# roughly this pixel; fitted on 349 home runs from 2026 Guardians games so that
# pixel distance best matches Statcast's projected distance.
HIT_ORIGIN_X = 125.6
HIT_ORIGIN_Y = 207.5
HIT_FEET_PER_UNIT = 2.3625

# Wall heights (ft). The 19-footer runs from the left-field pole to the deep
# corner just left of dead center; center and right are 9 ft, with a taller
# section tucked into the right-field corner.
LF_WALL_FT = 19.0
CF_RF_WALL_FT = 9.0
RF_CORNER_WALL_FT = 14.0
TALL_WALL_ENDS_DEG = -4.0
RF_CORNER_STARTS_DEG = 43.0

FOUL_LINE_DEG = 45.0


@lru_cache(maxsize=1)
def _load() -> dict:
    return json.loads(_DATA.read_text())


def outline() -> dict[str, list[list[float]]]:
    """Field outline segments in feet (home plate at 0,0; +y to center)."""
    return _load()["segments"]


def spray_angle(coord_x: float, coord_y: float) -> float:
    """Degrees from dead center: negative = left field, positive = right field."""
    return math.degrees(math.atan2(coord_x - HIT_ORIGIN_X, HIT_ORIGIN_Y - coord_y))


def coord_distance(coord_x: float, coord_y: float) -> float:
    """Distance in feet implied by the hit coordinates alone (a sanity check)."""
    return math.hypot(coord_x - HIT_ORIGIN_X, HIT_ORIGIN_Y - coord_y) * HIT_FEET_PER_UNIT


def fence_distance(angle_deg: float) -> float:
    """Feet from home plate to the Progressive Field wall at this spray angle."""
    fence = _load()["fence"]
    a = max(fence[0][0], min(fence[-1][0], angle_deg))
    i = min(int(math.floor(a - fence[0][0])), len(fence) - 2)
    (a0, d0), (a1, d1) = fence[i], fence[i + 1]
    return d0 + (a - a0) / (a1 - a0) * (d1 - d0)


def wall_height(angle_deg: float) -> float:
    if angle_deg < TALL_WALL_ENDS_DEG:
        return LF_WALL_FT
    if angle_deg >= RF_CORNER_STARTS_DEG:
        return RF_CORNER_WALL_FT
    return CF_RF_WALL_FT


def field_zone(angle_deg: float) -> str:
    """Plain-English part of the outfield for a spray angle."""
    if angle_deg < -33:
        return "the left-field line" if angle_deg < -40 else "left field"
    if angle_deg < -12:
        return "left-center"
    if angle_deg <= 12:
        return "center field"
    if angle_deg <= 33:
        return "right-center"
    return "the right-field line" if angle_deg > 40 else "right field"
