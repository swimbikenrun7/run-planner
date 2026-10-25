# run-planner

Turns running plans into structured workouts on the Intervals.icu calendar, which syncs them to
Garmin Connect and the watch. `plans/plan_builder.xlsx` holds everything (workouts, plans, your
week); a small web app and a few scripts do the work.

## Setup (Linux, bash)
    cd ~/Projects/run-planner
    python -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    cp env.example .env        # then fill in INTERVALS_API_KEY and INTERVALS_ATHLETE_ID

## The app
    source .venv/bin/activate
    streamlit run app.py       # http://localhost:8501

- **Plan**: choose a plan, race date and your week; lay it out, check the calendar, check
  against Intervals, push.
- **Import a plan**: copy the prompt into a Claude chat with the plan, paste the CSV back, review,
  save.
- **Calendar**: everything on Intervals by plan, with the gaps between plans. Read-only.
- **Fill gaps**: training between plans from your rules, with projected fitness and form; push.

The app only listens on this machine. To open it from your other devices on your tailnet:

    tailscale serve --bg 8501

Point it at a copy of the workbook with `RUN_PLANNER_WORKBOOK=plans/scratch.xlsx streamlit run app.py`.

**Close the workbook in LibreOffice Calc before saving from the app or a script.** Calc doesn't lock
the file, so a save from Calc afterwards would overwrite the change; the app and scripts refuse to
save while Calc's `.~lock.plan_builder.xlsx#` file is there.

## What pushing does
- Workouts are sent as Intervals events with `external_id` `<plan_tag>-<date>`, so pushing again
  updates them in place.
- Future events of the same plan_tag that the plan no longer has are deleted. Past events are
  never deleted.
- Gap filler (tagged `fill-<first day>`) in the plan's dates is replaced; refill the gaps around
  the plan afterwards on the Fill gaps page.
- If another plan overlaps, you choose: keep it (this plan skips those dates) or replace it.
- Events you add by hand in Intervals, including races, are never deleted. The goal race isn't
  pushed: add it in Intervals.
- Pace targets are % of your threshold pace in Intervals, so updating threshold there updates the
  targets and the load estimates.
- Nothing is sent until you confirm. `--dry-run` (or the app's Check button) only reads.

## Scripts (the same steps without the app)
    python setup_workbook.py plans/plan_builder.xlsx        # once, and after updates: adds tabs/columns (safe to rerun)
    python import_plan.py prompt plans/plan_builder.xlsx    # writes imports/prompt.md for a Claude chat
    python import_plan.py stage  plans/plan_builder.xlsx imports/<plan>.csv
    python import_plan.py apply  plans/plan_builder.xlsx --plan <name> --week-end sun   # or --library-only
    python layout.py plans/plan_builder.xlsx [--option N]
    python push.py   plans/plan_builder.xlsx --dry-run [--overlap keep|replace]
    python push.py   plans/plan_builder.xlsx
    python -m pytest

## Workbook
- **Config**: `plan` (which plan to lay out), `race_date`, `plan_tag` (Intervals ID prefix),
  `taper_days`, `long_run_gap` (no long run within this many days of the race),
  `allow_pre_long`, `hard_categories`, `threshold_pace`, optional `long_run_days`; and the gap
  filler's rules (edited on the Fill gaps page).
- **Week**: your standing week. Each day's role is `long`, `quality`, `fixed` (always this
  `workout_id`, e.g. a group run) or `easy`.
- **Library**: workouts. Entries are never overwritten. **Paces**: the pace table the importer uses.
- **Plans** / **Schedule**: every imported plan, by name. Plans also holds each plan's rest-day
  fill, race distance, and the tag and race it was last pushed for.
- **Layout**: generated. Grey = before today (never pushed), blue = moved, yellow = flagged,
  rows with no date = sessions that couldn't be placed.
- **Fill**: each pushed gap's workouts, with the fitness, fatigue and form forecast when it was
  pushed (to compare with what actually happens).

## How layout places a plan
Race on `race_date`, nothing hard in the taper. Long runs and tune-up races on the long day
(not within `long_run_gap` of the race). Other hard sessions on quality days in plan order,
or another legal day that week if the quality days run out. Never two hard days in a row,
except the plan's pre-long-run session the day before the long run when `allow_pre_long` is yes.
Rest days become the plan's easy fill run, with the shortest run the day before the race.
If hard sessions don't fit, layout writes nothing and lists options instead: your week as it
is, plus the best change that keeps your long day (and fixed days, if possible) and the best
that moves the long day.

## Importing a plan
The app's Import page does this; the scripts work the same way. `action` on the review: `add`
keeps the workout as a new Library entry (renamed with `-2` if the ID is taken), or type an
existing workout_id to use that one instead.

Pace targets in the CSV are keys like `{T}` or `{T+20s}` from the Paces tab; the importer
turns them into percentages. Offsets are seconds of pace per threshold_pace unit.
Warmups, cooldowns, single continuous runs and untimed recoveries use `Press lap`
(the importer rejects workouts that don't).
