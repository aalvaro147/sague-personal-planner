"""Unit tests for block completion, live day timeline, monthly calendar overview,
and architecture contracts.
"""

from __future__ import annotations

import ast
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from planner import calendar_view, clock, core
from planner.core import (
    load_events,
    load_settings,
    load_tasks,
)
from planner.storage import (
    load_notes,
)


@pytest.fixture(autouse=True)
def setup_env(tmp_path, monkeypatch):
    data_dir = tmp_path / "planner_data"
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("PLANNER_DATA_DIR", str(data_dir))
    monkeypatch.setattr(core, "LEGACY_TASKS_FILE", tmp_path / "legacy.jsonl")
    core.configure_data_dir()
    clock.reset_clock()
    yield data_dir
    clock.reset_clock()


# ---------------------------------------------------------------------------
# Part 1: Block Status & Completion Core Tests
# ---------------------------------------------------------------------------

def test_set_block_status_and_errors():
    today = date(2026, 11, 20)
    clock.set_clock(datetime(2026, 11, 20, 10, 0))

    task = core.create_task("Test task")
    block = core.plan_block(task.id, today.isoformat(), "09:00", "10:00")

    # Set to done
    res = core.set_block_status(task.id, block.id, "done")
    assert res["status"] == "done"
    assert res["completed_at"] is not None

    # Idempotent: no history change
    res2 = core.set_block_status(task.id, block.id, "done")
    assert res2["status"] == "done"

    # Set back to planned while task pending
    res3 = core.set_block_status(task.id, block.id, "planned")
    assert res3["status"] == "planned"
    assert res3["completed_at"] is None

    # Complete task
    core.complete_task(task.id)
    # Attempt to set block to planned on a done task raises ValueError
    with pytest.raises(ValueError, match="Reopen the task first"):
        core.set_block_status(task.id, block.id, "planned")

    # Non-existent task or block
    with pytest.raises(ValueError, match="No active task found"):
        core.set_block_status("invalid-task", block.id, "planned")
    with pytest.raises(ValueError, match="Block not found"):
        core.set_block_status(task.id, "invalid-block", "planned")

    # Deleted task
    del_task = core.create_task("To delete")
    del_block = core.plan_block(del_task.id, today.isoformat(), "10:00", "11:00")
    core.delete_task(del_task.id)
    with pytest.raises(ValueError, match="Cannot update block on a deleted task"):
        core.set_block_status(del_task.id, del_block.id, "done")


def test_complete_block_and_suggest_complete_task():
    today = date(2026, 11, 20)
    clock.set_clock(datetime(2026, 11, 20, 10, 0))

    # Task with multiple blocks
    task = core.create_task("Multi block")
    b1 = core.plan_block(task.id, today.isoformat(), "09:00", "10:00")
    b2 = core.plan_block(task.id, today.isoformat(), "11:00", "12:00")

    # Complete b1 (complete_task=False) -> suggest_complete_task should be False because b2 is planned today
    res1 = core.complete_block(task.id, b1.id, complete_task=False)
    assert res1["block"]["status"] == "done"
    assert not res1["task_completed"]
    assert not res1["suggest_complete_task"]

    # Complete b2 (complete_task=False) -> suggest_complete_task should be True (no other planned blocks from today onward)
    res2 = core.complete_block(task.id, b2.id, complete_task=False)
    assert res2["block"]["status"] == "done"
    assert not res2["task_completed"]
    assert res2["suggest_complete_task"]

    # When complete_task=True, suggest_complete_task is False and task is completed
    task2 = core.create_task("Single block")
    b_single = core.plan_block(task2.id, today.isoformat(), "14:00", "15:00")
    res3 = core.complete_block(task2.id, b_single.id, complete_task=True)
    assert res3["task_completed"]
    assert not res3["suggest_complete_task"]
    assert core.get_task(task2.id).done


