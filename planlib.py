"""Shared helpers for layout.py and push.py: workbook reading, days, and plan rules."""

from datetime import date, datetime, timedelta

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
