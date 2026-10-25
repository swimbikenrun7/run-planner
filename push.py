"""Push the Layout tab of plan_builder.xlsx to the Intervals.icu calendar.

Usage:
    python layout.py plans/plan_builder.xlsx           # first: arrange Schedule into Layout
    python push.py plans/plan_builder.xlsx --dry-run   # print events, send nothing
    python push.py plans/plan_builder.xlsx             # push to Intervals.icu

Reads credentials from .env (INTERVALS_API_KEY, INTERVALS_ATHLETE_ID).
Events are upserted on external_id = "<plan_tag>-<date>", so re-pushing updates in place.
After upserting, any event from this plan_tag whose date no longer has a workout is deleted.
Gap filler in the plan's dates is replaced. If another plan overlaps, choose with
--overlap keep (skip this plan's workouts in its dates) or --overlap replace (delete its workouts
in this plan's dates). Events added by hand in Intervals are never deleted.
"""

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta

import requests
from dotenv import load_dotenv

from master import FILL_PREFIX, MANUAL, is_race, tag_of
from planlib import (
    PlanError,
    blank,
    category_of,
    hard_categories,
    last_used_row,
    load_workbook_tables,
    rule_violations,
    save_workbook,
    taper_days,
    to_date,
    yes,
)

API_BASE = "https://intervals.icu/api/v1"
LINE_BREAK = " / "  # in-cell convention for a newline in workout_text
SKIP_CATEGORIES = {"race"}  # added to Intervals by hand for now
CLEANUP_WINDOW = timedelta(days=180)  # how far around the plan to look for stale events


# ---------- logic (pure, testable) ----------

def to_intervals_text(cell_text):
    """Convert ' / '-separated cell text to Intervals.icu workout text.

    Section headers (any line not starting with '-') get a blank line before them,
    which is how Intervals.icu tells where one section ends and the next begins.
    """
    lines = [part.strip() for part in str(cell_text).split(LINE_BREAK) if part.strip()]
    out = []
    for line in lines:
        if not line.startswith("-") and out:
            out.append("")
        out.append(line)
    return "\n".join(out)


def build_events(config, library, layout, today=None):
    """Validate the Layout rows and return the Intervals.icu event list. Raises PlanError.

    Rows without a date (sessions layout couldn't place) and dates before today are skipped.
    """
    today = today or date.today()
    if blank(config.get("plan_tag")):
        raise PlanError("Config is missing plan_tag")
    plan_tag = str(config["plan_tag"]).strip()

    errors, events, seen = [], [], {}
    for i, row in enumerate(layout, start=2):
        wid = row.get("workout_id")
        if blank(wid) or blank(row.get("date")):
            continue  # rest day, or a session layout couldn't place
        wid = str(wid).strip()
        try:
            d = to_date(row["date"])
        except (TypeError, ValueError) as e:
            errors.append(f"Layout row {i}: bad date ({e})")
            continue
        if d < today:
            continue
        if wid not in library:
            errors.append(f"Layout row {i}: workout_id {wid!r} not in Library")
            continue
        if d in seen:
            errors.append(f"{d} has two workouts: {seen[d]} and {wid}")
            continue
        seen[d] = wid
        if category_of(library, wid) in SKIP_CATEGORIES:
            continue
        text = library[wid].get("workout_text")
        if blank(text):
            errors.append(f"Library {wid!r} has no workout_text")
            continue
        events.append({
            "category": "WORKOUT",
            "type": "Run",
            "start_date_local": f"{d.isoformat()}T00:00:00",
            "name": str(library[wid].get("name") or wid),
            "description": to_intervals_text(text),
            "external_id": f"{plan_tag}-{d.isoformat()}",
        })

    if not events and not errors:
        errors.append("Layout has no workouts to push")
    if errors:
        raise PlanError("\n".join(errors))
    return sorted(events, key=lambda e: e["start_date_local"])


