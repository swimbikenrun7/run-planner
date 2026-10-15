"""Add what the importer needs to an existing plan_builder.xlsx, without touching anything else.

Usage:
    python setup_workbook.py plans/plan_builder.xlsx

Safe to run more than once: it only adds what's missing.
  - a Paces tab (the pace table, keyed by convention name)
  - Config: threshold_pace (you fill in the value)
  - Config: 'hills' and 'tuneup' added to hard_categories
Close the workbook in Excel first.
"""

import argparse
import sys

import openpyxl
from openpyxl.styles import Font

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
    return {str(ws.cell(r, 1).value).strip(): r for r in range(2, ws.max_row + 1)
            if ws.cell(r, 1).value is not None}


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
    if "threshold_pace" not in rows:
        r = cfg.max_row + 1
        cfg.cell(r, 1, "threshold_pace").font = ARIAL
        cfg.cell(r, 2, None).font = ARIAL
        changes.append("added Config threshold_pace (fill in, e.g. 7:30/mi)")

    if "hard_categories" in rows:
        cell = cfg.cell(rows["hard_categories"], 2)
        cats = [c.strip() for c in str(cell.value or "").split(",") if c.strip()]
        missing = [c for c in ("hills", "tuneup") if c not in cats]
        if missing:
            cell.value = ", ".join(cats + missing)
            changes.append(f"added {', '.join(missing)} to hard_categories")

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
        wb.save(args.workbook)
    except PermissionError:
        print("Could not save: close the workbook in Excel and run again.", file=sys.stderr)
        return 1
    for c in changes:
        print(f"  {c}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
