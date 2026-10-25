"""Push the Layout tab of plan_builder.xlsx to the Intervals.icu calendar.

Usage:
    python layout.py plans/plan_builder.xlsx           # first: arrange Schedule into Layout
    python push.py plans/plan_builder.xlsx --dry-run   # print events, send nothing
    python push.py plans/plan_builder.xlsx             # push to Intervals.icu

Reads credentials from .env (INTERVALS_API_KEY, INTERVALS_ATHLETE_ID).
Events are upserted on external_id = "<plan_tag>-<date>", so re-pushing updates in place.
After upserting, any event from this plan_tag whose date no longer has a workout is deleted.
"""

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta

import requests
from dotenv import load_dotenv

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


def preview(config, library, layout, client, today=None):
    """Everything a push would do, without sending anything. Raises PlanError.

    client may be None (no .env): then Intervals isn't read and stale events can't be found.
    """
    today = today or date.today()
    events = build_events(config, library, layout, today)
    out = {"events": events, "warnings": layout_warnings(config, library, layout),
           "existing": None, "found": None, "stale": []}
    if client is not None:
        tag = str(config["plan_tag"]).strip()
        last = to_date(config["race_date"])
        existing = client.list_events(today - CLEANUP_WINDOW, last + CLEANUP_WINDOW)
        out["existing"] = len(existing)
        out["found"] = sum(1 for e in existing if (e.get("external_id") or "").startswith(f"{tag}-"))
        out["stale"] = stale_ids(existing, events, tag, today)
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


def send(client, events, stale):
    """Upsert the events and delete the stale ones. This writes to the live calendar."""
    client.upsert(events)
    if stale:
        client.delete(stale)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Push the Layout tab to Intervals.icu.")
    parser.add_argument("workbook")
    parser.add_argument("--dry-run", action="store_true", help="print events, send nothing")
    args = parser.parse_args(argv)

    client = client_from_env()
    if client is None and not args.dry_run:
        print("Set INTERVALS_ATHLETE_ID and INTERVALS_API_KEY in .env", file=sys.stderr)
        return 1
    try:
        _, config, library, sheets = load_workbook_tables(args.workbook)
        if "layout" not in sheets:
            raise PlanError("No Layout tab: run layout.py first")
        p = preview(config, library, sheets["layout"], client)
    except PlanError as e:
        print(f"Plan has problems:\n{e}", file=sys.stderr)
        return 1
    events, stale = p["events"], p["stale"]

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

    if args.dry_run:
        print(f"{len(events)} events would be pushed; {len(stale)} stale events would be deleted:")
        for x in stale:
            print(f"  delete {x}")
        print("\nFirst event payload:")
        print(json.dumps(events[0], indent=2))
        return 0

    send(client, events, stale)
    print(f"\nPushed {len(events)} events to Intervals.icu.")
    if stale:
        print(f"Deleted {len(stale)} stale events: {', '.join(stale)}")
    try:
        wb = load_workbook_tables(args.workbook)[0]
        record_push(wb, config)
        save_workbook(wb, args.workbook)
    except PlanError as e:
        print(f"Pushed, but couldn't note it on the Plans tab: {e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
