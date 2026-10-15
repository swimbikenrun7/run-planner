You are converting a running training plan into a CSV for my plan builder. I've attached or
pasted the plan below these instructions. Read the whole plan first, including any glossary,
legend, or notes, because they define what the plan's words mean.

# Output

Reply with ONE CSV code block and nothing else after it. Columns, in this order:

    week,day,workout_id,category,name,workout_text,note

- One row per day of the plan, all seven days of every week, including rest days.
- `week`: 1 = first week of the plan. The highest week is race week.
- `day`: Mon, Tue, Wed, Thu, Fri, Sat, Sun, as laid out in the plan.
- Quote any field that contains a comma.
- Before the code block, list in a few short lines anything you had to interpret
  (ambiguous workouts, "X or Y" choices, assumptions about a term). Keep it brief.

# Rest days

- Rest, cross-training, or "rest or cross-train": leave workout_id, category, name and
  workout_text blank. Put the plan's wording in `note`.
- "Rest or <easy run>" choices: treat as rest, put the alternative in `note`.

# Categories

Use exactly one of: easy, long, steady, tempo, threshold, interval, fartlek, hills,
tuneup, race.
- `race`: the goal race at the end of the plan. workout_id RACE, workout_text blank.
- `tuneup`: any other race inside the plan (e.g. a 5K race in week 3). Give it a
  workout_text like `- Press lap {5K} 5km`.
- A session mixing several kinds of work takes the category of its hardest main set
  (hills + intervals in one session: `interval`).
- Strides or pickups added to an easy run do not change it from `easy`.

# Pace targets: use these keys, never raw numbers

Write every target as a key in braces followed by nothing else; my script turns keys into
my Intervals.icu targets. The keys and what they mean:

{{PACES}}

- Map the PLAN'S definitions onto these keys, not its words. If the plan defines "tempo"
  as an effort you could hold 45-60 minutes, that is {T}. If it describes tempo as a
  progression building to 10K pace, write it as a progression of steps.
- "Goal pace", "GP" or "race pace" means the pace of the plan's goal race distance
  (10K plan: {10K}; half marathon plan: {HM}; marathon plan: {M}).
- Unspecified "hard" reps: {I} for reps of 1 minute or longer, {R} for shorter reps and
  strides. "Moderate effort": {M}. "Easy" between reps: {RECOVERY}.
- Offsets: a key plus or minus seconds, like {T+20s} or {10K-5s}, for "tempo +20 sec".
  Offsets are seconds per {{OFFSET_UNIT}}. Use offsets only with E, LONG, STEADY, M, HM,
  T, 10K, 5K, I or R.
- Hills have no pace target. Write the step with a text cue and a duration:
  `- Uphill hard 90s`.

# workout_text format

Intervals.icu workout syntax on one line, with ` / ` (space slash space) where a line break
goes. Section headers are plain text; steps start with `- `.

    Warmup / - Press lap {WU} 2mi / Main Set 5x / - 1mi {T} / - 60s {RECOVERY} / Cooldown / - Press lap {WU} 2mi

Step rules:
- Durations: `30s`, `90s`, `2m`, `1m30s`, `1h`. Distances: `400mtr` (meters: `m` means
  minutes), `1km`, `1mi`, `0.5mi`.
- Repeats go on a section header: `Main Set 6x`, `Hills 5x`, `Strides 4x`.
  Use a separate named section for each distinct set.

## The Press lap convention (important)

I never let the watch auto-advance out of a warmup, a cooldown, or a continuous run,
because it ends steps in the wrong place. These steps start with `Press lap`, then the
target, then the planned time or distance as a reminder:

    - Press lap {WU} 10m
    - Press lap {E} 5mi

Use `Press lap` for:
- every warmup and cooldown step,
- every workout that is a single continuous run (easy runs, long runs),
- continuous segments of a run, like the easy part of a long run with a fast finish,
- recoveries with no set length ("jog back down", "walk back"): `- Press lap Jog down {RECOVERY}`.

Timed or measured work and recovery inside sets stay normal steps (`- 800mtr {5K}`,
`- 2m {RECOVERY}`).

## Warmup and cooldown

If the plan says to add a warmup/cooldown (e.g. "2 miles warmup and cooldown on all
Tue/Thu workouts"), include it in every workout it applies to. If the plan says nothing,
quality sessions (tempo, threshold, interval, fartlek, hills) get
`Warmup / - Press lap {WU} 10m` and `Cooldown / - Press lap {WU} 10m`.

# workout_id and name

- IDs are short, uppercase, hyphenated, and describe the workout: EASY-4MI, LONG-90,
  TEMPO-5x1MI, INT-6x800, HILLS-5x1, TUNEUP-5K.
- The same workout appearing on several days uses the same workout_id and identical
  workout_text every time.
- If a plan workout is the same workout as one in my existing library (below), use that
  library workout_id and copy its workout_text exactly as listed, including its raw
  targets like `80% Pace`. Only do this when it really is the same workout: same reps,
  lengths, intensities and warmup/cooldown. Otherwise write a new workout with keys.
- `name`: a few words for the calendar, like "Tempo 5x1mi".

# My existing library

{{LIBRARY}}
