"""Gap filler: training for the days between plans (ROADMAP step 5, docs/FITNESS.md).

After a race: a recovery block of easy runs (length by race distance). Then build weeks that raise
fitness by at most ramp_limit a week, with weekly load up at most max_weekly_increase % on the last
build week and the long run up at most one size step, a lighter week after every build_weeks, and
form kept out of the high-risk zone. Fitness keeps building (the user's goal between plans), or with
between_plans "match", builds only to the level the next plan's first week assumes and holds. Workouts follow the Week tab: fixed days keep
their workout, the long day gets the long run, quality days get quality sessions from the Library,
and every other day an easy run.
"""

import re
from datetime import timedelta

from fitness import project, zone_floor
from planlib import blank

DEFAULT_RULES = {
    "recovery_days": "5k:3, 10k:4, half:7, marathon:14",
    "ramp_limit": 5,
    "max_weekly_increase": 10,
    "build_weeks": 3,
    "recovery_week_pct": 70,
    "quality_per_week": 1,
    "quality_categories": "tempo, threshold, interval",
    "race_form_target": "grey",
    "between_plans": "build",
}
DISTANCES = ["5k", "10k", "half", "marathon"]
LONG_SHARE = 2.5  # the long run is about this many easy runs' worth of load
QUALITY_SHARE = 0.18  # a quality session's share of the week's load
SIZES = {  # (easy sizes, long sizes) by how the neighbouring plan writes its runs
    "distance": ([x / 2 for x in range(4, 17)], list(range(6, 17))),  # 2-8 mi by 0.5; 6-16 mi
    "time": (list(range(20, 75, 5)), list(range(60, 155, 5))),  # 20-70 min; 60-150 min
}


def rules_from_config(config):
    """The gap-filler rules from Config, with defaults for any that aren't set."""
    raw = {k: config.get(k) if not blank(config.get(k)) else v for k, v in DEFAULT_RULES.items()}
    recovery = {}
    for part in str(raw["recovery_days"]).split(","):
        if ":" in part:
            name, days = part.split(":")
            recovery[name.strip().lower()] = int(float(days))
    return {"recovery_days": recovery, "ramp_limit": float(raw["ramp_limit"]),
            "max_weekly_increase": float(raw["max_weekly_increase"]),
            "between_plans": str(raw["between_plans"]).strip().lower(),
            "build_weeks": int(float(raw["build_weeks"])), "recovery_week_pct": float(raw["recovery_week_pct"]),
            "quality_per_week": int(float(raw["quality_per_week"])),
            "quality_categories": [c.strip().lower() for c in str(raw["quality_categories"]).split(",") if c.strip()],
            "race_form_target": str(raw["race_form_target"]).strip().lower()}


def race_distance(plan_name):
    """Best guess at a plan's race distance from its name; the user can correct it on the Plans tab."""
    name = str(plan_name or "").lower()
    if "half" in name or re.search(r"\bhm\b|_hm|-hm|hm[-_]", name):
        return "half"
    if "marathon" in name:
        return "marathon"
    if "10k" in name:
        return "10k"
    if "5k" in name:
        return "5k"
    return None


def sized_workout(kind, size, unit, targets):
    """(workout_id, name, workout_text) for an easy or long run of the given size."""
    target = targets["E" if kind == "easy" else "LONG"]
    if unit == "distance":
        n = f"{size:g}"
        return f"{kind.upper()}-{n}MI", f"{kind.title()} {n}mi", f"- Press lap {target} {n}mi"
    return f"{kind.upper()}-{size}", f"{kind.title()} {size}", f"- Press lap {target} {size}m"


def normalize(text):
    return " ".join(str(text or "").lower().split())


