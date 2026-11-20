import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

from planner import core, storage


@pytest.fixture(autouse=True)
def isolated_planner_env(tmp_path, monkeypatch):
    data_dir = tmp_path / "planner-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("PLANNER_DATA_DIR", str(data_dir))
    monkeypatch.setattr(core, "TASKS_FILE", data_dir / "tasks.json")
    monkeypatch.setattr(core, "EVENTS_FILE", data_dir / "events.json")
    monkeypatch.setattr(core, "SETTINGS_FILE", data_dir / "settings.json")


def test_create_habit_validations():
    ref_date = date(2026, 11, 20)

    # Empty or blank name
    with pytest.raises(ValueError, match="between 1 and 80"):
        core.create_habit(name="", reference_date=ref_date)
    with pytest.raises(ValueError, match="between 1 and 80"):
        core.create_habit(name="   ", reference_date=ref_date)

    # Name > 80 chars
    with pytest.raises(ValueError, match="between 1 and 80"):
        core.create_habit(name="x" * 81, reference_date=ref_date)

    # Invalid days
    with pytest.raises(ValueError, match="at least one day"):
        core.create_habit(name="Test", days=[], reference_date=ref_date)
    with pytest.raises(ValueError, match="Invalid weekday"):
        core.create_habit(name="Test", days=["mon", "funday"], reference_date=ref_date)
    with pytest.raises(ValueError, match="cannot contain duplicates"):
        core.create_habit(name="Test", days=["mon", "mon"], reference_date=ref_date)

    # Valid daily habit (days=None)
    h_daily = core.create_habit(name="Read 30 minutes", reference_date=ref_date)
    assert h_daily["name"] == "Read 30 minutes"
    assert h_daily["schedule"] == {"type": "daily"}
    assert h_daily["start_date"] == "2026-11-20"
    assert h_daily["archived"] is False
    assert h_daily["archived_on"] is None
    assert h_daily["deleted"] is False

    # Duplicate name case-insensitive
    with pytest.raises(ValueError, match="already exists"):
        core.create_habit(name="read 30 minutes", reference_date=ref_date)
    with pytest.raises(ValueError, match="already exists"):
        core.create_habit(name="  READ 30 MINUTES  ", reference_date=ref_date)

    # Valid weekdays habit
    h_weekdays = core.create_habit(
        name="Gym",
        days=["wed", "mon", "fri"],
        start_date="2026-11-01",
        reference_date=ref_date,
    )
    assert h_weekdays["name"] == "Gym"
    assert h_weekdays["schedule"] == {"type": "weekdays", "days": ["mon", "wed", "fri"]}
    assert h_weekdays["start_date"] == "2026-11-01"


def test_edit_archive_delete_habit():
    ref_date = date(2026, 11, 20)
    h = core.create_habit(name="Yoga", reference_date=ref_date)
    hid = h["id"]

    # Unsupported field
    with pytest.raises(ValueError, match="Unsupported habit field"):
        core.edit_habit(hid, invalid_key="val")

    # Edit without real changes does not update timestamp
    orig_updated = h["updated"]
    same = core.edit_habit(hid, name="Yoga")
    assert same["updated"] == orig_updated

    # Real edit
    edited = core.edit_habit(hid, name="Power Yoga", days=["tue", "thu"])
    assert edited["name"] == "Power Yoga"
    assert edited["schedule"] == {"type": "weekdays", "days": ["tue", "thu"]}

    # Archive habit
    archived = core.archive_habit(hid, archived=True, on_date="2026-11-20")
    assert archived["archived"] is True
    assert archived["archived_on"] == "2026-11-20"

    # Unarchive habit
    unarchived = core.archive_habit(hid, archived=False)
    assert unarchived["archived"] is False
    assert unarchived["archived_on"] is None

    # Delete habit (logical delete)
    deleted = core.delete_habit(hid)
    assert deleted["deleted"] is True

    # Cannot edit or archive deleted habit
    with pytest.raises(ValueError, match="not found"):
        core.edit_habit(hid, name="New")
    with pytest.raises(ValueError, match="not found"):
        core.archive_habit(hid)


