"""Plan page: choose a plan and race, lay it out around your week, review it, push it."""

from datetime import date, datetime

import pandas as pd
import streamlit as st

import push
from import_plan import CATEGORIES, ImportError_, set_config, set_plan_fields
from layout import compute_layout, hard_days_summary, write_result, write_week
from planlib import (
    DAYS,
    PlanError,
    blank,
    hard_categories,
    load_workbook_tables,
    long_run_gap,
    read_week,
    save_workbook,
    taper_days,
    to_date,
    yes,
)
from ui.common import sidebar, workbook_path

# background colours for the calendar; text is set dark so it reads in light and dark themes
COLOURS = {"easy": "#d9ead3", "long": "#cfe2f3", "tuneup": "#f4cccc", "race": "#ea9999"}
HARD_COLOUR = "#fce5cd"

path = workbook_path()
sidebar(path)
try:
    _, config, library, sheets = load_workbook_tables(path)
except (FileNotFoundError, KeyError, PlanError) as e:
    st.error(f"Can't read {path}: {e}")
    st.stop()
plans = {str(r["plan"]).strip(): r for r in sheets.get("plans", []) if not blank(r.get("plan"))}
if not plans:
    st.info("No plans yet: import one on the Import page.")
    st.stop()


def saving(change):
    """Load the workbook fresh, apply change(wb), save. Returns an error message or None."""
    try:
        wb, *_ = load_workbook_tables(path)
        change(wb)
        save_workbook(wb, path)
    except (PlanError, ImportError_) as e:
        return str(e)
    return None


def save_settings(new):
    """Save section 1: Config plan/race/rules, the plan's rest-day fill, and the Week tab."""
    def change(wb):
        set_config(wb, "plan", new["plan"])
        set_config(wb, "race_date", datetime.combine(new["race_date"], datetime.min.time()))
        set_config(wb, "plan_tag", new["plan_tag"])
        for key in ("taper_days", "long_run_gap", "allow_pre_long", "long_run_days", "hard_categories"):
            set_config(wb, key, new[key])
        set_plan_fields(wb, new["plan"], {"rest_fill": new["rest_fill"] or None,
                                          "pre_race_fill": new["pre_race_fill"] or None})
        write_week(wb, new["week"])
    error = saving(change)
    st.session_state.message = ("error", error) if error else (
        "success", "Settings saved. Lay out the plan again so the Layout matches them.")
    st.session_state.pop("picks", None)
    st.session_state.pop("preview", None)


def week_choices(week):
    """Week tab -> one dropdown value per day: '' (open), 'long', 'quality' or a fixed workout_id."""
    return [wid if role == "fixed" else role if role in ("long", "quality") else "" for role, wid in
            (week[d] for d in range(7))]


def week_from_choices(choices):
    return {d: ("fixed", c) if c in library else (c, None) if c in ("long", "quality") else ("easy", None)
            for d, c in enumerate(choices)}


def lay_out(option=None):
    """Run layout. If hard sessions don't fit, keep the options to show instead of writing."""
    st.session_state.pop("preview", None)
    try:
        result = compute_layout(config, library, sheets, date.today(), option)
    except PlanError as e:
        st.session_state.message = ("error", str(e))
        return
    if "picks" in result:
        st.session_state.picks = result
        return
    st.session_state.pop("picks", None)
    error = saving(lambda wb: write_result(wb, result))
    changed = " Your Week tab was updated to the chosen option." if result["week_change"] else ""
    st.session_state.message = ("error", error) if error else ("success", f"Layout written.{changed}")


def check():
    """Dry run: what a push would send and delete. Reads Intervals, sends nothing."""
    try:
        if "layout" not in sheets:
            raise PlanError("No Layout tab yet: lay out the plan first")
        st.session_state.preview = push.preview(config, library, sheets["layout"], push.client_from_env())
    except PlanError as e:
        st.session_state.message = ("error", str(e))
    except Exception as e:  # network or API trouble: show it, don't crash the page
        st.session_state.message = ("error", f"Couldn't read Intervals.icu: {e}")


