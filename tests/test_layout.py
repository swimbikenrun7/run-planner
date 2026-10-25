from datetime import date, timedelta

import pytest

from layout import (
    Context,
    fill_rest_days,
    future_hard,
    layout_rows,
    place,
    plan_items,
    selected_plan,
    suggest,
    violations,
)
from planlib import PlanError

RACE = date(2027, 5, 2)  # a Sunday
ONE_DAY = timedelta(days=1)
TODAY = date(2026, 10, 16)
HARD = {"interval", "tempo", "hills", "long", "tuneup", "race"}
LIBRARY = {
    "EASY": {"category": "easy", "name": "Easy"},
    "GROUP": {"category": "easy", "name": "Group run"},
    "LONG": {"category": "long", "name": "Long"},
    "INT": {"category": "interval", "name": "Int"},
    "TEMPO": {"category": "tempo", "name": "Tempo"},
    "PACE": {"category": "tempo", "name": "HM pace"},
    "TUNE": {"category": "tuneup", "name": "5K race"},
    "RACE": {"category": "race", "name": "Race"},
    "E3": {"category": "easy", "name": "Easy 3mi", "workout_text": "- Press lap 80% Pace 3mi"},
    "E2": {"category": "easy", "name": "Easy 2mi", "workout_text": "- Press lap 80% Pace 2mi"},
}
DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def week_tpl(**roles):
    """week_tpl(sun='long', tue='quality', thu=('fixed', 'GROUP'))"""
    out = {d: ("easy", None) for d in range(7)}
    for name, role in roles.items():
        d = DAY_NAMES.index(name.title())
        out[d] = role if isinstance(role, tuple) else (role, None)
    return out


def rows_for(weeks):
    """weeks: list of 7-item lists Mon..Sun of workout ids (None = rest)."""
    return [{"week": w, "day": DAY_NAMES[d], "workout_id": wid}
            for w, days in enumerate(weeks, start=1) for d, wid in enumerate(days)]


def ctx_for(weeks, today=TODAY, gap=5, taper=2):
    items, last = plan_items(RACE, 6, LIBRARY, rows_for(weeks))  # weeks end Sunday
    return Context(RACE, HARD, taper, gap, LIBRARY, today, items, last)


HIGDON_WEEK = ["EASY", "INT", "EASY", "TEMPO", None, "PACE", "LONG"]
RACE_WEEK = ["EASY", "INT", "EASY", "EASY", None, None, "RACE"]
MY_WEEK = week_tpl(sun="long", tue="quality", thu=("fixed", "GROUP"), fri="quality")


def by_date(placed):
    return {d: i["wid"] for d, i in placed.items()}


def test_plan_that_fits_lands_on_its_days():
    ctx = ctx_for([["EASY", "INT", "EASY", "TEMPO", None, "EASY", "LONG"], RACE_WEEK])
    placed, unplaced = place(ctx, week_tpl(sun="long", tue="quality", thu="quality"), False)
    assert not future_hard(ctx, unplaced)
    assert not violations(ctx, placed, False)
    wk1 = RACE - timedelta(days=13)  # Mon of week 1
    assert by_date(placed)[wk1 + timedelta(days=1)] == "INT"
    assert by_date(placed)[wk1 + timedelta(days=6)] == "LONG"


def test_fixed_day_always_gets_its_workout():
    ctx = ctx_for([HIGDON_WEEK, RACE_WEEK])
    placed, _ = place(ctx, MY_WEEK, False)
    thursdays = [d for d in ctx.days if d.weekday() == 3]
    assert all(placed[d]["wid"] == "GROUP" for d in thursdays)


def test_extra_hard_session_is_reported_not_crammed_in():
    ctx = ctx_for([HIGDON_WEEK, RACE_WEEK])
    placed, unplaced = place(ctx, MY_WEEK, False)
    assert [i["wid"] for i, _ in future_hard(ctx, unplaced)] == ["PACE"]
    assert not violations(ctx, placed, False)


def test_no_long_run_within_gap_of_race():
    ctx = ctx_for([["EASY"] * 6 + ["LONG"], ["EASY", "EASY", "LONG", "EASY", None, None, "RACE"]])
    placed, unplaced = place(ctx, week_tpl(wed="long"), False)
    reasons = [why for i, why in unplaced if i["wid"] == "LONG"]
    assert reasons == ["long run within 5 days of the race"]


def test_tuneup_race_takes_the_long_run_day():
    ctx = ctx_for([["EASY", "INT", "EASY", "TEMPO", None, None, "TUNE"], RACE_WEEK])
    placed, _ = place(ctx, week_tpl(sat="long", tue="quality", thu="quality"), False)
    assert by_date(placed)[RACE - timedelta(days=8)] == "TUNE"  # Sat of week 1


def test_pre_long_session_allowed_only_when_switched_on():
    ctx = ctx_for([HIGDON_WEEK, RACE_WEEK])
    tpl = week_tpl(sun="long", tue="quality", thu="quality", sat="quality")
    placed, unplaced = place(ctx, tpl, True)
    assert not future_hard(ctx, unplaced) and not violations(ctx, placed, True)
    assert by_date(placed)[RACE - timedelta(days=8)] == "PACE"
    placed, unplaced = place(ctx, tpl, False)
    assert any(i["wid"] == "PACE" for i, _ in unplaced)


