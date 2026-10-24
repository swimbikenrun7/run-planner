from datetime import date, timedelta

import pytest

from layout import Context, future_hard, layout_rows, place, plan_items, selected_plan, suggest, violations
from planlib import PlanError

RACE = date(2027, 5, 2)  # a Sunday
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