def send():
    """Push for real, from a fresh read of the workbook and Intervals."""
    try:
        _, cfg, lib, sh = load_workbook_tables(path)
        client = push.client_from_env()
        if client is None:
            raise PlanError("Set INTERVALS_ATHLETE_ID and INTERVALS_API_KEY in .env")
        p = push.preview(cfg, lib, sh["layout"], client)
        push.send(client, p["events"], p["stale"])
    except PlanError as e:
        st.session_state.message = ("error", str(e))
        return
    except Exception as e:
        st.session_state.message = ("error", f"Push failed: {e}")
        return
    deleted = f" Deleted {len(p['stale'])} stale events." if p["stale"] else ""
    st.session_state.message = ("success", f"Pushed {len(p['events'])} workouts to Intervals.icu.{deleted}")
    st.session_state.pop("preview", None)
    st.session_state.pop("confirm", None)


def calendar(rows):
    """Layout rows -> a week-by-week grid (Mon..Sun), coloured by category."""
    dated = [r for r in rows if not blank(r.get("date"))]
    weeks = {}
    for r in dated:
        d = to_date(r["date"])
        monday = d.toordinal() - d.weekday()
        weeks.setdefault(monday, {})[d.weekday()] = r
    grid, styles = [], []
    for monday in sorted(weeks):
        days = weeks[monday]
        label = date.fromordinal(monday).strftime("%b %d")
        grid.append({"week of": label, **{DAYS[i].title(): (days[i].get("name") or "") if i in days else ""
                                          for i in range(7)}})
        styles.append({DAYS[i].title(): style(days.get(i)) for i in range(7)})
    return grid, styles


def style(row):
    if not row or blank(row.get("workout_id")):
        return ""
    cat = str(row.get("category") or "")
    css = f"background-color: {COLOURS.get(cat, HARD_COLOUR)}; color: #1f1f1f"
    if to_date(row["date"]) < date.today():
        css += "; opacity: 0.45"
    return css


st.title("Plan")
if "message" in st.session_state:
    kind, text = st.session_state.pop("message")
    (st.success if kind == "success" else st.error)(text)

# ---------- 1. plan, race and your week ----------
st.subheader("1. Plan, race and your week")
names = sorted(plans)
current = str(config.get("plan") or "").strip()
labels = {"": "(open)", "long": "long run", "quality": "quality"}
options = ["", "long", "quality"] + sorted(library)
easy = [""] + sorted(w for w, r in library.items() if str(r.get("category") or "").strip().lower() == "easy")
try:
    saved_week = week_choices(read_week(sheets.get("week", []), library))
except PlanError as e:
    st.error(f"The Week tab has problems: {e}")
    saved_week = [""] * 7


def plan_fill(name):
    row = plans.get(name, {})
    return [v if v in easy else "" for v in (str(row.get(k) or "").strip() for k in ("rest_fill", "pre_race_fill"))]


saved = {
    "plan": current if current in names else names[0],
    "race_date": to_date(config["race_date"]) if not blank(config.get("race_date")) else None,
    "plan_tag": str(config.get("plan_tag") or "").strip(),
    "taper_days": taper_days(config), "long_run_gap": long_run_gap(config),
    "allow_pre_long": "yes" if yes(config.get("allow_pre_long")) else "no",
    "long_run_days": ", ".join(DAYS[d] for d in sorted(
        {DAYS.index(x.strip()[:3].lower()) for x in str(config.get("long_run_days") or "sat, sun").split(",")
         if x.strip()})),
    "hard_categories": ", ".join(c for c in sorted(CATEGORIES) if c in hard_categories(config)),
}

# Whenever the workbook file changes (Save settings, an option card, Lay out, the Import page, a save
# in Calc), section 1 reloads from it, so anything already saved never shows as an unsaved change.
stamp = path.stat().st_mtime_ns
if st.session_state.get("loaded") != stamp:
    st.session_state.update({
        "s_plan": saved["plan"], "s_race_date": saved["race_date"] or date.today(),
        "s_plan_tag": saved["plan_tag"], "s_taper_days": saved["taper_days"],
        "s_long_run_gap": saved["long_run_gap"], "s_allow_pre_long": saved["allow_pre_long"] == "yes",
        "s_long_run_days": saved["long_run_days"].split(", "),
        "s_hard_categories": saved["hard_categories"].split(", "),
        **{f"day{d}": saved_week[d] if saved_week[d] in options else "" for d in range(7)},
    })
    st.session_state.s_rest_fill, st.session_state.s_pre_race_fill = plan_fill(saved["plan"])
    st.session_state.loaded = stamp


