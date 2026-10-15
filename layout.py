"""Arrange the Schedule tab onto real dates and write the result to a Layout tab.

Usage:
    python layout.py plans/plan_builder.xlsx

Schedule holds a source plan in its own week convention (Config: source_week_end).
This script maps it onto 7-day blocks ending on race_date, then places it backward from
race day (see build_layout): taper first, then long runs, then other hard sessions,
each sliding earlier only as far as the rules require. Easy runs and rest days fill in.
Close the workbook in Excel before running: Excel locks open files.
"""

import argparse
import sys
from datetime import timedelta

from openpyxl.styles import Font, PatternFill

from planlib import (
    DAYS,
    PlanError,
    blank,
    category_of,
    day_index,
    hard_categories,
    load_workbook_tables,
    rule_violations,
    taper_days,
    to_date,
)

LAYOUT_SHEET = "Layout"
LAYOUT_HEADERS = ["date", "day", "week", "workout_id", "category", "name",
                  "source_day", "moved", "flag", "note"]


def read_schedule(config, library, schedule):
    """Turn Schedule rows into items with a naive date (same position relative to week end)."""
    race_date = to_date(config["race_date"])
    src_end = race_date.weekday() if blank(config.get("source_week_end")) else day_index(config["source_week_end"])

    errors, cells = [], {}
    for i, row in enumerate(schedule, start=2):
        try:
            week = int(row["week"])
            src_day = day_index(row["day"])
        except (TypeError, ValueError, PlanError) as e:
            errors.append(f"Schedule row {i}: bad week/day ({e})")
            continue
        wid = None if blank(row.get("workout_id")) else str(row["workout_id"]).strip()
        if wid is not None and wid not in library:
            errors.append(f"Schedule row {i}: workout_id {wid!r} not in Library")
            continue
        offset = (src_end - src_day) % 7  # 0 = last day of the source week
        if (week, offset) in cells:
            errors.append(f"Schedule row {i}: week {week} {row['day']} appears twice")
            continue
        cells[(week, offset)] = (wid, DAYS[src_day].title(), row.get("note"))
    if not cells and not errors:
        errors.append("Schedule is empty")
    if errors:
        raise PlanError("\n".join(errors))

    first_week = min(w for w, _ in cells)
    last_week = max(w for w, _ in cells)
    items = []
    for week in range(first_week, last_week + 1):
        for offset in range(6, -1, -1):
            wid, src_day, note = cells.get((week, offset), (None, DAYS[(src_end - offset) % 7].title(), None))
            items.append({
                "wid": wid,
                "category": category_of(library, wid) if wid else "rest",
                "source_day": src_day,
                "note": note,
                "naive": race_date - timedelta(weeks=last_week - week, days=offset),
            })
    return items, last_week


