"""Lay the selected plan onto real dates around your week, and suggest structural changes
when the plan doesn't fit.

Usage:
    python layout.py plans/plan_builder.xlsx              # check, then lay out (or suggest)
    python layout.py plans/plan_builder.xlsx --option 2   # apply suggestion 2, then lay out

Inputs:
  Config:   plan (which plan in Schedule), race_date, taper_days, long_run_gap, allow_pre_long
  Week:     a role for each weekday: long, quality, fixed (with a workout_id) or easy
  Plans:    each plan's source_week_end (the weekday its weeks end on)
  Schedule: plan / week / day / workout_id / note

Rules:
  - the race goes on race_date; no hard session within taper_days before it
  - long runs (and tune-up races) go on the long day, never within long_run_gap days of the race
  - other hard sessions go on quality days in their plan order; if a week runs out of quality
    days, a session may use another legal day in the same week
  - no two hard days back to back, except (when allow_pre_long is yes) a session the plan put
    the day before its long run, placed the day before your long run
  - fixed days always get their workout
  - easy runs and rest days fill what's left; dates before today are shown but never pushed

If hard sessions are left unplaced, nothing is written: the script lists structural options
(a different long day, other quality days, skipping a fixed workout, allowing the plan's
pre-long-run session) ranked by how well they fit, and you pick one with --option.
Close the workbook in Excel before running.
"""

import argparse
import sys
from datetime import date, timedelta
from itertools import combinations

from openpyxl.styles import Font, PatternFill

from planlib import (
    DAYS,
    PlanError,
    blank,
    category_of,
    day_index,
    hard_categories,
    last_used_row,
    load_workbook_tables,
    long_run_gap,
    read_week,
    run_length,
    save_workbook,
    taper_days,
    to_date,
    yes,
)

ONE = timedelta(days=1)
LAYOUT_SHEET = "Layout"
OPTIONS_SHEET = "Options"
LAYOUT_HEADERS = ["date", "day", "week", "workout_id", "category", "name",
                  "source_day", "moved", "flag", "note"]
MAX_QUALITY_DAYS = 4


# ---------- reading the plan ----------

def selected_plan(config, sheets):
    """Return (plan name, source week-end index, that plan's Schedule rows)."""
    name = None if blank(config.get("plan")) else str(config["plan"]).strip()
    if name is None:
        raise PlanError("Config is missing plan (which plan in Schedule to lay out)")
    plans = {str(r["plan"]).strip(): r for r in sheets.get("plans", []) if not blank(r.get("plan"))}
    if name not in plans:
        raise PlanError(f"plan {name!r} is not on the Plans tab")
    week_end = day_index(plans[name].get("source_week_end"))
    rows = [r for r in sheets["schedule"] if str(r.get("plan") or "").strip() == name]
    if not rows:
        raise PlanError(f"Schedule has no rows for plan {name!r}")
    return name, week_end, rows


def plan_fill(sheets, name, library):
    """The plan's (rest_fill, pre_race_fill) workout ids from the Plans tab; None = keep rest days."""
    row = next(r for r in sheets.get("plans", []) if str(r.get("plan") or "").strip() == name)
    fill = tuple(None if blank(row.get(k)) else str(row[k]).strip() for k in ("rest_fill", "pre_race_fill"))
    bad = [w for w in fill if w and w not in library]
    if bad:
        raise PlanError(f"Plans tab {name}: rest-day fill {', '.join(bad)} not in Library")
    return fill


def plan_items(race_date, week_end, library, rows):
    """Schedule rows -> items with a naive date (same position relative to the race)."""
    errors, cells = [], {}
    for i, row in enumerate(rows, start=2):
        try:
            week = int(row["week"])
            src_day = day_index(row["day"])
        except (TypeError, ValueError, PlanError) as e:
            errors.append(f"Schedule row {i}: bad week/day ({e})")
            continue
        wid = None if blank(row.get("workout_id")) else str(row["workout_id"]).strip()
        if wid is not None and wid not in library:
            errors.append(f"Schedule row {i}: workout_id {wid!r} not in Library")
            continue
        offset = (week_end - src_day) % 7
        if (week, offset) in cells:
            errors.append(f"Schedule row {i}: week {week} {row['day']} appears twice")
            continue
        cells[(week, offset)] = (wid, DAYS[src_day].title(), row.get("note"))
    if errors:
        raise PlanError("\n".join(errors))

    first_week = min(w for w, _ in cells)
    last_week = max(w for w, _ in cells)
    items = []
    for week in range(first_week, last_week + 1):
        for offset in range(6, -1, -1):
            wid, src_day, note = cells.get((week, offset), (None, DAYS[(week_end - offset) % 7].title(), None))
            items.append({
                "wid": wid,
                "category": category_of(library, wid) if wid else "rest",
                "source_day": src_day,
                "note": note,
                "naive": race_date - timedelta(weeks=last_week - week, days=offset),
                "week": week,
            })
    return items, last_week