def test_complete_recurring_task_creates_next_instance_and_undo_redo():
    today = date(2026, 11, 20)
    clock.set_clock(datetime(2026, 11, 20, 10, 0))

    task = core.create_task(
        "Recurring habit-like task",
        due=today,
        recurrence={"freq": "daily"},
    )
    block = core.plan_block(task.id, today.isoformat(), "09:00", "10:00")

    res = core.complete_block(task.id, block.id, complete_task=True)
    assert res["task_completed"]
    assert res["next_instance"] is not None
    assert res["next_instance"]["due"] == (today + timedelta(days=1)).isoformat()

    # Single undo reverts block completion, task completion, and next instance creation
    core.undo()
    tasks_after_undo = core.load_tasks()
    orig = next(t for t in tasks_after_undo if t.id == task.id)
    assert not orig.done
    assert orig.blocks[0].status == "planned"
    assert len(tasks_after_undo) == 1

    # Redo reapplies everything
    core.redo()
    tasks_after_redo = core.load_tasks()
    orig_redo = next(t for t in tasks_after_redo if t.id == task.id)
    assert orig_redo.done
    assert orig_redo.blocks[0].status == "done"
    assert len(tasks_after_redo) == 2


def test_block_visibility_rules():
    today = date(2026, 11, 20)
    clock.set_clock(datetime(2026, 11, 20, 12, 0))

    # 1. Pending task with planned block -> visible
    t_pending = core.create_task("Pending task")
    b_pending = core.plan_block(t_pending.id, today.isoformat(), "08:00", "09:00")

    # 2. Pending task with done block -> visible
    t_pending2 = core.create_task("Pending with done block")
    b_done_pending = core.plan_block(t_pending2.id, today.isoformat(), "09:00", "10:00")
    core.set_block_status(t_pending2.id, b_done_pending.id, "done")

    # 3. Done task with done block -> visible as history
    t_done = core.create_task("Done task")
    b_done_done = core.plan_block(t_done.id, today.isoformat(), "10:00", "11:00")
    core.complete_block(t_done.id, b_done_done.id, complete_task=True)

    # 4. Done task with planned block (e.g. from future) -> hidden
    t_done2 = core.create_task("Done task with future block")
    b_future = core.plan_block(t_done2.id, today.isoformat(), "15:00", "16:00")
    # Manually complete task without touching future block
    core.complete_task(t_done2.id)

    agenda = core.get_day_agenda(today.isoformat())
    block_ids = [entry["block"].id for entry in agenda if entry["kind"] == "block"]

    assert b_pending.id in block_ids
    assert b_done_pending.id in block_ids
    assert b_done_done.id in block_ids
    assert b_future.id not in block_ids  # Hidden!


def test_complete_task_status_updates_started_today_blocks_only():
    today = date(2026, 11, 20)
    yesterday = today - timedelta(days=1)
    # Clock set to 12:00 today
    clock.set_clock(datetime(2026, 11, 20, 12, 0))

    task = core.create_task("Multi-day task")
    b_past = core.plan_block(task.id, yesterday.isoformat(), "10:00", "11:00")
    b_started_today = core.plan_block(task.id, today.isoformat(), "10:00", "11:00")
    b_not_started_today = core.plan_block(task.id, today.isoformat(), "14:00", "15:00")

    # Complete task
    core.complete_task(task.id)

    reloaded = core.get_task(task.id)
    b_map = {b.id: b for b in reloaded.blocks}

    # Past day block is untouched (planned)
    assert b_map[b_past.id].status == "planned"
    # Started today block (10:00 <= 12:00) is set to done
    assert b_map[b_started_today.id].status == "done"
    # Not yet started today block (14:00 > 12:00) remains planned (and thus hidden)
    assert b_map[b_not_started_today.id].status == "planned"


def test_done_blocks_in_day_load_overlaps_and_missed_blocks():
    today = date(2026, 11, 20)
    clock.set_clock(datetime(2026, 11, 20, 15, 0))

    task = core.create_task("Completed task with block")
    block = core.plan_block(task.id, today.isoformat(), "09:00", "10:30")
    core.complete_block(task.id, block.id, complete_task=True)

    # Done block occupies time in day_load (90 minutes)
    assert core.day_load(today) == 90

    # Overlaps detect the done block
    overlaps = core.find_overlaps(today.isoformat(), "09:30", "10:00")
    assert len(overlaps) == 1
    assert overlaps[0]["block"].id == block.id

    # Done blocks are excluded from missed_blocks
    missed = core.missed_blocks(today)
    assert not any(m["block"].id == block.id for m in missed)


