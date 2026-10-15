from datetime import date, timedelta

from layout import build_layout

RACE = date(2026, 11, 26)  # a Thursday
LIBRARY = {
    "EASY": {"category": "easy", "name": "Easy"},
    "LONG": {"category": "long", "name": "Long"},
    "INT": {"category": "interval", "name": "Int"},
    "TEMPO": {"category": "tempo", "name": "Tempo"},
    "RACE": {"category": "race", "name": "Race"},
}
HARD = {"interval", "tempo", "long", "race"}


def config(**overrides):
    base = {"race_date": RACE, "plan_tag": "t", "long_run": "sat",
            "hard_categories": "interval, tempo, long, race", "taper_days": 2}
    base.update(overrides)
    return base


def week(n, **days):
    return [{"week": n, "day": d, "workout_id": wid} for d, wid in days.items()]


def by_date(rows):
    return {r["date"]: r for r in rows}


def hard_dates(rows):
    return sorted(r["date"] for r in rows if r["category"] in HARD)


def assert_rules_hold(rows):
    hd = hard_dates(rows)
    assert all((b - a).days > 1 for a, b in zip(hd, hd[1:])), hd
    assert not any(r["flag"] for r in rows)


def test_plan_already_in_target_convention_is_unchanged():
    # Fri-Thu weeks, long Sat, intervals Tue/Thu: nothing should move
    sched = (week(1, Fri="EASY", Sat="LONG", Sun="EASY", Mon="EASY", Tue="INT", Wed="EASY", Thu="TEMPO")
             + week(2, Fri="EASY", Sat="LONG", Sun="EASY", Mon="INT", Tue="EASY", Wed="EASY", Thu="RACE"))
    rows = build_layout(config(source_week_end="thu"), LIBRARY, sched)
    assert not any(r["moved"] for r in rows)
    assert_rules_hold(rows)


def test_sunday_plan_rearranged_for_thursday_race_and_saturday_long_run():
    sched = (week(1, Tue="INT", Wed="EASY", Thu="TEMPO", Sat="EASY", Sun="LONG")
             + week(2, Tue="INT", Wed="EASY", Thu="TEMPO", Sat="EASY", Sun="LONG")
             + week(3, Tue="INT", Thu="EASY", Sun="RACE"))
    rows = build_layout(config(source_week_end="sun"), LIBRARY, sched)
    d = by_date(rows)
    assert d[RACE]["workout_id"] == "RACE"
    for r in rows:
        if r["workout_id"] == "LONG":
            assert r["day"] == "Sat"
    assert_rules_hold(rows)
    # source order kept inside each week: INT before TEMPO
    wk1 = [r["workout_id"] for r in rows if r["week"] == 1 and r["workout_id"] in ("INT", "TEMPO")]
    assert wk1 == ["INT", "TEMPO"]
    # every workout survives: 3 hard + 2 easy per week in weeks 1-2
    assert sum(1 for r in rows if r["week"] == 1 and r["workout_id"]) == 5


def test_hard_session_pulled_out_of_taper_window():
    # source puts intervals the day before the race
    sched = week(1, Fri="EASY", Sat="EASY", Sun="EASY", Mon="EASY", Tue="EASY", Wed="INT", Thu="RACE")
    rows = build_layout(config(source_week_end="thu", long_run=None), LIBRARY, sched)
    int_row = next(r for r in rows if r["workout_id"] == "INT")
    assert int_row["date"] < RACE - timedelta(days=2)
    assert int_row["moved"] == "yes"
    assert_rules_hold(rows)


def test_spacing_respected_across_week_boundary():
    # week 1 ends with TEMPO on Thu; week 2's INT sits on Fri in the source
    sched = (week(1, Fri="EASY", Sat="LONG", Sun="EASY", Mon="EASY", Tue="INT", Wed="EASY", Thu="TEMPO")
             + week(2, Fri="INT", Sat="EASY", Sun="EASY", Mon="EASY", Tue="EASY", Wed="EASY", Thu="RACE"))
    rows = build_layout(config(source_week_end="thu", long_run=None), LIBRARY, sched)
    assert_rules_hold(rows)


def test_impossible_week_is_flagged_not_dropped():
    # five hard sessions can't fit in seven days without touching
    sched = week(1, Fri="INT", Sat="LONG", Sun="INT", Mon="TEMPO", Tue="INT", Wed="EASY", Thu="RACE")
    rows = build_layout(config(source_week_end="thu"), LIBRARY, sched)
    assert any(r["flag"] for r in rows)
    assert sum(1 for r in rows if r["workout_id"]) == 7