# ---------- placement ----------

class Context:
    def __init__(self, race_date, hard, taper, gap, library, today, items, last_week):
        self.race_date = race_date
        self.hard = hard
        self.taper_window = {race_date - timedelta(days=k) for k in range(1, taper + 1)}
        self.gap = gap
        self.library = library
        self.today = today
        self.items = items
        self.last_week = last_week
        self.plan_start = items[0]["naive"]
        self.days = [self.plan_start + timedelta(days=k)
                     for k in range((race_date - self.plan_start).days + 1)]
        by_naive = {i["naive"]: i for i in items}
        # sessions the plan put on the day before one of its long runs
        self.pairs = {id(i) for i in items
                      if i["category"] in hard and i["category"] not in ("long", "race", "tuneup")
                      and by_naive.get(i["naive"] + ONE, {}).get("category") == "long"}

    def block(self, d):
        return self.last_week - (self.race_date - d).days // 7


def place(ctx, week, allow_pre_long, off_template=None):
    """Place every item. Returns (placed: date -> item, unplaced: list of (item, reason)).

    off_template, if given, collects the dates of hard sessions that had to use a day that
    isn't a quality day in your week.
    """
    placed, hard_days, unplaced = {}, set(), []
    long_idx = next((d for d, (role, _) in week.items() if role == "long"), None)
    quality = {d for d, (role, _) in week.items() if role == "quality"}

    def put(d, item, hard):
        placed[d] = item
        if hard:
            hard_days.add(d)

    def legal(d, pair_ok=False):
        if not (ctx.plan_start <= d < ctx.race_date) or d in ctx.taper_window or d in placed:
            return False
        before, after = d - ONE in hard_days, d + ONE in hard_days
        if after and pair_ok and placed[d + ONE]["category"] == "long":
            after = False
        return not before and not after

    # race and fixed days
    races = [i for i in ctx.items if i["category"] == "race"]
    if races:
        put(ctx.race_date, races[0], True)
    for i in races[1:]:
        unplaced.append((i, "more than one race in the plan"))
    for d in ctx.days:
        role, wid = week[d.weekday()]
        if role == "fixed" and d not in placed:
            cat = category_of(ctx.library, wid)
            put(d, {"wid": wid, "category": cat, "source_day": "(your week)", "note": None,
                    "naive": d, "fixed": True}, cat in ctx.hard)

    blocks = {}
    for i in ctx.items:
        blocks.setdefault(i["week"], []).append(i)

    # long runs and tune-up races on the long day, all weeks first
    for wk in sorted(blocks):
        long_type = [i for i in blocks[wk] if i["category"] in ("tuneup", "long")]
        long_type.sort(key=lambda i: i["category"] != "tuneup")  # tune-up race takes the slot
        slot = next((d for d in ctx.days if ctx.block(d) == wk and d.weekday() == long_idx), None)
        for n, item in enumerate(long_type):
            ok_gap = slot is not None and (item["category"] == "tuneup"
                                           or (ctx.race_date - slot).days > ctx.gap)
            if n == 0 and slot is not None and ok_gap and legal(slot):
                put(slot, item, True)
            elif item["category"] == "long" and slot is not None and not ok_gap:
                unplaced.append((item, f"long run within {ctx.gap} days of the race"))
            else:
                unplaced.append((item, "no long-run day free this week"))

    # other hard sessions, in plan order, on quality days, then any legal day that week
    for wk in sorted(blocks):
        week_days = [d for d in ctx.days if ctx.block(d) == wk]
        long_day = next((d for d in week_days if d.weekday() == long_idx and d in placed
                         and placed[d]["category"] == "long"), None)
        others = [i for i in blocks[wk] if i["category"] in ctx.hard
                  and i["category"] not in ("long", "tuneup", "race")]
        for item in others:
            spot = None
            if allow_pre_long and id(item) in ctx.pairs and long_day is not None:
                pre = long_day - ONE
                if pre.weekday() in quality and legal(pre, pair_ok=True):
                    spot = pre
            if spot is None:
                spot = next((d for d in week_days if d.weekday() in quality and legal(d)), None)
            if spot is None:
                fallback = sorted((d for d in week_days if legal(d)),
                                  key=lambda d: (d > item["naive"], abs((d - item["naive"]).days)))
                spot = fallback[0] if fallback else None
                if spot is not None and off_template is not None:
                    off_template.append(spot)
            if spot is None:
                unplaced.append((item, "no legal day left in its week"))
            else:
                put(spot, item, True)

    # easy runs keep their own date when free, otherwise the nearest open day in their own week
    # (earlier first, like hard sessions); the plan's rest days give way to them
    displaced = []
    for item in (i for i in ctx.items if i["wid"] and i["category"] not in ctx.hard):
        if item["naive"] not in placed and ctx.plan_start <= item["naive"] <= ctx.race_date:
            placed[item["naive"]] = item
        else:
            displaced.append(item)
    for item in displaced:
        free = sorted((d for d in ctx.days if ctx.block(d) == item["week"] and d not in placed),
                      key=lambda d: (d > item["naive"], abs((d - item["naive"]).days)))
        if free:
            placed[free[0]] = item
        else:
            unplaced.append((item, "no free day for this easy run in its week"))
    rest = {i["naive"]: i for i in ctx.items if not i["wid"]}
    for d in ctx.days:
        if d not in placed:
            placed[d] = rest.get(d) or {"wid": None, "category": "rest", "source_day": "", "note": None, "naive": d}
    return placed, unplaced