def plan_changed():
    st.session_state.s_rest_fill, st.session_state.s_pre_race_fill = plan_fill(st.session_state.s_plan)


c1, c2, c3 = st.columns(3)
new = {"plan": c1.selectbox("Plan", names, key="s_plan", on_change=plan_changed),
       "race_date": c2.date_input("Race date", key="s_race_date", format="YYYY-MM-DD"),
       "plan_tag": c3.text_input("plan_tag (Intervals ID prefix)", key="s_plan_tag").strip()}

st.markdown("**Your week**: what each day is for. Layout fits the plan around it.")
cols = st.columns(7)
choices = [cols[d].selectbox(DAYS[d].title(), options, format_func=lambda o: labels.get(o, o), key=f"day{d}")
           for d in range(7)]
st.caption("**long run**: the long run and tune-up races. **quality**: hard sessions go here first. "
           "**A workout**: that day always gets it (e.g. a club run). **(open)**: no constraint; the plan's "
           "easy runs land here, and a hard session only if it fits nowhere else.")
new["week"] = week_from_choices(choices)
if sum(1 for c in choices if c == "long") > 1:
    st.error("Only one long-run day.")

c4, c5 = st.columns(2)
new["rest_fill"] = c4.selectbox("Rest days become (blank = keep rest days)", easy, key="s_rest_fill")
new["pre_race_fill"] = c5.selectbox("Day before the race (shortest run last)", easy, key="s_pre_race_fill")

with st.expander("Layout rules"):
    r1, r2 = st.columns(2)
    new["taper_days"] = r1.number_input("No hard sessions in the last N days before the race", 0, 14,
                                        key="s_taper_days")
    new["long_run_gap"] = r2.number_input("No long run within N days of the race", 0, 21, key="s_long_run_gap")
    new["allow_pre_long"] = "yes" if st.toggle(
        "Allow the plan's session the day before the long run (back-to-back hard days)",
        key="s_allow_pre_long") else "no"
    long_days = st.multiselect("Days the long run may move to when layout suggests options", DAYS,
                               key="s_long_run_days", format_func=str.title)
    hard = st.multiselect("Categories that count as hard", sorted(CATEGORIES), key="s_hard_categories")
    new["long_run_days"] = ", ".join(d for d in DAYS if d in long_days)  # order doesn't matter
    new["hard_categories"] = ", ".join(c for c in sorted(CATEGORIES) if c in hard)

saved["week"] = week_from_choices(saved_week)
saved["rest_fill"], saved["pre_race_fill"] = plan_fill(new["plan"])
NAMES = {"plan": "plan", "race_date": "race date", "plan_tag": "plan_tag", "rest_fill": "rest-day fill",
         "pre_race_fill": "day-before-race fill", "taper_days": "taper days", "long_run_gap": "long-run gap",
         "allow_pre_long": "pre-long session", "long_run_days": "long-run days", "hard_categories": "hard categories"}
unsaved = [DAYS[d].title() for d in range(7) if new["week"][d] != saved["week"][d]]
unsaved += [NAMES[k] for k in NAMES if new[k] != saved[k]]
dirty = bool(unsaved)
if new["plan_tag"] != saved["plan_tag"] and saved["plan_tag"]:
    st.caption("Changing plan_tag after a push leaves the events pushed under the old tag in Intervals.")
st.button("Save settings", type="primary" if dirty else "secondary",
          disabled=not dirty or not new["plan_tag"] or sum(1 for c in choices if c == "long") > 1,
          on_click=save_settings, args=(new,))
if dirty:
    st.caption("Not saved yet: " + ", ".join(unsaved))

# ---------- 2. lay out ----------
st.subheader("2. Lay out")
if dirty:
    st.info("Save the settings above first.")
