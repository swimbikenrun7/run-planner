"""Import page: copy the prompt, paste Claude's CSV, review the matches, save to the workbook."""

import streamlit as st

from import_plan import (
    ImportError_,
    apply_import,
    apply_to_workbook,
    build_prompt,
    load_paces,
    parse_csv,
    parse_pace,
    stage_plan,
)
from planlib import DAYS, PlanError, blank, load_workbook_tables, save_workbook
from ui.common import sidebar, workbook_path

MATCH_ORDER = {"similar": 0, "new": 1, "exact": 2}  # rows that need a decision first
COLUMNS = ["action", "match", "incoming_id", "category", "name", "workout_text",
           "existing_id", "reason", "differences", "warnings"]

path = workbook_path()
sidebar(path)
try:
    _, config, library, sheets = load_workbook_tables(path)
except (FileNotFoundError, KeyError, PlanError) as e:
    st.error(f"Can't read {path}: {e}")
    st.stop()


def check():
    """Stage the pasted CSV: validate it and match each workout against the Library."""
    st.session_state.pop("staged", None)
    st.session_state.pop("errors", None)
    try:
        threshold = None if blank(config.get("threshold_pace")) else parse_pace(config["threshold_pace"])
        workouts, schedule = stage_plan(parse_csv(st.session_state.csv_text), library,
                                        load_paces(sheets), threshold)
    except (ImportError_, PlanError) as e:
        st.session_state.errors = str(e).splitlines()
        return
    for w in workouts:
        w["warnings"] = "; ".join(w["warnings"])
    workouts.sort(key=lambda w: MATCH_ORDER[w["match"]])
    st.session_state.staged = {"workouts": workouts, "schedule": schedule}


def save(rows, plan, week_end, select):
    """Apply the reviewed import to a freshly loaded workbook and save it."""
    try:
        wb, _, current_library, _ = load_workbook_tables(path)
        new_rows, sched = apply_import(current_library, rows, st.session_state.staged["schedule"])
        apply_to_workbook(wb, new_rows, sched, plan, week_end, "imported in the app", select)
        save_workbook(wb, path)
    except (ImportError_, PlanError) as e:
        st.session_state.save_error = str(e)
        return
    added = ", ".join(r["workout_id"] for r in new_rows) or "none"
    done = f"Added {len(new_rows)} workouts to Library: {added}."
    if plan:
        done += f" Saved plan **{plan.strip()}** ({len(sched)} days, weeks end {week_end.title()})."
        done += (" It's now the selected plan in Config." if select
                 else " Config's selected plan is unchanged.")
    st.session_state.done = done
    for key in ("staged", "errors", "save_error", "csv_text"):
        st.session_state.pop(key, None)


st.title("Import a plan")
if "done" in st.session_state:
    st.success(st.session_state.pop("done"))

st.subheader("1. Copy the prompt")
st.write("Paste it into a Claude chat together with the plan (a PDF, a link, or a table). "
         "The prompt lists your paces and Library, so it's rebuilt from the workbook each time.")
with st.expander("Prompt (copy button at the top right of the box)"):
    st.code(build_prompt(config, library, sheets), language=None, wrap_lines=True)

st.subheader("2. Paste Claude's reply")
st.text_area("Paste the whole reply: only the CSV block in it is read.", key="csv_text", height=200,
             placeholder="week,day,workout_id,category,name,workout_text,note")
st.button("Check", type="primary", on_click=check,
          disabled=not st.session_state.get("csv_text", "").strip())

if "errors" in st.session_state:
    st.error("The CSV has problems. Paste this list back into the Claude chat and ask it to fix "
             "them, then paste the new reply above.")
    st.code("\n".join(st.session_state.errors), language=None, wrap_lines=True)

staged = st.session_state.get("staged")
if staged:
    workouts, schedule = staged["workouts"], staged["schedule"]
    st.subheader("3. Review")
    counts = {m: sum(1 for w in workouts if w["match"] == m) for m in MATCH_ORDER}
    cols = st.columns(4)
    cols[0].metric("Days", len(schedule))
    cols[1].metric("Already in Library", counts["exact"])
    cols[2].metric("New", counts["new"])
    cols[3].metric("Similar: decide", counts["similar"])
    st.write("**action**: `add` keeps the workout as a new Library entry (renamed with `-2` if "
             "its ID is taken), or pick an existing workout to use instead. Similar workouts "
             "are listed first and need a choice.")
    edited = st.data_editor(
        [{c: w.get(c) for c in COLUMNS} for w in workouts],
        column_config={
            "action": st.column_config.SelectboxColumn(
                "action", options=["add"] + sorted(library), required=False, width="medium"),
            "workout_text": st.column_config.TextColumn("workout_text", width="large"),
            "differences": st.column_config.TextColumn("differences", width="large"),
        },
        disabled=COLUMNS[1:], hide_index=True, width="stretch", key="review")
    rows = edited.to_dict("records") if hasattr(edited, "to_dict") else edited
    rows = [{**w, "action": r["action"]} for w, r in zip(workouts, rows)]

    with st.expander("Schedule by week"):
        grid = {}
        for s in schedule:
            grid.setdefault(s["week"], {})[s["day"]] = s["incoming_id"] or f"({s['note'] or 'rest'})"
        st.dataframe([{"week": wk, **{d.title(): grid[wk].get(d.title(), "") for d in DAYS}}
                      for wk in sorted(grid)], hide_index=True, width="stretch")

    st.subheader("4. Save to the workbook")
    mode = st.radio("Save", ["As a plan", "Library only (add new workouts, no plan)"],
                    horizontal=True, label_visibility="collapsed")
    plan = week_end = None
    select = False
    if mode == "As a plan":
        c1, c2 = st.columns(2)
        plan = c1.text_input("Plan name", placeholder="e.g. higdon_hm").strip() or None
        week_end = c2.selectbox("The plan's weeks end on (usually race day)",
                                [d.title() for d in DAYS], index=6).lower()
        existing = {str(r.get("plan") or "").strip() for r in sheets.get("plans", [])}
        if plan in existing:
            st.warning(f"A plan named **{plan}** already exists. Saving replaces its Schedule rows.")
        current = config.get("plan")
        select = st.checkbox(
            f"Make it the selected plan now (changes Config's plan from **{current}** and removes "
            f"the current Layout tab, including any changes you made to it by hand)", value=False)
    missing_action = [w["incoming_id"] for w in rows if not w.get("action")]
    if missing_action:
        st.info("Choose an action for: " + ", ".join(missing_action))
    st.button("Save", type="primary", on_click=save, args=(rows, plan, week_end, select),
              disabled=bool(missing_action) or (mode == "As a plan" and not plan))
    if "save_error" in st.session_state:
        st.error(st.session_state.pop("save_error"))