class Picker:
    """Chooses workouts: Library ones where the text matches, new ones (added once) otherwise."""

    def __init__(self, library, unit, targets, load_of, rules):
        self.library, self.unit, self.targets, self.load_of = library, unit, targets, load_of
        self.by_text = {normalize(r.get("workout_text")): w for w, r in library.items()}
        self.new = {}  # workout_id -> Library row to add
        self.quality = sorted(((load_of(r.get("workout_text")), w) for w, r in library.items()
                               if str(r.get("category") or "").strip().lower() in rules["quality_categories"]
                               and not blank(r.get("workout_text"))), key=lambda x: x[0])
        self.last_quality = []
        self.long_size = None  # size of the last long run chosen

    def sized(self, kind, size):
        wid, name, text = sized_workout(kind, size, self.unit, self.targets)
        existing = self.by_text.get(normalize(text))
        if existing:
            return existing, self.load_of(text)
        if wid in self.library and normalize(self.library[wid].get("workout_text")) != normalize(text):
            wid = f"{wid}-F"  # the id is taken by a different workout: never overwrite
        self.new.setdefault(wid, {"workout_id": wid, "category": kind, "name": name, "workout_text": text})
        return wid, self.load_of(text)

    def nearest(self, kind, load, max_size=None):
        sizes = [s for s in SIZES[self.unit][0 if kind == "easy" else 1] if max_size is None or s <= max_size]
        best = min(sizes or SIZES[self.unit][1][:1],
                   key=lambda s: abs(self.load_of(sized_workout(kind, s, self.unit, self.targets)[2]) - load))
        if kind == "long":
            self.long_size = best
        return self.sized(kind, best)

    def size_of(self, kind, load):
        """The largest size of this kind whose load is at most `load` (the smallest if none)."""
        sizes = SIZES[self.unit][0 if kind == "easy" else 1]
        fits = [s for s in sizes if self.load_of(sized_workout(kind, s, self.unit, self.targets)[2]) <= load]
        return fits[-1] if fits else sizes[0]

    def next_size(self, kind, size):
        sizes = SIZES[self.unit][0 if kind == "easy" else 1]
        return next((s for s in sizes if s > size), sizes[-1])

    def smallest(self, kind):
        return self.sized(kind, SIZES[self.unit][0 if kind == "easy" else 1][0])

    def quality_near(self, load):
        """A quality session close to the wanted load, not one used in the last two weeks."""
        if not self.quality:
            return None, 0.0
        fresh = [q for q in self.quality if q[1] not in self.last_quality] or self.quality
        q_load, wid = min(fresh, key=lambda q: abs(q[0] - load))
        self.last_quality = (self.last_quality + [wid])[-2:]
        return wid, q_load


def week_days(first, last):
    """Split [first, last] into calendar weeks (Mon-Sun), as lists of dates."""
    weeks, d = [], first
    while d <= last:
        end = min(last, d + timedelta(days=6 - d.weekday()))
        weeks.append([d + timedelta(days=k) for k in range((end - d).days + 1)])
        d = end + timedelta(days=1)
    return weeks


def plan_week(days, week, picker, load, quality_count, library, long_max=None):
    """Workouts for these days adding up to about `load`. Returns {date: (workout_id, load, note)}."""
    out, roles = {}, {}
    quality_left = quality_count
    for d in days:
        role, wid = week[d.weekday()]
        if role == "fixed":
            roles[d] = ("fixed", wid)
        elif role == "long":
            roles[d] = "long"
        elif role == "quality" and quality_left:
            roles[d], quality_left = "quality", quality_left - 1
        else:
            roles[d] = "easy"
    remaining = load
    for d, r in roles.items():
        if isinstance(r, tuple):
            out[d] = (r[1], picker.load_of(library[r[1]].get("workout_text")), "your week")
            remaining -= out[d][1]
        elif r == "quality":
            wid, q = picker.quality_near(load * QUALITY_SHARE)
            if wid:
                out[d] = (wid, q, "quality")
                remaining -= q
            else:
                roles[d] = "easy"
    easy_days = [d for d, r in roles.items() if r == "easy"]
    long_days = [d for d, r in roles.items() if r == "long"]
    per_easy = max(remaining, 0) / max(len(easy_days) + LONG_SHARE * len(long_days), 1)
    for d in easy_days:
        out[d] = (*picker.nearest("easy", per_easy), "easy")
    for d in long_days:
        out[d] = (*picker.nearest("long", per_easy * LONG_SHARE, long_max), "long run")
    return out


