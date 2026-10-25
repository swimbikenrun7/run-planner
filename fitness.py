"""Fitness, fatigue and form, the way Intervals.icu computes them (see docs/FITNESS.md).

Load of a workout: for each step, hours x (pace % of threshold / 100)^2 x 100. Steps without a
pace target (hills, jog-backs) add nothing, as in Intervals. Fitness and fatigue are 42-day and
7-day exponential averages of daily load; form going into a day is yesterday's fitness minus
yesterday's fatigue.
"""

import re
from datetime import timedelta

CTL_DAYS, ATL_DAYS = 42, 7
PERCENT_ABOVE = 60  # user: form as % of fitness once fitness is above 60, absolute below
METERS = {"mi": 1609.344, "km": 1000, "mtr": 1}
SECONDS = {"h": 3600, "m": 60, "s": 1}
LENGTH = re.compile(r"(\d+(?:\.\d+)?)(mi|km|mtr|h|m|s)")
TARGET = re.compile(r"(\d+(?:\.\d+)?)% Pace|Z(\d) Pace")
REPEAT = re.compile(r"(\d+)x\s*$")

# Friel's form bands as Intervals draws them: (name, lower bound); absolute, or % above fitness 60
ZONES = [("transition", 20), ("fresh", 5), ("grey", -10), ("optimal", -30), ("high risk", float("-inf"))]


def zone_pace(zone, zones):
    """Pace % Intervals uses for a 'Zn Pace' target: the middle of that zone (Z1 from 50%)."""
    lower = 50.0 if zone == 1 else zones[zone - 2]
    return (lower + zones[zone - 1]) / 2


def step_hours(length_token, pct, threshold_speed):
    parts = LENGTH.findall(length_token)
    if not parts or "".join(n + u for n, u in parts) != length_token:
        return 0.0
    if all(u in SECONDS for _, u in parts):
        return sum(float(n) * SECONDS[u] for n, u in parts) / 3600
    if all(u in METERS for _, u in parts) and pct:
        meters = sum(float(n) * METERS[u] for n, u in parts)
        return meters / (threshold_speed * pct / 100) / 3600
    return 0.0


def workout_load(text, threshold_speed, zones):
    """Estimated load of a workout written in the Library's ' / ' format (or with newlines)."""
    if not text:
        return 0.0
    lines = [ln.strip() for ln in re.split(r" / |\n", str(text)) if ln.strip()]
    total, repeat = 0.0, 1
    for line in lines:
        if not line.startswith("-"):
            m = REPEAT.search(line)
            repeat = int(m.group(1)) if m else 1
            continue
        target = TARGET.search(line)
        if not target:
            continue  # no pace target: Intervals counts no load
        pct = float(target.group(1)) if target.group(1) else zone_pace(int(target.group(2)), zones)
        # the length can come before the target ("- 15m 105% Pace") or after ("- Press lap 80% Pace 30m")
        hours = next((h for h in (step_hours(tok, pct, threshold_speed) for tok in line.split()) if h), 0.0)
        total += repeat * hours * (pct / 100) ** 2 * 100
    return total


def project(ctl, atl, loads, first, last):
    """Daily projection from first to last, starting from fitness/fatigue at the end of the day
    before first. loads maps date -> load. Returns [(date, load, fitness, fatigue, form)] where
    form is going into the day and fitness/fatigue are at the end of it."""
    out, d = [], first
    while d <= last:
        form = ctl - atl
        load = loads.get(d, 0.0)
        ctl += (load - ctl) / CTL_DAYS
        atl += (load - atl) / ATL_DAYS
        out.append((d, load, ctl, atl, form))
        d += timedelta(days=1)
    return out


def form_value(form, fitness):
    """Form the way to judge it: absolute below fitness 60, % of fitness above (user's rule)."""
    return form / fitness * 100 if fitness > PERCENT_ABOVE else form


def zone(form, fitness):
    value = form_value(form, fitness)
    return next(name for name, lower in ZONES if value > lower)


def zone_floor(name):
    """Lowest form value that still counts as the named zone (e.g. 'grey' -> -10)."""
    return dict(ZONES)[name]