# ---------------------------------------------------------------------------
# Part 2: Live Day Timeline Core Tests
# ---------------------------------------------------------------------------

def test_day_timeline_phases_and_now_scenarios():
    today = date(2026, 11, 20)

    # Setup 2 blocks and 1 event
    t1 = core.create_task("Task 1")
    b1 = core.plan_block(t1.id, today.isoformat(), "09:00", "10:00")

    t2 = core.create_task("Task 2")
    b2 = core.plan_block(t2.id, today.isoformat(), "11:00", "12:00")

    ev = core.create_event("Lunch", today.isoformat(), "12:00", "13:00")

    # 1. now before first item: 08:30
    tl1 = core.day_timeline(today, now_val="08:30")
    assert tl1["is_today"]
    assert tl1["now"] == "08:30"
    phases1 = [item["phase"] for item in tl1["items"]]
    assert phases1 == ["upcoming", "upcoming", "upcoming"]
    assert tl1["summary"]["next_item"]["id"] == b1.id
    assert tl1["summary"]["current_ids"] == []

    # 2. now inside Task 1: 09:30
    tl2 = core.day_timeline(today, now_val="09:30")
    assert tl2["items"][0]["phase"] == "current"
    assert tl2["items"][1]["phase"] == "upcoming"
    assert tl2["summary"]["current_ids"] == [b1.id]

    # 3. now between Task 1 and Task 2: 10:30
    tl3 = core.day_timeline(today, now_val="10:30")
    assert tl3["items"][0]["phase"] == "past"
    assert tl3["items"][1]["phase"] == "upcoming"
    # Task 1 was planned and is now past -> missed == True
    assert tl3["items"][0]["missed"] is True
    assert tl3["summary"]["blocks_missed"] == 1

    # 4. now after last item: 14:00
    tl4 = core.day_timeline(today, now_val="14:00")
    assert all(item["phase"] == "past" for item in tl4["items"])
    assert tl4["summary"]["next_item"] is None

    # 5. Overlapping items: both current
    t_overlap = core.create_task("Overlap Task")
    b_overlap = core.plan_block(t_overlap.id, today.isoformat(), "11:30", "12:30")
    tl5 = core.day_timeline(today, now_val="11:45")
    # At 11:45, both Task 2 (11:00-12:00) and Overlap Task (11:30-12:30) are current
    curr = tl5["summary"]["current_ids"]
    assert b2.id in curr
    assert b_overlap.id in curr

    # 6. Past and future days have uniform phases and now is None
    tl_past = core.day_timeline(today - timedelta(days=2))
    assert not tl_past["is_today"]
    assert tl_past["now"] is None
    assert all(item["phase"] == "past" for item in tl_past["items"])

    tl_future = core.day_timeline(today + timedelta(days=2))
    assert not tl_future["is_today"]
    assert tl_future["now"] is None
    assert all(item["phase"] == "upcoming" for item in tl_future["items"])

    # 7. JSON serializability check
    dumps_result = json.dumps(tl5)
    assert dumps_result is not None


# ---------------------------------------------------------------------------
# Part 3: Monthly Calendar View Core Tests
# ---------------------------------------------------------------------------

def test_shift_date_arithmetic():
    # Jan 31 + 1 month -> Feb 28 in non-leap year (e.g. 2027)
    d1 = date(2027, 1, 31)
    assert calendar_view.shift_date(d1, months=1) == date(2027, 2, 28)

    # Jan 31 + 1 month in leap year (2028) -> Feb 29
    d2 = date(2028, 1, 31)
    assert calendar_view.shift_date(d2, months=1) == date(2028, 2, 29)

    # Leap year day Feb 29 - 1 year -> Feb 28
    d3 = date(2028, 2, 29)
    assert calendar_view.shift_date(d3, months=-12) == date(2027, 2, 28)

    # Days and weeks addition
    assert calendar_view.shift_date(date(2026, 11, 20), days=2, weeks=1) == date(2026, 11, 29)