def build_layout(config, library, schedule):
    """Place the plan backward from race day. Returns one Layout row per day.

    Order of work, each step respecting everything placed before it:
      1. the race on race_date, with taper_days of no hard sessions before it
      2. long runs on the long_run weekday of their week (or earlier if that day is taken)
      3. other hard sessions, latest first, each on the latest date that is on or before
         its source date, before the next session in the plan, and not next to any
         placed hard day. A session that doesn't fit slides earlier, and pushes the
         sessions before it earlier too. If that runs off the start of the plan, the
         sessions at the start get pushed later instead, only as far as needed.
      4. easy runs and rest days stay on their source date when it's free; the ones
         displaced fill the remaining days in their source order.
    """
    for key in ("race_date", "plan_tag"):
        if blank(config.get(key)):
            raise PlanError(f"Config is missing {key}")
    race_date = to_date(config["race_date"])
    long_idx = None if blank(config.get("long_run")) else day_index(config["long_run"])
    hard = hard_categories(config)
    taper = taper_days(config)
    items, last_week = read_schedule(config, library, schedule)
    plan_start = items[0]["naive"]

    occupied = {}  # date -> item, hard sessions only
    flags = {}

    one = timedelta(days=1)
    last_hard_day = race_date - timedelta(days=taper + 1)

    def fits(d):
        return (plan_start <= d <= last_hard_day and d not in occupied
                and d - one not in occupied and d + one not in occupied)

    def latest(start, ok=lambda d: True):
        """Latest date on or before start that fits, or None if it would leave the plan."""
        d = start
        while d >= plan_start:
            if fits(d) and ok(d):
                return d
            d -= one
        return None

    def earliest(start, ok=lambda d: True):
        """Earliest date on or after start that fits, or None if there's no room before the taper."""
        d = max(start, plan_start)
        while d <= last_hard_day:
            if fits(d) and ok(d):
                return d
            d += one
        return None

    def squeeze(item):
        """No legal day left: put it on the latest free day before the taper (or, failing
        that, inside it) and flag it."""
        candidates = [plan_start + timedelta(days=k) for k in range((race_date - plan_start).days)]
        before = [d for d in candidates if d <= last_hard_day]
        after = [d for d in candidates if d > last_hard_day]
        free = [d for d in before[::-1] + after if d not in occupied]
        flags[id(item)] = "no legal day left: plan has too many hard sessions"
        return free[0]

    by_naive_desc = sorted(items, key=lambda i: i["naive"], reverse=True)
    races = [i for i in by_naive_desc if i["category"] == "race"]
    longs = [i for i in by_naive_desc if i["category"] == "long" and long_idx is not None]
    others = [i for i in by_naive_desc if i["category"] in hard and i not in races and i not in longs]

    # 1. race (extra race rows are treated like any other hard session)
    for n, item in enumerate(races):
        if n == 0:
            occupied[race_date] = item
        else:
            others.append(item)
            flags[id(item)] = "more than one race in Schedule"
    others.sort(key=lambda i: i["naive"], reverse=True)

    def target(item):
        """Where a session wants to be: its source date, or for a long run, the
        long-run weekday in the same week block."""
        if item["category"] != "long" or long_idx is None:
            return item["naive"]
        block_end = race_date - timedelta(weeks=(race_date - item["naive"]).days // 7)
        return block_end - timedelta(days=(race_date.weekday() - long_idx) % 7)

    def place(group, ok):
        """Backward pass, then a forward pass that only matters if the backward pass ran out of plan.

        Backward: latest first, each on the latest legal day on or before both its source date
        and the next session's day, so a session that doesn't fit pushes earlier ones earlier.
        Forward: earliest first, each kept on its backward day unless something before it was
        pushed later (which only happens when sessions ran off the start of the plan).
        """
        backward, bound = {}, last_hard_day
        for item in group:  # latest first
            d = latest(min(target(item), bound), ok)
            backward[id(item)] = d if d is not None else plan_start
            if d is not None:
                occupied[d] = item
                bound = d - one
            else:
                bound = plan_start - one
        for d in [d for d, i in occupied.items() if i in group]:
            del occupied[d]
        prev = plan_start - one
        for item in reversed(group):  # earliest first
            d = earliest(max(backward[id(item)], prev + one), ok)
            if d is None:
                d = squeeze(item)
            occupied[d] = item
            prev = d

    # 2. long runs on the long-run weekday, then 3. everything else that's hard
    place(longs, lambda d: d.weekday() == long_idx)
    place(others, lambda d: True)

    # 4. easy runs and rest days
    days = [plan_start + timedelta(days=k) for k in range((race_date - plan_start).days + 1)]
    placed = dict(occupied)
    displaced = []
    for item in (i for i in items if i["category"] not in hard):
        if item["naive"] not in placed:
            placed[item["naive"]] = item
        else:
            displaced.append(item)
    open_days = [d for d in days if d not in placed]
    for d, item in zip(open_days, displaced):
        placed[d] = item
    for d in open_days[len(displaced):]:
        placed[d] = {"wid": None, "category": "rest", "source_day": "", "note": None, "naive": d}

    rows = []
    for d in days:
        item = placed[d]
        wid = item["wid"]
        flag = flags.get(id(item), "")
        rows.append({
            "date": d,
            "day": d.strftime("%a"),
            "week": last_week - (race_date - d).days // 7,
            "workout_id": wid,
            "category": item["category"],
            "name": str(library[wid].get("name") or wid) if wid else "Rest",
            "source_day": item["source_day"],
            "moved": "yes" if wid and d != item["naive"] else "",
            "flag": flag,
            "note": item["note"],
        })

    # final check across the whole plan
    by_date = {r["date"]: r for r in rows}
    for d, msg in rule_violations([(r["date"], r["category"]) for r in rows], race_date, hard, taper):
        r = by_date[d]
        r["flag"] = "; ".join(filter(None, [r["flag"], msg]))
    return rows


def write_layout(wb, rows):
    if LAYOUT_SHEET in wb.sheetnames:
        del wb[LAYOUT_SHEET]
    ws = wb.create_sheet(LAYOUT_SHEET)
    ws.append(LAYOUT_HEADERS)
    for r in rows:
        ws.append([r[h] for h in LAYOUT_HEADERS])
    flag_fill = PatternFill("solid", fgColor="FFF2CC")
    moved_fill = PatternFill("solid", fgColor="DDEBF7")
    for row in ws.iter_rows():
        for c in row:
            c.font = Font(name="Arial", bold=c.row == 1)
    for i, r in enumerate(rows, start=2):
        ws.cell(i, 1).number_format = "yyyy-mm-dd"
        if r["flag"]:
            for c in ws[i]:
                c.fill = flag_fill
        elif r["moved"]:
            for c in ws[i]:
                c.fill = moved_fill
    widths = {"A": 12, "B": 6, "C": 6, "D": 16, "E": 11, "F": 20, "G": 11, "H": 7, "I": 40, "J": 20}
    for col, w in widths.items():
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "A2"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Arrange Schedule onto dates in a Layout tab.")
    parser.add_argument("workbook")
    args = parser.parse_args(argv)

    try:
        wb, config, library, sheets = load_workbook_tables(args.workbook)
        rows = build_layout(config, library, sheets["schedule"])
    except PlanError as e:
        print(f"Plan has problems:\n{e}", file=sys.stderr)
        return 1

    write_layout(wb, rows)
    try:
        wb.save(args.workbook)
    except PermissionError:
        print("Could not save: close the workbook in Excel and run again.", file=sys.stderr)
        return 1

    hard = hard_categories(config)
    moved = [r for r in rows if r["moved"] and r["category"] in hard]
    flagged = [r for r in rows if r["flag"]]
    print(f"Layout written: {len(rows)} days, {len(moved)} key sessions moved, {len(flagged)} flagged.")
    for r in moved:
        print(f"  moved   {r['date']} {r['day']}  {r['name']} (source {r['source_day']})")
    for r in flagged:
        print(f"  FLAG    {r['date']} {r['day']}  {r['name']}: {r['flag']}")
    print("Review the Layout tab, then run push.py.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
