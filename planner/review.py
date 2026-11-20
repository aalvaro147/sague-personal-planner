from datetime import date, datetime, timedelta
from typing import Literal, TypedDict

from planner import clock, core


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
    target_date = value or clock.today()
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
    first_date = max(value, clock.today())
    for offset in range(366):
        target_date = first_date + timedelta(days=offset)
        not_before = (
            clock.time_str()
            if target_date == clock.today()
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


def missed_blocks(
    value: date | None = None,
    now: datetime | None = None,
) -> list[core.BlockAgendaEntry]:
    target_date = value or clock.today()
    if type(target_date) is not date:
        raise ValueError("Review date must be a date without a time.")

    cur_now = now or clock.now()
    today = clock.today()
    missed = [
        {"kind": "block", "block": block, "task": task}
        for task in core.load_tasks()
        if not task.done and not task.deleted
        for block in task.blocks
        if getattr(block, "status", "planned") != "done"
        and (
            block.date < target_date
            or (
                block.date == target_date
                and (target_date < today or block.end <= cur_now.strftime("%H:%M"))
            )
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
    tasks = core.load_tasks()
    task = core._find_task(tasks, task_id)
    with core.record_action(f'Rescheduled "{task.title}" to {date_text} {start}-{end}'):
        return core.move_block(task_id, block_id, date_text, start, end)


def defer_task(task_id: str, new_due: date) -> core.Task:
    if type(new_due) is not date:
        raise ValueError("Due date must be a date without a time.")
    tasks = core.load_tasks()
    task = core._find_task(tasks, task_id)
    with core.record_action(f'Deferred "{task.title}" to {new_due.isoformat()}'):
        return core.edit_task_details(task_id, due=new_due)


class ReviewSession:
    def __init__(
        self,
        mode: Literal["plan", "close"],
        review_date: date,
        unscheduled_limit: int | None = None,
    ) -> None:
        self.mode = mode
        self.review_date = review_date
        self.unscheduled_limit = (
            unscheduled_limit
            if unscheduled_limit is not None
            else int(core.load_settings().get("max_candidates", core.MAX_CANDIDATES))
        )
        self.candidates: list[ReviewCandidate] = []
        self.candidate_summary: ReviewCandidateSummary = {
            "pending_count": 0,
            "scheduled_count": 0,
            "urgent_count": 0,
            "unscheduled_count": 0,
        }
        self.missed: list[core.BlockAgendaEntry] = []
        self.habits: list[dict[str, Any]] = []
        self.habit_index: int = 0
        self.catch_up_items: list[dict[str, Any]] = []
        self.catch_up_index: int = 0
        self.in_catch_up: bool = False
        self.current_index: int = 0
        self.finished: bool = False
        self.created_task_ids: list[str] = []
        self.rescheduled: list[str] = []
        self.history_stack: list[dict[str, Any]] = []
        self.redo_stack: list[dict[str, Any]] = []
        self.initialize()

    def initialize(self) -> None:
        if self.mode == "plan":
            self.candidate_summary = review_candidate_summary(self.review_date)
            self.candidates = review_candidates(
                self.review_date, unscheduled_limit=self.unscheduled_limit
            )
            self.current_index = 0
            self.finished = False
        else:
            self.missed = missed_blocks(self.review_date)
            self.habits = core.habits_for_day(self.review_date)
            self.current_index = 0
            self.habit_index = 0
            self.catch_up_items = []
            self.catch_up_index = 0
            self.in_catch_up = False
            if not self.missed and not self.habits:
                self.finished = True
            else:
                self.finished = False

    @property
    def phase(self) -> Literal["candidates", "blocks", "habits", "finished"]:
        if self.mode == "plan":
            return "finished" if self.finished else "candidates"
        if self.current_index < len(self.missed):
            return "blocks"
        if self.habit_index < len(self.habits):
            return "habits"
        return "finished"

    @property
    def created_count(self) -> int:
        return len(self.created_task_ids)

    def record_schedule(self, task_id: str) -> None:
        self.history_stack.append({
            "action": "schedule",
            "target_id": task_id,
            "index": self.current_index,
        })
        self.redo_stack.clear()
        self.current_index += 1
        if self.current_index >= len(self.candidates):
            self.finished = True

    def record_skip(self, task_id: str) -> None:
        self.history_stack.append({
            "action": "skip",
            "target_id": task_id,
            "index": self.current_index,
        })
        self.current_index += 1
        if self.current_index >= len(self.candidates):
            self.finished = True

    def record_defer(self, task_id: str) -> None:
        self.history_stack.append({
            "action": "defer",
            "target_id": task_id,
            "index": self.current_index,
        })
        self.redo_stack.clear()
        self.current_index += 1
        if self.mode == "plan":
            if self.current_index >= len(self.candidates):
                self.finished = True
        else:
            if self.current_index >= len(self.missed):
                self.finished = True

    def record_drop(self, task_id: str) -> None:
        self.history_stack.append({
            "action": "drop",
            "target_id": task_id,
            "index": self.current_index,
        })
        self.redo_stack.clear()
        self.current_index += 1
        if self.current_index >= len(self.candidates):
            self.finished = True

    def record_done(self, task_id: str) -> None:
        self.history_stack.append({
            "action": "done",
            "target_id": task_id,
            "index": self.current_index,
        })
        self.redo_stack.clear()
        self.current_index += 1
        self._advance_missed()

    def record_worked_on(self, task_id: str, block_id: str) -> None:
        self.history_stack.append({
            "action": "worked_on",
            "target_id": task_id,
            "block_id": block_id,
            "index": self.current_index,
        })
        self.redo_stack.clear()
        self.current_index += 1
        self._advance_missed()

    def record_reschedule(self, task_id: str, block_id: str, summary_str: str) -> None:
        self.history_stack.append({
            "action": "reschedule",
            "target_id": task_id,
            "block_id": block_id,
            "index": self.current_index,
            "metadata": summary_str,
        })
        self.rescheduled.append(summary_str)
        self.redo_stack.clear()
        self.current_index += 1
        self._advance_missed()

    def record_leave(self, task_id: str) -> None:
        self.history_stack.append({
            "action": "leave",
            "target_id": task_id,
            "index": self.current_index,
        })
        self.current_index += 1
        self._advance_missed()

    def _advance_missed(self) -> None:
        while (
            self.current_index < len(self.missed)
            and (
                self.missed[self.current_index]["task"].done
                or getattr(self.missed[self.current_index]["block"], "status", "planned") == "done"
            )
        ):
            self.current_index += 1
        if self.current_index >= len(self.missed):
            if self.habits and self.habit_index < len(self.habits):
                self.finished = False
            else:
                self.finished = True

    def record_habit_decision(self, habit_id: str, status: str) -> None:
        self.history_stack.append({
            "action": "habit_decision",
            "target_id": habit_id,
            "index": self.habit_index,
            "status": status,
        })
        self.redo_stack.clear()
        self.habit_index += 1
        if self.habit_index >= len(self.habits):
            self.finished = True

    def record_habit_skip(self, habit_id: str) -> None:
        self.history_stack.append({
            "action": "habit_skip",
            "target_id": habit_id,
            "index": self.habit_index,
        })
        self.redo_stack.clear()
        self.habit_index += 1
        if self.habit_index >= len(self.habits):
            self.finished = True

    def record_habit_created(self, habit: dict[str, Any]) -> None:
        if core._is_habit_scheduled(habit, self.review_date):
            h_copy = dict(habit)
            h_copy["status"] = "unlogged"
            h_copy["current_streak"] = 0
            if not any(h["id"] == habit["id"] for h in self.habits):
                self.habits.append(h_copy)
        self.history_stack.append({
            "action": "create_habit",
            "target_id": habit["id"],
            "index": self.habit_index,
        })
        self.redo_stack.clear()

    def start_catch_up(self, days: int = 3) -> list[dict[str, Any]]:
        unlogged_groups = core.habits_unlogged(days=days, end_date=self.review_date)
        items: list[dict[str, Any]] = []
        for group in unlogged_groups:
            g_date = group["date"]
            for h in group["habits"]:
                items.append({
                    "date": g_date,
                    "habit": h,
                })
        self.catch_up_items = items
        self.catch_up_index = 0
        self.in_catch_up = len(items) > 0
        return self.catch_up_items

    def record_catch_up_decision(self, habit_id: str, date_str: str, status: str) -> None:
        self.history_stack.append({
            "action": "catch_up_decision",
            "target_id": habit_id,
            "date": date_str,
            "index": self.catch_up_index,
            "status": status,
        })
        self.redo_stack.clear()
        self.catch_up_index += 1
        if self.catch_up_index >= len(self.catch_up_items):
            self.in_catch_up = False

    def record_catch_up_skip(self, habit_id: str, date_str: str) -> None:
        self.history_stack.append({
            "action": "catch_up_skip",
            "target_id": habit_id,
            "date": date_str,
            "index": self.catch_up_index,
        })
        self.redo_stack.clear()
        self.catch_up_index += 1
        if self.catch_up_index >= len(self.catch_up_items):
            self.in_catch_up = False

    def record_task_created(self, task: core.Task) -> None:
        if task.id not in self.created_task_ids:
            self.created_task_ids.append(task.id)
        if not any(c["task"].id == task.id for c in self.candidates):
            self.candidates.append({"task": task, "reason": "unscheduled"})
        self.history_stack.append({
            "action": "create_task",
            "target_id": task.id,
            "index": self.current_index,
        })
        self.redo_stack.clear()

    def rebuild_queue(self) -> None:
        all_tasks = {t.id: t for t in core.load_tasks()}
        if self.mode == "plan":
            new_candidates: list[ReviewCandidate] = []
            for c in self.candidates:
                tid = c["task"].id
                if tid in all_tasks:
                    task = all_tasks[tid]
                    if not task.deleted:
                        new_candidates.append({"task": task, "reason": c["reason"]})
            for cid in self.created_task_ids:
                if cid in all_tasks and not all_tasks[cid].deleted:
                    if not any(c["task"].id == cid for c in new_candidates):
                        new_candidates.append({"task": all_tasks[cid], "reason": "unscheduled"})
            self.candidates = new_candidates
            if self.current_index >= len(self.candidates) and self.candidates:
                self.current_index = len(self.candidates) - 1
        else:
            for m in self.missed:
                tid = m["task"].id
                if tid in all_tasks:
                    m["task"] = all_tasks[tid]
                    for b in m["task"].blocks:
                        if b.id == m["block"].id:
                            m["block"] = b
                            break
            updated_habits = {h["id"]: h for h in core.habits_for_day(self.review_date)}
            new_habits = []
            for h in self.habits:
                if h["id"] in updated_habits:
                    new_habits.append(updated_habits[h["id"]])
                elif not h.get("deleted", False):
                    new_habits.append(h)
            self.habits = new_habits

    def handle_undo(self, affected_ids: list[str]) -> None:
        # Check if created habit undone
        for i in range(len(self.history_stack) - 1, -1, -1):
            step = self.history_stack[i]
            if step["action"] == "create_habit" and step["target_id"] in affected_ids:
                popped = self.history_stack.pop(i)
                self.redo_stack.append(popped)
                self.habits = [h for h in self.habits if h["id"] != step["target_id"]]
                if self.habit_index >= len(self.habits) and self.habits:
                    self.habit_index = len(self.habits) - 1
                self.rebuild_queue()
                return

        # Check if habit decision or skip was undone
        for i in range(len(self.history_stack) - 1, -1, -1):
            step = self.history_stack[i]
            if step["action"] in ("habit_decision", "habit_skip"):
                popped = self.history_stack[i:]
                self.history_stack = self.history_stack[:i]
                for p in reversed(popped):
                    self.redo_stack.append(p)
                self.habit_index = step["index"]
                self.finished = False
                self.rebuild_queue()
                return

        # Check catch up undo
        for i in range(len(self.history_stack) - 1, -1, -1):
            step = self.history_stack[i]
            if step["action"] in ("catch_up_decision", "catch_up_skip"):
                popped = self.history_stack[i:]
                self.history_stack = self.history_stack[:i]
                for p in reversed(popped):
                    self.redo_stack.append(p)
                self.catch_up_index = step["index"]
                self.in_catch_up = True
                self.rebuild_queue()
                return

        undone_created = next(
            (cid for cid in self.created_task_ids if cid in affected_ids),
            None,
        )
        if undone_created is not None:
            self.created_task_ids.remove(undone_created)
            self.candidates = [c for c in self.candidates if c["task"].id != undone_created]
            for i in range(len(self.history_stack) - 1, -1, -1):
                if (
                    self.history_stack[i]["action"] == "create_task"
                    and self.history_stack[i]["target_id"] == undone_created
                ):
                    self.redo_stack.append(self.history_stack.pop(i))
                    break
            self.rebuild_queue()
            return

        for i in range(len(self.history_stack) - 1, -1, -1):
            step = self.history_stack[i]
            if step["target_id"] in affected_ids:
                popped = self.history_stack[i:]
                self.history_stack = self.history_stack[:i]
                for p in reversed(popped):
                    self.redo_stack.append(p)
                self.current_index = step["index"]
                self.finished = False
                if step["action"] == "reschedule":
                    meta = step.get("metadata")
                    if meta and meta in self.rescheduled:
                        self.rescheduled.remove(meta)
                self.rebuild_queue()
                return

        if self.mode == "close" and self.phase == "habits" and self.habit_index > 0:
            self.habit_index -= 1
            self.finished = False
        elif self.current_index > 0:
            self.current_index -= 1
            self.finished = False
        self.rebuild_queue()

    def handle_redo(self, affected_ids: list[str]) -> None:
        if not self.redo_stack:
            self.rebuild_queue()
            return

        step = self.redo_stack.pop()
        self.history_stack.append(step)
        if step["action"] == "create_task":
            if step["target_id"] not in self.created_task_ids:
                self.created_task_ids.append(step["target_id"])
            self.rebuild_queue()
            return

        if step["action"] == "create_habit":
            self.rebuild_queue()
            return

        if step["action"] in ("habit_decision", "habit_skip"):
            self.habit_index = step["index"] + 1
            self.rebuild_queue()
            if self.habit_index >= len(self.habits):
                self.finished = True
            return

        if step["action"] in ("catch_up_decision", "catch_up_skip"):
            self.catch_up_index = step["index"] + 1
            if self.catch_up_index >= len(self.catch_up_items):
                self.in_catch_up = False
            self.rebuild_queue()
            return

        if step["action"] == "reschedule":
            meta = step.get("metadata")
            if meta and meta not in self.rescheduled:
                self.rescheduled.append(meta)
        self.current_index = step["index"] + 1
        self.rebuild_queue()
        if self.mode == "plan":
            if self.current_index >= len(self.candidates):
                self.finished = True
        else:
            self._advance_missed()


def day_review_summary(value: date | None = None) -> DayReviewSummary:
    target_date = value or clock.today()
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
    completed = [
        (task, block)
        for task, block in planned
        if getattr(block, "status", "planned") == "done"
    ]
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