def test_set_habit_status_lifecycle():
    today = date(2026, 11, 20)  # Friday
    h = core.create_habit(
        name="Gym",
        days=["mon", "wed", "fri"],
        start_date="2026-11-01",
        reference_date=today,
    )
    hid = h["id"]

    # Reject future date
    future = today + timedelta(days=1)
    with pytest.raises(ValueError, match="future dates"):
        core.set_habit_status(hid, future, "done", reference_date=today)

    # Reject unscheduled day (2026-11-19 is Thursday)
    thu = date(2026, 11, 19)
    with pytest.raises(ValueError, match="not scheduled"):
        core.set_habit_status(hid, thu, "done", reference_date=today)

    # Reject deleted habit
    h_temp = core.create_habit(name="Temp", reference_date=today)
    core.delete_habit(h_temp["id"])
    with pytest.raises(ValueError, match="not found"):
        core.set_habit_status(h_temp["id"], today, "done", reference_date=today)

    # 1. Create log: "done"
    log1 = core.set_habit_status(hid, today, "done", reference_date=today)
    assert log1 is not None
    assert log1["status"] == "done"
    assert log1["deleted"] is False
    log1_id = log1["id"]

    # No-op set_habit_status returns same log without error
    same = core.set_habit_status(hid, today, "done", reference_date=today)
    assert same["id"] == log1_id

    # 2. Change status: "skipped"
    log2 = core.set_habit_status(hid, today, "skipped", reference_date=today)
    assert log2["id"] == log1_id
    assert log2["status"] == "skipped"

    # 3. Clear log: status=None (soft delete)
    cleared = core.set_habit_status(hid, today, None, reference_date=today)
    assert cleared["id"] == log1_id
    assert cleared["deleted"] is True

    # Clearing again when already cleared is a no-op
    cleared_again = core.set_habit_status(hid, today, None, reference_date=today)
    assert cleared_again is None

    # 4. Re-log on same day reactivates the SAME entry (same id), doesn't create duplicate
    log3 = core.set_habit_status(hid, today, "done", reference_date=today)
    assert log3["id"] == log1_id
    assert log3["status"] == "done"
    assert log3["deleted"] is False

    # Check total logs in storage: exactly 1 log entry
    all_logs = storage.load_habit_logs()
    matching = [l for l in all_logs if l["habit_id"] == hid and l["date"] == today.isoformat()]
    assert len(matching) == 1


