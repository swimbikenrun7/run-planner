"""Fill gaps page: plan the training between plans from your rules, see the projected form, push it."""

from datetime import date, datetime, timedelta

import altair as alt
import pandas as pd
import streamlit as st

import push
from filler import DEFAULT_RULES, DISTANCES, fill, rules_from_config, week_days
from fitness import ZONES, form_value, project, workout_hours, workout_load
from forecast import event_loads, plan_races, race_load, start_state
from import_plan import ImportError_, append_row, set_config
from master import FILL_AHEAD_DAYS, FILL_PREFIX, fill_status, fill_tag_fits, summarize, tag_of
from planlib import (
    DAYS,
    PlanError,
    blank,
    last_used_row,
    load_workbook_tables,
    read_week,
    run_length,
    save_workbook,
    to_date,
)
from ui.common import sidebar, workbook_path

FILL_SHEET = "Fill"
# the record of each pushed gap, with the forecast at push time (for comparing with what actually happens)
FILL_HEADERS = ["plan_tag", "date", "workout_id", "load", "note", "fitness", "fatigue", "form", "pushed"]
QUALITY_CHOICES = ["tempo", "threshold", "interval", "fartlek", "hills", "steady"]
ZONE_COLOURS = {"transition": "#fff2cc", "fresh": "#cfe2f3", "grey": "#eeeeee", "optimal": "#d9ead3",
                "high risk": "#f4cccc"}

path = workbook_path()
sidebar(path)
try:
    _, config, library, sheets = load_workbook_tables(path)
    week = read_week(sheets.get("week", []), library)
except (FileNotFoundError, KeyError, PlanError) as e:
    st.error(f"Can't read {path}: {e}")
    st.stop()
plans_rows = [r for r in sheets.get("plans", []) if not blank(r.get("plan"))]
paces = {str(r["key"]).strip().upper(): r["target"] for r in sheets.get("paces", [])}
today = date.today()


def load_intervals():
    client = push.client_from_env()
    if client is None:
        st.session_state.fill_error = "Set INTERVALS_ATHLETE_ID and INTERVALS_API_KEY in .env"
        return
    try:
        st.session_state.fill_data = {
            "events": client.list_events(today - timedelta(days=60), today + timedelta(days=550)),
            "wellness": client.wellness(today - timedelta(days=3), today),
            "run": client.run_settings()}
        st.session_state.pop("fill_error", None)
    except Exception as e:  # network or API trouble: show it, don't crash the page
        st.session_state.fill_error = f"Couldn't read Intervals.icu: {e}"


st.title("Fill gaps")
if "fill_message" in st.session_state:
    kind, text = st.session_state.pop("fill_message")
    (st.success if kind == "success" else st.error)(text)
st.write("Plans the training between your plans: recovery after a race, then steady building with "
         "lighter weeks, following your Week tab. Nothing is sent until you push.")
if "fill_data" not in st.session_state and "fill_error" not in st.session_state:
    load_intervals()
st.button("Refresh from Intervals", on_click=load_intervals)
if "fill_error" in st.session_state:
    st.error(st.session_state.fill_error)
    st.stop()
data = st.session_state.fill_data
speed, zones = data["run"]["threshold_speed"], data["run"]["pace_zones"]


def load_of(text):
    return workout_load(text, speed, zones)


# ---------- the calendar as it stands ----------
events = data["events"]
races = plan_races(plans_rows)
by_tag = {str(r.get("plan_tag") or "").strip(): r for r in plans_rows if not blank(r.get("plan_tag"))}
loads = event_loads(events)
for race_day, dist, _ in races:
    if not any(to_date(e["start_date_local"]) == race_day and str(e.get("category", "")).startswith("RACE")
               for e in events):
        loads[race_day] += race_load(dist, paces, speed)
horizon = today + timedelta(days=540)
fixed = [e for e in events if not tag_of(e).startswith(FILL_PREFIX)]  # earlier fills can be planned again
cal = summarize(fixed, {tag: to_date(r["race_date"]) for tag, r in by_tag.items() if not blank(r.get("race_date"))},
                today, horizon)
