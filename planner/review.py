from datetime import date, datetime, timedelta
from typing import Literal, TypedDict

from planner import core


class ReviewCandidate(TypedDict):
    task: core.Task
    reason: str


class ReviewCandidateSummary(TypedDict):
    pending_count: int
    scheduled_count: int
    urgent_count: int
    unscheduled_count: int


class DayReviewSummary(TypedDict):
    done_tasks: int
    not_done_tasks: int
    completed_blocks: int
    planned_minutes: int
    completed_minutes: int


class DayOverview(TypedDict):
    agenda: list[core.AgendaEntry]
    events: list[core.EventOccurrence]
    free_gaps: list[tuple[str, str]]
    free_minutes: int
    booked_minutes: int
    overlaps: list[tuple[core.AgendaEntry, core.AgendaEntry]]


class ReviewTimelineItem(TypedDict, total=False):
    kind: str
    start: str
    end: str
    title: str
    recurring: bool
    overlap: bool
    suggested: bool
    conflict_with: str
    entry: core.AgendaEntry | None


def _minutes(time_text: str) -> int:
    parsed = datetime.strptime(time_text, "%H:%M")
    return parsed.hour * 60 + parsed.minute


def _time(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _review_candidate_groups(
    value: date | None,
) -> tuple[list[ReviewCandidate], list[ReviewCandidate], ReviewCandidateSummary]:
    target_date = value or date.today()
    if type(target_date) is not date:
        raise ValueError("Review date must be a date without a time.")

    pending_tasks = [
        task
        for task in core.list_tasks()
        if not task.done
        and not task.deleted
    ]
    active_tasks = [
        task
        for task in pending_tasks
        if all(block.date != target_date for block in task.blocks)
    ]
    categories = (
        (
            "overdue",
            lambda task: task.due is not None and task.due < target_date,
        ),
        (
            "due_today",
            lambda task: task.due == target_date,
        ),
        (
            "due_soon",
            lambda task: (
                task.due is not None
                and target_date < task.due <= target_date + timedelta(days=3)
                and not task.blocks
            ),
        ),
        (
            "high_priority",
            lambda task: task.priority == "alta" and not task.blocks,
        ),
    )
    urgent: list[ReviewCandidate] = []
    seen: set[str] = set()
    for reason, matches in categories:
        for task in active_tasks:
            if task.id not in seen and matches(task):
                urgent.append({"task": task, "reason": reason})
                seen.add(task.id)

    priority_order = {"alta": 0, "media": 1, "baja": 2}
    unscheduled_tasks = sorted(
        (
            task
            for task in active_tasks
            if task.id not in seen
            and not any(block.date > target_date for block in task.blocks)
        ),
        key=lambda task: (
            priority_order.get(task.priority, len(priority_order)),
            task.created,
            task.title.casefold(),
        ),
    )
    unscheduled = [
        {"task": task, "reason": "unscheduled"}
        for task in unscheduled_tasks
    ]
    summary: ReviewCandidateSummary = {
        "pending_count": len(pending_tasks),
        "scheduled_count": sum(
            any(block.date >= target_date for block in task.blocks)
            for task in pending_tasks
        ),
        "urgent_count": len(urgent),
        "unscheduled_count": len(unscheduled),
    }
    return urgent, unscheduled, summary


def review_candidate_summary(value: date | None = None) -> ReviewCandidateSummary:
    _, _, summary = _review_candidate_groups(value)
    return summary


def review_candidates(
    value: date | None = None,
    *,
    unscheduled_limit: int | None = None,
) -> list[ReviewCandidate]:
    urgent, unscheduled, _ = _review_candidate_groups(value)
    settings_limit = core.load_settings()["max_candidates"]
    limit = settings_limit if unscheduled_limit is None else unscheduled_limit
    if type(limit) is not int or limit <= 0:
        raise ValueError("Unscheduled candidate limit must be a positive integer.")
    return urgent + unscheduled[:limit]


def suggest_slot(
    value: date,
    duration_minutes: int,
    day_start: str = "09:00",
    day_end: str = "18:00",
) -> tuple[str, str] | None:
    return _find_slot(value, duration_minutes, day_start, day_end, None)


def suggest_next_slot(
    value: date,
    duration_minutes: int,
    day_start: str = "09:00",
    day_end: str = "18:00",
) -> tuple[date, str, str] | None:
    if type(value) is not date:
        raise ValueError("Slot date must be a date without a time.")
    first_date = max(value, date.today())
    for offset in range(366):
        target_date = first_date + timedelta(days=offset)
        not_before = (
            datetime.now().strftime("%H:%M")
            if target_date == date.today()
            else None
        )
        slot = _find_slot(
            target_date,
            duration_minutes,
            day_start,
            day_end,
            not_before,
        )
        if slot is not None:
            return target_date, slot[0], slot[1]
    return None


def _find_slot(
    value: date,
    duration_minutes: int,
    day_start: str,
    day_end: str,
    not_before: str | None,
) -> tuple[str, str] | None:
    if type(value) is not date:
        raise ValueError("Slot date must be a date without a time.")
    if type(duration_minutes) is not int or duration_minutes <= 0:
        raise ValueError("Duration must be a positive number of minutes.")
    start_time = core.normalize_time(day_start, "day start")
    end_time = core.normalize_time(day_end, "day end")
    window_start = _minutes(start_time)
    window_end = _minutes(end_time)
    if window_start >= window_end:
        raise ValueError("Day end must be later than day start.")

    cursor = max(window_start, _minutes(not_before)) if not_before else window_start
    for entry in core.get_day_agenda(value.isoformat()):
        item = entry["block"] if entry["kind"] == "block" else entry["event"]
        occupied_start = _minutes(item.start)
        occupied_end = _minutes(item.end)
        if occupied_end <= cursor or occupied_start >= window_end:
            continue
        available_end = min(occupied_start, window_end)
        if available_end - cursor >= duration_minutes:
            return _time(cursor), _time(cursor + duration_minutes)
        cursor = max(cursor, occupied_end)
        if cursor + duration_minutes > window_end:
            return None

    if cursor + duration_minutes <= window_end:
        return _time(cursor), _time(cursor + duration_minutes)
    return None


def missed_blocks(value: date | None = None) -> list[core.BlockAgendaEntry]:
    target_date = value or date.today()
    if type(target_date) is not date:
        raise ValueError("Review date must be a date without a time.")

    now = datetime.now()
    today = date.today()
    missed = [
        {"kind": "block", "block": block, "task": task}
        for task in core.load_tasks()
        if not task.done and not task.deleted
        for block in task.blocks
        if block.date < target_date
        or (
            block.date == target_date
            and (target_date < today or block.end <= now.strftime("%H:%M"))
        )
    ]
    return sorted(
        missed,
        key=lambda entry: (
            entry["block"].date,
            entry["block"].start,
            entry["task"].title.casefold(),
        ),
    )


def reschedule_block(
    task_id: str,
    block_id: str,
    new_date: date | str,
    start: str,
    end: str,
) -> core.ScheduledBlock:
    date_text = new_date.isoformat() if type(new_date) is date else new_date
    if not isinstance(date_text, str):
        raise ValueError("New block date must be a date or YYYY-MM-DD string.")
    return core.move_block(task_id, block_id, date_text, start, end)


def defer_task(task_id: str, new_due: date) -> core.Task:
    if type(new_due) is not date:
        raise ValueError("Due date must be a date without a time.")
    return core.edit_task_details(task_id, due=new_due)


def day_review_summary(value: date | None = None) -> DayReviewSummary:
    target_date = value or date.today()
    if type(target_date) is not date:
        raise ValueError("Review date must be a date without a time.")

    planned = [
        (task, block)
        for task in core.load_tasks()
        if not task.deleted
        for block in task.blocks
        if block.date == target_date
    ]
    tasks_by_id = {task.id: task for task, _ in planned}
    done_tasks = sum(task.done for task in tasks_by_id.values())
    completed = [(task, block) for task, block in planned if task.done]
    return {
        "done_tasks": done_tasks,
        "not_done_tasks": len(tasks_by_id) - done_tasks,
        "completed_blocks": len(completed),
        "planned_minutes": sum(
            _minutes(block.end) - _minutes(block.start)
            for _, block in planned
        ),
        "completed_minutes": sum(
            _minutes(block.end) - _minutes(block.start)
            for _, block in completed
        ),
    }


def day_review_overview(
    value: date,
    day_start: str = "09:00",
    day_end: str = "18:00",
) -> DayOverview:
    if type(value) is not date:
        raise ValueError("Review date must be a date without a time.")
    start = _minutes(core.normalize_time(day_start, "day start"))
    end = _minutes(core.normalize_time(day_end, "day end"))
    if start >= end:
        raise ValueError("Day end must be later than day start.")

    agenda = core.get_day_agenda(value.isoformat())
    intervals: list[tuple[int, int]] = []
    for entry in agenda:
        item = entry["block"] if entry["kind"] == "block" else entry["event"]
        intervals.append(
            (max(start, _minutes(item.start)), min(end, _minutes(item.end)))
        )
    intervals = sorted((left, right) for left, right in intervals if left < right)

    free_gaps: list[tuple[str, str]] = []
    cursor = start
    for left, right in intervals:
        if left > cursor:
            free_gaps.append((_time(cursor), _time(left)))
        cursor = max(cursor, right)
    if cursor < end:
        free_gaps.append((_time(cursor), _time(end)))

    overlaps: list[tuple[core.AgendaEntry, core.AgendaEntry]] = []
    for index, first in enumerate(agenda):
        first_item = first["block"] if first["kind"] == "block" else first["event"]
        for second in agenda[index + 1 :]:
            second_item = (
                second["block"] if second["kind"] == "block" else second["event"]
            )
            if (
                first_item.start < second_item.end
                and first_item.end > second_item.start
            ):
                overlaps.append((first, second))

    free_minutes = sum(
        _minutes(right) - _minutes(left) for left, right in free_gaps
    )
    booked_minutes = (end - start) - free_minutes

    return {
        "agenda": agenda,
        "events": [entry["event"] for entry in agenda if entry["kind"] == "event"],
        "free_gaps": free_gaps,
        "free_minutes": free_minutes,
        "booked_minutes": booked_minutes,
        "overlaps": overlaps,
    }


def format_hours(minutes: int) -> str:
    h = minutes // 60
    m = minutes % 60
    if m == 0:
        return f"{h}h"
    return f"{h}h {m}m"


def due_tasks_summary(target_date: date) -> dict[str, int]:
    if type(target_date) is not date:
        raise ValueError("Target date must be a date without a time.")
    tasks = [
        task
        for task in core.load_tasks()
        if not task.deleted and not task.done and task.due == target_date
    ]
    planned = sum(
        1 for task in tasks if any(block.date == target_date for block in task.blocks)
    )
    return {
        "total": len(tasks),
        "planned": planned,
        "unplanned": len(tasks) - planned,
    }


def review_timeline(
    overview: DayOverview,
    suggested_slot: tuple[str, str] | None = None,
    preview: tuple[str, str, str, list[core.AgendaEntry]] | None = None,
) -> list[ReviewTimelineItem]:
    overlapping_entries: set[int] = set()
    for first, second in overview["overlaps"]:
        item_first = first["block"] if first["kind"] == "block" else first["event"]
        item_second = second["block"] if second["kind"] == "block" else second["event"]
        overlapping_entries.add(id(item_first))
        overlapping_entries.add(id(item_second))

    items: list[ReviewTimelineItem] = []
    for entry in overview["agenda"]:
        if entry["kind"] == "block":
            item = entry["block"]
            title = entry["task"].title
            recurring = False
        else:
            item = entry["event"]
            title = item.title
            recurring = bool(item.recurring)
        items.append(
            {
                "kind": entry["kind"],
                "start": item.start,
                "end": item.end,
                "title": title,
                "recurring": recurring,
                "overlap": id(item) in overlapping_entries,
                "suggested": False,
                "conflict_with": "",
                "entry": entry,
            }
        )

    for gap_start, gap_end in overview["free_gaps"]:
        gap_start_min = _minutes(gap_start)
        gap_end_min = _minutes(gap_end)
        if suggested_slot is not None:
            s_start_min = _minutes(suggested_slot[0])
            s_end_min = _minutes(suggested_slot[1])
            if gap_start_min <= s_start_min and s_end_min <= gap_end_min:
                if gap_start_min < s_start_min:
                    items.append(
                        {
                            "kind": "gap",
                            "start": gap_start,
                            "end": suggested_slot[0],
                            "title": "FREE",
                            "recurring": False,
                            "overlap": False,
                            "suggested": False,
                            "conflict_with": "",
                        }
                    )
                items.append(
                    {
                        "kind": "gap",
                        "start": suggested_slot[0],
                        "end": suggested_slot[1],
                        "title": "FREE",
                        "recurring": False,
                        "overlap": False,
                        "suggested": True,
                        "conflict_with": "",
                    }
                )
                if s_end_min < gap_end_min:
                    items.append(
                        {
                            "kind": "gap",
                            "start": suggested_slot[1],
                            "end": gap_end,
                            "title": "FREE",
                            "recurring": False,
                            "overlap": False,
                            "suggested": False,
                            "conflict_with": "",
                        }
                    )
                continue
        items.append(
            {
                "kind": "gap",
                "start": gap_start,
                "end": gap_end,
                "title": "FREE",
                "recurring": False,
                "overlap": False,
                "suggested": False,
                "conflict_with": "",
            }
        )

    if preview is not None:
        p_start, p_end, p_title, p_overlaps = preview
        p_conflict = core.format_overlaps(p_overlaps) if p_overlaps else ""
        items.append(
            {
                "kind": "preview",
                "start": p_start,
                "end": p_end,
                "title": p_title,
                "recurring": False,
                "overlap": bool(p_overlaps),
                "suggested": (suggested_slot == (p_start, p_end)),
                "conflict_with": p_conflict,
            }
        )

    return sorted(
        items,
        key=lambda it: (
            it["start"],
            0 if it["kind"] == "gap" else (1 if it["kind"] != "preview" else 2),
            it["end"],
            it["title"],
        ),
    )
