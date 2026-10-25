# Decisions

Short record of choices and why, so they aren't relitigated by accident. Newest at the bottom.
Anything marked (user) is the user's call; change it only with him.

1. **Intervals.icu as the bridge to Garmin.** Garmin Connect can't import plans, and its own
   plans top out at 5 days a week for 10K. Intervals syncs planned workouts to Garmin.
2. **The workbook is the UI** (user). He's fluent in Excel; review and edits happen there.
   Scripts read and write it with openpyxl.
3. **Weeks are 7-day blocks ending on race day**, so any race weekday works. Each plan keeps
   its own week convention (`source_week_end`) and is mapped by days-before-race.
4. **`external_id = <plan_tag>-<date>`** makes pushes idempotent (upsert). One workout per day.
5. **Pace targets follow convention, not personal preference** (user): Daniels VDOT ratios as
   % of threshold speed. The user's older Library had tempo 95% / threshold 105% / 10K 100% /
   long 85%; convention says tempo = threshold = 100%, 10K 103%, long at E 80%. His instruction:
   "update me, not the table".
6. **Single-value targets** (user): Intervals adds ±2.5% when sending to Garmin, which he used
   to do by hand. Z1/Z2 stay as zones because warmups and recoveries don't need precision.
7. **Press lap convention** (user): warmups, cooldowns, continuous runs and untimed recoveries
   advance on the lap button, with the planned length as a text reminder. Auto-advance ended
   warmups in bad spots and split runs into extra laps. Enforced at import.
8. **Conversion v1 is copy-paste through a Claude chat**, not the API: no API billing, the
   user sees the conversion, and it fixes the CSV format before automating.
9. **Pace keys in the CSV, numbers in the Library.** The LLM writes `{T+20s}`; the script does
   the arithmetic. LLMs are unreliable at the math; the Paces tab stays the single source.
10. **Each plan defines its own words.** The prompt maps a plan's glossary onto pace keys
    (Brooks "tempo" = T; Higdon "tempo" = a progression to 10K pace). "Goal/race pace" = the
    plan's race distance.
11. **Import never overwrites the Library.** Exact matches reuse IDs; similar ones need the
    user's decision; collisions get `-2`. The master Library accumulates across plans (user).
12. **Plans stored by name** instead of one Schedule, so importing never threatens the live plan.
13. **Week template with roles** (user): his real constraints are a long-run day, quality days,
    and fixed commitments (a Thursday group run).
14. **No long run within 5 days of the race** (user), configurable as `long_run_gap`.
15. **The engine advises instead of improvising** (user). When hard sessions don't fit his week,
    layout lists structural options and he chooses. This replaced an earlier backward-cascade
    engine that pushed sessions into prior weeks: it handled scrambled plans but produced
    nonsense when a plan simply had more hard days than the week allowed.
16. **Back-to-back hard days are never allowed, except a plan's deliberate pre-long-run session**
    (e.g. Higdon's Saturday pace run before Sunday's long run), and only when `allow_pre_long` is on.
17. **Dates before today are laid out but never pushed, and past events are never deleted.**
18. **Rest days become easy runs** (user). He runs every day: the plan's rest days get `rest_fill`
    (3mi or 30m, matching how the plan writes easy runs) and the day before the race a shorter
    `pre_race_fill` (2mi or 20m). It's a rule per plan on the Plans tab rather than hand overrides,
    so rerunning layout keeps it. In race week the shortest run goes the day before the race
    ("shortest run last"), so a plan's own 2mi race-week run becomes the shakeout.
19. **No paid Claude API** (user, 2026-10-24). Plan conversion stays copy-paste through a Claude
    chat; the "automate conversion" backlog item is closed.
20. **Form is projected, not guessed.** Intervals' fitness/fatigue are 42-day and 7-day exponential
    averages of load (verified against the user's data to within 0.4), and planned workouts carry an
    estimated load, so the app can project form for any plan or filler (see FITNESS.md).
21. **Filler gives way to plans; plans ask before replacing plans** (user, 2026-10-25). Filler is
    disposable: a plan pushed over it replaces it, and the gaps either side are planned again, since
    their start (recovery after the race) and end depend on the calendar around them. Another plan
    is the user's commitment, so overlapping one needs his choice: keep it or replace it.
22. **Filler with no plan after it runs at most 90 days ahead** (user, 2026-10-25). Between two plans
    the whole gap is filled. Replanning a gap under way starts from today's actual fitness and the
    current threshold pace, so it doubles as a refresh.
