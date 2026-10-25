from datetime import date

import pytest

from planlib import PlanError
import push
from push import build_events, layout_warnings, preview, send, stale_ids, to_intervals_text

RACE = date(2026, 11, 26)  # a Thursday
CONFIG = {"race_date": RACE, "plan_tag": "t"}
LIBRARY = {
    "EASY": {"category": "easy", "name": "Easy", "workout_text": "- 30m Z2 Pace"},
    "INT": {"category": "interval", "name": "Int", "workout_text": "- 5m 105% Pace"},
    "RACE": {"category": "race", "name": "Race", "workout_text": None},
}


def test_line_break_convention():
    assert to_intervals_text("Warmup / - 10m Z2 Pace") == "Warmup\n- 10m Z2 Pace"


def test_each_section_header_starts_after_a_blank_line():
    cell = "Warmup / - 10m Z2 Pace / Main Set 8x / - 2m 100% Pace / Cooldown / - 10m Z2 Pace"
    assert to_intervals_text(cell) == (
        "Warmup\n- 10m Z2 Pace\n\nMain Set 8x\n- 2m 100% Pace\n\nCooldown\n- 10m Z2 Pace"
    )


def test_blank_and_race_rows_are_not_pushed():
    events = build_events(CONFIG, LIBRARY, [
        {"date": date(2026, 11, 24), "workout_id": None},
        {"date": date(2026, 11, 25), "workout_id": "EASY"},
        {"date": RACE, "workout_id": "RACE"},
    ], today=date(2026, 10, 1))
    assert [e["external_id"] for e in events] == ["t-2026-11-25"]


def test_unknown_workout_id_fails_loudly():
    with pytest.raises(PlanError, match="NOPE"):
        build_events(CONFIG, LIBRARY, [{"date": RACE, "workout_id": "NOPE"}], today=date(2026, 10, 1))


def test_duplicate_day_fails():
    with pytest.raises(PlanError, match="two workouts"):
        build_events(CONFIG, LIBRARY, [
            {"date": RACE, "workout_id": "EASY"},
            {"date": RACE, "workout_id": "EASY"},
        ], today=date(2026, 10, 1))


def test_stale_ids_only_touch_this_plans_future_events():
    existing = [
        {"external_id": "t-2026-11-20"},  # still in plan: keep
        {"external_id": "t-2026-11-21"},  # workout moved away: delete
        {"external_id": "t-2026-11-01"},  # in the past: history, never delete
        {"external_id": "other-2026-11-21"},  # different plan: leave alone
        {"external_id": None},  # created by hand in Intervals: leave alone
    ]
    events = [{"external_id": "t-2026-11-20"}]
    assert stale_ids(existing, events, "t", today=date(2026, 11, 10)) == ["t-2026-11-21"]


def test_past_and_unplaced_rows_are_not_pushed():
    events = build_events(CONFIG, LIBRARY, [
        {"date": date(2026, 11, 1), "workout_id": "EASY"},
        {"date": None, "workout_id": "INT"},
        {"date": date(2026, 11, 25), "workout_id": "EASY"},
    ], today=date(2026, 11, 10))
    assert [e["external_id"] for e in events] == ["t-2026-11-25"]


def test_hand_edits_to_layout_are_checked():
    layout = [
        {"date": date(2026, 11, 19), "workout_id": "INT"},
        {"date": date(2026, 11, 20), "workout_id": "INT"},
    ]
    warnings = layout_warnings(CONFIG, LIBRARY, layout)
    assert any("back-to-back" in msg for _, msg in warnings)


class FakeIntervals:
    """Stands in for the Intervals.icu client: records calls, never touches the network."""

    def __init__(self, existing):
        self.existing, self.upserted, self.deleted = existing, None, None

    def list_events(self, oldest, newest):
        return self.existing

    def upsert(self, events):
        self.upserted = events

    def delete(self, external_ids):
        self.deleted = external_ids