def fill_rest_days(ctx, placed, rest_fill, pre_race_fill):
    """Rest days left after placement become rest_fill easy runs. In race week the shortest run
    goes on the day before the race (user): the plan's own easy run if it's no longer than
    pre_race_fill, otherwise pre_race_fill itself."""
    pre = ctx.race_date - ONE
    if pre_race_fill and pre in placed:
        slots = [d for d in ctx.days if ctx.block(d) == ctx.last_week and d < ctx.race_date
                 and not placed[d].get("fixed") and placed[d]["category"] in ("easy", "rest")]
        shakeout = length_of(ctx, pre_race_fill)
        lengths = [(length_of(ctx, placed[d]["wid"]), d) for d in slots if placed[d]["wid"]]
        short = min(((n, d) for (kind, n), d in ((l, d) for l, d in lengths if l)
                     if shakeout and kind == shakeout[0]), default=None)  # (length, date)
        if pre in slots and short and short[0] <= shakeout[1]:
            placed[pre], placed[short[1]] = placed[short[1]], placed[pre]
        elif pre in slots:
            if placed[pre]["wid"]:  # a longer plan run: move it to an earlier open day, if any
                free = [d for d in slots if not placed[d]["wid"] and d != pre]
                if free:
                    placed[free[-1]], placed[pre] = placed[pre], placed[free[-1]]
            if not placed[pre]["wid"]:
                placed[pre] = filled(ctx, placed[pre], pre, pre_race_fill)
    for d in ctx.days:
        if not placed[d]["wid"] and d != ctx.race_date and rest_fill:
            placed[d] = filled(ctx, placed[d], d, rest_fill)


def length_of(ctx, wid):
    return run_length(str(ctx.library.get(wid, {}).get("workout_text") or ""))


def filled(ctx, rest_item, d, wid):
    was = f" (plan: {rest_item['note']})" if rest_item.get("note") else ""
    return {"wid": wid, "category": category_of(ctx.library, wid), "source_day": "(rest fill)",
            "note": f"rest day filled{was}", "naive": d}


def violations(ctx, placed, allow_pre_long):
    out = []
    hard = sorted(d for d, i in placed.items() if i["category"] in ctx.hard)
    for a, b in zip(hard, hard[1:]):
        if (b - a).days == 1:
            pair_ok = (allow_pre_long and placed[b]["category"] == "long"
                       and id(placed[a]) in ctx.pairs)
            if not pair_ok:
                out.append((b, f"back-to-back hard days ({a} and {b})"))
    out += [(d, "hard day inside the taper") for d in hard
            if d in ctx.taper_window]
    return out


