# Fitness, fatigue and form (Intervals.icu)

What the app can see and compute, checked against the user's account on 2026-10-24. This is the
basis for the gap filler; training targets are the user's decisions (see the end).

## What Intervals exposes (read-only)

| Endpoint | What we get |
|---|---|
| `GET /wellness?oldest=&newest=` | Per day: `ctl` (fitness), `atl` (fatigue), `rampRate` (fitness change per week), `ctlLoad`/`atlLoad` (that day's load, including today's planned load), resting HR, sleep |
| `GET /activities?oldest=&newest=` | Each run: `icu_training_load`, distance, moving time |
| `GET /events?oldest=&newest=` | Each planned workout: `icu_training_load`, Intervals' estimate of its load from the workout text |
| `GET /athlete` | Run settings: threshold pace, LTHR 173, max HR 185, load order power > pace > HR |

## The model (verified)

Fitness and fatigue are exponentially weighted averages of daily load:

    fitness(d) = fitness(d-1) + (load(d) - fitness(d-1)) / 42
    fatigue(d) = fatigue(d-1) + (load(d) - fatigue(d-1)) / 7
    form(d)    = fitness(d-1) - fatigue(d-1)        (yesterday's values: form going into the day)
    form %     = form / fitness

Rebuilt from the user's activity loads, this matches Intervals' reported fitness and fatigue to
within 0.4 every day. That means the app can **project** form for any planned training using the
load Intervals estimates for each planned workout.

## Form zones (Intervals' chart; Joe Friel's TSB bands)

| Zone | Form | Meaning |
|---|---|---|
| Transition | above +20 | detraining |
| Fresh | +5 to +20 | race-ready ("blue") |
| Grey zone | -10 to +5 | maintaining |
| Optimal | -10 to -30 | building fitness |
| High risk | below -30 | overreaching |

The chart can show these as absolute form or as % of fitness. Intervals' developer describes them as
a rule of thumb from Friel, designed for absolute values; he used % because it suited his own
training load. The user's reading of Intervals' help: use absolute below fitness 60, % above it.

## The user's projected numbers (2026-10-24, from the planned workouts on Intervals)

- **Turkey trot (Thu Nov 26, 2026):** fitness about 40, race-day form -2 (-5%): grey zone, not fresh.
- **Gap Nov 26 to Feb 7:** with nothing planned, fitness falls from about 40 to about 7.
- **Higdon (Sun May 2, 2027):** race-day form +1.5 (+3%), starting from the decayed fitness. Peak
  fitness about 47. Weekly planned load is 300 to 470, but 197 in race week.

## Evidence used

- **Taper:** Bosquet et al. 2007 meta-analysis (27 studies): about 2 weeks, volume reduced
  exponentially by 41-60%, intensity and frequency kept.
- **Post-race recovery:** no controlled trial sets a number of easy days.
  - After a half marathon, muscle-damage markers peak at 24-72 h and are back near baseline in
    about 5-7 days.
  - A 10K reduces strength and power for at least 48 h.
  - Pfitzinger's "one easy day per mile raced" is a marathon coaching heuristic.
- **Ramp:** a fitness increase of about 5-8 per week is a coaching rule of thumb, not an
  injury threshold. The acute:chronic band 0.8-1.3 comes from team sports and is debated.

## Open: the user's training rules for the gap filler

Recovery days by race distance; ramp-rate ceiling; recovery-week rhythm; race-day form target;
what to do after the last plan.