def test_preview_reads_intervals_but_sends_nothing():
    client = FakeIntervals([{"external_id": "t-2026-11-21"}, {"external_id": "other-2026-11-21"}])
    p = preview(CONFIG, LIBRARY, [{"date": date(2026, 11, 25), "workout_id": "EASY"}], client,
                today=date(2026, 11, 10))
    assert (len(p["events"]), p["existing"], p["found"], p["stale"]) == (1, 2, 1, ["t-2026-11-21"])
    assert client.upserted is None and client.deleted is None
    send(client, p["events"], p["stale"])
    assert len(client.upserted) == 1 and client.deleted == ["t-2026-11-21"]


def test_preview_without_credentials_skips_the_stale_check():
    p = preview(CONFIG, LIBRARY, [{"date": date(2026, 11, 25), "workout_id": "EASY"}], None,
                today=date(2026, 11, 10))
    assert p["existing"] is None and p["stale"] == []


def ev(xid, d, category="WORKOUT", name="w"):
    return {"external_id": xid, "start_date_local": f"{d}T00:00:00", "category": category, "name": name}


TODAY = date(2026, 11, 10)
OURS = [ev(f"t-{date(2026, 11, d)}", date(2026, 11, d)) for d in (12, 14, 20, 25)]


def test_overlaps_sorts_filler_other_plans_and_hand_added_events():
    existing = [ev("fill-2026-11-01-2026-11-12", date(2026, 11, 12)),
                ev("fill-2026-11-01-2026-11-05", date(2026, 11, 5)),  # past: history
                ev("old-2026-11-13", date(2026, 11, 13)), ev("old-2026-11-16", date(2026, 11, 16)),
                ev(None, date(2026, 11, 22), "RACE_C", "Parkrun"), ev(None, RACE, "RACE_A", "Turkey trot"),
                ev("t-2026-11-14", date(2026, 11, 14))]
    o = push.overlaps(existing, OURS, "t", RACE, {"old": date(2026, 11, 15)}, TODAY)
    assert o["fill"] == ["fill-2026-11-01-2026-11-12"]
    assert o["plans"] == {"old": {"first": date(2026, 11, 13), "last": date(2026, 11, 16),
                                  "ids": ["old-2026-11-13", "old-2026-11-16"], "ours": 1}}
    assert o["manual"] == [(date(2026, 11, 22), "Parkrun")]  # this plan's own race isn't listed


def test_resolve_needs_a_choice_and_applies_it():
    existing = [ev("fill-x-2026-11-25", date(2026, 11, 25)), ev("old-2026-11-13", date(2026, 11, 13)),
                ev("old-2026-11-14", date(2026, 11, 14)), ev("t-2026-11-14", date(2026, 11, 14))]
    p = {"events": OURS, "existing_events": existing,
         "overlap": push.overlaps(existing, OURS, "t", RACE, {}, TODAY)}
    with pytest.raises(PlanError, match="overlaps old"):
        push.resolve(p, "t", {}, TODAY)
    events, deletions = push.resolve(p, "t", {"old": "keep"}, TODAY)
    assert [e["external_id"] for e in events] == ["t-2026-11-12", "t-2026-11-20", "t-2026-11-25"]
    assert sorted(deletions) == ["fill-x-2026-11-25", "t-2026-11-14"]  # our old workout there goes too
    events, deletions = push.resolve(p, "t", {"old": "replace"}, TODAY)
    assert len(events) == 4 and sorted(deletions) == ["fill-x-2026-11-25", "old-2026-11-13", "old-2026-11-14"]


def test_stale_fill_ids_replace_any_earlier_filler_in_the_gap():
    existing = [ev("fill-2026-11-01-2026-11-05", date(2026, 11, 5)),  # past
                ev("fill-2026-11-01-2026-11-20", date(2026, 11, 20)),  # split off by a plan: replaced
                ev("fill-2026-11-12-2026-11-21", date(2026, 11, 21)),  # same day as a new one: upserted
                ev("fill-2026-11-12-2026-12-30", date(2026, 12, 30)),  # outside the gap
                ev("t-2026-11-22", date(2026, 11, 22))]
    new = [{"external_id": "fill-2026-11-12-2026-11-21"}]
    assert push.stale_fill_ids(existing, new, date(2026, 11, 12), date(2026, 12, 1), TODAY) == [
        "fill-2026-11-01-2026-11-20"]