def test_calculation_rules_and_streaks():
    # Fixed today: Friday 2026-11-20
    today = date(2026, 11, 20)
    # Start habit 6 days ago: Saturday 2026-11-14
    start = date(2026, 11, 14)
    h = core.create_habit(name="Reading", start_date=start, reference_date=today)
    hid = h["id"]

    # Rule 1: today unlogged does not count, does not break streak
    # Rule 2: past unlogged counts as missed
    # Rule 5: percentage None when no accountable days
    h_new = core.create_habit(name="Brand New", start_date=today, reference_date=today)
    stats_new = core.habit_stats(h_new["id"], end_date=today)
    assert stats_new["current_streak"] == 0
    assert stats_new["best_streak"] == 0
    assert stats_new["rate_all"] is None

    # Now simulate a sequence for Reading habit:
    # 2026-11-14 (Sat): done
    # 2026-11-15 (Sun): done
    # 2026-11-16 (Mon): missed
    # 2026-11-17 (Tue): done
    # 2026-11-18 (Wed): skipped (excused)
    # 2026-11-19 (Thu): done
    # 2026-11-20 (Fri): unlogged today!
    core.set_habit_status(hid, date(2026, 11, 14), "done", reference_date=today)
    core.set_habit_status(hid, date(2026, 11, 15), "done", reference_date=today)
    core.set_habit_status(hid, date(2026, 11, 16), "missed", reference_date=today)
    core.set_habit_status(hid, date(2026, 11, 17), "done", reference_date=today)
    core.set_habit_status(hid, date(2026, 11, 18), "skipped", reference_date=today)
    core.set_habit_status(hid, date(2026, 11, 19), "done", reference_date=today)

    # At this point, today (Nov 20) is unlogged.
    # Current streak looking back from yesterday (Nov 19):
    # Nov 19: done (1)
    # Nov 18: skipped (neither adds nor breaks)
    # Nov 17: done (2)
    # Nov 16: missed (streak breaks)
    # Expected current_streak = 2.
    # Best streak:
    # Nov 14 (done) -> 1
    # Nov 15 (done) -> 2
    # Nov 16 (missed) -> 0
    # Nov 17 (done) -> 1
    # Nov 18 (skipped) -> 1
    # Nov 19 (done) -> 2
    # Best streak = 2.
    stats = core.habit_stats(hid, end_date=today)
    assert stats["current_streak"] == 2
    assert stats["best_streak"] == 2

    # Accountable days: Nov 14 to Nov 19 (6 days).
    # done: 4 (14, 15, 17, 19)
    # missed: 1 (16)
    # skipped: 1 (18)
    # Rate: 4 / (4 + 1) = 80%.
    assert stats["total_done"] == 4
    assert stats["total_missed"] == 1
    assert stats["total_skipped"] == 1
    assert stats["rate_all"] == 80
    assert stats["last_done"] == "2026-11-19"

    # Now log today as done:
    core.set_habit_status(hid, today, "done", reference_date=today)
    stats2 = core.habit_stats(hid, end_date=today)
    # Now current streak should be: today(1) + Nov 19(1) + Nov 17(1) = 3!
    assert stats2["current_streak"] == 3
    assert stats2["best_streak"] == 3
    assert stats2["total_done"] == 5
    assert stats2["last_done"] == "2026-11-20"


def test_unlogged_past_day_counts_as_missed():
    today = date(2026, 11, 20)
    # Start 3 days ago: 2026-11-17
    # 17: done
    # 18: unlogged (counts as missed)
    # 19: done
    # 20: unlogged today
    h = core.create_habit(name="Writing", start_date=date(2026, 11, 17), reference_date=today)
    core.set_habit_status(h["id"], date(2026, 11, 17), "done", reference_date=today)
    core.set_habit_status(h["id"], date(2026, 11, 19), "done", reference_date=today)

    stats = core.habit_stats(h["id"], end_date=today)
    # From yesterday (19): done (1). 18: unlogged (missed -> streak cuts).
    assert stats["current_streak"] == 1
    assert stats["total_done"] == 2
    assert stats["total_missed"] == 1  # Nov 18 unlogged counted as missed!
    assert stats["rate_all"] == round(2 * 100 / 3)  # 67%


def test_archived_and_future_habits():
    today = date(2026, 11, 20)
    # Habit archived on Nov 18
    h = core.create_habit(name="Old Habit", start_date=date(2026, 11, 1), reference_date=today)
    core.set_habit_status(h["id"], date(2026, 11, 17), "done", reference_date=today)
    core.set_habit_status(h["id"], date(2026, 11, 18), "done", reference_date=today)
    core.archive_habit(h["id"], archived=True, on_date="2026-11-18")

    # Calculation ends at archived_on
    stats = core.habit_stats(h["id"], end_date=today)
    assert stats["current_streak"] == 2
    assert stats["total_done"] == 2

    # Days after archived_on are not scheduled in habits_for_day
    for_today = core.habits_for_day(date=today)
    assert not any(x["id"] == h["id"] for x in for_today)

    # Habit with future start_date
    h_future = core.create_habit(
        name="Future Habit",
        start_date=today + timedelta(days=5),
        reference_date=today,
    )
    assert not any(x["id"] == h_future["id"] for x in core.habits_for_day(date=today))
    f_stats = core.habit_stats(h_future["id"], end_date=today)
    assert f_stats["current_streak"] == 0
    assert f_stats["rate_all"] is None