def future_hard(ctx, unplaced):
    return [(i, why) for i, why in unplaced
            if i["category"] in ctx.hard and i["naive"] >= ctx.today]


# ---------- structural suggestions ----------

def describe(base, cand, base_allow, cand_allow):
    """List the changes from your week to a candidate week, and their cost."""
    changes, cost = [], 0.0
    for d in range(7):
        (r0, w0), (r1, _) = base[d], cand[d]
        if r0 != r1:
            label = f"{r0} ({w0})" if r0 == "fixed" else r0
            note = f" - skips {w0}" if r0 == "fixed" else ""
            changes.append(f"{DAYS[d].title()}: {label} -> {r1}{note}")
            cost += 3 if r0 == "fixed" else 1
    if cand_allow and not base_allow:
        changes.append("allow the plan's pre-long-run session the day before the long run")
        cost += 0.5
    return changes, cost


def candidate_weeks(base, long_days):
    fixed = [d for d, (r, _) in base.items() if r == "fixed"]
    for long_day in long_days:
        for drop in range(len(fixed) + 1):
            for dropped in combinations(fixed, drop):
                kept = [f for f in fixed if f not in dropped]
                if long_day in kept:
                    continue
                free = [d for d in range(7) if d != long_day and d not in kept]
                for n in range(1, MAX_QUALITY_DAYS + 1):
                    for q in combinations(free, n):
                        for allow in (False, True):
                            pre = (long_day - 1) % 7
                            if allow and pre not in q:
                                continue
                            if any(f not in q for f in dropped):
                                continue  # skipping a fixed workout only helps if the day becomes quality
                            hard = set(q) | {long_day}
                            bad = any(d in hard and (d + 1) % 7 in hard
                                      and not (allow and d == pre)
                                      for d in range(7))
                            if bad:
                                continue
                            week = {}
                            for d in range(7):
                                if d == long_day:
                                    week[d] = ("long", None)
                                elif d in kept:
                                    week[d] = base[d]
                                elif d in q:
                                    week[d] = ("quality", base[d][1] if base[d][0] == "fixed" else None)
                                else:
                                    week[d] = ("easy", None)
                            yield week, allow


def suggest(ctx, base, base_allow, long_days):
    """Your week as it is, plus the best alternative in each kind of change:
    keep the long day and fixed days / keep the long day / move the long day keeping fixed
    days / move the long day. Best = fewest sessions left unplaced, then fewest changes."""
    base_long = next((d for d, (r, _) in base.items() if r == "long"), None)

    def evaluate(week, allow):
        off = []
        placed, unplaced = place(ctx, week, allow, off)
        if violations(ctx, placed, allow):
            return None
        changes, cost = describe(base, week, base_allow, allow)
        future_off = [d for d in off if d >= ctx.today]
        return {"week": week, "allow": allow, "missing": future_hard(ctx, unplaced),
                "changes": changes, "cost": cost + 0.25 * len(future_off), "off": len(future_off)}

    current = evaluate(base, base_allow) or {
        "week": base, "allow": base_allow, "changes": [], "cost": 0.0, "off": 0,
        "missing": future_hard(ctx, place(ctx, base, base_allow)[1])}
    best = {}
    for week, allow in candidate_weeks(base, long_days):
        r = evaluate(week, allow)
        if r is None or not r["changes"] or len(r["missing"]) >= len(current["missing"]):
            continue
        long_moved = week.get(base_long, ("",))[0] != "long"
        skips = any("skips" in c for c in r["changes"])
        kinds = ["move long" if long_moved else "keep long"]
        if not skips:
            kinds.append(kinds[0] + ", keep fixed")
        for kind in kinds:
            if kind not in best or (len(r["missing"]), r["cost"]) < (len(best[kind]["missing"]), best[kind]["cost"]):
                best[kind] = r
    picks, seen = [current], []
    for kind in ("keep long, keep fixed", "keep long", "move long, keep fixed", "move long"):
        r = best.get(kind)
        if r and not any(r is p for p in picks):
            picks.append(r)
    return picks


