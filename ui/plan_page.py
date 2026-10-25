"""Plan page: choose a plan and race, lay it out around your week, review it, push it."""

from datetime import date, datetime

import pandas as pd
import streamlit as st

import push
from import_plan import ImportError_, set_config, set_plan_fields
from layout import compute_layout, hard_days_summary, write_result
from planlib import DAYS, PlanError, blank, load_workbook_tables, save_workbook, to_date
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


def save_settings(plan, race_date, plan_tag, rest_fill, pre_race_fill):
    def change(wb):
        set_config(wb, "plan", plan)
        set_config(wb, "race_date", datetime.combine(race_date, datetime.min.time()))
        set_config(wb, "plan_tag", plan_tag)
        set_plan_fields(wb, plan, {"rest_fill": rest_fill or None, "pre_race_fill": pre_race_fill or None})
    error = saving(change)
    st.session_state.message = ("error", error) if error else (
        "success", "Settings saved. Lay out the plan again so the Layout matches them.")
    st.session_state.pop("picks", None)
    st.session_state.pop("preview", None)


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

# ---------- 1. plan and race ----------
st.subheader("1. Plan and race")
names = sorted(plans)
current = str(config.get("plan") or "").strip()
c1, c2, c3 = st.columns(3)
plan = c1.selectbox("Plan", names, index=names.index(current) if current in names else 0)
race_date = c2.date_input("Race date", value=to_date(config["race_date"]) if not blank(config.get("race_date"))
                          else date.today(), format="YYYY-MM-DD")
plan_tag = c3.text_input("plan_tag (Intervals ID prefix)", value=str(config.get("plan_tag") or ""))
easy = [""] + sorted(w for w, r in library.items() if str(r.get("category") or "").strip().lower() == "easy")
row = plans[plan]
c4, c5 = st.columns(2)
rest_now, pre_now = (str(row.get(k) or "").strip() for k in ("rest_fill", "pre_race_fill"))
rest_fill = c4.selectbox("Rest days become (blank = keep rest days)", easy,
                         index=easy.index(rest_now) if rest_now in easy else 0)
pre_race_fill = c5.selectbox("Day before the race (shortest run last)", easy,
                             index=easy.index(pre_now) if pre_now in easy else 0)
saved_date = to_date(config["race_date"]) if not blank(config.get("race_date")) else None
dirty = (plan != current or race_date != saved_date or plan_tag.strip() != str(config.get("plan_tag") or "").strip()
         or rest_fill != rest_now or pre_race_fill != pre_now)
if plan_tag.strip() != str(config.get("plan_tag") or "").strip() and config.get("plan_tag"):
    st.caption("Changing plan_tag after a push leaves the events pushed under the old tag in Intervals.")
st.button("Save settings", type="primary" if dirty else "secondary", disabled=not dirty or not plan_tag.strip(),
          on_click=save_settings, args=(plan, race_date, plan_tag.strip(), rest_fill, pre_race_fill))

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
    if saved_date and race_rows and to_date(race_rows[0]["date"]) != saved_date:
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
