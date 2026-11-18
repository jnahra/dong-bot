"""The dong model: geometry, flight, and agreement with what really happened."""
from pathlib import Path

import pytest

from dongbot import park
from dongbot.judge import BattedBall, judge, worth_posting
from dongbot.physics import solve_flight

DATA = Path(__file__).parent / "data"


def make_ball(ev, la, dist, x, y, event_type="field_out", **kw) -> BattedBall:
    defaults = dict(
        game_pk=1, at_bat_index=1, batter="Test Batter", pitcher="Test Pitcher",
        batter_is_guardian=True, event="Home Run" if event_type == "home_run" else "Flyout",
        event_type=event_type, exit_velo=ev, launch_angle=la, distance=dist, coord_x=x, coord_y=y,
        inning=5, is_top=True, away_abbr="CLE", home_abbr="KC", away_score=1, home_score=2,
        venue="Kauffman Stadium",
    )
    defaults.update(kw)
    return BattedBall(**defaults)


@pytest.mark.parametrize("ev,la,dist", [(104.9, 29, 404), (95, 35, 340), (110, 18, 380), (88, 45, 300)])
def test_flight_lands_where_statcast_says(ev, la, dist):
    flight = solve_flight(ev, la, dist)
    assert flight.landing_distance == pytest.approx(dist, abs=0.5)
    assert flight.height_at(dist + 1) is None
    assert flight.height_at(dist - 30) > 0
    assert flight.apex > flight.height_at(dist - 5)


def test_fence_matches_posted_dimensions():
    # Posted: 325 LF line, 370 left-center, 410 deep corner, 405 center, 375 right-center, 325 RF line
    assert park.fence_distance(-45) == pytest.approx(325, abs=4)
    assert park.fence_distance(-22.5) == pytest.approx(370, abs=7)
    assert max(park.fence_distance(a) for a in range(-10, 5)) == pytest.approx(410, abs=4)
    assert park.fence_distance(0) == pytest.approx(405, abs=4)
    assert park.fence_distance(22.5) == pytest.approx(375, abs=4)
    assert park.fence_distance(45) == pytest.approx(325, abs=4)


def test_wall_heights():
    assert park.wall_height(-40) == 19
    assert park.wall_height(-10) == 19
    assert park.wall_height(0) == 9
    assert park.wall_height(30) == 9
    assert park.wall_height(44.5) == 14


def test_spray_angle_direction():
    assert park.spray_angle(60, 90) < 0 < park.spray_angle(200, 90)
    assert abs(park.spray_angle(park.HIT_ORIGIN_X, 40)) < 0.01


def test_junk_coordinates_are_not_judged():
    # A real 2026 row: 376 ft fly ball whose coordinates sit next to home plate.
    assert judge(make_ball(95.5, 31, 376, 125.2, 187.2)) is None


def test_worth_posting_rules():
    low_liner = make_ball(105, 5, 150, 125.6, 144.0)
    v = judge(low_liner)
    assert v is not None and not worth_posting(low_liner, v, near_wall_ft=20)

    shallow = make_ball(76.6, 40, 251, 57.2, 125.6)
    assert not worth_posting(shallow, judge(shallow), near_wall_ft=20)

    warning_track = make_ball(100.5, 33, 391, 126.85, 41.37)   # 7 ft short in center
    assert worth_posting(warning_track, judge(warning_track), near_wall_ft=20)
    assert not worth_posting(warning_track, judge(warning_track), near_wall_ft=3)


def test_agrees_with_real_outcomes_at_progressive_field():
    """697 deep fly balls actually hit at Progressive Field in 2026.

    Each row: exit velo x10, launch angle, distance, coordX x10, coordY x10, outcome
    (H = home run; anything else stayed in the park).
    """
    rows = (DATA / "progressive_2026_batted_balls.txt").read_text().strip().split(";")
    right = wrong_dong = missed_dong = 0
    for row in rows:
        ev, la, dist, x, y, outcome = row.split(",")
        verdict = judge(make_ball(int(ev) / 10, int(la), int(dist), int(x) / 10, int(y) / 10))
        if verdict is None:
            continue
        was_hr = outcome == "H"
        if verdict.is_dong == was_hr:
            right += 1
        elif verdict.is_dong:
            wrong_dong += 1
        else:
            missed_dong += 1
    total = right + wrong_dong + missed_dong
    assert total >= 680
    assert right / total >= 0.97
    assert wrong_dong <= 12 and missed_dong <= 12   # errors roughly balanced