if not cal["gaps"]:
    st.info("No gaps of a week or more in the next 18 months.")
    st.stop()


ahead = today + timedelta(days=FILL_AHEAD_DAYS)


def open_ended(gap):
    return gap[1] >= horizon - timedelta(days=1)


def fill_end(gap):
    """Last day to fill: the day before the next plan, or 90 days from today with no plan after the gap."""
    return min(gap[1], ahead) if open_ended(gap) else gap[1]


STATUS = {"empty": "not filled", "filled": "filled", "partly": "filled to {:%b %d}",
          "outdated": "filler out of date: the calendar changed around it"}


def describe(gap):
    first, last = gap
    status, filled_to = fill_status(events, first, fill_end(gap), today)
    before = next((r for r in races if r[0] == first - timedelta(days=1)), None)
    after_day = [x for x in cal["days"].get(last + timedelta(days=1), []) if not x["race"]]
    parts = [f"{first:%b %d, %Y} onward" if open_ended(gap)
             else f"{first:%b %d, %Y} to {last:%b %d, %Y} ({(last - first).days + 1} days)"]
    if before:
        parts.append(f"after the {before[1]} race ({before[2]})")
    if after_day:
        parts.append(f"before {after_day[0]['tag']}")
    elif open_ended(gap):
        parts.append(f"no plan after it yet (fills to {ahead:%b %d})" if first <= ahead
                     else f"no plan after it yet (fills from {first - timedelta(days=FILL_AHEAD_DAYS):%b %d})")
    return ", ".join(parts) + f": {STATUS[status].format(filled_to)}"


gap = st.selectbox("Gap", cal["gaps"], format_func=describe)
first, last = gap[0], fill_end(gap)
if first > last:
    st.info(f"With no plan after it, a gap is filled at most {FILL_AHEAD_DAYS} days ahead, so this one can be "
            f"filled from {first - timedelta(days=FILL_AHEAD_DAYS):%b %d, %Y}. Add a plan after it to fill it now.")
    st.stop()
if fill_status(events, first, last, today)[0] == "outdated":
    st.warning("The filler here was planned before a plan was pushed into it, so its recovery and build "
               "no longer start in the right place. Push this gap again to replan it around the plan.")
before = next((r for r in races if r[0] == first - timedelta(days=1)), None)
next_tag = next((x["tag"] for x in cal["days"].get(gap[1] + timedelta(days=1), []) if not x["race"]), None)
target_ctl = None
if next_tag:
    first_week = [e for e in events if tag_of(e) == next_tag]
    start_next = min(to_date(e["start_date_local"]) for e in first_week)
    target_ctl = sum(e.get("icu_training_load") or 0 for e in first_week
                     if to_date(e["start_date_local"]) < start_next + timedelta(days=7)) / 7


def unit_of(tag):
    row = by_tag.get(tag or "")
    fill_wid = str((row or {}).get("rest_fill") or "").strip()
    length = run_length(str(library.get(fill_wid, {}).get("workout_text") or ""))
    return length[0] if length else None


unit = unit_of(next_tag) or unit_of(before[2] if before else None) or "distance"

# ---------- training rules ----------
stamp = path.stat().st_mtime_ns
saved = rules_from_config(config)
if st.session_state.get("fill_loaded") != stamp:
    st.session_state.update({f"r_{d}": saved["recovery_days"].get(d, 0) for d in DISTANCES})
    st.session_state.update({"r_ramp": saved["ramp_limit"], "r_increase": saved["max_weekly_increase"],
                             "r_build": saved["build_weeks"], "r_lighter": saved["recovery_week_pct"],
                             "r_quality": saved["quality_per_week"],
                             "r_categories": [c for c in saved["quality_categories"] if c in QUALITY_CHOICES],
                             "r_between": saved["between_plans"], "r_target": saved["race_form_target"]})
    st.session_state.fill_loaded = stamp

