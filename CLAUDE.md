# run-planner

Turns running plans (PDFs, web pages, spreadsheets) into structured workouts on the
Intervals.icu calendar, which syncs them to Garmin Connect and the user's watch.

**North star:** the user finds a plan anywhere, imports it in minutes, adapts it to his week
(substituting workouts, filling easy runs), and pushes it to his watch with one command,
rerunnable whenever the plan changes. The workbook is the user interface; Python does the work.

Read `docs/HANDOFF.md` for current status and open items, `docs/ROADMAP.md` for direction,
and `docs/DECISIONS.md` before changing anything a decision there covers.

## Working agreement

- **Git workflow (user, Oct 2026):** do all work on a feature branch and commit there in
  logical pieces as it's proven (tests pass, evidence shown). **Ask for approval before merging
  to `main` and before any `git push`.** The user owns final acceptance.
- **Evidence over claims.** Show test output, a dry run, or the generated Layout rather than
  saying something works.
- **Never run `push.py` without `--dry-run`, or press Push in the app, unless the user explicitly asks.** It writes to
  his live Intervals.icu calendar (and his watch). `--dry-run` with `.env` present is safe:
  it only reads.
- **Don't modify `plans/plan_builder.xlsx` for experiments.** It's the user's master workbook
  (Library accumulates over years). Copy it, e.g. `plans/scratch.xlsx`, and work on the copy.
- **The user defines training correctness.** He's a licensed mechanical engineer and an
  experienced runner, and a programming novice with a lot of Excel VBA background. Explain
  code decisions plainly; defer to him on training rules. When a rule is ambiguous, ask.
- **When the user has to act, give explicit numbered steps** with exact bash commands
  and where files go. He has asked for this specifically.
- He prefers priorities to emerge from building over big up-front plans. Propose the next
  step, not a full roadmap.

## Environment

- Linux (Arch), bash. Python 3.14 (via mise) in `.venv` (`source .venv/bin/activate`).
  Moved from Windows/PowerShell in October 2026; older docs and the README may still show
  Windows commands.
