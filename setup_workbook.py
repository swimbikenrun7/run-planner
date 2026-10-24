"""Add what the importer needs to an existing plan_builder.xlsx, without touching anything else.

Usage:
    python setup_workbook.py plans/plan_builder.xlsx

Safe to run more than once: it only adds what's missing.
  - a Paces tab (the pace table, keyed by convention name)
  - Config: threshold_pace (you fill in the value)
  - Config: 'hills' and 'tuneup' added to hard_categories
  - a Week tab (your weekly structure), a Plans tab, and a plan column on Schedule
  - Config: plan, long_run_gap, allow_pre_long
Close the workbook in Excel first.
"""

import argparse
import sys

import openpyxl
from openpyxl.styles import Font

from planlib import DAYS, PlanError, last_used_row, read_table, save_workbook, to_date

# Daniels VDOT relationships, as % of threshold SPEED (Intervals.icu uses % of speed)
PACES = [
    ("RECOVERY", "Recovery jog between reps", "Z1 Pace"),
    ("WU", "Warmup / cooldown", "Z2 Pace"),
    ("E", "Easy (Daniels E)", "80% Pace"),
    ("LONG", "Long run (Daniels: E pace)", "80% Pace"),
    ("STEADY", "Steady: not a Daniels pace; a bit slower than marathon pace", "90% Pace"),
    ("M", "Marathon pace (Daniels M)", "94% Pace"),
    ("HM", "Half marathon pace", "98% Pace"),
    ("T", "Threshold / tempo, ~1-hour race pace (Daniels T)", "100% Pace"),
    ("10K", "10K race pace", "103% Pace"),
    ("5K", "5K race pace", "107% Pace"),
    ("I", "Interval, ~3K pace (Daniels I)", "110% Pace"),
    ("R", "Repetition, ~mile pace (Daniels R)", "118% Pace"),
]

ARIAL = Font(name="Arial")
ARIAL_BOLD = Font(name="Arial", bold=True)


def config_rows(ws):
    return {str(ws.cell(r, 1).value).strip(): r for r in range(2, last_used_row(ws) + 1)
            if ws.cell(r, 1).value is not None}


def add_config(cfg, key, value, changes, note=""):
    if key not in config_rows(cfg):
        r = last_used_row(cfg) + 1
        cfg.cell(r, 1, key).font = ARIAL
        cfg.cell(r, 2, value).font = ARIAL
        changes.append(f"added Config {key}" + (f" ({note})" if note else ""))


def styled_sheet(wb, title, headers, rows, widths):
    ws = wb.create_sheet(title)
    ws.append(headers)
    for row in rows:
        ws.append(row)
    for row in ws.iter_rows():
        for c in row:
            c.font = ARIAL_BOLD if c.row == 1 else ARIAL
    for col, w in widths.items():
        ws.column_dimensions[col].width = w
    return ws


def setup(wb):
    changes = []

    if "Paces" not in wb.sheetnames:
        ws = wb.create_sheet("Paces", index=wb.sheetnames.index("Library") + 1)
        ws.append(["key", "description", "target"])
        for row in PACES:
            ws.append(list(row))
        for row in ws.iter_rows():
            for c in row:
                c.font = ARIAL_BOLD if c.row == 1 else ARIAL
        ws.column_dimensions["A"].width = 11
        ws.column_dimensions["B"].width = 58
        ws.column_dimensions["C"].width = 11
        changes.append("added Paces tab")

    cfg = wb["Config"]
    rows = config_rows(cfg)
    add_config(cfg, "threshold_pace", None, changes, "fill in, e.g. 7:30/mi")

    if "hard_categories" in rows:
        cell = cfg.cell(rows["hard_categories"], 2)
        cats = [c.strip() for c in str(cell.value or "").split(",") if c.strip()]
        missing = [c for c in ("hills", "tuneup") if c not in cats]
        if missing:
            cell.value = ", ".join(cats + missing)
            changes.append(f"added {', '.join(missing)} to hard_categories")

    config = {str(cfg.cell(r, 1).value).strip(): cfg.cell(r, 2).value
              for r in range(2, last_used_row(cfg) + 1) if cfg.cell(r, 1).value}

    if "Week" not in wb.sheetnames:
        long_day = str(config.get("long_run") or "sun").strip().lower()[:3]
        roles = {d: "easy" for d in DAYS}
        roles.update({"tue": "quality", "thu": "quality", long_day: "long"})
        styled_sheet(wb, "Week", ["day", "role", "workout_id"],
                     [[d.title(), roles[d], None] for d in DAYS], {"A": 6, "B": 10, "C": 16})
        changes.append(f"added Week tab (long run {long_day.title()}, quality Tue/Thu): edit to fit your week")

    sched = wb["Schedule"]
    headers = [str(c.value or "").strip().lower() for c in sched[1]]
    if "plan" not in headers:
        sched.insert_cols(1)
        sched.cell(1, 1, "plan").font = ARIAL_BOLD
        for r in range(2, last_used_row(sched) + 1):
            if any(c.value not in (None, "") for c in sched[r][1:]):
                sched.cell(r, 1, "legacy").font = ARIAL
        changes.append("added plan column to Schedule (existing rows named 'legacy')")

    if "Plans" not in wb.sheetnames:
        has_rows = any(str(r.get("plan") or "").strip() == "legacy" for r in read_table(sched))
        week_end = config.get("source_week_end")
        if not week_end and config.get("race_date"):
            week_end = DAYS[to_date(config["race_date"]).weekday()]
        styled_sheet(wb, "Plans", ["plan", "source_week_end", "notes"],
                     [["legacy", week_end, "rows that were on Schedule before plans had names"]]
                     if has_rows else [], {"A": 26, "B": 16, "C": 50})
        changes.append("added Plans tab")
        add_config(cfg, "plan", "legacy" if has_rows else None, changes, "the plan to lay out")

    add_config(cfg, "plan", None, changes, "the plan to lay out")
    add_config(cfg, "taper_days", 2, changes)
    add_config(cfg, "long_run_gap", 5, changes, "no long run within this many days of the race")
    add_config(cfg, "allow_pre_long", "no", changes)
    return changes


def main(argv=None):
    parser = argparse.ArgumentParser(description="Add importer setup to plan_builder.xlsx.")
    parser.add_argument("workbook")
    args = parser.parse_args(argv)

    wb = openpyxl.load_workbook(args.workbook)
    changes = setup(wb)
    if not changes:
        print("Nothing to do: workbook already set up.")
        return 0
    try:
        save_workbook(wb, args.workbook)
    except PlanError as e:
        print(e, file=sys.stderr)
        return 1
    for c in changes:
        print(f"  {c}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
