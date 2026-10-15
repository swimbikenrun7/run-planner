from datetime import date

import pytest

from planlib import PlanError
from push import build_events, layout_warnings, stale_ids, to_intervals_text

RACE = date(2026, 11, 26)  # a Thursday
CONFIG = {"race_date": RACE, "plan_tag": "t"}
LIBRARY = {
    "EASY": {"category": "easy", "name": "Easy", "workout_text": "- 30m Z2 Pace"},
    "INT": {"category": "interval", "name": "Int", "workout_text": "- 5m 105% Pace"},
    "RACE": {"category": "race", "name": "Race", "workout_text": None},
}


def test_line_break_convention():
    assert to_intervals_text("Warmup / - 10m Z2 Pace") == "Warmup\n- 10m Z2 Pace"


def test_each_section_header_starts_after_a_blank_line():
    cell = "Warmup / - 10m Z2 Pace / Main Set 8x / - 2m 100% Pace / Cooldown / - 10m Z2 Pace"
    assert to_intervals_text(cell) == (
        "Warmup\n- 10m Z2 Pace\n\nMain Set 8x\n- 2m 100% Pace\n\nCooldown\n- 10m Z2 Pace"
    )


def test_blank_and_race_rows_are_not_pushed():
    events = build_events(CONFIG, LIBRARY, [
        {"date": date(2026, 11, 24), "workout_id": None},
        {"date": date(2026, 11, 25), "workout_id": "EASY"},
        {"date": RACE, "workout_id": "RACE"},
    ])
    assert [e["external_id"] for e in events] == ["t-2026-11-25"]


def test_unknown_workout_id_fails_loudly():
    with pytest.raises(PlanError, match="NOPE"):
        build_events(CONFIG, LIBRARY, [{"date": RACE, "workout_id": "NOPE"}])


def test_duplicate_day_fails():
    with pytest.raises(PlanError, match="two workouts"):
        build_events(CONFIG, LIBRARY, [
            {"date": RACE, "workout_id": "EASY"},
            {"date": RACE, "workout_id": "EASY"},
        ])


def test_stale_ids_only_touch_this_plans_events():
    existing = [
        {"external_id": "t-2026-11-20"},  # still in plan: keep
        {"external_id": "t-2026-11-21"},  # workout moved away: delete
        {"external_id": "other-2026-11-21"},  # different plan: leave alone
        {"external_id": None},  # created by hand in Intervals: leave alone
    ]
    events = [{"external_id": "t-2026-11-20"}]
    assert stale_ids(existing, events, "t") == ["t-2026-11-21"]


def test_hand_edits_to_layout_are_checked():
    layout = [
        {"date": date(2026, 11, 19), "workout_id": "INT"},
        {"date": date(2026, 11, 20), "workout_id": "INT"},
    ]
    warnings = layout_warnings(CONFIG, LIBRARY, layout)
    assert any("back-to-back" in msg for _, msg in warnings)