def fill(first, last, ctl, atl, week, library, rules, unit, targets, load_of,
         after_race=None, target_ctl=None, recent_week_load=None, recent_long_load=None):
    """Plan the gap [first, last]. after_race: race distance ('half', ...) if the gap starts the
    day after a race. target_ctl: fitness the next plan's first week assumes (None: no next plan).
    recent_week_load / recent_long_load: the user's usual week and longest recent long run, the
    starting points for the 10% and long-run limits (default: what fitness implies).

    Returns {"days": {date: (workout_id, load, note)}, "new": [Library rows to add],
    "projection": [(date, load, fitness, fatigue, form)]}.
    """
    picker = Picker(library, unit, targets, load_of, rules)
    floor = zone_floor("optimal")  # never plan into high risk
    days = {}
    recovery = rules["recovery_days"].get(after_race, 0) if after_race else 0
    recovery_days = [first + timedelta(days=k) for k in range(recovery) if first + timedelta(days=k) <= last]
    for n, d in enumerate(recovery_days):
        role, wid = week[d.weekday()]
        if role == "fixed":
            days[d] = (wid, load_of(library[wid].get("workout_text")), "your week")
        elif n == 0:  # the day after the race: the shortest easy run
            days[d] = (*picker.smallest("easy"), "recovery")
        else:  # then the usual short easy run (3mi / 30m)
            days[d] = (*picker.sized("easy", 3 if unit == "distance" else 30), "recovery")
    state = project(ctl, atl, {d: v[1] for d, v in days.items()}, first, recovery_days[-1])[-1][2:4] \
        if recovery_days else (ctl, atl)

    build_start = recovery_days[-1] + timedelta(days=1) if recovery_days else first
    last_build_load = None  # per 7 days
    base_load = recent_week_load or 7 * ctl
    long_size = picker.size_of("long", recent_long_load or base_load * 0.3)  # last build week's long run
    for k, wk in enumerate(week_days(build_start, last)):
        c0, a0 = state
        frac = len(wk) / 7
        lighter = (k + 1) % (rules["build_weeks"] + 1) == 0
        if lighter and last_build_load:
            goal_load = last_build_load * rules["recovery_week_pct"] / 100 * frac
            planned = plan_week(wk, week, picker, goal_load, 0, library)
        else:
            goal = c0 + rules["ramp_limit"] * frac  # keep building
            if target_ctl is not None and rules["between_plans"] == "match":
                goal = min(goal, target_ctl) if c0 < target_ctl else c0  # to the next plan's level, then hold
            cap = (last_build_load or base_load) * (1 + rules["max_weekly_increase"] / 100) * frac
            planned = best_week(wk, week, picker, rules, library, c0, a0, goal, floor, cap,
                                picker.next_size("long", long_size))  # long run: one step up at most
            last_build_load = sum(v[1] for v in planned.values()) / frac
            long_size = picker.long_size or long_size
        days.update(planned)
        state = project(c0, a0, {d: v[1] for d, v in planned.items()}, wk[0], wk[-1])[-1][2:4]

    used = {v[0] for v in days.values()}
    return {"days": days, "new": [r for w, r in picker.new.items() if w in used],
            "projection": project(ctl, atl, {d: v[1] for d, v in days.items()}, first, last)}


def best_week(days, week, picker, rules, library, c0, a0, goal, floor, cap, long_max):
    """The week whose load brings fitness closest to `goal`, with load at most `cap`, the long run
    at most `long_max`, and form never below `floor`."""
    def trial(load):
        saved = list(picker.last_quality)
        planned = plan_week(days, week, picker, load, rules["quality_per_week"], library, long_max)
        picker.last_quality = saved
        proj = project(c0, a0, {d: v[1] for d, v in planned.items()}, days[0], days[-1])
        return planned, proj[-1][2], min(p[4] for p in proj) if proj else 0

    lo, hi = 0.0, cap
    for _ in range(30):
        mid = (lo + hi) / 2
        planned, ctl_end, min_form = trial(mid)
        if ctl_end < goal and min_form >= floor and sum(v[1] for v in planned.values()) <= cap:
            lo = mid
        else:
            hi = mid
    return plan_week(days, week, picker, lo, rules["quality_per_week"], library, long_max)
