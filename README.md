# run-planner

Builds a running plan in `plans/plan_builder.xlsx` and pushes it to the Intervals.icu
calendar, which syncs to Garmin Connect.

## Setup (Windows PowerShell)
    python -m venv .venv
    .venv\Scripts\Activate.ps1
    pip install -r requirements.txt
    copy .env.example .env   # then fill in your API key and athlete ID

## Use
Close the workbook in Excel first (Excel locks open files).

    python layout.py plans/plan_builder.xlsx           # lay out Config's plan around your Week
    python layout.py plans/plan_builder.xlsx --option N   # if it suggested options: pick one
    python push.py plans/plan_builder.xlsx --dry-run   # check what will be sent/deleted
    python push.py plans/plan_builder.xlsx             # send
    python -m pytest                                   # run tests

## Workbook
- **Config**: `plan` (which plan to lay out), `race_date`, `plan_tag` (Intervals ID prefix),
  `taper_days`, `long_run_gap` (no long run within this many days of the race),
  `allow_pre_long`, `hard_categories`, `threshold_pace`, optional `long_run_days`
  (days the long run may move to when suggesting; default `sat, sun`).
- **Week**: your standing week. Each day's role is `long`, `quality`, `fixed` (always this
  `workout_id`, e.g. a group run) or `easy`.
- **Library**: workouts. **Paces**: the pace table the importer uses.
- **Plans** / **Schedule**: every imported plan, by name. Schedule rows are plan / week / day /
  workout_id / note in the plan's own week convention (Plans: `source_week_end`).
- **Layout**: generated. Grey = before today (never pushed), blue = moved, yellow = flagged,
  rows with no date = sessions that couldn't be placed.

## How layout places a plan
Race on `race_date`, nothing hard in the taper. Long runs and tune-up races on the long day
(not within `long_run_gap` of the race). Other hard sessions on quality days in plan order,
or another legal day that week if the quality days run out. Never two hard days in a row,
except the plan's pre-long-run session the day before the long run when `allow_pre_long` is yes.
If hard sessions don't fit, layout writes nothing and lists options instead: your week as it
is, plus the best change that keeps your long day (and fixed days, if possible) and the best
that moves the long day. `--option N` saves that week to the Week tab and lays out the plan.

## Importing a plan
One-time setup (adds the Paces tab and Config keys; safe to rerun):

    python setup_workbook.py plans/plan_builder.xlsx

Then fill in `threshold_pace` in Config (e.g. `7:30/mi`). For each plan:

    python import_plan.py prompt plans/plan_builder.xlsx
    # paste imports/prompt.md into Claude with the plan; save the CSV it returns
    python import_plan.py stage plans/plan_builder.xlsx imports/<plan>.csv
    # review the Import tab: green = already in Library, yellow = similar (fill 'action')
    python import_plan.py apply plans/plan_builder.xlsx --plan <name> --week-end sun
    # saves the plan under <name> (other plans untouched) and selects it in Config;
    # check race_date / plan_tag, then layout.py and push.py

To add a plan's workouts to Library without saving the plan itself:

    python import_plan.py apply plans/plan_builder.xlsx --library-only

`action` on the Import tab: `add` keeps the workout as a new Library entry (renamed with
`-2` if the ID is taken), or type an existing workout_id to use that one instead.

Pace targets in the CSV are keys like `{T}` or `{T+20s}` from the Paces tab; the importer
turns them into percentages. Offsets are seconds of pace per threshold_pace unit.
Warmups, cooldowns, single continuous runs and untimed recoveries use `Press lap`
(the importer rejects workouts that don't).
