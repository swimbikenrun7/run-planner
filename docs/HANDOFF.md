# Handoff: status and open items

Written at the move from claude.ai chat to Claude Code (October 2026). Update it as things
change; delete items once they're done.

## Where things stand

Built and tested (33 tests: `test_push.py`, `test_layout.py`, `test_import.py`):

- **Push** to Intervals.icu, verified end to end on the user's watch. Section headers render
  correctly; stale-event cleanup verified (Intervals returns `external_id` when listing).
- **Importer** (prompt → stage → apply), verified with the Brooks 10K Advanced plan (converted
  by hand as `imports/brooks-10k-advanced.csv`) and the Hal Higdon Half Marathon Advanced plan
  (converted by a fresh Claude chat using the prompt). Both plans' workouts are in the user's
  Library. Higdon's conversion was judged correct, including its (3/1) long runs and tune-up races.
- **Layout engine** around the Week template, with structural suggestions. Run against the
  user's workbook with the Higdon plan and his week (long Sun, quality Tue/Fri, fixed Thu group
  run), it offered: keep the week (7 HM-pace runs unplaced), skip the Thursday group run for a
  quality day and allow the pre-long pace run (0 unplaced), or move the long run to Saturday and
  keep the group run (0 unplaced).

Live on the user's calendar: the turkey trot 10K plan (Thu Nov 26, 2026), plan_tag
`turkey-trot-10k-2026`, pushed with the earlier layout engine.

## In progress when handed off: confirm with the user first

The user had just received the named-plans / Week-template version and these migration steps
for his master workbook. Ask which are done before assuming the workbook's shape:

1. `python setup_workbook.py plans/plan_builder.xlsx` (adds Week, Plans, Schedule `plan` column,
   Config keys; existing Schedule rows become plan `legacy`).
2. Rename `legacy` to `turkey-trot-10k` on Schedule and Plans; set its `source_week_end` to `thu`.
3. Add `GROUP-4MI` (easy, `- Press lap 80% Pace 4mi`) to Library; set the Week tab to Sun long,
   Tue quality, Thu fixed GROUP-4MI, Fri quality, rest easy.
4. Remove the now-unused Config rows `long_run` and `source_week_end`.
5. Re-import Higdon as a named plan (`stage` then `apply --plan higdon-half-advanced --week-end sun`).
6. Run layout, choose an option, review, dry-run push. Target race: Sun May 2, 2027,
   plan_tag `pig-half-2027`.

The user also mentioned moving his own long run to Sunday with Tue/Fri as quality days; that's
what the Week tab above encodes.

## Unverified or open

- **Hill steps with no pace target** (`- Uphill hard 90s`): not yet seen on the watch. Push one
  hill workout and have the user check it before relying on the format.
- **The user's older Library entries use pre-convention paces** (tempo 95%, threshold 105%,
  10K-pace intervals 100%, long 85%; see DECISIONS). Whether to update them is his call.
- **Brooks conversion ambiguities** chosen by hand: "hard" reps as I/R, "moderate" as M,
  "equal rest" on 12x600 as 2 min, "6x800 then 250 faster" as a 250 after every 800, ladder
  paces as T-15s to T-30s then I and R. A fresh round-trip conversion of the Brooks PDF may
  disagree; the user decides which reading is right.
- **The prompt hasn't been tested on the user's own Excel plans** (dated calendars with mileage
  and short notes, e.g. `10k_Training.xlsx`). They're a different shape from PDF grids.
- The user's master Library has a block of blank rows (an old append bug, now fixed). Harmless;
  he can delete them in Excel.
- README lost its short "push behaviour" section in the last rewrite; CLAUDE.md covers it, but
  the user-facing README should say it again.

## Backlog (the user sets priorities; don't start these unprompted)

- **Triathlon plans** (the user has `Tri_Training_Sched.xlsx`). Needs a sport per workout
  (Intervals takes Swim/Ride/Run), more than one workout per day (touches Schedule, Layout,
  and the one-hard-day-per-date assumptions in layout), and cross-sport spacing rules.
- **Automate the conversion step** with a direct Claude API call instead of copy-paste through
  a chat. Wait until the prompt is reliable across plan styles.
- **More suggestion kinds** in layout, e.g. fold HM-pace work into the long run as a fast
  finish (the user considered this for Higdon).
- The goal race isn't pushed; Intervals has race event categories that could be used.
