import openpyxl
import pytest

from planlib import PlanError, easy_run_unit, lock_file, save_workbook


def test_lock_file_sits_beside_workbook(tmp_path):
    assert lock_file(tmp_path / "plan_builder.xlsx") == tmp_path / ".~lock.plan_builder.xlsx#"


def test_save_refuses_while_open_in_calc(tmp_path):
    path = tmp_path / "plan_builder.xlsx"
    lock_file(path).write_text("")
    with pytest.raises(PlanError, match="open in LibreOffice Calc"):
        save_workbook(openpyxl.Workbook(), path)
    assert not path.exists()


def test_save_when_closed(tmp_path):
    path = tmp_path / "plan_builder.xlsx"
    save_workbook(openpyxl.Workbook(), path)
    assert path.exists()


def test_easy_run_unit_follows_how_the_plan_writes_easy_runs():
    assert easy_run_unit(["- Press lap 80% Pace 3mi", "- Press lap 80% Pace 30m"]) == "distance"  # tie
    assert easy_run_unit(["- Press lap 80% Pace 30m", "- Press lap 80% Pace 45m", "- Press lap 80% Pace 5km"]) == "time"
    assert easy_run_unit(["Warmup / - Press lap Z2 Pace 10m / Main Set / - 3mi 80% Pace"]) == "distance"  # multi-step ignored