def test_suggestions_offer_both_kinds_of_fix():
    ctx = ctx_for([HIGDON_WEEK] * 3 + [RACE_WEEK])
    picks = suggest(ctx, MY_WEEK, False, [5, 6])
    assert len(picks[0]["missing"]) == 3  # your week as it is
    fixes = [p for p in picks[1:] if not p["missing"]]
    assert any(any("skips GROUP" in c for c in p["changes"]) for p in fixes)  # keep Sunday long
    assert any(p["week"][5][0] == "long" and p["week"][3] == ("fixed", "GROUP") for p in fixes)


def test_past_dates_are_flagged_and_not_counted():
    ctx = ctx_for([HIGDON_WEEK, RACE_WEEK], today=RACE - timedelta(days=7))
    placed, unplaced = place(ctx, MY_WEEK, False)
    assert not future_hard(ctx, unplaced)  # week 1's leftover pace run is in the past
    rows = layout_rows(ctx, placed, unplaced, False)
    assert all(r["flag"].startswith("past") for r in rows if r["date"] and r["date"] < ctx.today)


def test_plans_are_selected_by_name():
    sheets = {"plans": [{"plan": "a", "source_week_end": "sun"}],
              "schedule": [{"plan": "a", "week": 1, "day": "Mon", "workout_id": "EASY"},
                           {"plan": "b", "week": 1, "day": "Mon", "workout_id": "INT"}]}
    name, week_end, rows = selected_plan({"plan": "a"}, sheets)
    assert (name, week_end, [r["workout_id"] for r in rows]) == ("a", 6, ["EASY"])
    with pytest.raises(PlanError):
        selected_plan({"plan": "b"}, sheets)  # not on the Plans tab


def test_rest_days_give_way_to_displaced_easy_runs():
    # the user's week: the fixed group run and three quality days leave no room for the plan's rest day
    ctx = ctx_for([HIGDON_WEEK, HIGDON_WEEK, RACE_WEEK])
    tpl = week_tpl(sat="long", mon="quality", wed="quality", fri="quality", thu=("fixed", "GROUP"))
    placed, unplaced = place(ctx, tpl, True)
    assert unplaced == []
    for wk in (1, 2, 3):  # each week keeps its own easy runs: none drift into another week
        days = [d for d in ctx.days if ctx.block(d) == wk]
        assert sum(placed[d]["wid"] == "EASY" for d in days) == sum(
            i["wid"] == "EASY" for i in ctx.items if i["week"] == wk)


def test_rest_days_filled_with_a_shorter_run_the_day_before_the_race():
    ctx = ctx_for([HIGDON_WEEK, RACE_WEEK])  # rest on both Fridays and race-week Saturday
    tpl = week_tpl(sun="long", tue="quality", thu="quality", sat="quality")
    placed, _ = place(ctx, tpl, True)
    fill_rest_days(ctx, placed, "E3", "E2")
    assert all(i["wid"] for i in placed.values())  # no rest days left
    assert placed[RACE - timedelta(days=1)]["wid"] == "E2"
    assert placed[RACE - timedelta(days=2)]["wid"] == "E3"
    assert placed[RACE - timedelta(days=2)]["source_day"] == "(rest fill)"
    assert not violations(ctx, placed, True)


def test_blank_fill_keeps_rest_days():
    ctx = ctx_for([HIGDON_WEEK, RACE_WEEK])
    placed, _ = place(ctx, week_tpl(sun="long", tue="quality", thu="quality", sat="quality"), True)
    fill_rest_days(ctx, placed, None, None)
    assert placed[RACE - timedelta(days=1)]["wid"] is None


USER_WEEK = week_tpl(sat="long", mon="quality", wed="quality", fri="quality", thu=("fixed", "GROUP"))


def race_week(plan_week):
    ctx = ctx_for([HIGDON_WEEK, plan_week])
    placed, _ = place(ctx, USER_WEEK, True)
    fill_rest_days(ctx, placed, "E3", "E2")
    return [placed[RACE - timedelta(days=k)]["wid"] for k in range(6, 0, -1)]  # Mon..Sat


def test_race_week_plans_own_short_run_becomes_the_shakeout():
    # Higdon race week: Mon 3mi, Tue intervals, Wed 2mi, Thu tempo, Fri/Sat rest (the user's edit)
    assert race_week(["E3", "INT", "E2", "TEMPO", None, None, "RACE"]) == ["INT", "E3", "TEMPO", "GROUP", "E3", "E2"]


def test_race_week_without_a_short_run_gets_the_shakeout_fill():
    assert race_week(["E3", "INT", "E3", "TEMPO", None, None, "RACE"]) == ["INT", "E3", "TEMPO", "GROUP", "E3", "E2"]


def test_longer_plan_run_the_day_before_the_race_moves_earlier():
    ctx = ctx_for([HIGDON_WEEK, ["E3", None, None, None, None, "E3", "RACE"]])
    placed, _ = place(ctx, week_tpl(sun="long"), True)
    fill_rest_days(ctx, placed, "E3", "E2")
    assert placed[RACE - ONE_DAY]["wid"] == "E2"
    assert [placed[RACE - timedelta(days=k)]["wid"] for k in range(6, 1, -1)] == ["E3"] * 5


def test_tuneup_is_placed_once_even_when_not_counted_as_hard():
    items, last = plan_items(RACE, 6, LIBRARY, rows_for([["EASY", "INT", "EASY", "TEMPO", None, None, "TUNE"],
                                                          RACE_WEEK]))
    ctx = Context(RACE, HARD - {"tuneup"}, 2, 5, LIBRARY, TODAY, items, last)
    placed, _ = place(ctx, week_tpl(sat="long", tue="quality", thu="quality"), False)
    assert [d for d, i in placed.items() if i["wid"] == "TUNE"] == [RACE - timedelta(days=8)]  # Sat only