def long_run_days(config, week):
    """Days the long run may move to (Config long_run_days, default Sat and Sun, plus today's)."""
    raw = config.get("long_run_days") or "sat, sun"
    days = {day_index(d) for d in str(raw).split(",") if d.strip()}
    days |= {d for d, (r, _) in week.items() if r == "long"}
    return sorted(days)


# ---------- output ----------

def layout_rows(ctx, placed, unplaced, allow_pre_long):
    rows = []
    for d in ctx.days:
        item = placed[d]
        wid = item["wid"]
        flag = "past: not pushed" if d < ctx.today else ""
        rows.append({
            "date": d, "day": d.strftime("%a"), "week": ctx.block(d), "workout_id": wid,
            "category": item["category"],
            "name": str(ctx.library[wid].get("name") or wid) if wid else "Rest",
            "source_day": item["source_day"],
            "moved": "yes" if wid and not item.get("fixed") and d != item["naive"] else "",
            "flag": flag, "note": item["note"],
        })
    by_date = {r["date"]: r for r in rows}
    for d, msg in violations(ctx, placed, allow_pre_long):
        by_date[d]["flag"] = "; ".join(filter(None, [by_date[d]["flag"], msg]))
    for item, why in unplaced:
        rows.append({"date": None, "day": None, "week": item["week"], "workout_id": item["wid"],
                     "category": item["category"],
                     "name": str(ctx.library[item["wid"]].get("name") or item["wid"]),
                     "source_day": item["source_day"], "moved": "", "flag": f"NOT PLACED: {why}",
                     "note": item["note"]})
    return rows


def write_layout(wb, rows):
    if LAYOUT_SHEET in wb.sheetnames:
        del wb[LAYOUT_SHEET]
    ws = wb.create_sheet(LAYOUT_SHEET)
    ws.append(LAYOUT_HEADERS)
    for r in rows:
        ws.append([r[h] for h in LAYOUT_HEADERS])
    fills = {"flag": PatternFill("solid", fgColor="FFF2CC"),
             "moved": PatternFill("solid", fgColor="DDEBF7"),
             "past": PatternFill("solid", fgColor="EDEDED")}
    for row in ws.iter_rows():
        for c in row:
            c.font = Font(name="Arial", bold=c.row == 1)
    for i, r in enumerate(rows, start=2):
        ws.cell(i, 1).number_format = "yyyy-mm-dd"
        kind = ("past" if r["flag"].startswith("past") else "flag" if r["flag"]
                else "moved" if r["moved"] else None)
        if kind:
            for c in ws[i]:
                c.fill = fills[kind]
    for col, w in {"A": 12, "B": 6, "C": 6, "D": 16, "E": 11, "F": 22, "G": 11,
                   "H": 7, "I": 44, "J": 20}.items():
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "A2"


def hard_days_summary(week, allow):
    q = [DAYS[d].title() for d in range(7) if week[d][0] == "quality"]
    long_day = next((DAYS[d].title() for d in range(7) if week[d][0] == "long"), "-")
    fixed = [f"{DAYS[d].title()} {week[d][1]}" for d in range(7) if week[d][0] == "fixed"]
    text = f"long {long_day}; quality {', '.join(q) or '-'}; fixed {', '.join(fixed) or '-'}"
    return text + ("; pre-long session allowed" if allow else "")


def week_summary(week, allow):
    parts = []
    for d in range(7):
        role, wid = week[d]
        parts.append(f"{DAYS[d].title()} {role}" + (f" ({wid})" if role == "fixed" else ""))
    return ", ".join(parts) + ("; pre-long session allowed" if allow else "")


def write_options(wb, picks):
    if OPTIONS_SHEET in wb.sheetnames:
        del wb[OPTIONS_SHEET]
    ws = wb.create_sheet(OPTIONS_SHEET)
    ws.append(["option", "sessions not placed", "changes", "resulting week", "not placed"])
    for n, p in enumerate(picks):
        ws.append([n, len(p["missing"]), "; ".join(p["changes"]) or "(keep your week)",
                   week_summary(p["week"], p["allow"]),
                   "; ".join(f"wk{i['week']} {i['wid']}" for i, _ in p["missing"])])
    for row in ws.iter_rows():
        for c in row:
            c.font = Font(name="Arial", bold=c.row == 1)
    for col, w in {"A": 7, "B": 10, "C": 70, "D": 80, "E": 60}.items():
        ws.column_dimensions[col].width = w


