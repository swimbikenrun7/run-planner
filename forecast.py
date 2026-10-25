"""Daily load for projecting form: planned workouts on Intervals plus races (which aren't pushed)."""

from collections import defaultdict
from datetime import timedelta

from fitness import project
from master import tag_of
from planlib import blank, to_date

RACE_METERS = {"5k": 5000, "10k": 10000, "half": 21097.5, "marathon": 42195}
RACE_PACE_KEY = {"5k": "5K", "10k": "10K", "half": "HM", "marathon": "M"}


def event_loads(events, exclude_tag=None):
    """{date: load} from Intervals events, leaving out one plan_tag (e.g. the plan being replaced)."""
    loads = defaultdict(float)
    for e in events:
        if exclude_tag and tag_of(e) == exclude_tag:
            continue
        loads[to_date(e["start_date_local"])] += e.get("icu_training_load") or 0
    return loads


def race_load(distance, paces, threshold_speed):
    """Estimated load of racing this distance at its race pace from the Paces tab."""
    pct = float(str(paces[RACE_PACE_KEY[distance]]).split("%")[0])
    hours = RACE_METERS[distance] / (threshold_speed * pct / 100) / 3600
    return hours * (pct / 100) ** 2 * 100


def plan_races(plans_rows):
    """[(race date, distance, plan_tag)] for plans with a race date and distance on the Plans tab."""
    out = []
    for r in plans_rows:
        dist = str(r.get("race_distance") or "").strip().lower()
        if not blank(r.get("race_date")) and dist in RACE_METERS:
            out.append((to_date(r["race_date"]), dist, str(r.get("plan_tag") or "").strip()))
    return out


def start_state(wellness, day):
    """(fitness, fatigue) at the end of the day before `day`, from Intervals wellness rows."""
    rows = {w["id"]: w for w in wellness}
    prev = rows.get((day - timedelta(days=1)).isoformat())
    if not prev or prev.get("ctl") is None:
        raise ValueError(f"Intervals has no fitness for {day - timedelta(days=1)}")
    return prev["ctl"], prev["atl"]


def race_day_form(ctl, atl, today, race_date, loads, layout_rows, library, load_of):
    """(form, fitness) going into race day: the other planned load plus this plan's Layout."""
    loads = defaultdict(float, loads)
    for r in layout_rows:
        wid = str(r.get("workout_id") or "").strip()
        if wid in library and not blank(r.get("date")) and to_date(r["date"]) >= today:
            loads[to_date(r["date"])] += load_of(library[wid].get("workout_text"))
    proj = project(ctl, atl, loads, today, race_date)
    return proj[-1][4], proj[-1][2]
