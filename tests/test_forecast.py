from datetime import date

import pytest

from forecast import event_loads, plan_races, race_load, start_state

PACES = {"5K": "107% Pace", "10K": "103% Pace", "HM": "98% Pace", "M": "94% Pace"}


def test_event_loads_by_day_leaving_out_a_plan():
    events = [{"start_date_local": "2026-11-20T00:00:00", "icu_training_load": 30, "external_id": "a-2026-11-20"},
              {"start_date_local": "2026-11-20T00:00:00", "icu_training_load": 10, "external_id": None},
              {"start_date_local": "2026-11-21T00:00:00", "icu_training_load": 50, "external_id": "b-2026-11-21"}]
    assert dict(event_loads(events)) == {date(2026, 11, 20): 40, date(2026, 11, 21): 50}
    assert dict(event_loads(events, exclude_tag="b")) == {date(2026, 11, 20): 40}


def test_race_load_matches_a_pushed_10k_tuneup():
    # Intervals gave the 10K tune-up ("- Press lap 103% Pace 10km") a load of 74
    assert race_load("10k", PACES, 3.8779278) == pytest.approx(74, abs=1)


def test_plan_races_need_a_date_and_a_distance():
    rows = [{"race_date": date(2026, 11, 26), "race_distance": "10k", "plan_tag": "tt"},
            {"race_date": None, "race_distance": "half", "plan_tag": "x"},
            {"race_date": date(2027, 5, 2), "race_distance": None, "plan_tag": "y"}]
    assert plan_races(rows) == [(date(2026, 11, 26), "10k", "tt")]


def test_start_state_is_the_day_before():
    assert start_state([{"id": "2026-10-23", "ctl": 30.1, "atl": 48.6}], date(2026, 10, 24)) == (30.1, 48.6)
    with pytest.raises(ValueError):
        start_state([], date(2026, 10, 24))