def layout_warnings(config, library, layout):
    """Rule violations in the Layout as it stands (including any hand edits)."""
    entries = []
    for row in layout:
        wid = row.get("workout_id")
        if not blank(wid) and not blank(row.get("date")) and str(wid).strip() in library:
            entries.append((to_date(row["date"]), category_of(library, str(wid).strip())))
    problems = rule_violations(entries, to_date(config["race_date"]),
                               hard_categories(config), taper_days(config))
    if yes(config.get("allow_pre_long")):
        cats = dict(entries)
        problems = [(d, m) for d, m in problems
                    if not (m.startswith("back-to-back") and cats.get(d) == "long")]
    return problems


def stale_ids(existing, events, plan_tag, today=None):
    """external_ids of this plan's future events in Intervals that the new plan no longer has.

    Past events are never deleted: they're history, even if the plan has changed since.
    """
    today = today or date.today()
    keep = {e["external_id"] for e in events}
    prefix = f"{plan_tag}-"
    out = []
    for e in existing:
        xid = e.get("external_id") or ""
        if not xid.startswith(prefix) or xid in keep:
            continue
        start = str(e.get("start_date_local") or xid[len(prefix):])[:10]
        try:
            if date.fromisoformat(start) < today:
                continue
        except ValueError:
            pass
        out.append(xid)
    return sorted(out)


def overlaps(existing, events, plan_tag, race, races=None, today=None):
    """What else is on Intervals between this plan's first workout and its race (future days only).

    races maps other plan_tags to their race dates (Plans tab), so a plan's span runs to its race.
    Returns {"fill": [external_ids], "plans": {tag: {"first", "last", "ids", "ours"}}, "manual": [(date, name)]}:
    filler is always replaced; another plan needs the user's choice (keep it, or replace its workouts
    here with this plan's: "ids" are its workouts in this plan's dates, "ours" how many of this plan's
    workouts fall in its span); events added by hand in Intervals (races included) are only listed.
    """
    today, races = today or date.today(), races or {}
    if not events:
        return {"fill": [], "plans": {}, "manual": []}
    first = max(to_date(events[0]["start_date_local"]), today)
    last = max(to_date(events[-1]["start_date_local"]), race)
    out = {"fill": [], "plans": {}, "manual": []}
    spans = {}
    for e in existing:
        d, tag = event_day(e), tag_of(e)
        if d is None or d < today or tag == plan_tag:
            continue
        if tag != MANUAL and not tag.startswith(FILL_PREFIX):
            span = spans.setdefault(tag, [d, d, []])
            span[0], span[1] = min(span[0], d), max(span[1], d)
            if first <= d <= last:
                span[2].append(e["external_id"])
        elif first <= d <= last:
            if tag.startswith(FILL_PREFIX):
                out["fill"].append(e["external_id"])
            elif not (is_race(e) and d == race):  # this plan's own race, added by hand: expected
                out["manual"].append((d, str(e.get("name") or "")))
    for tag, (lo, hi, ids) in spans.items():
        hi = max(hi, races.get(tag) or hi)
        ours = sum(1 for e in events if lo <= to_date(e["start_date_local"]) <= hi)
        if ids or ours:
            out["plans"][tag] = {"first": lo, "last": hi, "ids": sorted(ids), "ours": ours}
    out["fill"].sort()
    out["manual"].sort()
    return out


def event_day(e):
    """An Intervals event's date: start_date_local, else the date in its external_id (None if neither)."""
    raw = str(e.get("start_date_local") or (e.get("external_id") or "")[-10:])[:10]
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def resolve(p, plan_tag, choices, today=None):
    """The events to send and external_ids to delete, given the user's choice for each overlapping
    plan ({tag: "keep" | "replace"}). Raises PlanError if a choice is missing."""
    overlap = p.get("overlap") or {"fill": [], "plans": {}}
    missing = [t for t in overlap["plans"] if choices.get(t) not in ("keep", "replace")]
    if missing:
        raise PlanError(f"This plan overlaps {', '.join(missing)}: choose to keep it or replace it")
    events = [e for e in p["events"] if not any(
        choices[t] == "keep" and o["first"] <= to_date(e["start_date_local"]) <= o["last"]
        for t, o in overlap["plans"].items())]
    if not events:
        raise PlanError("Keeping the other plans leaves this plan nothing to push")
    deletions = stale_ids(p["existing_events"], events, plan_tag, today) + overlap["fill"]
    for t, o in overlap["plans"].items():
        if choices[t] == "replace":
            deletions += o["ids"]
    return events, deletions


