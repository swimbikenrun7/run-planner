"""Shared by the app's pages."""

import os
from pathlib import Path

import streamlit as st

from planlib import lock_file

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_WORKBOOK = ROOT / "plans" / "plan_builder.xlsx"


def workbook_path():
    """The workbook the app works on: RUN_PLANNER_WORKBOOK if set, else the master workbook."""
    return Path(os.environ.get("RUN_PLANNER_WORKBOOK") or DEFAULT_WORKBOOK)


def sidebar(path):
    st.sidebar.caption(f"Workbook: `{path.name}`")
    if lock_file(path).exists():
        st.sidebar.warning("The workbook is open in LibreOffice Calc. Close it before saving.")