def test_habit_calendar():
    today = date(2026, 11, 20)  # Friday
    h = core.create_habit(
        name="Gym",
        days=["mon", "wed", "fri"],
        start_date=date(2026, 11, 16),  # Mon
        reference_date=today,
    )
    # Mon 16: done
    # Tue 17: not_scheduled
    # Wed 18: skipped
    # Thu 19: not_scheduled
    # Fri 20: unlogged (today)
    core.set_habit_status(h["id"], date(2026, 11, 16), "done", reference_date=today)
    core.set_habit_status(h["id"], date(2026, 11, 18), "skipped", reference_date=today)

    # Range: Nov 15 (Sun, before start -> out_of_range) to Nov 20
    cal = core.habit_calendar(h["id"], "2026-11-15", "2026-11-20", reference_date=today)
    statuses = {item["date"]: item["status"] for item in cal}
    assert statuses["2026-11-15"] == "out_of_range"
    assert statuses["2026-11-16"] == "done"
    assert statuses["2026-11-17"] == "not_scheduled"
    assert statuses["2026-11-18"] == "skipped"
    assert statuses["2026-11-19"] == "not_scheduled"
    assert statuses["2026-11-20"] == "unlogged"

    # Exceeding 400 days raises ValueError
    with pytest.raises(ValueError, match="cannot exceed 400 days"):
        core.habit_calendar(h["id"], "2025-01-01", "2026-03-01", reference_date=today)


def test_habits_series_and_summary():
    today = date(2026, 11, 20)
    h1 = core.create_habit(name="Habit A", start_date=date(2026, 11, 18), reference_date=today)
    h2 = core.create_habit(name="Habit B", start_date=date(2026, 11, 18), reference_date=today)

    # Nov 18: both done
    core.set_habit_status(h1["id"], date(2026, 11, 18), "done", reference_date=today)
    core.set_habit_status(h2["id"], date(2026, 11, 18), "done", reference_date=today)

    # Nov 19: h1 done, h2 unlogged (counts as missed)
    core.set_habit_status(h1["id"], date(2026, 11, 19), "done", reference_date=today)

    # Nov 20 (today): h1 done, h2 unlogged (today unlogged does not count)
    core.set_habit_status(h1["id"], today, "done", reference_date=today)

    series = core.habits_series("2026-11-18", "2026-11-20", reference_date=today)
    s_map = {item["date"]: item for item in series}

    # Nov 18: 2 scheduled, 2 done -> 100%
    assert s_map["2026-11-18"]["scheduled"] == 2
    assert s_map["2026-11-18"]["done"] == 2
    assert s_map["2026-11-18"]["percent"] == 100

    # Nov 19: 2 scheduled, 1 done, 1 missed -> 50%
    assert s_map["2026-11-19"]["scheduled"] == 2
    assert s_map["2026-11-19"]["done"] == 1
    assert s_map["2026-11-19"]["missed"] == 1
    assert s_map["2026-11-19"]["percent"] == 50

    # Nov 20: 2 scheduled, 1 accountable (h1 done), 1 unlogged today (not accountable) -> 100%
    assert s_map["2026-11-20"]["scheduled"] == 2
    assert s_map["2026-11-20"]["done"] == 1
    assert s_map["2026-11-20"]["percent"] == 100

    summary = core.habits_summary(end_date=today)
    assert len(summary["habits"]) == 2
    assert summary["best_habit"] is not None
    assert summary["worst_habit"] is not None
    assert summary["best_habit"]["name"] == "Habit A"
    assert summary["worst_habit"]["name"] == "Habit B"


def test_habits_unlogged():
    today = date(2026, 11, 20)
    h = core.create_habit(name="Meditate", start_date=date(2026, 11, 15), reference_date=today)
    # Log Nov 19 and 20, but leave Nov 17 and 18 unlogged
    core.set_habit_status(h["id"], date(2026, 11, 19), "done", reference_date=today)
    core.set_habit_status(h["id"], today, "done", reference_date=today)

    unlogged = core.habits_unlogged(days=3, end_date=today)
    # Days checked: Nov 17, 18, 19.
    # Nov 19 is logged, so unlogged days should be Nov 17 and Nov 18
    unlogged_dates = [item["date"] for item in unlogged]
    assert "2026-11-17" in unlogged_dates
    assert "2026-11-18" in unlogged_dates
    assert "2026-11-19" not in unlogged_dates


