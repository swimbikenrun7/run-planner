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

## Migration to named plans: done except the real push

Checked in the workbook on 2026-10-24 and confirmed by the user:

- Plans `turkey-trot-10k` (week ends `thu`) and `higdon_hm` (week ends `sun`). The user keeps
  these names.
- Week tab: **Sat long**; Mon, Wed, Fri quality; Thu fixed `EASY-4MI`
  (`- Press lap 80% Pace 4mi`, the group run); Tue and Sun easy. The user chose this layout
  option on purpose: making a Sunday long run fit around the Thursday group run took
  impractical schedule changes.
- Config: `plan` = `higdon_hm`, `race_date` 2027-05-02, `plan_tag` `pig-half-2027`. The old
  `long_run` and `source_week_end` rows are gone.
- Layout: 84 dated rows from Feb 8 to May 2, 2027, none unplaced or flagged.

Dry-run push on 2026-10-24 was clean: 83 events would be pushed (every Layout row except the
goal race), 0 stale deletions, no existing `pig-half-2027` events. Still to do: the real push,
when the user says so.

## Import page (built 2026-10-24, on branch `import-page`)

`streamlit run app.py`, Tailscale for other devices (ROADMAP). It covers the steps above:
- copy the prompt
- paste Claude's whole reply (only the CSV block is read)
- Check
- review the matches and choose actions in a table
- save as a plan or Library only

Saving a plan does **not** make it Config's selected plan unless the user ticks the box, so
importing a future plan doesn't wipe his hand-edited Layout (the CLI `apply` still selects).
Verified headlessly on a copy of the master workbook with the Higdon reply (84 days, 32 exact
matches). A live browser check failed because the browser automation didn't respond, so the user
hasn't seen it running yet. The user hasn't set up Tailscale yet either.

## Unverified or open

- **Layout fixed 2026-10-24; the saved Layout has 4 easy runs the plan doesn't.** Two bugs were
  fixed in `place()`: the plan's rest days now give way to displaced easy runs, and a displaced
  easy run stays in its own plan week instead of drifting to the earliest open day in the
  whole plan. Rerun on a copy, the Layout now matches the plan week for week. The saved Layout
  (the one the dry run used) also has easy runs on rest days in weeks 3, 6, 9 and 12 (Sun Feb 28,
  Mar 21, Apr 11, and both Fri Apr 30 and Sat May 1 in race week). **The user confirmed they
  are his own edits.** Rerunning layout on the master workbook would remove them, so don't. The
  Plan page needs a way to keep hand changes across reruns (see ROADMAP).
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
  he can delete them in his spreadsheet app.
- README lost its short "push behaviour" section in the last rewrite; CLAUDE.md covers it, but
  the user-facing README should say it again. Its setup section still shows Windows PowerShell
  commands; the project moved to Linux (bash) in October 2026.

## Backlog (the user sets priorities; don't start these unprompted)

- **Triathlon plans** (the user has `Tri_Training_Sched.xlsx`). Needs a sport per workout
  (Intervals takes Swim/Ride/Run), more than one workout per day (touches Schedule, Layout,
  and the one-hard-day-per-date assumptions in layout), and cross-sport spacing rules.
- **Automate the conversion step** with a direct Claude API call instead of copy-paste through
  a chat. Wait until the prompt is reliable across plan styles.
- **More suggestion kinds** in layout, e.g. fold HM-pace work into the long run as a fast
  finish (the user considered this for Higdon).
- The goal race isn't pushed; Intervals has race event categories that could be used.
