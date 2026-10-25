from datetime import date, timedelta

from master import MANUAL, gaps, summarize, tag_of

D = date(2026, 11, 1)


def ev(day, tag=None, name="Easy", category="WORKOUT"):
    d = D + timedelta(days=day)
    return {"start_date_local": f"{d}T00:00:00", "name": name, "category": category,
            "external_id": f"{tag}-{d}" if tag else None}


def test_tag_comes_from_the_external_id():
    assert tag_of(ev(0, "pig-half-2027")) == "pig-half-2027"
    assert tag_of(ev(0)) == MANUAL


def test_plans_races_and_the_gap_between_them():
    events = [ev(k, "a") for k in range(0, 10)] + [ev(k, "b") for k in range(30, 40)]
    cal = summarize(events, {"a": D + timedelta(days=10), "b": D + timedelta(days=40)}, D, D + timedelta(days=45))
    assert [(p["tag"], p["workouts"], p["race"]) for p in cal["plans"]] == [
        ("a", 10, D + timedelta(days=10)), ("b", 10, D + timedelta(days=40))]
    assert cal["days"][D + timedelta(days=10)] == [{"tag": "a", "name": "Race day", "race": True}]
    assert cal["plans"][0]["last"] == D + timedelta(days=9)  # last workout, not race day
    # race day counts as planned; the 5 days after b's race are too short to be a gap
    assert cal["gaps"] == [(D + timedelta(days=11), D + timedelta(days=29))]


def test_rest_days_inside_a_plan_are_not_gaps():
    events = [ev(k, "a") for k in range(0, 30) if k % 7 != 4]  # a rest day every week
    assert summarize(events, {}, D, D + timedelta(days=29))["gaps"] == []


def test_races_added_in_intervals_count_and_manual_events_are_kept():
    events = [ev(3, name="Club 5K", category="RACE_B"), ev(5, name="Group run")]
    cal = summarize(events, {}, D, D + timedelta(days=5))
    assert cal["days"][D + timedelta(days=3)][0]["race"] and cal["plans"] == []
    assert cal["days"][D + timedelta(days=5)][0]["tag"] == MANUAL


def test_gap_at_the_end_of_the_range_is_reported():
    assert gaps({D}, D, D + timedelta(days=8)) == [(D + timedelta(days=1), D + timedelta(days=8))]


def test_fill_status():
    from master import fill_status
    first, last, today = date(2026, 12, 1), date(2026, 12, 20), date(2026, 11, 1)
    fill = lambda tag, d: {"external_id": f"{tag}-{d}", "start_date_local": f"{d}T00:00:00"}
    assert fill_status([], first, last, today) == ("empty", None)
    assert fill_status([fill("fill-2026-12-01", last)], first, last, today) == ("filled", last)
    assert fill_status([fill("fill-2026-12-01", date(2026, 12, 9))], first, last, today)[0] == "partly"
    # filler from before a plan was pushed into the middle of it: the gap after the race starts later
    assert fill_status([fill("fill-2026-11-20", last)], first, last, today)[0] == "outdated"
    # a gap already under way starts today; its filler was tagged when it began
    assert fill_status([fill("fill-2026-11-20", last)], first, last, first)[0] == "filled"
