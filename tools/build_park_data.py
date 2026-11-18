"""Build dongbot/data/progressive_field.json from the GeomMLBStadiums outlines.

Source: https://github.com/bdilday/GeomMLBStadiums (inst/extdata/mlb_stadia_paths.csv)

The outlines are in MLB Gameday hit-coordinate pixels. We re-express them in
feet with home plate at (0, 0) and +y pointing to dead center. FEET_PER_UNIT
was chosen so the outline reproduces Progressive Field's posted dimensions
(325 / 370 / 410 / 405 / 375 / 325) to within a few feet.

Usage: python tools/build_park_data.py path/to/mlb_stadia_paths.csv
"""
import csv
import json
import math
import sys
from pathlib import Path

TEAM = "guardians"
APEX = (125.18, 204.53)  # where the outline's foul lines meet (home plate)
FEET_PER_UNIT = 2.40


def main(src: str) -> None:
    rows = [r for r in csv.DictReader(open(src)) if r["team"] == TEAM]
    segments: dict[str, list[list[float]]] = {}
    for r in rows:
        x = (float(r["x"]) - APEX[0]) * FEET_PER_UNIT
        y = (APEX[1] - float(r["y"])) * FEET_PER_UNIT
        segments.setdefault(r["segment"], []).append([round(x, 1), round(y, 1)])

    # Fence distance by spray angle (0 = dead center, negative = left field).
    polar = sorted(
        (math.degrees(math.atan2(x, y)), math.hypot(x, y))
        for x, y in segments["outfield_outer"]
    )
    polar = [(a, d) for a, d in polar if -47 <= a <= 47 and d > 250]
    angles = [a for a, _ in polar]
    dists = [d for _, d in polar]

    def interp(a: float) -> float:
        if a <= angles[0]:
            return dists[0]
        for i in range(1, len(angles)):
            if a <= angles[i]:
                t = (a - angles[i - 1]) / (angles[i] - angles[i - 1])
                return dists[i - 1] + t * (dists[i] - dists[i - 1])
        return dists[-1]

    fence = [[a, round(interp(a), 1)] for a in range(-45, 46)]
    out = {
        "name": "Progressive Field",
        "venue_id": 5,
        "source": "bdilday/GeomMLBStadiums outline, scaled to posted dimensions",
        "fence": fence,
        "segments": segments,
    }
    dest = Path(__file__).resolve().parent.parent / "dongbot" / "data" / "progressive_field.json"
    dest.write_text(json.dumps(out, separators=(",", ":")))
    print("wrote", dest, "fence@[-45,-22,-4,0,22,45] =",
          [dict(fence)[a] for a in (-45, -22, -4, 0, 22, 45)])


if __name__ == "__main__":
    main(sys.argv[1])