def save_week(wb, week, allow):
    ws = wb["Week"]
    headers = [str(c.value).strip().lower() for c in ws[1]]
    col = {h: i + 1 for i, h in enumerate(headers)}
    for r in range(2, last_used_row(ws) + 1):
        try:
            d = day_index(ws.cell(r, col["day"]).value)
        except PlanError:
            continue
        ws.cell(r, col["role"]).value = week[d][0]
    cfg = wb["Config"]
    keys = {str(cfg.cell(r, 1).value).strip(): r for r in range(2, last_used_row(cfg) + 1)}
    value = "yes" if allow else "no"
    if "allow_pre_long" in keys:
        cfg.cell(keys["allow_pre_long"], 2).value = value
    else:
        cfg.cell(last_used_row(cfg) + 1, 1).value = "allow_pre_long"
        cfg.cell(last_used_row(cfg), 2).value = value


def main(argv=None, today=None):
    parser = argparse.ArgumentParser(description="Lay out the selected plan around your week.")
    parser.add_argument("workbook")
    parser.add_argument("--option", type=int, help="apply suggestion N (0 keeps your week) and lay out")
    args = parser.parse_args(argv)
    today = today or date.today()

    try:
        wb, config, library, sheets = load_workbook_tables(args.workbook)
        if blank(config.get("race_date")):
            raise PlanError("Config is missing race_date")
        race_date = to_date(config["race_date"])
        name, week_end, rows = selected_plan(config, sheets)
        rest_fill, pre_race_fill = plan_fill(sheets, name, library)
        week = read_week(sheets.get("week", []), library)
        items, last_week = plan_items(race_date, week_end, library, rows)
    except PlanError as e:
        print(f"Plan has problems:\n{e}", file=sys.stderr)
        return 1

    ctx = Context(race_date, hard_categories(config), taper_days(config), long_run_gap(config),
                  library, today, items, last_week)
    allow = yes(config.get("allow_pre_long"))
    placed, unplaced = place(ctx, week, allow)
    missing = future_hard(ctx, unplaced)

    if missing or args.option is not None:
        picks = suggest(ctx, week, allow, long_run_days(config, week))
        if args.option is None:
            write_options(wb, picks)
            if not save(wb, args.workbook):
                return 1
            print(f"{name}: {len(missing)} hard sessions don't fit your week. Options "
                  f"(also on the Options tab):\n")
            for n, p in enumerate(picks):
                extra = f" (+{p['off']} sessions on non-quality days)" if p["off"] else ""
                print(f"  [{n}] {len(p['missing'])} not placed -> {hard_days_summary(p['week'], p['allow'])}{extra}")
                for c in p["changes"] or ["(keep your week as it is)"]:
                    print(f"        {c}")
                if p["missing"] and n == 0:
                    print("        not placed: " + ", ".join(f"wk{i['week']} {i['wid']}" for i, _ in p["missing"]))
            print(f"\nPick one: python layout.py {args.workbook} --option N")
            return 2
        if not 0 <= args.option < len(picks):
            print(f"--option must be 0 to {len(picks) - 1}", file=sys.stderr)
            return 1
        chosen = picks[args.option]
        week, allow = chosen["week"], chosen["allow"]
        if chosen["changes"]:
            save_week(wb, week, allow)
        placed, unplaced = place(ctx, week, allow)

    fill_rest_days(ctx, placed, rest_fill, pre_race_fill)
    rows = layout_rows(ctx, placed, unplaced, allow)
    write_layout(wb, rows)
    if OPTIONS_SHEET in wb.sheetnames:
        del wb[OPTIONS_SHEET]
    if not save(wb, args.workbook):
        return 1

    dated = [r for r in rows if r["date"]]
    print(f"{name}: Layout written, {dated[0]['date']} to {dated[-1]['date']} "
          f"({sum(1 for r in dated if r['date'] < today)} days before today, not pushed).")
    for r in rows:
        if r["flag"] and not r["flag"].startswith("past"):
            print(f"  {r['date'] or '      --  '} {r['name']}: {r['flag']}")
    print("Review the Layout tab, then run push.py.")
    return 0


def save(wb, path):
    try:
        save_workbook(wb, path)
        return True
    except PlanError as e:
        print(e, file=sys.stderr)
        return False


if __name__ == "__main__":
    sys.exit(main())
