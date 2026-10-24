# run-planner

Turns running plans (PDFs, web pages, spreadsheets) into structured workouts on the
Intervals.icu calendar, which syncs them to Garmin Connect and the user's watch.

**North star:** the user finds a plan anywhere, imports it in minutes, adapts it to his week
(substituting workouts, filling easy runs), and pushes it to his watch with one command,
rerunnable whenever the plan changes. The workbook is the user interface; Python does the work.

Read `docs/HANDOFF.md` for current status and open items, and `docs/DECISIONS.md` before
changing anything a decision there covers.

## Working agreement

- **The user owns Git commits and final acceptance.** Don't commit. When work is ready, say
  what changed and suggest a commit message.
- **Evidence over claims.** Show test output, a dry run, or the generated Layout rather than
  saying something works.
- **Never run `push.py` without `--dry-run` unless the user explicitly asks.** It writes to
  his live Intervals.icu calendar (and his watch). `--dry-run` with `.env` present is safe:
  it only reads.
- **Don't modify `plans/plan_builder.xlsx` for experiments.** It's the user's master workbook
  (Library accumulates over years). Copy it, e.g. `plans/scratch.xlsx`, and work on the copy.
- **The user defines training correctness.** He's a licensed mechanical engineer and an
  experienced runner, and a programming novice with a lot of Excel VBA background. Explain
  code decisions plainly; defer to him on training rules. When a rule is ambiguous, ask.
- **When the user has to act, give explicit numbered steps** with exact PowerShell commands
  and where files go. He has asked for this specifically.
- He prefers priorities to emerge from building over big up-front plans. Propose the next
  step, not a full roadmap.

## Environment

- Windows, PowerShell, Python 3.14 in `.venv` (`.venv\Scripts\Activate.ps1`).
- Run tests with `python -m pytest` (plain `pytest` can't import the modules from `tests/`).
- **Excel locks open workbooks.** Scripts that save the workbook fail with a PermissionError
  if it's open; they print "close the workbook in Excel". Keep that behavior.
- PowerShell `>` redirection writes UTF-16. Scripts write their own output files in UTF-8
  instead of relying on redirection.
- Credentials live in `.env` (`INTERVALS_API_KEY`, `INTERVALS_ATHLETE_ID`); never print or
  commit them. `.env.example` is the committed template.

## Commands

```powershell
python setup_workbook.py plans/plan_builder.xlsx        # idempotent: adds tabs/keys the code needs
python import_plan.py prompt plans/plan_builder.xlsx    # writes imports/prompt.md for a Claude chat
python import_plan.py stage  plans/plan_builder.xlsx imports/<plan>.csv
python import_plan.py apply  plans/plan_builder.xlsx --plan <name> --week-end sun   # or --library-only
python layout.py plans/plan_builder.xlsx [--option N]
python push.py   plans/plan_builder.xlsx --dry-run
python -m pytest
```

## Code map

| File | Role |
|---|---|
| `planlib.py` | Shared: workbook reading (`read_table`, `last_used_row`), days, Config helpers, `read_week`, `rule_violations` |
| `import_plan.py` | prompt → stage → apply. Pace keys to targets, workout validation, Library matching, named plans |
| `layout.py` | Places the selected plan on dates around the Week template; suggests structural options when it doesn't fit |
| `push.py` | Layout → Intervals.icu events (bulk upsert), deletes stale future events |
| `setup_workbook.py` | Migrates an older workbook: Paces, Week, Plans tabs, Schedule `plan` column, Config keys |
| `prompts/convert_plan.md` | Conversion prompt template (`{{PACES}}`, `{{OFFSET_UNIT}}`, `{{LIBRARY}}` filled by `prompt`) |
| `tests/` | One test file per module. Pure logic is tested without the workbook or network |

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
| Config | key/value: `plan`, `race_date`, `plan_tag`, `threshold_pace` (e.g. `6:55/mi`), `taper_days` (2), `long_run_gap` (5), `allow_pre_long` (yes/no), `hard_categories`, optional `long_run_days` (default `sat, sun`) |
| Library | `workout_id`, `category`, `name`, `workout_text`. Grows forever; never overwrite an entry |
| Paces | `key`, `description`, `target` (see pace table below) |
| Week | `day`, `role` (`long`/`quality`/`fixed`/`easy`), `workout_id` (for fixed days) |
| Plans | `plan`, `source_week_end`, `notes` |
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
- `PUT /events/bulk-delete` with `[{"external_id": ...}]`. Push deletes only *future* events
  with this plan_tag whose dates no longer have a workout. Past events are history: never deleted.