- Run tests with `python -m pytest` (plain `pytest` can't import the modules from `tests/`).
- **The user edits the workbook in LibreOffice Calc, which doesn't lock open files** the way
  Windows Excel did. A script can save the workbook while Calc has it open, and saving from
  Calc afterwards silently overwrites the script's changes. While a workbook is open, Calc
  leaves a `.~lock.<name>.xlsx#` file next to it. Every save goes through
  `planlib.save_workbook`, which refuses while that lock file exists (and still catches
  Windows' PermissionError). Keep that behavior; never call `wb.save` directly.
- Scripts write their own output files in UTF-8 instead of relying on shell redirection
  (a holdover from PowerShell writing UTF-16; still the pattern).
- Credentials live in `.env` (`INTERVALS_API_KEY`, `INTERVALS_ATHLETE_ID`); never print or
  commit them. `env.example` is the committed template.

## Commands

```bash
streamlit run app.py                                    # the app (Plan, Import, Calendar, Fill gaps pages), on localhost:8501
python setup_workbook.py plans/plan_builder.xlsx        # idempotent: adds tabs/keys the code needs
python import_plan.py prompt plans/plan_builder.xlsx    # writes imports/prompt.md for a Claude chat
python import_plan.py stage  plans/plan_builder.xlsx imports/<plan>.csv
python import_plan.py apply  plans/plan_builder.xlsx --plan <name> --week-end sun   # or --library-only
python layout.py plans/plan_builder.xlsx [--option N]
python push.py   plans/plan_builder.xlsx --dry-run [--overlap keep|replace]
python -m pytest
```

## Code map

| File | Role |
|---|---|
| `app.py`, `ui/` | Streamlit app over the workbook. Pages call the same functions as the scripts; `RUN_PLANNER_WORKBOOK` points it at a copy |
| `planlib.py` | Shared: workbook reading (`read_table`, `last_used_row`), `save_workbook` (lock check), days, Config helpers, `read_week`, `rule_violations` |
| `import_plan.py` | prompt → stage → apply (`build_prompt`, `parse_csv`, `stage_plan`, `apply_import`, `apply_to_workbook`). Pace keys to targets, workout validation, Library matching, named plans |
| `layout.py` | Places the selected plan on dates around the Week template; suggests structural options when it doesn't fit (`compute_layout`, `write_result`) |
| `push.py` | Layout → Intervals.icu events (bulk upsert), deletes stale future events (`preview` reads only, `send` writes, `record_push` notes it on Plans) |
| `fitness.py` | Workout load and duration from text (matches Intervals within ~1), fitness/fatigue/form projection, form zones |
| `forecast.py` | Daily loads from Intervals events and races, starting fitness, race-day form |
| `filler.py` | Gap filler: recovery after a race, then building weeks within the user's rules |
| `master.py` | The master calendar: Intervals events by plan_tag, race days, and gaps of 7+ days with nothing planned |
| `setup_workbook.py` | Migrates an older workbook: Paces, Week, Plans tabs, Schedule `plan` column, Config keys |
| `prompts/convert_plan.md` | Conversion prompt template (`{{PACES}}`, `{{OFFSET_UNIT}}`, `{{LIBRARY}}` filled by `prompt`) |
| `tests/` | One test file per module. Pure logic is tested without the workbook or network; `test_app.py` drives pages headlessly with Streamlit's AppTest on a temporary workbook |

Pattern to keep: logic in pure functions (inputs → outputs, `today` passed in), thin `main()`
for I/O. Validation collects every problem and reports them together instead of stopping at
the first.

## Pipeline and workbook

```
plan source --(Claude chat + prompt)--> CSV --stage--> Import tabs --apply--> Library + Schedule/Plans
Schedule[Config.plan] + Week --layout--> Layout tab (or Options tab) --push--> Intervals.icu --> Garmin
```

| Tab | Contents |
|---|---|
| Config | key/value: `plan`, `race_date`, `plan_tag`, `threshold_pace` (e.g. `6:55/mi`), `taper_days` (2), `long_run_gap` (5), `allow_pre_long` (yes/no), `hard_categories`, optional `long_run_days` (default `sat, sun`); gap-filler rules (see below) |
| Library | `workout_id`, `category`, `name`, `workout_text`. Grows forever; never overwrite an entry |
| Paces | `key`, `description`, `target` (see pace table below) |
| Week | `day`, `role` (`long`/`quality`/`fixed`/`easy`), `workout_id` (for fixed days) |
| Plans | `plan`, `source_week_end`, `notes`, `rest_fill`, `pre_race_fill` (blank = keep rest days), `plan_tag`, `race_date`, `pushed` (written by push: which Intervals tag and race the plan was pushed for), `race_distance` (5k/10k/half/marathon) |
| Fill | generated by the Fill gaps page: `plan_tag` (`fill-<first day>`), `date`, `workout_id`, `load`, `note`, and the forecast at push time: `fitness`, `fatigue` (end of day), `form` (going into the day), `pushed`. Kept for comparing forecast with actual (ROADMAP step 6); Intervals keeps the actuals |
| Schedule | `plan`, `week`, `day`, `workout_id`, `note`: each plan in its own week convention |
| Layout | generated: one row per date; rows with no date are sessions that couldn't be placed |
| Import / Import Schedule / Options | transient review tabs, removed when their step completes |

Excel workbooks often carry hundreds of formatted empty rows. Append with `last_used_row`,
never `ws.max_row` or `ws.append`. `read_table` skips blank rows.

## Domain rules (from the user; don't change without asking)

**Workout text** is Intervals.icu syntax stored on one line with ` / ` as the line break.
Steps start with `- `. Section headers are plain text and `push.to_intervals_text` puts a
blank line before each one (Intervals needs it to separate sections). `m` = minutes,
`mtr` = meters, `mi`, `km`.

**Press lap convention.** Warmup and cooldown steps, single continuous runs (easy, long),
continuous segments, and untimed recoveries ("jog back down") start with `Press lap`, then the
target, then the planned time/distance as a reminder: `- Press lap Z2 Pace 10m`. The user
doesn't want the watch auto-advancing out of these. Stage rejects workouts that break this.

**Pace table** (Paces tab), as % of threshold *speed* (Intervals' convention), derived from
Daniels VDOT ratios: RECOVERY Z1, WU Z2, E 80, LONG 80, STEADY 90, M 94, HM 98, T 100,
10K 103, 5K 107, I 110, R 118. Single values, not ranges: Intervals adds ±2.5% when it sends
to Garmin. Z1/Z2 stay zones. Hills have no pace target (`- Uphill hard 90s`). The CSV uses keys
(`{T}`, `{T+20s}`); offsets are seconds of pace per threshold_pace unit and are converted by
the script, not the LLM. The table assumes threshold pace ≈ one-hour race pace.

**Categories:** easy, long, steady, tempo, threshold, interval, fartlek, hills, tuneup, race.
Hard by default: everything except easy. `race` = the goal race (not pushed; the user adds it
in Intervals); `tuneup` = races inside a plan (pushed, take the long-run slot).

**Layout rules:** race on `race_date`; no hard session in the `taper_days` before it; long runs
on the Week's long day and never within `long_run_gap` days of the race; other hard sessions
on quality days in plan order, falling back to another legal day in the same week; no
back-to-back hard days except the plan's pre-long-run session the day before the long run when
`allow_pre_long` is yes; fixed days always get their workout. If hard sessions don't fit, the
engine **advises instead of improvising**: it writes nothing, lists options (current week plus
the best change of each kind: keep the long day / keep fixed days / move the long day), and the
user picks with `--option N`, which rewrites the Week tab.

**Rest-day fill** (user): the user doesn't take rest days. After placement, every rest day left
becomes the plan's `rest_fill`. In race week the shortest run goes on the day before the race:
the plan's own easy run if it's no longer than `pre_race_fill` (the run it displaces moves to an
open day earlier in the week), otherwise `pre_race_fill` itself. A longer plan run on that day
moves to an earlier open day. The fill workouts are
`EASY-3MI`/`EASY-2MI` for plans that write easy runs in distance and `EASY-30`/`EASY-20` for
time, detected when a plan is first imported and editable on the Plans tab. Re-importing keeps
his values.

**Gap filler and form** (user, defaults editable on the Fill gaps page; see `docs/FITNESS.md`):
- **Recovery:** easy days after a race: 5K 3, 10K 4, half 7, marathon 14. The first is the shortest
  easy run.
- **Building:** fitness ramp at most 5 a week; weekly load at most +10% on the last build week; the
  long run at most one step longer (1 mi / 5 min); a lighter week at 70% after every 3 build weeks;
  1 quality session per build week (tempo, threshold, interval); never planned into high risk.
- **Filler gives way** (user): filler is tagged `fill-<first day>`. Pushing a plan replaces the filler in
  its dates (first workout to race) without asking; the gaps around it are then refilled on the Fill
  gaps page, which flags filler planned before the calendar changed. Refilling a gap replaces all
  filler in it, whatever its tag.
- **Plans overlapping plans:** when a plan's dates overlap another pushed plan, the user chooses: keep
  the other plan (this plan's workouts in its dates aren't sent) or replace it (its workouts in this
  plan's dates are deleted). Events added by hand in Intervals, races included, are never deleted.
- **How far ahead:** a gap between two plans is filled whatever its length; with no plan after it, at
  most 90 days from today.
- **Between plans:** keep building (the user's goal), or optionally match the next plan's starting
  fitness.
- **Units:** the filler uses the units of the plan after the gap (else the one before). Workouts
  outside a plan's dates are free of its conventions.
- **Race-day form target:** "grey" (-10 and up) by default, since the user isn't racing all out;
  "fresh" (+5 and up) is the option for a hard taper. The Plan page's check warns when a plan
  projects short of it.
- **Form zones:** absolute below fitness 60, % of fitness above (user's reading of the Intervals
  help).

**Matching on import:** exact (identical text, ignoring case and spacing) reuses the Library
ID; similar (multi-step, same category, same main set or same structure with different
numbers) needs the user's `action`; single continuous runs of different lengths are always
new. ID collisions are renamed with `-2`, never overwritten.

## Intervals.icu API (as used)

- Auth: HTTP basic, username `API_KEY`, password = key. Base `https://intervals.icu/api/v1/athlete/{id}`.
- `POST /events/bulk?upsert=true` with `category: "WORKOUT"`, `type: "Run"`,
  `start_date_local`, `name`, `description` (workout text), `external_id = "<plan_tag>-<date>"`.
  Upsert matches on external_id, so re-pushing updates in place.
- `GET /events?oldest=&newest=` returns `external_id` (verified by the user).
- `PUT /sport-settings/Run?recalcHrZones=false` with `{"threshold_pace": m/s}`: the Plan page's
  threshold update (from a 10K prediction ÷ the Paces tab's 10K %), only after the user confirms;
  it re-reads to check the change took. Not yet run against the live account.
- `PUT /events/bulk-delete` with `[{"external_id": ...}]`. Push deletes only *future* events:
  this plan_tag's whose dates no longer have a workout, filler in the plan's dates, and an
  overlapping plan's workouts when the user chose to replace it (`push.overlaps`, `push.resolve`).
  Past events are history: never deleted.