else:
    st.write(f"Places **{current}** around your Week tab and fills rest days. This replaces the Layout tab, "
             "including anything you changed on it by hand.")
    st.button("Lay out", on_click=lay_out)

picks = st.session_state.get("picks")
if picks and not dirty:
    st.warning(f"{len(picks['missing'])} hard sessions don't fit your week. Choose how to change it:")
    for n, p in enumerate(picks["picks"]):
        with st.container(border=True):
            title = "Keep your week" if not p["changes"] else f"Option {n}"
            st.markdown(f"**{title}**: {len(p['missing'])} not placed")
            st.caption(hard_days_summary(p["week"], p["allow"]))
            for c in p["changes"]:
                st.markdown(f"- {c}")
            if p["off"]:
                st.caption(f"+{p['off']} sessions on non-quality days")
            if p["missing"] and not p["changes"]:
                st.caption("Not placed: " + ", ".join(f"wk{i['week']} {i['wid']}" for i, _ in p["missing"]))
            st.button("Use this", key=f"pick{n}", on_click=lay_out, args=(n,))

# ---------- 3. calendar ----------
st.subheader("3. Calendar")
layout_rows = sheets.get("layout", [])
if not layout_rows:
    st.info("No Layout yet.")
else:
    race_rows = [r for r in layout_rows if str(r.get("category") or "") == "race" and not blank(r.get("date"))]
    if saved["race_date"] and race_rows and to_date(race_rows[0]["date"]) != saved["race_date"]:
        st.warning("The Layout's race day doesn't match the race date: lay out again.")
    grid, styles = calendar(layout_rows)
    frame = pd.DataFrame(grid).set_index("week of")
    css = pd.DataFrame(styles, index=frame.index)
    st.dataframe(frame.style.apply(lambda _: css, axis=None), width="stretch",
                 height=min(38 * (len(grid) + 1) + 3, 900))
    unplaced = [r for r in layout_rows if blank(r.get("date"))]
    flagged = [r for r in layout_rows if r.get("flag") and not str(r["flag"]).startswith("past")]
    for r in unplaced + [r for r in flagged if r not in unplaced]:
        st.warning(f"{to_date(r['date']) if not blank(r.get('date')) else 'not placed'}: "
                   f"{r.get('name')} - {r.get('flag')}")
    st.caption("Green easy, blue long, orange hard, red races. Faded days are past and aren't pushed.")

# ---------- 4. push ----------
st.subheader("4. Push to Intervals.icu")
if dirty:
    st.info(f"Section 1 has changes that aren't saved ({', '.join(unsaved)}). Save them and lay out "
            "again, or set them back, so the check matches what you see.")
st.button("Check against Intervals", on_click=check, disabled=not layout_rows or dirty,
          help="Dry run: reads your Intervals calendar and shows what a push would do. Sends nothing.")
preview = st.session_state.get("preview")
if preview:
    events, stale = preview["events"], preview["stale"]
    first, last = (to_date(events[i]["start_date_local"]) for i in (0, -1))
    st.write(f"**{len(events)} workouts** would be sent ({first} to {last}), tagged `{config.get('plan_tag')}`.")
    if preview["existing"] is None:
        st.warning("No .env credentials, so Intervals wasn't checked and pushing is off.")
    else:
        st.write(f"Intervals has {preview['existing']} events in the window; "
                 f"{preview['found']} already belong to this plan_tag (they'll be updated in place).")
        if stale:
            st.warning(f"{len(stale)} future events of this plan would be **deleted**: " + ", ".join(stale))
        else:
            st.write("Nothing would be deleted.")
    for d, msg in preview["warnings"]:
        st.warning(f"{d}: {msg}")
    with st.expander("Workouts to send"):
        st.dataframe([{"date": e["start_date_local"][:10], "day": to_date(e["start_date_local"]).strftime("%a"),
                       "workout": e["name"]} for e in events], hide_index=True, width="stretch")
    if preview["existing"] is not None:
        confirm = st.checkbox(f"Send {len(events)} workouts to my Intervals calendar and watch"
                              + (f" and delete {len(stale)}" if stale else ""), key="confirm")
        st.button("Push", type="primary", disabled=not confirm, on_click=send)
