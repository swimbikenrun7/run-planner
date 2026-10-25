"""Drives the Import page headlessly with Streamlit's AppTest, on a copy of a small workbook."""

import shutil
from pathlib import Path

import openpyxl
import pytest
from streamlit.testing.v1 import AppTest

from planlib import lock_file

ROOT = Path(__file__).resolve().parent.parent
CSV = """Notes: treated 'rest or run' as rest.

```csv
week,day,workout_id,category,name,workout_text,note
1,Mon,,,,,Rest
1,Tue,INT-TEST,interval,Test intervals,Warmup / - Press lap {WU} 10m / Main Set 4x / - 800mtr {I} / - 2m {RECOVERY} / Cooldown / - Press lap {WU} 10m,
1,Wed,EASY-3MI,easy,Easy 3mi,- Press lap {E} 3mi,
1,Thu,,,,,Rest
1,Fri,,,,,Rest
1,Sat,,,,,Rest
1,Sun,RACE,race,Race Day,,
```
"""


@pytest.fixture
def workbook(tmp_path, monkeypatch):
    wb = openpyxl.Workbook()
    wb.active.title = "Config"
    tables = {
        "Config": [["key", "value"], ["plan", "old"], ["threshold_pace", "7:30/mi"]],
        "Paces": [["key", "description", "target"], ["WU", "", "Z2 Pace"], ["RECOVERY", "", "Z1 Pace"],
                  ["E", "", "80% Pace"], ["I", "", "110% Pace"]],
        "Library": [["workout_id", "category", "name", "workout_text"],
                    ["EASY-3MI", "easy", "Easy 3mi", "- Press lap 80% Pace 3mi"],
                    ["RACE", "race", "Race Day", None]],
        "Plans": [["plan", "source_week_end", "notes", "rest_fill", "pre_race_fill"],
                  ["old", "sun", None, None, None]],
        "Schedule": [["plan", "week", "day", "workout_id", "note"], ["old", 1, "Mon", "EASY-3MI", None]],
        "Layout": [["date"]],
    }
    for name, rows in tables.items():
        ws = wb[name] if name in wb.sheetnames else wb.create_sheet(name)
        for r in rows:
            ws.append(r)
    path = tmp_path / "wb.xlsx"
    wb.save(path)
    monkeypatch.setenv("RUN_PLANNER_WORKBOOK", str(path))
    return path


def page():
    return AppTest.from_file(str(ROOT / "ui" / "import_page.py"), default_timeout=30).run()


def paste_and_check(at, text=CSV):
    at.text_area(key="csv_text").input(text).run()
    at.button[0].click().run()
    return at


def test_prompt_is_shown_with_the_workbooks_paces(workbook):
    at = page()
    assert not at.exception
    assert "{I}" in at.code[0].value and "EASY-3MI" in at.code[0].value


def test_problems_are_listed_for_the_chat_to_fix(workbook):
    at = paste_and_check(page(), CSV.replace("- Press lap {E} 3mi", "- {E} 3mi"))
    assert "Press lap" in at.code[-1].value  # the error list, ready to paste back
    assert not at.get("data_editor")


def test_check_then_save_as_a_plan_without_selecting_it(workbook):
    at = paste_and_check(page())
    assert [m.value for m in at.metric] == ["7", "2", "1", "0"]  # days, exact, new, similar
    at.text_input[0].input("test-plan").run()
    at.button[1].click().run()
    assert not at.exception and "Saved plan **test-plan**" in at.success[0].value
    assert "filled with **EASY-3MI** (**EASY-2MI**" in at.success[0].value
    wb = openpyxl.load_workbook(workbook)
    assert "INT-TEST" in [r[0] for r in wb["Library"].iter_rows(values_only=True)]
    assert {r[0] for r in wb["Schedule"].iter_rows(min_row=2, values_only=True)} == {"old", "test-plan"}
    assert wb["Config"]["B2"].value == "old" and "Layout" in wb.sheetnames  # not selected
    assert "INT-TEST" in at.code[0].value  # the prompt already lists the workout just added


def test_save_refuses_while_open_in_calc(workbook):
    lock_file(workbook).write_text("")
    at = paste_and_check(page())
    at.text_input[0].input("test-plan").run()
    at.button[1].click().run()
    assert "open in LibreOffice Calc" in at.error[0].value
    assert "test-plan" not in [r[0] for r in openpyxl.load_workbook(workbook)["Plans"].iter_rows(values_only=True)]
