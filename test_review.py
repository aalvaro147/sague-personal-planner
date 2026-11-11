import json
from datetime import date as Date
from datetime import datetime, timedelta

import pytest

from planner import core, review


@pytest.fixture(autouse=True)
def isolated_data_files(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "TASKS_FILE", tmp_path / "tasks.json")
    monkeypatch.setattr(core, "EVENTS_FILE", tmp_path / "events.json")
    monkeypatch.setattr(core, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(core, "LEGACY_TASKS_FILE", tmp_path / "legacy.jsonl")


def test_review_candidates_are_ordered_unique_and_exclude_ineligible_tasks():
    target = Date(2026, 11, 13)
    overdue = core.create_task("Overdue", target - timedelta(days=1), "alta")
    due_today = core.create_task("Due today", target)
    due_soon = core.create_task("Due soon", target + timedelta(days=2), "alta")
    high_priority = core.create_task("High priority", priority="alta")
    unscheduled = core.create_task("Unscheduled")
    scheduled_today = core.create_task("Already scheduled", target)
    core.plan_block(scheduled_today.id, target.isoformat(), "10:00", "11:00")
    completed = core.create_task("Completed", target - timedelta(days=1))
    core.complete_task(completed.id)
    deleted = core.create_task("Deleted", target - timedelta(days=1))
    core.delete_task(deleted.id)

    candidates = core.review_candidates(target)

    assert [(item["task"].id, item["reason"]) for item in candidates] == [
        (overdue.id, "overdue"),
        (due_today.id, "due_today"),
        (due_soon.id, "due_soon"),
        (high_priority.id, "high_priority"),
        (unscheduled.id, "unscheduled"),
    ]


def test_unscheduled_candidates_include_none_due_and_exclude_future_blocks():
    target = Date(2026, 11, 13)
    no_due = core.create_task("No due date")
    future_block = core.create_task("Already planned later")
    core.plan_block(
        future_block.id,
        (target + timedelta(days=1)).isoformat(),
        "10:00",
        "11:00",
    )

    candidates = core.review_candidates(target)

    assert [(item["task"].id, item["reason"]) for item in candidates] == [
        (no_due.id, "unscheduled")
    ]


def test_candidates_are_ordered_by_five_categories_without_duplicates():
    target = Date(2026, 11, 13)
    overdue = core.create_task("Overdue", target - timedelta(days=2), "alta")
    today = core.create_task("Due today", target)
    soon = core.create_task("Due soon", target + timedelta(days=1))
    high = core.create_task("High priority", priority="alta")
    unscheduled = core.create_task("No due date")
    far_due = core.create_task("Far due", target + timedelta(days=10), "baja")

    items = core.review_candidates(target)

    assert [(item["task"].id, item["reason"]) for item in items] == [
        (overdue.id, "overdue"),
        (today.id, "due_today"),
        (soon.id, "due_soon"),
        (high.id, "high_priority"),
        (unscheduled.id, "unscheduled"),
        (far_due.id, "unscheduled"),
    ]
    assert len({item["task"].id for item in items}) == len(items)


def test_max_candidates_limits_only_unscheduled_tasks():
    target = Date(2026, 11, 13)
    core.save_settings(max_candidates=2)
    urgent = [
        core.create_task(f"Urgent {index}", target - timedelta(days=1))
        for index in range(12)
    ]
    unscheduled = [core.create_task(f"Unscheduled {index}") for index in range(5)]

    candidates = core.review_candidates(target)
    expanded = core.review_candidates(target, unscheduled_limit=4)

    assert [item["task"].id for item in candidates[:12]] == [
        task.id for task in urgent
    ]
    assert [item["reason"] for item in candidates].count("unscheduled") == 2
    assert [
        item["task"].id
        for item in expanded
        if item["reason"] == "unscheduled"
    ] == [task.id for task in unscheduled[:4]]
    assert core.review_candidate_summary(target)["unscheduled_count"] == 5


def test_done_deleted_legacy_and_none_due_tasks_load_without_candidates():
    target = Date(2026, 11, 13)
    created = datetime(2026, 11, 1, 9, 0).isoformat()
    core.TASKS_FILE.write_text(
        json.dumps(
            [
                {
                    "id": "legacy-done",
                    "title": "Legacy completed",
                    "hecha": True,
                    "borrada": False,
                    "creada": created,
                    "actualizada": created,
                    "vence": None,
                    "prioridad": "media",
                    "bloques": [],
                },
                {
                    "id": "legacy-deleted",
                    "title": "Legacy deleted",
                    "hecha": False,
                    "borrada": True,
                    "creada": created,
                    "actualizada": created,
                    "vence": None,
                    "prioridad": "media",
                    "bloques": [],
                },
                {
                    "id": "legacy-unscheduled",
                    "title": "Legacy unscheduled",
                    "hecha": False,
                    "borrada": False,
                    "creada": created,
                    "actualizada": created,
                    "vence": None,
                    "prioridad": "media",
                    "bloques": [],
                },
            ]
        ),
        encoding="utf-8",
    )

    tasks = core.load_tasks()
    candidates = core.review_candidates(target)

    assert len(tasks) == 3
    assert [(item["task"].id, item["reason"]) for item in candidates] == [
        ("legacy-unscheduled", "unscheduled")
    ]


def test_suggest_slot_respects_blocks_events_and_recurring_occurrences():
    target = Date(2026, 11, 11)
    block_task = core.create_task("Morning work")
    core.plan_block(block_task.id, target.isoformat(), "09:00", "10:00")
    core.create_event(
        "Recurring class",
        "2026-11-09",
        "10:30",
        "11:30",
        recurrence={"freq": "weekly", "weekdays": ["mon", "wed"]},
    )
    second_block_task = core.create_task("Afternoon work")
    core.plan_block(second_block_task.id, target.isoformat(), "12:00", "13:00")

    assert core.suggest_slot(target, 60) == ("13:00", "14:00")
    assert core.suggest_slot(target, 30) == ("10:00", "10:30")


def test_suggest_slot_returns_none_when_no_gap_or_duration_is_too_long():
    target = Date(2026, 11, 11)
    first = core.create_task("First")
    second = core.create_task("Second")
    core.plan_block(first.id, target.isoformat(), "09:00", "10:00")
    core.plan_block(second.id, target.isoformat(), "11:00", "12:00")

    assert core.suggest_slot(target, 61, "09:00", "12:00") is None

    core.create_event("Lunch", target.isoformat(), "10:00", "11:00")
    assert core.suggest_slot(target, 1, "09:00", "12:00") is None


def test_missed_blocks_only_returns_past_pending_blocks(monkeypatch):
    today = Date.today()
    yesterday = today - timedelta(days=1)

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(today.year, today.month, today.day, 12, 0)

    monkeypatch.setattr(review, "datetime", FixedDateTime)
    past_task = core.create_task("Yesterday")
    core.plan_block(past_task.id, yesterday.isoformat(), "16:00", "17:00")
    earlier_today = core.create_task("Earlier today")
    core.plan_block(earlier_today.id, today.isoformat(), "10:00", "11:00")
    later_today = core.create_task("Later today")
    core.plan_block(later_today.id, today.isoformat(), "13:00", "14:00")
    completed = core.create_task("Completed")
    core.plan_block(completed.id, yesterday.isoformat(), "08:00", "09:00")
    core.complete_task(completed.id)
    deleted = core.create_task("Deleted")
    core.plan_block(deleted.id, yesterday.isoformat(), "09:00", "10:00")
    core.delete_task(deleted.id)

    missed = core.missed_blocks(today)

    assert [(entry["task"].id, entry["block"].date) for entry in missed] == [
        (past_task.id, yesterday),
        (earlier_today.id, today),
    ]


def test_reschedule_and_defer_update_timestamp_without_losing_task_data():
    task = core.create_task("Keep details", Date(2026, 11, 13), "alta")
    block = core.plan_block(task.id, "2026-11-12", "10:00", "11:00")
    before_move = core.load_tasks()[0]

    moved = core.reschedule_block(
        task.id,
        block.id,
        Date(2026, 11, 14),
        "12:00",
        "13:00",
    )
    after_move = core.load_tasks()[0]
    deferred = core.defer_task(task.id, Date(2026, 11, 20))
    after_defer = core.load_tasks()[0]

    assert moved.date == Date(2026, 11, 14)
    assert after_move.updated >= before_move.updated
    assert after_move.title == task.title
    assert after_move.priority == "alta"
    assert after_move.blocks[0].start == "12:00"
    assert deferred.due == Date(2026, 11, 20)
    assert after_defer.updated >= after_move.updated
    assert after_defer.title == task.title
    assert after_defer.priority == "alta"
    assert after_defer.blocks[0].date == Date(2026, 11, 14)


def test_day_review_summary_counts_empty_and_completed_days():
    day = Date(2026, 11, 12)
    assert core.day_review_summary(day) == {
        "done_tasks": 0,
        "not_done_tasks": 0,
        "completed_blocks": 0,
        "planned_minutes": 0,
        "completed_minutes": 0,
    }

    completed = core.create_task("Finished")
    core.plan_block(completed.id, day.isoformat(), "09:00", "09:30")
    core.plan_block(completed.id, day.isoformat(), "10:00", "11:00")
    core.complete_task(completed.id)
    pending = core.create_task("Still pending")
    core.plan_block(pending.id, day.isoformat(), "11:00", "11:30")

    assert core.day_review_summary(day) == {
        "done_tasks": 1,
        "not_done_tasks": 1,
        "completed_blocks": 2,
        "planned_minutes": 120,
        "completed_minutes": 90,
    }


def test_day_review_overview_booked_and_free_minutes_counts_overlaps_once():
    target = Date(2026, 11, 15)
    # 09:00 - 18:00 is 540 minutes (9 hours)
    # Event 1: 10:00 - 12:00 (120 min)
    # Event 2: 11:00 - 13:00 (120 min, overlaps 11:00 - 12:00)
    # Combined occupied is 10:00 - 13:00 (180 min = 3h booked, 6h free)
    core.create_event("Event 1", target.isoformat(), "10:00", "12:00")
    core.create_event("Event 2", target.isoformat(), "11:00", "13:00")

    overview = core.day_review_overview(target, "09:00", "18:00")
    assert overview["booked_minutes"] == 180
    assert overview["free_minutes"] == 360
    assert core.format_hours(overview["booked_minutes"]) == "3h"
    assert core.format_hours(overview["free_minutes"]) == "6h"
    assert len(overview["overlaps"]) == 1
    assert [gap for gap in overview["free_gaps"]] == [
        ("09:00", "10:00"),
        ("13:00", "18:00"),
    ]


def test_day_review_overview_with_recurring_and_skipped_events():
    base_date = Date(2026, 11, 10)
    target = Date(2026, 11, 12)
    ev1 = core.create_event(
        "Daily Active",
        base_date.isoformat(),
        "09:00",
        "10:00",
        recurrence={"freq": "daily"},
    )
    ev2 = core.create_event(
        "Daily Skipped",
        base_date.isoformat(),
        "10:00",
        "11:00",
        recurrence={"freq": "daily"},
    )
    core.delete_event(ev2.id, scope="this", occurrence_date=target)

    overview = core.day_review_overview(target, "09:00", "18:00")
    titles = [
        item["event"].title
        for item in overview["agenda"]
        if item["kind"] == "event"
    ]
    assert "Daily Active" in titles
    assert "Daily Skipped" not in titles


def test_review_timeline_formats_and_orders_items_and_gaps():
    target = Date(2026, 11, 15)
    task = core.create_task("Scheduled task")
    core.plan_block(task.id, target.isoformat(), "10:00", "11:00")
    core.create_event("Sync", target.isoformat(), "14:00", "15:00")

    overview = core.day_review_overview(target, "09:00", "18:00")
    timeline = core.review_timeline(overview, suggested_slot=("09:00", "10:00"))

    kinds_and_times = [(item["kind"], item["start"], item["end"]) for item in timeline]
    assert kinds_and_times == [
        ("gap", "09:00", "10:00"),
        ("block", "10:00", "11:00"),
        ("gap", "11:00", "14:00"),
        ("event", "14:00", "15:00"),
        ("gap", "15:00", "18:00"),
    ]
    assert timeline[0]["suggested"] is True
    assert timeline[2]["suggested"] is False


def test_due_tasks_summary():
    target = Date(2026, 11, 15)
    t1 = core.create_task("Due planned", due=target)
    core.plan_block(t1.id, target.isoformat(), "09:00", "10:00")
    core.create_task("Due unplanned", due=target)
    core.create_task("Due other day", due=target + timedelta(days=1))

    summary = core.due_tasks_summary(target)
    assert summary == {"total": 2, "planned": 1, "unplanned": 1}

