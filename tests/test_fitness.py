from datetime import date, timedelta

import pytest

from fitness import project, workout_load, zone, zone_floor

SPEED = 3.8779278  # the user's threshold pace, m/s (6:55/mi)
ZONES = [77.5, 87.7, 94.3, 100.0, 103.4, 111.5, 999.0]


@pytest.mark.parametrize("text, intervals_load", [  # loads Intervals gave these planned workouts
    ("- Press lap 80% Pace 30m", 32),
    ("- Press lap 80% Pace 3mi", 28),
    ("- Press lap 80% Pace 67m30s / - 22m30s 94% Pace", 105),
    ("Warmup / - Press lap Z2 Pace 10m / Main Set 10x / - 2m 100% Pace / - 1m Z1 Pace / "
     "Cooldown / - Press lap Z2 Pace 10m", 63),
    ("Warmup / - Press lap Z2 Pace 10m / Main Set 7x / - 400mtr 107% Pace / - 90s Z1 Pace / "
     "Cooldown / - Press lap Z2 Pace 10m", 51),
    ("Warmup / - Press lap Z2 Pace 10m / Hills 6x / - Uphill hard 90s / - Press lap Jog down Z1 Pace / "
     "Cooldown / - Press lap Z2 Pace 10m", 23),  # hills without a target count nothing
])
def test_load_matches_intervals(text, intervals_load):
    assert workout_load(text, SPEED, ZONES) == pytest.approx(intervals_load, abs=1.3)


def test_projection_matches_the_42_and_7_day_averages():
    d = date(2026, 11, 1)
    out = project(30.0, 45.0, {d: 90.0}, d, d + timedelta(days=1))
    assert out[0][4] == -15.0  # form going into the day
    assert out[0][2] == pytest.approx(30 + 60 / 42) and out[0][3] == pytest.approx(45 + 45 / 7)
    assert out[1][1] == 0.0


def test_zones_absolute_below_fitness_60_and_percent_above():
    assert zone(-2, 40) == "grey" and zone(-12, 40) == "optimal" and zone(-31, 40) == "high risk"
    assert zone(-25, 50) == "optimal"  # absolute: -25
    assert zone(-25, 80) == "high risk"  # percent: -25 / 80 = -31%
    assert zone(-7, 80) == "grey"  # -9%


def test_zone_floor():
    assert zone_floor("grey") == -10 and zone_floor("fresh") == 5