with st.expander("Training rules", expanded=False):
    st.caption("Changes apply to the preview below straight away, so you can try them out. "
               "Save them to make them your defaults.")
    st.markdown("**Easy days after a race.** Muscle damage settles in about a week after a half marathon and a "
                "few days after a 10K; one easy day per mile is a marathon rule of thumb. The first day is the "
                "shortest easy run, then 3mi / 30m runs.")
    cols = st.columns(4)
    for c, d in zip(cols, DISTANCES):
        c.number_input(d.upper() if d != "half" else "Half", 0, 30, key=f"r_{d}")
    st.markdown("**Building.** Fitness is your 42-day average load; it rises when your weeks are bigger than "
                "it. Most coaching advice keeps the rise to about 5 a week and weekly load to +10%.")
    c1, c2 = st.columns(2)
    c1.number_input("Fitness ramp limit (per week)", 1.0, 10.0, step=0.5, key="r_ramp")
    c2.number_input("Most weekly load can grow (%)", 0.0, 30.0, step=1.0, key="r_increase")
    st.markdown("**Lighter weeks** let form recover into the grey zone so the build can keep going.")
    c3, c4 = st.columns(2)
    c3.number_input("Build weeks before a lighter week", 1, 6, key="r_build")
    c4.number_input("Lighter week load (% of the last build week)", 40.0, 100.0, step=5.0, key="r_lighter")
    st.markdown("**Quality sessions** come from your Library, on your Week tab's quality days.")
    c5, c6 = st.columns([1, 3])
    c5.number_input("Per build week", 0, 3, key="r_quality")
    c6.multiselect("Kinds", QUALITY_CHOICES, key="r_categories")
    st.markdown("**Between plans.** Keep building, or build only to the fitness the next plan's first week "
                "assumes and hold there.")
    st.radio("Between plans", ["build", "match"], horizontal=True, key="r_between",
             format_func=lambda v: {"build": "Keep building", "match": "Match the next plan"}[v],
             label_visibility="collapsed")
    st.markdown("**Race-day form target** (used by the Plan page's check). Grey (-10 to +5) is fine for "
                "racing for fun; fresh (+5 to +20) is a hard taper for racing all out.")
    st.selectbox("Race-day form target", ["grey", "fresh"], key="r_target",
                 format_func=lambda v: {"grey": "Grey or better (-10 and up)", "fresh": "Fresh (+5 and up)"}[v])

rules = {"recovery_days": {d: int(st.session_state[f"r_{d}"]) for d in DISTANCES},
         "ramp_limit": float(st.session_state.r_ramp), "max_weekly_increase": float(st.session_state.r_increase),
         "build_weeks": int(st.session_state.r_build), "recovery_week_pct": float(st.session_state.r_lighter),
         "quality_per_week": int(st.session_state.r_quality),
         "quality_categories": list(st.session_state.r_categories),
         "between_plans": st.session_state.r_between, "race_form_target": st.session_state.r_target}


def save_rules(rules):
    values = {"recovery_days": ", ".join(f"{d}:{n}" for d, n in rules["recovery_days"].items()),
              "ramp_limit": rules["ramp_limit"], "max_weekly_increase": rules["max_weekly_increase"],
              "build_weeks": rules["build_weeks"], "recovery_week_pct": rules["recovery_week_pct"],
              "quality_per_week": rules["quality_per_week"],
              "quality_categories": ", ".join(rules["quality_categories"]),
              "between_plans": rules["between_plans"], "race_form_target": rules["race_form_target"]}
    try:
        wb = load_workbook_tables(path)[0]
        for k, v in values.items():
            set_config(wb, k, v)
        save_workbook(wb, path)
        st.session_state.fill_message = ("success", "Rules saved as your defaults.")
    except (PlanError, ImportError_) as e:
        st.session_state.fill_message = ("error", str(e))


st.button("Save rules", disabled=rules == saved, on_click=save_rules, args=(rules,))

# ---------- the plan for this gap ----------
try:
    ctl, atl = start_state(data["wellness"], today)