def test_month_overview_grid_structure_and_weeks():
    # Feb 2027 starts on Monday (Feb 1, 2027 is a Monday) and has 28 days
    # With first_weekday="mon", it spans exactly 4 weeks!
    overview_4w = calendar_view.month_overview(date(2027, 2, 15), first_weekday="mon")
    assert len(overview_4w["weeks"]) == 4

    # Nov 2026 (Nov 1 is Sunday) with first_weekday="mon" spans 6 weeks (Nov 1 in w1, Nov 30 in w6)
    overview_6w = calendar_view.month_overview(date(2026, 11, 20), first_weekday="mon")
    assert len(overview_6w["weeks"]) == 6

    # Verify first_weekday="sun"
    overview_sun = calendar_view.month_overview(date(2026, 11, 20), first_weekday="sun")
    assert overview_sun["first_weekday"] == "sun"
    # First day of grid in Sunday-first week
    first_cell_date = core.parse_date(overview_sun["weeks"][0][0]["date"])
    assert first_cell_date.weekday() == 6  # Sunday


def test_month_overview_load_thresholds_and_content():
    clock.set_clock(datetime(2026, 11, 20, 10, 0))
    d = date(2026, 11, 20)

    # Thresholds: light < 120, medium < 300, heavy >= 300
    t = core.create_task("Work block")
    core.plan_block(t.id, d.isoformat(), "09:00", "10:30")  # 90 mins -> light
    core.create_note(title="Meeting note", date=d.isoformat())

    overview = calendar_view.month_overview(d)
    # Find cell for Nov 20
    target_cell = None
    for week in overview["weeks"]:
        for cell in week:
            if cell["date"] == d.isoformat():
                target_cell = cell
                break

    assert target_cell is not None
    assert target_cell["is_today"] is True
    assert target_cell["in_month"] is True
    assert target_cell["block_count"] == 1
    assert target_cell["note_count"] == 1
    assert target_cell["busy_minutes"] == 90
    assert target_cell["load"] == "light"

    # Add blocks to reach 320 mins -> heavy
    core.plan_block(t.id, d.isoformat(), "11:00", "15:00")  # +240 mins = 330 mins
    overview2 = calendar_view.month_overview(d)
    cell2 = next(c for w in overview2["weeks"] for c in w if c["date"] == d.isoformat())
    assert cell2["load"] == "heavy"

    # Ensure JSON serializable
    assert json.dumps(overview2) is not None


def test_month_overview_reads_storage_only_once():
    d = date(2026, 11, 20)
    with patch("planner.calendar_view.core.load_tasks", wraps=core.load_tasks) as mock_tasks, \
         patch("planner.calendar_view.core.load_events", wraps=core.load_events) as mock_events, \
         patch("planner.calendar_view.core.load_notes", wraps=core.load_notes) as mock_notes:

        calendar_view.month_overview(d)

        assert mock_tasks.call_count == 1
        assert mock_events.call_count == 1
        assert mock_notes.call_count == 1


# ---------------------------------------------------------------------------
# Architecture Contracts
# ---------------------------------------------------------------------------

def test_contract_no_textual_import_in_core_or_calendar_view():
    core_path = Path("planner/core.py")
    cal_path = Path("planner/calendar_view.py")

    for path in (core_path, cal_path):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "textual" not in alias.name
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    assert "textual" not in node.module


def test_contract_no_direct_datetime_now_or_date_today():
    """Verify that only planner/clock.py calls datetime.now() or date.today()."""
    planner_dir = Path("planner")
    for py_file in planner_dir.rglob("*.py"):
        if py_file.name == "clock.py":
            continue
        content = py_file.read_text(encoding="utf-8")
        assert "datetime.now()" not in content, f"{py_file} calls datetime.now()"
        assert "date.today()" not in content, f"{py_file} calls date.today()"
