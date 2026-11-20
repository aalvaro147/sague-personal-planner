"""Monthly calendar view domain logic.

Provides date arithmetic and month overview data structures completely
decoupled from Textual.
"""

from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta
from typing import Any

from planner import clock, core


def shift_date(
    date_val: date | str,
    days: int = 0,
    weeks: int = 0,
    months: int = 0,
) -> date:
    """Perform date arithmetic adjusting for month bounds.

    When shifting by months, clamps the day to the last valid day of the
    target month (e.g. Jan 31 + 1 month -> Feb 28 or 29).
    """
    if isinstance(date_val, str):
        target = core.parse_date(date_val)
    elif isinstance(date_val, date):
        target = date_val
    else:
        raise ValueError("Invalid date value.")

    if months != 0:
        total_months = target.year * 12 + (target.month - 1) + months
        new_year = total_months // 12
        new_month = (total_months % 12) + 1
        max_day = calendar.monthrange(new_year, new_month)[1]
        new_day = min(target.day, max_day)
        target = date(new_year, new_month, new_day)

    total_days = days + weeks * 7
    if total_days != 0:
        target = target + timedelta(days=total_days)

    return target


def month_overview(
    date_val: date | str | None = None,
    first_weekday: str | None = None,
    max_preview: int = 3,
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Calculate the monthly overview grid.

    Storage is read once per invocation. Returns a structure containing
    year, month, first_weekday, and 4 to 6 full weeks of 7 days each.
    """
    if date_val is None:
        target_date = clock.today()
    elif isinstance(date_val, str):
        target_date = core.parse_date(date_val)
    elif isinstance(date_val, date):
        target_date = date_val
    else:
        raise ValueError("Invalid date value.")

    # Single read of storage
    tasks = core.load_tasks()
    events = core.load_events()
    notes = core.load_notes()
    sett = settings if settings is not None else core.load_settings()

    weekday_pref = first_weekday or sett.get("first_weekday", "mon")
    if weekday_pref not in ("mon", "sun"):
        weekday_pref = "mon"

    year = target_date.year
    month = target_date.month
    first_of_month = date(year, month, 1)
    days_in_month = calendar.monthrange(year, month)[1]
    last_of_month = date(year, month, days_in_month)

    grid_start = core.week_start(first_of_month, weekday_pref)
    last_week_start = core.week_start(last_of_month, weekday_pref)
    grid_end = last_week_start + timedelta(days=6)

    # 1. Resolve event occurrences across full grid range
    events_by_date: dict[date, list[dict[str, Any]]] = {}
    for event in events:
        if event.deleted:
            continue
        for occ in core.occurrences(event, grid_start, grid_end):
            events_by_date.setdefault(occ.date, []).append(
                {
                    "kind": "event",
                    "id": event.id,
                    "title": occ.title,
                    "start": occ.start,
                    "end": occ.end,
                    "recurring": event.recurrence is not None,
                }
            )

    # 2. Collect visible task blocks across full grid range
    blocks_by_date: dict[date, list[dict[str, Any]]] = {}
    for task in tasks:
        for block in task.blocks:
            if not core._is_block_visible(task, block):
                continue
            if grid_start <= block.date <= grid_end:
                blocks_by_date.setdefault(block.date, []).append(
                    {
                        "kind": "block",
                        "id": block.id,
                        "task_id": task.id,
                        "title": task.title,
                        "start": block.start,
                        "end": block.end,
                        "status": getattr(block, "status", "planned"),
                        "recurring": False,
                    }
                )

    # 3. Due tasks by date (pending and not deleted)
    due_tasks_by_date: dict[date, int] = {}
    for task in tasks:
        if not task.deleted and not task.done and task.due is not None:
            if grid_start <= task.due <= grid_end:
                due_tasks_by_date[task.due] = due_tasks_by_date.get(task.due, 0) + 1

    # 4. Notes by date (not deleted and not archived)
    notes_by_date: dict[date, int] = {}
    for note in notes:
        if not note.get("deleted", False) and not note.get("archived", False):
            note_date_str = note.get("date")
            if note_date_str:
                try:
                    nd = core.parse_date(note_date_str)
                    if grid_start <= nd <= grid_end:
                        notes_by_date[nd] = notes_by_date.get(nd, 0) + 1
                except ValueError:
                    pass

    # Thresholds for load calculation
    thresholds = sett.get("load_thresholds", {"light": 120, "medium": 300})
    light_threshold = thresholds.get("light", 120)
    medium_threshold = thresholds.get("medium", 300)

    today_val = clock.today()

    weeks: list[list[dict[str, Any]]] = []
    current_day = grid_start
    current_week: list[dict[str, Any]] = []

    while current_day <= grid_end:
        day_events = events_by_date.get(current_day, [])
        day_blocks = blocks_by_date.get(current_day, [])
        blocks_done = sum(1 for b in day_blocks if b["status"] == "done")

        # Merge intervals for busy minutes
        raw_intervals: list[tuple[int, int]] = []
        for item in day_blocks + day_events:
            start_m = core.time_to_minutes(item["start"])
            end_m = core.time_to_minutes(item["end"])
            if start_m < end_m:
                raw_intervals.append((start_m, end_m))
        raw_intervals.sort()

        merged_intervals: list[tuple[int, int]] = []
        for s, e in raw_intervals:
            if not merged_intervals:
                merged_intervals.append((s, e))
            else:
                prev_s, prev_e = merged_intervals[-1]
                if s <= prev_e:
                    merged_intervals[-1] = (prev_s, max(prev_e, e))
                else:
                    merged_intervals.append((s, e))

        busy_minutes = sum(e - s for s, e in merged_intervals)

        if busy_minutes == 0:
            load = "none"
        elif busy_minutes < light_threshold:
            load = "light"
        elif busy_minutes < medium_threshold:
            load = "medium"
        else:
            load = "heavy"

        all_day_items = sorted(
            day_blocks + day_events,
            key=lambda x: (x["start"], x["end"], x["title"].casefold()),
        )
        total_items = len(all_day_items)
        preview_items = [
            {
                "kind": it["kind"],
                "title": it["title"],
                "start": it["start"],
                "recurring": it.get("recurring", False),
            }
            for it in all_day_items[:max_preview]
        ]
        more = max(0, total_items - max_preview)

        current_week.append(
            {
                "date": current_day.isoformat(),
                "in_month": current_day.month == month,
                "is_today": current_day == today_val,
                "event_count": len(day_events),
                "block_count": len(day_blocks),
                "blocks_done": blocks_done,
                "busy_minutes": busy_minutes,
                "load": load,
                "due_count": due_tasks_by_date.get(current_day, 0),
                "note_count": notes_by_date.get(current_day, 0),
                "preview": preview_items,
                "more": more,
            }
        )

        if len(current_week) == 7:
            weeks.append(current_week)
            current_week = []

        current_day += timedelta(days=1)

    return {
        "year": year,
        "month": month,
        "first_weekday": weekday_pref,
        "weeks": weeks,
    }