except ValueError as e:
    st.error(str(e))
    st.stop()
base = project(ctl, atl, loads, today, first - timedelta(days=1)) if first > today else []
c0, a0 = (base[-1][2], base[-1][3]) if base else (ctl, atl)
window = [loads.get(first - timedelta(days=k), 0.0) for k in range(2, 30)]  # 4 weeks before, not race day
result = fill(first, last, c0, a0, week, library, rules, unit, {"E": paces["E"], "LONG": paces["LONG"]}, load_of,
              after_race=before[1] if before else None, target_ctl=target_ctl,
              recent_week_load=sum(window) / 4 or None, recent_long_load=max(window) or None)
days, proj = result["days"], result["projection"]

st.subheader("Preview")
m1, m2, m3 = st.columns(3)
m1.metric("Fitness at the start", f"{c0:.0f}")
m2.metric("Fitness at the end", f"{proj[-1][2]:.0f}", f"{proj[-1][2] - c0:+.0f}")
if target_ctl:
    m3.metric(f"{next_tag} week 1 assumes", f"{target_ctl:.0f}")
    if proj[-1][2] > target_ctl * 1.15:
        st.info(f"You'd start {next_tag} fitter than its first week assumes, so its early weeks will feel easy "
                "and fitness may dip at first. That's the trade-off of building between plans; choose "
                "'Match the next plan' under Training rules to hold at its level instead.")
lowest = min(form_value(p[4], p[2]) for p in proj)
st.caption(f"Lowest form in the gap: {lowest:.0f}"
           + (" (% of fitness)" if any(p[2] > 60 for p in proj) else "") + ". Never planned into high risk.")

# chart: fitness, fatigue and form, with the form zones behind form
lo_day, hi_day = first - timedelta(days=14), last + timedelta(days=14)
all_loads = dict(loads)
all_loads.update({d: v[1] for d, v in days.items()})
chart_rows = project(ctl, atl, all_loads, today, hi_day) if hi_day >= today else []
frame = pd.DataFrame([{"date": d, "Fitness": c, "Fatigue": a, "Form": f} for d, _, c, a, f in chart_rows
                      if d >= lo_day])
if not frame.empty:
    long = frame.melt("date", var_name="line", value_name="value")
    bands = pd.DataFrame([{"zone": name, "top": upper, "bottom": lower} for (name, lower), upper in
                          zip(ZONES, [40, 20, 5, -10, -30]) if name != "high risk"]
                         + [{"zone": "high risk", "top": -30, "bottom": -45}])
    band_layer = alt.Chart(bands).mark_rect(opacity=0.35).encode(
        y="bottom:Q", y2="top:Q", color=alt.Color("zone:N", scale=alt.Scale(
            domain=list(ZONE_COLOURS), range=list(ZONE_COLOURS.values())), legend=alt.Legend(title="Form zone")))
    lines = alt.Chart(long).mark_line().encode(
        x=alt.X("date:T", title=None), y=alt.Y("value:Q", title=None),
        color=alt.Color("line:N", scale=alt.Scale(domain=["Fitness", "Fatigue", "Form"],
                                                   range=["#1f77b4", "#9467bd", "#2ca02c"]), legend=alt.Legend(title=None)))
    gap_rule = alt.Chart(pd.DataFrame({"date": [first, last]})).mark_rule(strokeDash=[4, 4], color="#888").encode(x="date:T")
    st.altair_chart(alt.layer(band_layer, lines, gap_rule).resolve_scale(color="independent"), width="stretch")
    st.caption("Dashed lines: the gap. Form zones are absolute while fitness is under 60.")

known = {**library, **{r["workout_id"]: r for r in result["new"]}}
grid = []
for wk in week_days(first, last):
    row = {"week of": f"{wk[0] - timedelta(days=wk[0].weekday()):%b %d}", **{d.title(): "" for d in DAYS}}
    for d in wk:
        row[DAYS[d.weekday()].title()] = known.get(days[d][0], {}).get("name") or days[d][0]
    row["load"] = round(sum(days[d][1] for d in wk))
    row["hours"] = round(sum(workout_hours(known.get(days[d][0], {}).get("workout_text"), speed, zones)
                             for d in wk), 1)
    grid.append(row)
