"""Calendar page: everything on Intervals.icu by plan, with the gaps between plans. Read-only."""

from datetime import date, timedelta

import pandas as pd
import streamlit as st

import push
from master import MIN_GAP_DAYS, summarize
from planlib import DAYS, PlanError, blank, load_workbook_tables, to_date
from ui.common import sidebar, workbook_path

PALETTE = ["#cfe2f3", "#d9ead3", "#fce5cd", "#d9d2e9", "#fff2cc", "#d0e0e3", "#f4cccc", "#ead1dc"]
RACE_COLOUR, GAP_COLOUR, MANUAL_COLOUR = "#ea9999", "#eeeeee", "#ffffff"

path = workbook_path()
sidebar(path)
try:
    _, config, library, sheets = load_workbook_tables(path)
except (FileNotFoundError, KeyError, PlanError) as e:
    st.error(f"Can't read {path}: {e}")
    st.stop()

# which plan and race each Intervals tag belongs to (recorded when a plan is pushed)
by_tag = {}
for r in sheets.get("plans", []):
    if not blank(r.get("plan_tag")):
        by_tag[str(r["plan_tag"]).strip()] = {
            "plan": str(r.get("plan") or "").strip(),
            "race": to_date(r["race_date"]) if not blank(r.get("race_date")) else None}
if not blank(config.get("plan_tag")) and str(config["plan_tag"]).strip() not in by_tag:
    by_tag[str(config["plan_tag"]).strip()] = {
        "plan": str(config.get("plan") or "").strip(),
        "race": to_date(config["race_date"]) if not blank(config.get("race_date")) else None}

st.title("Calendar")
st.write("Everything on your Intervals.icu calendar, by plan, and the gaps between plans. "
         "This page only reads.")

today = date.today()
start = today - timedelta(days=today.weekday())  # Monday of this week
months = st.select_slider("Show", options=[3, 6, 9, 12, 18], value=9, format_func=lambda m: f"{m} months")
end = start + timedelta(days=round(months * 30.4))


def load():
    client = push.client_from_env()
    if client is None:
        st.session_state.cal_error = "Set INTERVALS_ATHLETE_ID and INTERVALS_API_KEY in .env"
        return
    try:
        st.session_state.cal_events = client.list_events(start, start + timedelta(days=round(18 * 30.4)))
        st.session_state.pop("cal_error", None)
    except Exception as e:  # network or API trouble: show it, don't crash the page
        st.session_state.cal_error = f"Couldn't read Intervals.icu: {e}"


if "cal_events" not in st.session_state and "cal_error" not in st.session_state:
    load()
st.button("Refresh from Intervals", on_click=load)
if "cal_error" in st.session_state:
    st.error(st.session_state.cal_error)
    st.stop()

cal = summarize(st.session_state.cal_events, {t: v["race"] for t, v in by_tag.items()}, start, end)
colour = {p["tag"]: PALETTE[i % len(PALETTE)] for i, p in enumerate(cal["plans"])}

st.subheader("Plans")
if not cal["plans"]:
    st.info("No plans on Intervals in this range.")
else:
    st.dataframe([{"plan_tag": p["tag"], "plan": by_tag.get(p["tag"], {}).get("plan", ""),
                   "first workout": p["first"], "last workout": p["last"],
                   "race": p["race"], "workouts": p["workouts"]} for p in cal["plans"]],
                 hide_index=True, width="stretch")
    unknown = [p["tag"] for p in cal["plans"] if not p["race"]]
    if unknown:
        st.caption(f"No race date on the Plans tab for {', '.join(unknown)}: it's filled in when a plan is "
                   "pushed, or add plan_tag and race_date to that plan's row by hand.")

st.subheader("Gaps")
if cal["gaps"]:
    for first, last in cal["gaps"]:
        more = " (and past the end of what's shown)" if last == end else ""
        st.markdown(f"- **{first:%a %b %d, %Y} to {last:%a %b %d, %Y}**: {(last - first).days + 1} days "
                    f"with nothing planned{more}")
else:
    st.write(f"No gaps of {MIN_GAP_DAYS} days or more.")

st.subheader("Weeks")
gap_days = {first + timedelta(days=k) for first, last in cal["gaps"] for k in range((last - first).days + 1)}
grid, styles = [], []
monday = start
while monday <= end:
    cells, css = {}, {}
    for i in range(7):
        d = monday + timedelta(days=i)
        entries = cal["days"].get(d, [])
        label = DAYS[i].title()
        cells[label] = " + ".join(("🏁 " if x["race"] else "") + x["name"] for x in entries)
        if d > end:
            css[label] = ""
        elif any(x["race"] for x in entries):
            css[label] = f"background-color: {RACE_COLOUR}; color: #1f1f1f"
        elif entries:
            tag = entries[0]["tag"]
            css[label] = f"background-color: {colour.get(tag, MANUAL_COLOUR)}; color: #1f1f1f"
        elif d in gap_days:
            css[label] = f"background-color: {GAP_COLOUR}; color: #1f1f1f"
        else:
            css[label] = ""
        if d < today:
            css[label] += "; opacity: 0.45"
    grid.append({"week of": f"{monday:%b %d}", **cells})
    styles.append(css)
    monday += timedelta(days=7)
frame = pd.DataFrame(grid).set_index("week of")
st.dataframe(frame.style.apply(lambda _: pd.DataFrame(styles, index=frame.index), axis=None),
             width="stretch", height=min(38 * (len(grid) + 1) + 3, 1200))
legend = " · ".join(f"{p['tag']}" for p in cal["plans"])
st.caption(f"Each plan has its own colour ({legend}). Red: races. Grey: gaps. White: events added in Intervals. "
           "Faded: past.")
