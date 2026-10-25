"""The master calendar: what's on Intervals.icu, by plan, and the gaps between plans.

Intervals is the record of everything committed, so this only reads it. Plans pushed by
push.py carry external_id "<plan_tag>-<date>"; the Plans tab says which race each tag is for.
"""

import re
from datetime import timedelta

from planlib import to_date

MIN_GAP_DAYS = 7  # shorter stretches with nothing planned are rest days, not gaps
TAG_DATE = re.compile(r"^(.*)-(\d{4}-\d{2}-\d{2})$")
MANUAL = "(added in Intervals)"
FILL_PREFIX = "fill-"  # gap filler's plan_tags: fill-<first day of the gap>
FILL_AHEAD_DAYS = 90  # with no plan after a gap, fill at most this far from today (user)


def tag_of(event):
    """The plan_tag an event was pushed under, or MANUAL for events created in Intervals."""
    m = TAG_DATE.match(event.get("external_id") or "")
    return m.group(1) if m else MANUAL


def is_race(event):
    return str(event.get("category") or "").upper().startswith("RACE")


def summarize(events, races, start, end):
    """Events from Intervals -> the master calendar between start and end (inclusive).

    races maps plan_tag -> race date (from the Plans tab). Returns
    {"days": {date: [entries]}, "plans": [...], "gaps": [(first, last), ...]}, where an entry is
    {"tag", "name", "race"}. A race counts as planned, so a race day is never part of a gap.
    """
    days = {}
    for e in events:
        d = to_date(e["start_date_local"])
        if start <= d <= end:
            days.setdefault(d, []).append({"tag": tag_of(e), "name": str(e.get("name") or ""),
                                           "race": is_race(e)})
    for tag, race in races.items():
        if race and start <= race <= end and not any(x["race"] for x in days.get(race, [])):
            days.setdefault(race, []).append({"tag": tag, "name": "Race day", "race": True})

    plans = {}
    for d, entries in days.items():
        for x in entries:
            if x["tag"] == MANUAL or x["race"]:
                continue
            p = plans.setdefault(x["tag"], {"tag": x["tag"], "first": d, "last": d, "workouts": 0,
                                            "race": races.get(x["tag"])})
            p["first"], p["last"] = min(p["first"], d), max(p["last"], d)
            p["workouts"] += 1
    return {"days": days, "plans": sorted(plans.values(), key=lambda p: p["first"]),
            "gaps": gaps(set(days), start, end)}


def gaps(planned, start, end, min_days=MIN_GAP_DAYS):
    """Stretches of at least min_days in [start, end] with nothing planned, as (first, last)."""
    out, run = [], None
    d = start
    while d <= end + timedelta(days=1):
        empty = d <= end and d not in planned
        if empty and run is None:
            run = d
        elif not empty and run is not None:
            if (d - run).days >= min_days:
                out.append((run, d - timedelta(days=1)))
            run = None
        d += timedelta(days=1)
    return out


def fill_status(events, first, last, today):
    """How the filler in the gap [first, last] stands: (status, filled_to).

    status is "empty", "filled", "partly" (filled to filled_to, e.g. an open-ended gap whose
    90 days have moved on) or "outdated" (filler from before the calendar changed around it:
    a plan pushed into it, so it no longer starts on the gap's first day). A gap already under way
    starts today, so its filler's tag can be earlier.
    """
    fill = [(to_date(e["start_date_local"]), tag_of(e)) for e in events if tag_of(e).startswith(FILL_PREFIX)]
    fill = [(d, t) for d, t in fill if first <= d <= last]
    if not fill:
        return "empty", None
    filled_to = max(d for d, _ in fill)
    if any(not fill_tag_fits(t, first, today) for _, t in fill):
        return "outdated", filled_to
    return ("filled" if filled_to >= last else "partly"), filled_to


def fill_tag_fits(tag, first, today):
    """Whether filler tagged `tag` was planned for a gap starting on `first`."""
    start = tag[len(FILL_PREFIX):]
    return start == first.isoformat() or (first <= today and start < first.isoformat())
