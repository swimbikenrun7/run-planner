"""Arrange the Schedule tab onto real dates and write the result to a Layout tab.

Usage:
    python layout.py plans/plan_builder.xlsx

Schedule holds a source plan in its own week convention (Config: source_week_end).
This script maps it onto 7-day blocks ending on race_date and rearranges key sessions so:
  - the race is on race_date and the long run is on the long_run day
  - no two hard days are back-to-back (including across weeks)
  - no hard day falls within taper_days of the race
  - key sessions keep their source order and move as little as possible
Easy runs and rest days fill the remaining days in their source order.
Close the workbook in Excel before running: Excel locks open files.
"""

import argparse
import sys
from datetime import timedelta
from itertools import combinations

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


def build_layout(config, library, schedule):
    """Return a list of Layout rows (dicts), one per day from week 1 to race day."""
    for key in ("race_date", "plan_tag"):
        if blank(config.get(key)):
            raise PlanError(f"Config is missing {key}")
    race_date = to_date(config["race_date"])
    race_idx = race_date.weekday()
    src_end = race_idx if blank(config.get("source_week_end")) else day_index(config["source_week_end"])
    long_idx = None if blank(config.get("long_run")) else day_index(config["long_run"])
    hard = hard_categories(config)
    taper = taper_days(config)

    # --- read the source plan into weeks[week][offset], offset 0 = last day of the week
    errors, weeks = [], {}
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
        offset = (src_end - src_day) % 7
        if offset in weeks.setdefault(week, {}):
            errors.append(f"Schedule row {i}: week {week} {row['day']} appears twice")
            continue
        weeks[week][offset] = {
            "wid": wid,
            "category": category_of(library, wid) if wid else "rest",
            "source_day": DAYS[src_day].title(),
            "note": row.get("note"),
            "naive": offset,
        }
    if not weeks and not errors:
        errors.append("Schedule is empty")
    if errors:
        raise PlanError("\n".join(errors))

    first_week, last_week = min(weeks), max(weeks)

    def block_end(week):
        return race_date - timedelta(weeks=last_week - week)

    def date_of(week, offset):
        return block_end(week) - timedelta(days=offset)

    long_off = None if long_idx is None else (race_idx - long_idx) % 7
    taper_window = {race_date - timedelta(days=k) for k in range(1, taper + 1)}

    rows, hard_dates = [], set()
    for week in range(first_week, last_week + 1):
        src = weeks.get(week, {})
        flags = {}
        # every day of the block gets an item; missing source days are rest
        items = {off: src.get(off) or {"wid": None, "category": "rest", "source_day": DAYS[(src_end - off) % 7].title(),
                                       "note": None, "naive": off}
                 for off in range(7)}
        chrono = list(range(6, -1, -1))  # offsets in date order
        keys = [items[o] for o in chrono if items[o]["category"] in hard]

        # pin the race and the long run
        pinned, free = {}, []
        for item in keys:
            if item["category"] == "race" and week == last_week and 0 not in pinned:
                pinned[0] = item
            elif item["category"] == "long" and long_off is not None and long_off not in pinned:
                pinned[long_off] = item
            else:
                free.append(item)
        if long_off == 0 and any(i["category"] == "long" for i in free):
            flags[0] = "long run day is race day"

        # neighbours outside this week that spacing must respect
        neighbour = set(hard_dates)
        nxt = weeks.get(week + 1, {})
        if long_off is not None and any(i["category"] == "long" for i in nxt.values() if i):
            neighbour.add(date_of(week + 1, long_off))

        avail = [o for o in chrono if o not in pinned]
        best = None
        for choice in combinations(avail, len(free)):  # preserves source order
            dates = {date_of(week, o) for o in list(pinned) + list(choice)}
            all_hard = sorted(dates | neighbour)
            adjacent = sum(1 for a, b in zip(all_hard, all_hard[1:]) if (b - a).days == 1)
            in_taper = sum(1 for d in dates if d in taper_window and d != race_date)
            displacement = sum(abs(o - item["naive"]) for o, item in zip(choice, free))
            gaps = [(b - a).days for a, b in zip(all_hard, all_hard[1:])]
            score = (adjacent + in_taper, displacement, -min(gaps, default=7))
            if best is None or score < best[0]:
                best = (score, choice)

        placed = dict(pinned)
        placed.update(zip(best[1], free))
        hard_dates |= {date_of(week, o) for o in placed}

        # easy runs and rest days fill what's left, in source order
        fillers = [items[o] for o in chrono if items[o]["category"] not in hard]
        open_slots = [o for o in chrono if o not in placed]
        placed.update(zip(open_slots, fillers))

        for off in chrono:
            item = placed[off]
            d = date_of(week, off)
            wid = item["wid"]
            rows.append({
                "date": d,
                "day": d.strftime("%a"),
                "week": week,
                "workout_id": wid,
                "category": item["category"],
                "name": str(library[wid].get("name") or wid) if wid else "Rest",
                "source_day": item["source_day"],
                "moved": "yes" if off != item["naive"] else "",
                "flag": flags.get(off, ""),
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