def stale_fill_ids(existing, events, first, last, today=None):
    """external_ids of future filler in [first, last] that the new fill doesn't have (any fill tag:
    filler split by a plan pushed into it is planned again as a whole)."""
    today = today or date.today()
    keep = {e["external_id"] for e in events}
    return sorted(e["external_id"] for e in existing
                  if tag_of(e).startswith(FILL_PREFIX) and e["external_id"] not in keep
                  and max(first, today) <= (event_day(e) or first - timedelta(days=1)) <= last)


# ---------- talking to Intervals.icu ----------

class Intervals:
    def __init__(self, athlete_id, api_key):
        self.base = f"{API_BASE}/athlete/{athlete_id}"
        self.auth = ("API_KEY", api_key)

    def list_events(self, oldest, newest):
        resp = requests.get(f"{self.base}/events", auth=self.auth, timeout=30,
                            params={"oldest": oldest.isoformat(), "newest": newest.isoformat()})
        resp.raise_for_status()
        return resp.json()

    def wellness(self, oldest, newest):
        """Daily fitness (ctl), fatigue (atl) and ramp rate. Read-only."""
        resp = requests.get(f"{self.base}/wellness", auth=self.auth, timeout=30,
                            params={"oldest": oldest.isoformat(), "newest": newest.isoformat()})
        resp.raise_for_status()
        return resp.json()

    def run_settings(self):
        """Threshold pace (m/s) and pace zones (% of threshold) for runs. Read-only."""
        resp = requests.get(self.base, auth=self.auth, timeout=30)
        resp.raise_for_status()
        run = next(s for s in resp.json().get("sportSettings", []) if "Run" in (s.get("types") or []))
        return {"threshold_speed": run["threshold_pace"], "pace_zones": run["pace_zones"]}

    def upsert(self, events):
        resp = requests.post(f"{self.base}/events/bulk", params={"upsert": "true"},
                             auth=self.auth, json=events, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def delete(self, external_ids):
        resp = requests.put(f"{self.base}/events/bulk-delete", auth=self.auth, timeout=30,
                            json=[{"external_id": x} for x in external_ids])
        resp.raise_for_status()


def client_from_env():
    load_dotenv()
    athlete_id = os.getenv("INTERVALS_ATHLETE_ID")
    api_key = os.getenv("INTERVALS_API_KEY")
    if not athlete_id or not api_key:
        return None
    return Intervals(athlete_id, api_key)


def preview(config, library, layout, client, today=None, races=None):
    """Everything a push would do, without sending anything. Raises PlanError.

    client may be None (no .env): then Intervals isn't read and stale events can't be found.
    races: other plans' race dates by plan_tag, for the overlap check.
    """
    today = today or date.today()
    events = build_events(config, library, layout, today)
    out = {"events": events, "warnings": layout_warnings(config, library, layout),
           "existing": None, "found": None, "stale": [], "existing_events": [], "overlap": None}
    if client is not None:
        tag = str(config["plan_tag"]).strip()
        last = to_date(config["race_date"])
        existing = client.list_events(today - CLEANUP_WINDOW, last + CLEANUP_WINDOW)
        out["existing"] = len(existing)
        out["existing_events"] = existing
        out["found"] = sum(1 for e in existing if (e.get("external_id") or "").startswith(f"{tag}-"))
        out["stale"] = stale_ids(existing, events, tag, today)
        out["overlap"] = overlaps(existing, events, tag, last, races, today)
    return out


def record_push(wb, config, today=None):
    """Note on the plan's Plans row which tag and race it was pushed for, and when."""
    plans = wb["Plans"]
    col = {str(c.value or "").strip().lower(): c.column for c in plans[1]}
    if not {"plan_tag", "race_date", "pushed"} <= set(col):
        raise PlanError("Plans tab has no plan_tag/race_date/pushed columns: run setup_workbook.py")
    plan = str(config.get("plan") or "").strip()
    for r in range(2, last_used_row(plans) + 1):
        if str(plans.cell(r, 1).value or "").strip() == plan:
            plans.cell(r, col["plan_tag"]).value = str(config["plan_tag"]).strip()
            plans.cell(r, col["race_date"]).value = config["race_date"]
            plans.cell(r, col["race_date"]).number_format = "yyyy-mm-dd"
            plans.cell(r, col["pushed"]).value = datetime.combine(today or date.today(), datetime.min.time())
            plans.cell(r, col["pushed"]).number_format = "yyyy-mm-dd"
            return
    raise PlanError(f"plan {plan!r} is not on the Plans tab")


def other_races(sheets):
    """Race dates by plan_tag from the Plans tab."""
    out = {}
    for r in sheets.get("plans", []):
        if not blank(r.get("plan_tag")) and not blank(r.get("race_date")):
            out[str(r["plan_tag"]).strip()] = to_date(r["race_date"])
    return out


def send(client, events, stale):
    """Upsert the events and delete the stale ones. This writes to the live calendar."""
    client.upsert(events)
    if stale:
        client.delete(stale)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Push the Layout tab to Intervals.icu.")
    parser.add_argument("workbook")
    parser.add_argument("--dry-run", action="store_true", help="print events, send nothing")
    parser.add_argument("--overlap", choices=["keep", "replace"],
                        help="when another plan overlaps this one: keep it, or replace it with this plan")
    args = parser.parse_args(argv)

    client = client_from_env()
    if client is None and not args.dry_run:
        print("Set INTERVALS_ATHLETE_ID and INTERVALS_API_KEY in .env", file=sys.stderr)
        return 1
    try:
        _, config, library, sheets = load_workbook_tables(args.workbook)
        if "layout" not in sheets:
            raise PlanError("No Layout tab: run layout.py first")
        p = preview(config, library, sheets["layout"], client, races=other_races(sheets))
    except PlanError as e:
        print(f"Plan has problems:\n{e}", file=sys.stderr)
        return 1
    events = p["events"]

    for e in events:
        d = to_date(e["start_date_local"])
        print(f"{d}  {d.strftime('%a')}  {e['name']}")
    for d, msg in p["warnings"]:
        print(f"  WARNING {d}: {msg}")

    if client is None:
        print(f"\n{len(events)} events (dry run). No .env credentials, so stale-event check skipped.")
        return 0
    tag = str(config["plan_tag"]).strip()
    print(f"\nIntervals has {p['existing']} events in the window; {p['found']} belong to plan_tag {tag!r}.")
    overlap = p["overlap"]
    if overlap["fill"]:
        print(f"{len(overlap['fill'])} gap-filler workouts in this plan's dates will be replaced.")
    for t, o in overlap["plans"].items():
        print(f"Overlaps {t} ({o['first']} to {o['last']}): keep skips {o['ours']} of this plan's workouts, "
              f"replace deletes {len(o['ids'])} of {t}'s.")
    for d, name in overlap["manual"]:
        print(f"  also on {d}: {name} (added in Intervals, left alone)")
    try:
        events, stale = resolve(p, tag, {t: args.overlap for t in overlap["plans"]})
    except PlanError as e:
        if not args.dry_run:
            print(f"{e}: rerun with --overlap keep or --overlap replace", file=sys.stderr)
            return 1
        print(f"{e}: pass --overlap keep or --overlap replace to see the result")
        events, stale = p["events"], p["stale"] + overlap["fill"]

    if args.dry_run:
        print(f"{len(events)} events would be pushed; {len(stale)} events would be deleted:")
        for x in stale:
            print(f"  delete {x}")
        print("\nFirst event payload:")
        print(json.dumps(events[0], indent=2))
        return 0

    send(client, events, stale)
    print(f"\nPushed {len(events)} events to Intervals.icu.")
    if stale:
        print(f"Deleted {len(stale)} events: {', '.join(stale)}")
    if overlap["fill"]:
        print("Refill the gaps around this plan on the app's Fill gaps page.")
    try:
        wb = load_workbook_tables(args.workbook)[0]
        record_push(wb, config)
        save_workbook(wb, args.workbook)
    except PlanError as e:
        print(f"Pushed, but couldn't note it on the Plans tab: {e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