def test_schedule_change_recalculates_past():
    today = date(2026, 11, 20)  # Friday
    # Start as daily habit on Nov 16 (Mon)
    h = core.create_habit(name="Workout", start_date=date(2026, 11, 16), reference_date=today)
    # Log Mon 16 done, Tue 17 unlogged (missed if daily)
    core.set_habit_status(h["id"], date(2026, 11, 16), "done", reference_date=today)
    core.set_habit_status(h["id"], date(2026, 11, 18), "done", reference_date=today)

    # Now change schedule to weekdays mon, wed, fri
    core.edit_habit(h["id"], days=["mon", "wed", "fri"])

    # Recalculated stats: Tue 17 is now unscheduled, so it's ignored!
    # Mon 16 (done), Wed 18 (done), Thu 19 (unscheduled), Fri 20 (today unlogged).
    # Streak should be 2!
    stats = core.habit_stats(h["id"], end_date=today)
    assert stats["current_streak"] == 2
    assert stats["total_missed"] == 0


def test_undo_redo_habits():
    today = date(2026, 11, 20)
    # 1. Create habit
    h = core.create_habit(name="Floss", reference_date=today)
    hid = h["id"]
    assert len(storage.load_habits()) == 1

    core.undo()
    assert len(storage.load_habits()) == 0

    core.redo()
    assert len(storage.load_habits()) == 1

    # 2. Set status
    core.set_habit_status(hid, today, "done", reference_date=today)
    logs = storage.load_habit_logs()
    assert len(logs) == 1
    assert logs[0]["status"] == "done"

    core.undo()
    logs_after_undo = storage.load_habit_logs()
    assert len(logs_after_undo) == 0

    core.redo()
    logs_after_redo = storage.load_habit_logs()
    assert len(logs_after_redo) == 1
    assert logs_after_redo[0]["status"] == "done"


def test_missing_and_corrupt_files(tmp_path, monkeypatch):
    data_dir = tmp_path / "planner-data-files"
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("PLANNER_DATA_DIR", str(data_dir))
    monkeypatch.setattr(core, "TASKS_FILE", data_dir / "tasks.json")
    monkeypatch.setattr(core, "EVENTS_FILE", data_dir / "events.json")

    # Missing files return []
    assert storage.load_habits() == []
    assert storage.load_habit_logs() == []

    # Corrupt habits.json
    habits_file = storage.get_habits_file()
    habits_file.write_text("invalid json", encoding="utf-8")
    with pytest.raises(ValueError, match="Corrupt data file"):
        storage.load_habits()

    # Corrupt habit_logs.json
    logs_file = storage.get_habit_logs_file()
    logs_file.write_text("{not a list}", encoding="utf-8")
    with pytest.raises(ValueError, match="Corrupt data file"):
        storage.load_habit_logs()


def test_contract_json_dumps_and_no_textual():
    # Verify core does NOT import Textual
    assert "textual" not in sys.modules or not any(
        "planner.core" in getattr(m, "__file__", "") for m in sys.modules.values()
    )

    today = date(2026, 11, 20)
    h = core.create_habit(name="Read", reference_date=today)
    core.set_habit_status(h["id"], today, "done", reference_date=today)

    # Every public function return value must pass json.dumps
    json.dumps(core.create_habit(name="Contract Habit", reference_date=today))
    json.dumps(core.edit_habit(h["id"], description="Updated"))
    json.dumps(core.list_habits())
    json.dumps(core.habits_for_day(today))
    json.dumps(core.habits_unlogged(days=3, end_date=today))
    json.dumps(core.habit_stats(h["id"], end_date=today))
    json.dumps(core.habit_calendar(h["id"], today - timedelta(days=10), today))
    json.dumps(core.habits_series(today - timedelta(days=5), today))
    json.dumps(core.habits_summary(today))
    json.dumps(core.archive_habit(h["id"]))
    json.dumps(core.delete_habit(h["id"]))