st.dataframe(pd.DataFrame(grid).set_index("week of").fillna(""), width="stretch",
             height=min(38 * (len(grid) + 1) + 3, 900))
if result["new"]:
    st.caption("New Library workouts this adds (sized for the load): "
               + ", ".join(r["workout_id"] for r in result["new"]))

# ---------- push ----------
st.subheader("Push to Intervals.icu")
old_tags = {tag_of(e) for e in events if tag_of(e).startswith(FILL_PREFIX)
            and first <= to_date(e["start_date_local"]) <= gap[1]}
running = sorted(t for t in old_tags if first <= today and fill_tag_fits(t, first, today))
tag = running[0] if running else f"{FILL_PREFIX}{first.isoformat()}"  # a gap under way keeps its tag
rows = [{"date": d, "workout_id": v[0]} for d, v in sorted(days.items()) if d >= today]
st.write(f"**{len(rows)} workouts**, tagged `{tag}`."
         + (" This replaces the gap's earlier fill." if old_tags else ""))


def push_fill():
    try:
        client = push.client_from_env()
        wb, _, current, _ = load_workbook_tables(path)
        lib_ws = wb["Library"]
        for r in result["new"]:
            if r["workout_id"] not in current:  # never overwrite
                append_row(lib_ws, [r["workout_id"], r["category"], r["name"], r["workout_text"]])
                current[r["workout_id"]] = r
        write_fill(wb, tag, days, proj)
        save_workbook(wb, path)
        events_out = push.build_events({"plan_tag": tag}, current, rows, today)
        existing = client.list_events(today - push.CLEANUP_WINDOW, last + push.CLEANUP_WINDOW)
        stale = push.stale_fill_ids(existing, events_out, first, gap[1], today)
        push.send(client, events_out, stale)
    except (PlanError, ImportError_) as e:
        st.session_state.fill_message = ("error", str(e))
        return
    except Exception as e:
        st.session_state.fill_message = ("error", f"Push failed: {e}")
        return
    deleted = f" Deleted {len(stale)} old filler workouts." if stale else ""
    st.session_state.fill_message = ("success", f"Pushed {len(events_out)} workouts tagged {tag}.{deleted}")
    st.session_state.pop("fill_confirm", None)
    load_intervals()


def write_fill(wb, tag, days, projection):
    """Replace this tag's rows on the Fill tab (the record of what was pushed for a gap). Rows before
    the replanned days stay: a gap replanned while under way keeps its history."""
    if FILL_SHEET not in wb.sheetnames:
        wb.create_sheet(FILL_SHEET).append(FILL_HEADERS)
    ws = wb[FILL_SHEET]
    for i, h in enumerate(FILL_HEADERS, start=1):  # older Fill tabs lack the forecast columns
        ws.cell(1, i).value = h
    start = min(days)
    keep = [[c.value for c in row] for row in ws.iter_rows(min_row=2, max_row=last_used_row(ws))
            if row[0].value and (row[0].value != tag or to_date(row[1].value) < start)]
    ws.delete_rows(2, max(ws.max_row - 1, 1))
    for r in keep:
        append_row(ws, r)
    forecast = {p[0]: p[2:] for p in projection}
    pushed = datetime.combine(today, datetime.min.time())
    for d, (wid, load, note) in sorted(days.items()):
        fitness, fatigue, form = forecast[d]
        append_row(ws, [tag, datetime.combine(d, datetime.min.time()), wid, round(load), note,
                        round(fitness, 1), round(fatigue, 1), round(form, 1), pushed])


confirm = st.checkbox(f"Send {len(rows)} workouts to my Intervals calendar and watch", key="fill_confirm")
st.button("Push", type="primary", disabled=not confirm or not rows, on_click=push_fill)
