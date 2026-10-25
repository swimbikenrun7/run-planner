"""Shared helpers for layout.py and push.py: workbook reading, days, and plan rules."""

import re
from datetime import date, datetime, timedelta
from pathlib import Path

import openpyxl

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DEFAULT_HARD = {"interval", "threshold", "tempo", "fartlek", "hills", "steady", "long", "tuneup", "race"}
DEFAULT_TAPER_DAYS = 2


class PlanError(Exception):
    """Raised when the workbook fails validation."""


# ---------- reading ----------

def read_table(ws):
    """Return a sheet's rows as dicts keyed by the header row, skipping blank rows."""
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []
    headers = [str(h).strip().lower() if h is not None else "" for h in rows[0]]
    table = []
    for row in rows[1:]:
        if all(v is None or str(v).strip() == "" for v in row):
            continue
        table.append(dict(zip(headers, row)))
    return table


def load_workbook_tables(path):
    """Return (workbook, config, library, sheets) where sheets maps lowercase name -> rows."""
    wb = openpyxl.load_workbook(path)
    config = {str(r["key"]).strip(): r["value"] for r in read_table(wb["Config"])}
    library = {str(r["workout_id"]).strip(): r for r in read_table(wb["Library"])}
    sheets = {ws.title.lower(): read_table(ws) for ws in wb}
    return wb, config, library, sheets


# ---------- values ----------

def to_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value).strip()[:10])


def day_index(label):
    """'Thu', 'thu', 'Thursday' -> 3."""
    key = str(label).strip().lower()[:3]
    if key not in DAYS:
        raise PlanError(f"unknown day {label!r}")
    return DAYS.index(key)


def blank(value):
    return value is None or str(value).strip() == ""


def category_of(library, workout_id):
    return str(library[workout_id].get("category") or "").strip().lower()


# ---------- config ----------

def hard_categories(config):
    raw = config.get("hard_categories")
    if blank(raw):
        return set(DEFAULT_HARD)
    return {c.strip().lower() for c in str(raw).split(",") if c.strip()}


def taper_days(config):
    raw = config.get("taper_days")
    return DEFAULT_TAPER_DAYS if blank(raw) else int(raw)


# ---------- rules ----------

def rule_violations(entries, race_date, hard, taper):
    """Check a dated plan against the spacing rules.

    entries: iterable of (date, category). Returns a list of (date, message).
    """
    hard_dates = sorted({d for d, cat in entries if cat in hard})
    problems = []
    for a, b in zip(hard_dates, hard_dates[1:]):
        if (b - a).days == 1:
            problems.append((b, f"back-to-back hard days ({a} and {b})"))
    taper_window = {race_date - timedelta(days=k) for k in range(1, taper + 1)}
    for d in hard_dates:
        if d in taper_window:
            problems.append((d, f"hard day within {taper} days of the race"))
    return problems


DEFAULT_LONG_RUN_GAP = 5
ROLES = {"long", "quality", "fixed", "easy"}


def long_run_gap(config):
    """A long run must be more than this many days before the race."""
    raw = config.get("long_run_gap")
    return DEFAULT_LONG_RUN_GAP if blank(raw) else int(raw)


def yes(value):
    return str(value or "").strip().lower() in {"yes", "y", "true", "1"}


def last_used_row(ws):
    """Last row with any content (Excel often formats thousands of empty rows below data)."""
    for r in range(ws.max_row, 0, -1):
        if any(c.value not in (None, "") for c in ws[r]):
            return r
    return 0


def lock_file(path):
    """LibreOffice Calc keeps .~lock.<name># beside a workbook while it's open."""
    path = Path(path)
    return path.with_name(f".~lock.{path.name}#")


def save_workbook(wb, path):
    """Save, refusing while the workbook is open: Calc would overwrite our changes on its next save."""
    lock = lock_file(path)
    if lock.exists():
        raise PlanError(f"Could not save: {Path(path).name} is open in LibreOffice Calc. "
                        f"Close it and run again.\n(If Calc isn't running, delete the leftover lock file {lock})")
    try:
        wb.save(path)
    except PermissionError:
        raise PlanError("Could not save: close the workbook and run again.")


def read_week(rows, library):
    """Week tab -> {weekday index: (role, workout_id or None)}. Every weekday must appear once."""
    week, errors = {}, []
    for r in rows:
        try:
            d = day_index(r.get("day"))
        except PlanError as e:
            errors.append(f"Week tab: {e}")
            continue
        role = str(r.get("role") or "easy").strip().lower()
        wid = None if blank(r.get("workout_id")) else str(r["workout_id"]).strip()
        if role not in ROLES:
            errors.append(f"Week tab {DAYS[d].title()}: role {role!r} not one of {', '.join(sorted(ROLES))}")
        elif role == "fixed" and (wid is None or wid not in library):
            errors.append(f"Week tab {DAYS[d].title()}: fixed day needs a workout_id that's in Library")
        if d in week:
            errors.append(f"Week tab: {DAYS[d].title()} appears twice")
        week[d] = (role, wid)
    for d in range(7):
        week.setdefault(d, ("easy", None))
    if sum(1 for role, _ in week.values() if role == "long") > 1:
        errors.append("Week tab: only one long day allowed")
    if errors:
        raise PlanError("\n".join(errors))
    return week


# ---------- rest-day fill (user: rest days become easy runs, shorter the day before the race) ----------

# (workout_id, name, length) for each kind of plan: (rest_fill, pre_race_fill)
FILL_WORKOUTS = {
    "distance": (("EASY-3MI", "Easy 3mi", "3mi"), ("EASY-2MI", "Easy 2mi", "2mi")),
    "time": (("EASY-30", "Easy 30", "30m"), ("EASY-20", "Easy 20", "20m")),
}
LENGTH_UNIT = re.compile(r"\d(mi|km|mtr|h|m|s)$")


def easy_run_unit(texts):
    """'distance' or 'time': how a plan writes its single-step easy runs. Distance on a tie."""
    units = [LENGTH_UNIT.search(t.strip()) for t in texts if t and " / " not in t]
    time = sum(1 for m in units if m and m.group(1) in ("h", "m", "s"))
    distance = sum(1 for m in units if m and m.group(1) in ("mi", "km", "mtr"))
    return "time" if time > distance else "distance"


def plan_easy_texts(workout_ids, library):
    return [str(library[w].get("workout_text") or "") for w in workout_ids
            if w in library and str(library[w].get("category") or "").strip().lower() == "easy"]


def fill_workouts(unit, easy_target, library):
    """(rest_fill id, pre_race_fill id, Library rows to add for any that are missing)."""
    ids, missing = [], []
    for wid, name, length in FILL_WORKOUTS[unit]:
        ids.append(wid)
        if wid not in library:
            missing.append({"workout_id": wid, "category": "easy", "name": name,
                            "workout_text": f"- Press lap {easy_target} {length}"})
    return ids[0], ids[1], missing
