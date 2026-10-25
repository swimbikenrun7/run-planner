"""run-planner app: a browser UI over the workbook.

    streamlit run app.py

The workbook stays the source of data. Pages call the same functions as the scripts, and every
save goes through planlib.save_workbook, so nothing is written while Calc has the workbook open.
"""

import streamlit as st

st.set_page_config(page_title="run-planner", page_icon="🏃", layout="wide")
st.navigation([
    st.Page("ui/plan_page.py", title="Plan", icon="📅"),
    st.Page("ui/import_page.py", title="Import a plan", icon="📥"),
    st.Page("ui/calendar_page.py", title="Calendar", icon="🗓️"),
    st.Page("ui/fill_page.py", title="Fill gaps", icon="🧩"),
]).run()
