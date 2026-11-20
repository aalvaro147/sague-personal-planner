import json
import os
import re
import shutil
import tempfile
import unicodedata
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, TypedDict

_Date = date

from platformdirs import user_data_dir
from planner import clock
from planner import recurrence as recurrence_rules
from planner.history import (
    HistoryPeek,
    HistoryResult,
    history_list,
    history_peek,
    record_action,
    redo,
    undo,
)


def get_data_dir(create: bool = True) -> Path:
    configured_dir = os.environ.get("PLANNER_DATA_DIR")
    data_dir = (
        Path(configured_dir).expanduser()
        if configured_dir
        else Path(user_data_dir("planner"))
    ).resolve()
    if create:
        try:
            data_dir.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise OSError(
                f"Could not create planner data directory {data_dir}: {error}"
            ) from error
    return data_dir


_INITIAL_DATA_DIR = get_data_dir(create=False)
TASKS_FILE = _INITIAL_DATA_DIR / "tasks.json"
EVENTS_FILE = _INITIAL_DATA_DIR / "events.json"
SETTINGS_FILE = _INITIAL_DATA_DIR / "settings.json"
LEGACY_TASKS_FILE = Path(__file__).resolve().parent.parent / "tareas.jsonl"
VALID_PRIORITIES = {"alta", "media", "baja"}
MAX_CANDIDATES = 10
DEFAULT_HISTORY_LIMIT = 50
DEFAULT_DAY_START = "09:00"
DEFAULT_DAY_END = "18:00"
DEFAULT_REVIEW_DURATION_MINUTES = 60
WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}

def configure_data_dir() -> Path:
    global TASKS_FILE, EVENTS_FILE, SETTINGS_FILE
    data_dir = get_data_dir()
    TASKS_FILE = data_dir / "tasks.json"
    EVENTS_FILE = data_dir / "events.json"
    SETTINGS_FILE = data_dir / "settings.json"
    return data_dir


def initialize_data_storage() -> tuple[Path, list[Path]]:
    data_dir = configure_data_dir()
    project_dir = Path(__file__).resolve().parent.parent
    legacy_package_dir = project_dir / "planificador"
    candidates = {
        "tasks.json": (
            project_dir / "tasks.json",
            legacy_package_dir / "tasks.json",
            legacy_package_dir / "tareas.json",
            project_dir / "tareas.json",
        ),
        "events.json": (
            project_dir / "events.json",
            legacy_package_dir / "events.json",
        ),
        "settings.json": (
            project_dir / "settings.json",
            legacy_package_dir / "settings.json",
        ),
    }
    migrated: list[Path] = []
    for name, sources in candidates.items():
        target = data_dir / name
        if target.exists():
            continue
        source = next((candidate for candidate in sources if candidate.is_file()), None)
        if source is None:
            continue
        try:
            shutil.copy2(source, target)
            migrated.append(target)
            source_backup = source.with_name(f"{source.name}.bak")
            target_backup = target.with_name(f"{target.name}.bak")
            if source_backup.is_file() and not target_backup.exists():
                shutil.copy2(source_backup, target_backup)
        except OSError as error:
            raise OSError(
                f"Could not migrate {source} to {target}: {error}"
            ) from error
    return data_dir, migrated


@dataclass
class ScheduledBlock:
    id: str
    date: date
    start: str
    end: str
    status: str = "planned"
    completed_at: str | None = None


@dataclass
class Task:
    id: str
    title: str
    done: bool
    created: datetime
    updated: datetime
    deleted: bool
    due: date | None = None
    priority: str = "media"
    blocks: list[ScheduledBlock] = field(default_factory=list)
    recurrence: dict[str, Any] | None = None
    series_id: str | None = None
    series_start: date | None = None
    notes: str | None = None
    project_id: str | None = None


@dataclass
class Event:
    id: str
    title: str
    date: date
    start: str
    end: str
    location: str | None
    notes: str | None
    created: datetime
    updated: datetime
    deleted: bool = False
    recurrence: dict[str, Any] | None = None
@dataclass
class Project:
    id: str
    name: str
    description: str | None = None
    status: Literal["active", "paused", "done", "archived"] = "active"
    target_date: str | None = None
    created: str = field(default_factory=lambda: clock.now().isoformat())
    updated: str = field(default_factory=lambda: clock.now().isoformat())
    deleted: bool = False
    notes: str | None = None

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "Project":
        return Project(
            id=data["id"],
            name=data["name"],
            description=data.get("description"),
            status=data.get("status", "active"),
            target_date=data.get("target_date"),
            created=data.get("created", clock.now().isoformat()),
            updated=data.get("updated", clock.now().isoformat()),
            deleted=data.get("deleted", False),
            notes=data.get("notes"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "status": self.status,
            "target_date": self.target_date,
            "created": self.created,
            "updated": self.updated,
            "deleted": self.deleted,
            "notes": self.notes,
        }



@dataclass
class EventOccurrence:
    id: str
    title: str
    date: date
    start: str
    end: str
    location: str | None
    notes: str | None
    recurring: bool
    occurrence_date: date


class BlockAgendaEntry(TypedDict):
    kind: Literal["block"]
    block: ScheduledBlock
    task: Task


class EventAgendaEntry(TypedDict):
    kind: Literal["event"]
    event: EventOccurrence


class FreeGapEntry(TypedDict):
    kind: Literal["gap"]
    start: str
    end: str


AgendaEntry = BlockAgendaEntry | EventAgendaEntry
AgendaTimelineEntry = AgendaEntry | FreeGapEntry


def week_start(value: date, first_weekday: str = "mon") -> date:
    if type(value) is not date:
        raise ValueError("Week date must be a date without a time.")
    if not isinstance(first_weekday, str) or first_weekday not in {"mon", "sun"}:
        raise ValueError("First weekday must be 'mon' or 'sun'.")
    offset = value.weekday() if first_weekday == "mon" else (value.weekday() + 1) % 7
    return value - timedelta(days=offset)


def _time_minutes(time_text: str) -> int:
    parsed_time = datetime.strptime(time_text, "%H:%M")
    return parsed_time.hour * 60 + parsed_time.minute


def time_to_minutes(time_text: str) -> int:
    return _time_minutes(time_text)


def duration_minutes(start_time: str, end_time: str) -> int:
    start = normalize_time(start_time, "start")
    end = normalize_time(end_time, "end")
    if end <= start:
        raise ValueError("End time must be later than start time.")
    return _time_minutes(end) - _time_minutes(start)


def load_settings() -> dict[str, Any]:
    if not SETTINGS_FILE.exists():
        return {
            "first_weekday": "mon",
            "day_start": DEFAULT_DAY_START,
            "day_end": DEFAULT_DAY_END,
            "default_duration_minutes": DEFAULT_REVIEW_DURATION_MINUTES,
            "max_candidates": MAX_CANDIDATES,
            "history_limit": DEFAULT_HISTORY_LIMIT,
        }
    try:
        with SETTINGS_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Could not load settings from {SETTINGS_FILE}: {error}") from error
    if not isinstance(data, dict):
        raise ValueError("Settings must contain a JSON object.")
    if (
        not isinstance(data.get("first_weekday", "mon"), str)
        or data.get("first_weekday", "mon") not in {"mon", "sun"}
    ):
        raise ValueError("Settings 'first_weekday' must be 'mon' or 'sun'.")
    day_start = normalize_time(data.get("day_start", DEFAULT_DAY_START), "day start")
    day_end = normalize_time(data.get("day_end", DEFAULT_DAY_END), "day end")
    if day_start >= day_end:
        raise ValueError("Day end must be later than day start.")
    duration = data.get(
        "default_duration_minutes",
        DEFAULT_REVIEW_DURATION_MINUTES,
    )
    max_candidates = data.get("max_candidates", MAX_CANDIDATES)
    history_limit = data.get("history_limit", DEFAULT_HISTORY_LIMIT)
    if (
        type(duration) is not int
        or duration <= 0
        or duration > _time_minutes(day_end) - _time_minutes(day_start)
    ):
        raise ValueError("Default duration must fit within the planning day.")
    if type(max_candidates) is not int or max_candidates <= 0:
        raise ValueError("'max_candidates' must be a positive integer.")
    if type(history_limit) is not int or history_limit <= 0:
        raise ValueError("'history_limit' must be a positive integer.")
    return {
        "first_weekday": data.get("first_weekday", "mon"),
        "day_start": day_start,
        "day_end": day_end,
        "default_duration_minutes": duration,
        "max_candidates": max_candidates,
        "history_limit": history_limit,
    }


def save_settings(
    first_weekday: str | None = None,
    *,
    day_start: str | None = None,
    day_end: str | None = None,
    default_duration_minutes: int | None = None,
    max_candidates: int | None = None,
    history_limit: int | None = None,
) -> dict[str, Any]:
    settings = load_settings()
    if first_weekday is not None:
        if not isinstance(first_weekday, str) or first_weekday not in {"mon", "sun"}:
            raise ValueError("First weekday must be 'mon' or 'sun'.")
        settings["first_weekday"] = first_weekday
    if day_start is not None:
        settings["day_start"] = normalize_time(day_start, "day start")
    if day_end is not None:
        settings["day_end"] = normalize_time(day_end, "day end")
    if settings["day_start"] >= settings["day_end"]:
        raise ValueError("Day end must be later than day start.")
    if default_duration_minutes is not None:
        settings["default_duration_minutes"] = default_duration_minutes
    if max_candidates is not None:
        settings["max_candidates"] = max_candidates
    if history_limit is not None:
        settings["history_limit"] = history_limit
    duration = settings["default_duration_minutes"]
    if (
        type(duration) is not int
        or duration <= 0
        or duration
        > _time_minutes(settings["day_end"])
        - _time_minutes(settings["day_start"])
    ):
        raise ValueError("Default duration must fit within the planning day.")
    if (
        type(settings["max_candidates"]) is not int
        or settings["max_candidates"] <= 0
    ):
        raise ValueError("'max_candidates' must be a positive integer.")
    if (
        type(settings["history_limit"]) is not int
        or settings["history_limit"] <= 0
    ):
        raise ValueError("'history_limit' must be a positive integer.")
    _atomic_save_json(SETTINGS_FILE, settings)
    return settings


def week_agenda(
    value: date,
    first_weekday: str = "mon",
) -> list[dict[str, Any]]:
    start = week_start(value, first_weekday)
    return [
        {
            "date": day,
            "agenda": get_day_agenda(day.isoformat()),
        }
        for day in (start + timedelta(days=offset) for offset in range(7))
    ]


def day_load(value: date) -> int:
    if type(value) is not date:
        raise ValueError("Load date must be a date without a time.")
    intervals: list[tuple[int, int]] = []
    for entry in get_day_agenda(value.isoformat()):
        item = entry["block"] if entry["kind"] == "block" else entry["event"]
        start = datetime.strptime(item.start, "%H:%M")
        end = datetime.strptime(item.end, "%H:%M")
        intervals.append((start.hour * 60 + start.minute, end.hour * 60 + end.minute))
    if not intervals:
        return 0
    intervals.sort()
    occupied = 0
    current_start, current_end = intervals[0]
    for start, end in intervals[1:]:
        if start > current_end:
            occupied += current_end - current_start
            current_start, current_end = start, end
        else:
            current_end = max(current_end, end)
    return occupied + current_end - current_start


def week_summary(
    value: date,
    first_weekday: str = "mon",
) -> list[dict[str, Any]]:
    summary = []
    for day in week_agenda(value, first_weekday):
        current_date = day["date"]
        summary.append(
            {
                "date": current_date,
                "item_count": len(day["agenda"]),
                "occupied_minutes": day_load(current_date),
                "due_tasks": [
                    task
                    for task in list_tasks()
                    if not task.deleted and not task.done and task.due == current_date
                ],
            }
        )
    return summary


def week_due_without_block(
    value: date,
    first_weekday: str = "mon",
) -> list[Task]:
    start = week_start(value, first_weekday)
    end = start + timedelta(days=6)
    return sorted(
        (
            task
            for task in list_tasks()
            if not task.done
            and task.due is not None
            and start <= task.due <= end
            and not task.blocks
        ),
        key=lambda task: (task.due or date.max, task.title.casefold()),
    )


def parse_date(text: str, reference_date: date | None = None) -> date:
    if not isinstance(text, str):
        raise ValueError("Date must be entered as text.")
    normalized_text = text.strip().casefold()
    reference_date = reference_date or clock.today()
    if normalized_text == "today":
        return reference_date
    if normalized_text == "tomorrow":
        return reference_date + timedelta(days=1)
    if normalized_text in WEEKDAYS:
        days_until = (WEEKDAYS[normalized_text] - reference_date.weekday()) % 7
        if days_until == 0:
            days_until = 7
        return reference_date + timedelta(days=days_until)

    try:
        parsed_date = date.fromisoformat(normalized_text)
    except ValueError as error:
        raise ValueError(
            "Invalid date. Use YYYY-MM-DD, today, tomorrow, or an English weekday."
        ) from error
    if parsed_date.isoformat() != normalized_text:
        raise ValueError(
            "Invalid date. Use YYYY-MM-DD, today, tomorrow, or an English weekday."
        )
    return parsed_date


def parse_due_date(text: str) -> date | None:
    if not isinstance(text, str):
        raise ValueError("Due date must be entered as text.")
    normalized_text = text.strip()
    if not normalized_text:
        return None
    try:
        parsed_date = date.fromisoformat(normalized_text)
    except ValueError as error:
        raise ValueError("Invalid due date. Use YYYY-MM-DD or leave it blank.") from error
    if parsed_date.isoformat() != normalized_text:
        raise ValueError("Invalid due date. Use YYYY-MM-DD or leave it blank.")
    return parsed_date


def validate_recurrence(
    rule: dict[str, Any] | None,
    base_date: date,
) -> dict[str, Any] | None:
    return recurrence_rules.validate_rule(rule, base_date)


def _validate_event_recurrence(
    rule: dict[str, Any] | None,
    base_date: date,
    title: str,
    start_time: str,
    end_time: str,
    location: str | None,
    notes: str | None,
) -> dict[str, Any] | None:
    normalized = validate_recurrence(rule, base_date)
    if normalized is None:
        return None
    for override_date, changes in normalized["overrides"].items():
        effective_date = changes.get("date", override_date)
        validate_event_fields(
            changes.get("title", title),
            effective_date,
            changes.get("start", start_time),
            changes.get("end", end_time),
            changes.get("location", location),
            changes.get("notes", notes),
        )
    return normalized


def _validate_date(date_text: str, item_label: str = "Block") -> date:
    if not isinstance(date_text, str):
        raise ValueError(f"{item_label} date must use YYYY-MM-DD format.")
    try:
        parsed_date = date.fromisoformat(date_text)
    except ValueError as error:
        raise ValueError(f"Invalid {item_label.lower()} date. Use YYYY-MM-DD format.") from error
    if parsed_date.isoformat() != date_text:
        raise ValueError(f"Invalid {item_label.lower()} date. Use YYYY-MM-DD format.")
    return parsed_date


def _validate_time(time_text: str, label: str) -> str:
    if not isinstance(time_text, str):
        raise ValueError(f"{label} time must use HH:MM format.")
    try:
        parsed_time = datetime.strptime(time_text, "%H:%M")
    except ValueError as error:
        raise ValueError(f"Invalid {label} time. Use HH:MM format.") from error
    if parsed_time.strftime("%H:%M") != time_text:
        raise ValueError(f"Invalid {label} time. Use HH:MM format.")
    return time_text


def normalize_time(time_text: str, label: str = "event") -> str:
    if not isinstance(time_text, str):
        raise ValueError(f"{label} time must use HH:MM, H:MM, or H format.")
    parts = time_text.split(":")
    if len(parts) == 1:
        hour_text, minute_text = parts[0], "00"
    elif len(parts) == 2:
        hour_text, minute_text = parts
    else:
        raise ValueError(
            f"Invalid {label} time. Use HH:MM, H:MM, or H format."
        )
    if (
        not hour_text.isascii()
        or not hour_text.isdigit()
        or len(hour_text) not in {1, 2}
        or not minute_text.isascii()
        or not minute_text.isdigit()
        or len(minute_text) != 2
    ):
        raise ValueError(
            f"Invalid {label} time. Use HH:MM, H:MM, or H format."
        )
    hour = int(hour_text)
    minute = int(minute_text)
    if hour > 23 or minute > 59:
        raise ValueError(
            f"Invalid {label} time. Use HH:MM, H:MM, or H format."
        )
    return f"{hour:02d}:{minute:02d}"


def _validate_block_interval(
    date_text: str,
    start_time: str,
    end_time: str,
) -> date:
    parsed_date = _validate_date(date_text)
    _validate_time(start_time, "start")
    _validate_time(end_time, "end")
    if end_time <= start_time:
        raise ValueError("Block end time must be later than start time.")
    return parsed_date


def _validate_event_interval(
    date_text: str,
    start_time: str,
    end_time: str,
) -> date:
    parsed_date = _validate_date(date_text, "Event")
    normalized_start = normalize_time(start_time, "start")
    normalized_end = normalize_time(end_time, "end")
    if normalized_end <= normalized_start:
        raise ValueError("Event end time must be later than start time.")
    return parsed_date


def validate_event_fields(
    title: str,
    event_date: str,
    start_time: str,
    end_time: str,
    location: str | None = None,
    notes: str | None = None,
) -> date:
    if not isinstance(title, str) or not title.strip():
        raise ValueError("Event title cannot be empty.")
    if location is not None and not isinstance(location, str):
        raise ValueError("Event location must be text or None.")
    if notes is not None and not isinstance(notes, str):
        raise ValueError("Event notes must be text or None.")
    return _validate_event_interval(event_date, start_time, end_time)


def _block_from_data(data: Any, task_number: int, block_number: int) -> ScheduledBlock:
    if not isinstance(data, dict):
        raise ValueError(
            f"Block {block_number} on task {task_number} must be a JSON object."
        )
    identifier = data.get("id")
    if not isinstance(identifier, str) or not identifier:
        raise ValueError(
            f"Block {block_number} on task {task_number} must have a non-empty ID."
        )
    try:
        parsed_date = _validate_date(data.get("date", data.get("fecha")))
        start = _validate_time(data.get("start", data.get("inicio")), "start")
        end = _validate_time(data.get("end", data.get("fin")), "end")
        if end <= start:
            raise ValueError("Block end time must be later than start time.")
    except ValueError as error:
        raise ValueError(
            f"Invalid block {block_number} on task {task_number}: {error}"
        ) from error
    status = data.get("status", "planned")
    if status not in ("planned", "done"):
        status = "planned"
    completed_at = data.get("completed_at", None)
    return ScheduledBlock(
        identifier, parsed_date, start, end, status=status, completed_at=completed_at
    )


def _task_from_data(data: Any, number: int) -> Task:
    if not isinstance(data, dict):
        raise ValueError(f"Task {number} must be a JSON object.")

    identifier = data.get("id")
    title = data.get("title", data.get("titulo", data.get("descripcion")))
    done = data.get("done", data.get("hecha", False))
    deleted = data.get("deleted", data.get("borrada", False))
    created_data = data.get("created", data.get("creada"))
    updated_data = data.get("updated", data.get("actualizada"))
    due_data = data.get("due", data.get("vence", data.get("fecha_limite")))
    priority = data.get("prioridad", data.get("priority", "media"))
    raw_blocks = data.get("blocks", data.get("bloques", []))
    raw_recurrence = data.get("recurrence")
    series_id = data.get("series_id")
    series_start_data = data.get("series_start")
    notes = data.get("notes")
    project_id = data.get("project_id")

    if not isinstance(identifier, str) or not identifier:
        raise ValueError(f"Task {number} must have a non-empty string ID.")
    if not isinstance(title, str) or not title.strip():
        raise ValueError(f"Task {number} must have a non-empty title.")
    if type(done) is not bool or type(deleted) is not bool:
        raise ValueError(f"Task {number} 'done' and 'deleted' values must be booleans.")
    if not isinstance(priority, str) or priority not in VALID_PRIORITIES:
        raise ValueError(
            f"Task {number} priority must be 'alta', 'media', or 'baja'."
        )
    if not isinstance(raw_blocks, list):
        raise ValueError(f"Task {number} 'blocks' must be a list.")

    try:
        created = datetime.fromisoformat(created_data)
        updated = datetime.fromisoformat(updated_data)
        due = date.fromisoformat(due_data[:10]) if due_data is not None else None
    except (TypeError, ValueError, AttributeError) as error:
        raise ValueError(f"Task {number} contains invalid dates.") from error

    if created.tzinfo is not None or updated.tzinfo is not None:
        raise ValueError(f"Task {number} timestamps must not include a time zone.")

    blocks = [
        _block_from_data(block_data, number, block_number)
        for block_number, block_data in enumerate(raw_blocks, start=1)
    ]
    try:
        series_start = (
            date.fromisoformat(series_start_data)
            if series_start_data is not None
            else due if raw_recurrence is not None else None
        )
    except (TypeError, ValueError) as error:
        raise ValueError(f"Task {number} has an invalid series_start date.") from error
    if series_start_data is not None and series_start.isoformat() != series_start_data:
        raise ValueError(f"Task {number} has an invalid series_start date.")
    recurrence = (
        recurrence_rules.validate_rule(raw_recurrence, series_start)
        if raw_recurrence is not None and series_start is not None
        else None
    )
    if raw_recurrence is not None and due is None:
        raise ValueError(f"Task {number} with recurrence must have a due date.")
    if series_id is not None and (not isinstance(series_id, str) or not series_id):
        raise ValueError(f"Task {number} series_id must be a non-empty string or null.")
    if recurrence is not None and series_id is None:
        series_id = identifier
    block_ids = [block.id for block in blocks]
    if len(block_ids) != len(set(block_ids)):
        raise ValueError(f"Task {number} contains duplicate block IDs.")
    return Task(
        identifier,
        title,
        done,
        created,
        updated,
        deleted,
        due,
        priority,
        blocks,
        recurrence,
        series_id,
        series_start,
        notes=notes,
        project_id=project_id,
    )


def _task_to_data(task: Task) -> dict[str, Any]:
    return {
        "id": task.id,
        "title": task.title,
        "done": task.done,
        "created": task.created.isoformat(),
        "updated": task.updated.isoformat(),
        "deleted": task.deleted,
        "due": task.due.isoformat() if task.due is not None else None,
        "priority": task.priority,
        "blocks": [
            {
                "id": block.id,
                "date": block.date.isoformat(),
                "start": block.start,
                "end": block.end,
                "status": block.status,
                "completed_at": block.completed_at,
            }
            for block in task.blocks
        ],
        "recurrence": task.recurrence,
        "series_id": task.series_id,
        "series_start": task.series_start.isoformat() if task.series_start else None,
        "notes": task.notes,
        "project_id": task.project_id,
    }


def _event_from_data(data: Any, number: int) -> Event:
    if not isinstance(data, dict):
        raise ValueError(f"Event {number} must be a JSON object.")

    identifier = data.get("id")
    title = data.get("title")
    location = data.get("location")
    notes = data.get("notes")
    deleted = data.get("deleted", False)
    if not isinstance(identifier, str) or not identifier:
        raise ValueError(f"Event {number} must have a non-empty string ID.")
    if not isinstance(title, str) or not title.strip():
        raise ValueError(f"Event {number} must have a non-empty title.")
    if type(deleted) is not bool:
        raise ValueError(f"Event {number} 'deleted' value must be a boolean.")
    if location is not None and not isinstance(location, str):
        raise ValueError(f"Event {number} location must be text or null.")
    if notes is not None and not isinstance(notes, str):
        raise ValueError(f"Event {number} notes must be text or null.")

    date_text = data.get("date")
    start = data.get("start")
    end = data.get("end")
    created_text = data.get("created")
    updated_text = data.get("updated")
    if not all(
        isinstance(value, str)
        for value in (date_text, start, end, created_text, updated_text)
    ):
        raise ValueError(f"Event {number} has missing or non-text date/time fields.")

    try:
        event_date = _validate_event_interval(date_text, start, end)
        created = datetime.fromisoformat(created_text)
        updated = datetime.fromisoformat(updated_text)
        recurrence = _validate_event_recurrence(
            data.get("recurrence"),
            event_date,
            title.strip(),
            start,
            end,
            location,
            notes,
        )
    except ValueError as error:
        raise ValueError(
            f"Event {number} contains invalid dates or times: {error}"
        ) from error
    if created.tzinfo is not None or updated.tzinfo is not None:
        raise ValueError(f"Event {number} timestamps must not include a time zone.")

    return Event(
        identifier,
        title.strip(),
        event_date,
        start,
        end,
        location,
        notes,
        created,
        updated,
        deleted,
        recurrence,
    )


def _event_to_data(event: Event) -> dict[str, Any]:
    return {
        "id": event.id,
        "title": event.title,
        "date": event.date.isoformat(),
        "start": event.start,
        "end": event.end,
        "location": event.location,
        "notes": event.notes,
        "created": event.created.isoformat(),
        "updated": event.updated.isoformat(),
        "deleted": event.deleted,
        "recurrence": event.recurrence,
    }


def _atomic_save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as file:
            temporary_path = Path(file.name)
            json.dump(data, file, ensure_ascii=False, indent=2)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())

        if path.exists():
            shutil.copy2(path, path.with_name(f"{path.name}.bak"))
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _read_json_list(path: Path, item_name: str) -> list[Any]:
    try:
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)
        if not isinstance(data, list):
            raise ValueError(f"{path.name} must contain a list of {item_name}.")
        return data
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        backup_path = path.with_name(f"{path.name}.bak")
        backup_status = (
            f"Backup available at {backup_path}."
            if backup_path.exists()
            else f"No backup exists at {backup_path}."
        )
        raise ValueError(
            f"Could not load {item_name} data from {path}: {error}. {backup_status}"
        ) from error


def _invalid_json_data_error(path: Path, item_name: str, error: Exception) -> ValueError:
    backup_path = path.with_name(f"{path.name}.bak")
    backup_status = (
        f"Backup available at {backup_path}."
        if backup_path.exists()
        else f"No backup exists at {backup_path}."
    )
    return ValueError(
        f"Could not load {item_name} data from {path}: {error}. {backup_status}"
    )


def load_events() -> list[Event]:
    if not EVENTS_FILE.exists():
        return []
    data = _read_json_list(EVENTS_FILE, "event")
    try:
        events = [_event_from_data(item, number) for number, item in enumerate(data, 1)]
    except ValueError as error:
        raise _invalid_json_data_error(EVENTS_FILE, "event", error) from error
    identifiers = [event.id for event in events]
    if len(identifiers) != len(set(identifiers)):
        raise _invalid_json_data_error(
            EVENTS_FILE,
            "event",
            ValueError(f"Duplicate event IDs found in {EVENTS_FILE.name}."),
        )
    return events


def save_events(events: list[Event]) -> None:
    _atomic_save_json(EVENTS_FILE, [_event_to_data(event) for event in events])


def save_tasks(tasks: list[Task]) -> None:
    _atomic_save_json(TASKS_FILE, [_task_to_data(task) for task in tasks])


def _migrate_legacy_tasks() -> list[Task]:
    tasks = []
    now = clock.now()

    with LEGACY_TASKS_FILE.open("r", encoding="utf-8") as file:
        for number, line in enumerate(file, start=1):
            try:
                data = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(
                    f"Invalid JSON on line {number} of "
                    f"{LEGACY_TASKS_FILE.name}: {error.msg}"
                ) from error

            if not isinstance(data, dict):
                raise ValueError(
                    f"Line {number} of {LEGACY_TASKS_FILE.name} "
                    "must contain a JSON object."
                )
            due_data = data.get("due", data.get("vence", data.get("fecha_limite")))
            try:
                due = date.fromisoformat(due_data[:10]) if due_data is not None else None
            except (TypeError, ValueError, AttributeError) as error:
                raise ValueError(
                    f"Invalid due date on line {number} of "
                    f"{LEGACY_TASKS_FILE.name}."
                ) from error

            tasks.append(
                _task_from_data(
                    {
                        "id": data.get("id"),
                        "title": data.get("title", data.get("titulo", data.get("descripcion"))),
                        "done": data.get("done", data.get("hecha", False)),
                        "created": data.get("created", data.get("creada", now.isoformat())),
                        "updated": data.get("updated", data.get("actualizada", now.isoformat())),
                        "deleted": data.get("deleted", data.get("borrada", False)),
                        "due": due.isoformat() if due is not None else None,
                        "priority": data.get("priority", data.get("prioridad", "media")),
                        "blocks": data.get("blocks", data.get("bloques", [])),
                        "recurrence": data.get("recurrence"),
                        "series_id": data.get("series_id"),
                    },
                    number,
                )
            )

    save_tasks(tasks)
    return tasks


def load_tasks() -> list[Task]:
    if not TASKS_FILE.exists():
        if LEGACY_TASKS_FILE.exists():
            return _migrate_legacy_tasks()
        return []

    data = _read_json_list(TASKS_FILE, "task")
    try:
        tasks = [_task_from_data(item, number) for number, item in enumerate(data, 1)]
    except ValueError as error:
        raise _invalid_json_data_error(TASKS_FILE, "task", error) from error
    identifiers = [task.id for task in tasks]
    if len(identifiers) != len(set(identifiers)):
        raise _invalid_json_data_error(
            TASKS_FILE,
            "task",
            ValueError(f"Duplicate task IDs found in {TASKS_FILE.name}."),
        )
    block_ids = [
        block.id
        for task in tasks
        for block in task.blocks
    ]
    if len(block_ids) != len(set(block_ids)):
        raise _invalid_json_data_error(
            TASKS_FILE,
            "task",
            ValueError(f"Duplicate block IDs found in {TASKS_FILE.name}."),
        )

    if any(
        "priority" not in item
        or "blocks" not in item
        or any(
            key in item
            for key in (
                "titulo",
                "descripcion",
                "hecha",
                "creada",
                "actualizada",
                "borrada",
                "vence",
                "fecha_limite",
                "prioridad",
                "bloques",
            )
        )
        for item in data
    ):
        save_tasks(tasks)
    return tasks


def list_tasks() -> list[Task]:
    return [task for task in load_tasks() if not task.deleted]


def tasks_due_today(reference_date: date | None = None) -> list[Task]:
    today = reference_date or clock.today()
    return [
        task
        for task in list_tasks()
        if not task.done and task.due is not None and task.due <= today
    ]


def tasks_due_this_week(reference_date: date | None = None) -> list[Task]:
    today = reference_date or clock.today()
    week_end = today + timedelta(days=7)
    return [
        task
        for task in list_tasks()
        if (
            not task.done
            and task.due is not None
            and today <= task.due <= week_end
        )
    ]


def pending_tasks() -> list[Task]:
    return [task for task in list_tasks() if not task.done]


def completed_tasks() -> list[Task]:
    return [task for task in list_tasks() if task.done]


def list_tasks_by_filter(
    filter_name: str,
    reference_date: date | None = None,
) -> list[Task]:
    filters = {
        "pending": pending_tasks,
        "today": lambda: tasks_due_today(reference_date),
        "this_week": lambda: tasks_due_this_week(reference_date),
        "no_date": lambda: [
            task for task in pending_tasks() if task.due is None
        ],
        "done": completed_tasks,
    }
    if filter_name not in filters:
        raise ValueError(
            "Task filter must be 'pending', 'today', 'this_week', 'no_date', or 'done'."
        )

    priority_order = {"alta": 0, "media": 1, "baja": 2}
    return sorted(
        filters[filter_name](),
        key=lambda task: (
            task.due is None,
            task.due or date.max,
            priority_order.get(task.priority, len(priority_order)),
            task.title.casefold(),
        ),
    )


def upcoming_events(reference_date: date | None = None) -> list[EventOccurrence]:
    first_date = reference_date or clock.today()
    return list_events(first_date, first_date + timedelta(days=365))


def plan_block(
    task_id: str,
    block_date: str,
    start_time: str,
    end_time: str,
) -> ScheduledBlock:
    parsed_date = _validate_block_interval(block_date, start_time, end_time)
    tasks = load_tasks()
    task = _find_task(tasks, task_id)
    if task.done:
        raise ValueError("A completed task cannot be scheduled.")
    with record_action(f'Scheduled "{task.title}" {parsed_date:%a %d %b} {start_time}-{end_time}'):
        block = ScheduledBlock(uuid.uuid4().hex, parsed_date, start_time, end_time)
        task.blocks.append(block)
        task.updated = clock.now()
        save_tasks(tasks)
        return block


def remove_block(task_id: str, block_id: str) -> ScheduledBlock:
    tasks = load_tasks()
    task = _find_task(tasks, task_id)
    with record_action(f'Removed block from "{task.title}"'):
        for index, block in enumerate(task.blocks):
            if block.id == block_id:
                removed_block = task.blocks.pop(index)
                task.updated = clock.now()
                save_tasks(tasks)
                return removed_block
        raise ValueError("Block not found on the specified task.")


def move_block(
    task_id: str,
    block_id: str,
    block_date: str,
    start_time: str,
    end_time: str,
) -> ScheduledBlock:
    parsed_date = _validate_block_interval(block_date, start_time, end_time)
    tasks = load_tasks()
    task = _find_task(tasks, task_id)
    with record_action(f'Moved block for "{task.title}"'):
        for block in task.blocks:
            if block.id == block_id:
                block.date = parsed_date
                block.start = start_time
                block.end = end_time
                task.updated = clock.now()
                save_tasks(tasks)
                return block
        raise ValueError("Block not found on the specified task.")


def set_block_status(
    task_id: str,
    block_id: str,
    status: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Change block status ('planned' or 'done').

    If the task is done and status is set back to 'planned', raises
    ValueError("Reopen the task first"). If no change occurs, does not
    record a history action.
    """
    if status not in ("planned", "done"):
        raise ValueError("Block status must be 'planned' or 'done'.")
    tasks = load_tasks()
    task = None
    for t in tasks:
        if t.id == task_id:
            task = t
            break
    if task is None:
        raise ValueError("No active task found with that ID.")
    if task.deleted:
        raise ValueError("Cannot update block on a deleted task.")

    target_block = None
    for block in task.blocks:
        if block.id == block_id:
            target_block = block
            break
    if target_block is None:
        raise ValueError("Block not found on the specified task.")

    if task.done and status == "planned":
        raise ValueError("Reopen the task first")

    cur_status = getattr(target_block, "status", "planned")
    if cur_status == status:
        return {
            "id": target_block.id,
            "date": target_block.date.isoformat(),
            "start": target_block.start,
            "end": target_block.end,
            "status": target_block.status,
            "completed_at": target_block.completed_at,
        }

    cur_now = now or clock.now()
    action_label = f'Block marked {status}: "{task.title}"'
    with record_action(action_label):
        target_block.status = status
        target_block.completed_at = cur_now.isoformat() if status == "done" else None
        task.updated = cur_now
        save_tasks(tasks)

    return {
        "id": target_block.id,
        "date": target_block.date.isoformat(),
        "start": target_block.start,
        "end": target_block.end,
        "status": target_block.status,
        "completed_at": target_block.completed_at,
    }


def complete_block(
    task_id: str,
    block_id: str,
    complete_task: bool = False,
    reference_date: date | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Mark a block as done and optionally complete its parent task.

    Returns a dict with 'block', 'task', 'task_completed', 'next_instance',
    and 'suggest_complete_task'.
    """
    tasks = load_tasks()
    task = None
    for t in tasks:
        if t.id == task_id:
            task = t
            break
    if task is None:
        raise ValueError("No active task found with that ID.")
    if task.deleted:
        raise ValueError("Cannot complete block on a deleted task.")

    target_block = None
    for block in task.blocks:
        if block.id == block_id:
            target_block = block
            break
    if target_block is None:
        raise ValueError("Block not found on the specified task.")

    cur_now = now or clock.now()
    cur_today = reference_date or clock.today()

    if not complete_task:
        has_other_planned = any(
            b.id != block_id
            and b.date >= cur_today
            and getattr(b, "status", "planned") == "planned"
            for b in task.blocks
        )
        suggest_complete_task = not has_other_planned
    else:
        suggest_complete_task = False

    action_label = f'Completed block for "{task.title}"'
    with record_action(action_label):
        target_block.status = "done"
        target_block.completed_at = cur_now.isoformat()
        task.updated = cur_now
        task_completed = False
        next_instance = None

        if complete_task:
            task.done = True
            task_completed = True
            cur_time = cur_now.strftime("%H:%M")
            for b in task.blocks:
                if (
                    b.id != target_block.id
                    and b.date == cur_today
                    and b.start <= cur_time
                    and getattr(b, "status", "planned") == "planned"
                ):
                    b.status = "done"
                    b.completed_at = cur_now.isoformat()

            next_due = _next_task_due(tasks, task, cur_today)
            if next_due is not None:
                new_task = Task(
                    id=uuid.uuid4().hex,
                    title=task.title,
                    done=False,
                    created=cur_now,
                    updated=cur_now,
                    deleted=False,
                    due=next_due,
                    priority=task.priority,
                    recurrence=task.recurrence,
                    series_id=task.series_id or task.id,
                    series_start=task.series_start or task.due,
                )
                tasks.append(new_task)
                next_instance = _task_to_data(new_task)

        save_tasks(tasks)

    return {
        "block": {
            "id": target_block.id,
            "date": target_block.date.isoformat(),
            "start": target_block.start,
            "end": target_block.end,
            "status": target_block.status,
            "completed_at": target_block.completed_at,
        },
        "task": _task_to_data(task),
        "task_completed": task_completed,
        "next_instance": next_instance,
        "suggest_complete_task": suggest_complete_task,
    }


def day_timeline(
    date_val: date | str | None = None,
    now_val: str | datetime | None = None,
) -> dict[str, Any]:
    """Return live timeline representation for a given day.

    Builds upon get_day_agenda and gap calculations without duplicating logic.
    """
    if date_val is None:
        target_date = clock.today()
    elif isinstance(date_val, str):
        target_date = parse_date(date_val)
    elif isinstance(date_val, date):
        target_date = date_val
    else:
        raise ValueError("Invalid date value.")

    today_val = clock.today()
    is_today = target_date == today_val

    if now_val is None:
        now_str = clock.time_str() if is_today else None
    elif isinstance(now_val, datetime):
        now_str = now_val.strftime("%H:%M")
    elif isinstance(now_val, str):
        now_str = now_val
    else:
        raise ValueError("Invalid now value.")

    agenda_entries = get_day_agenda(target_date.isoformat())

    items: list[dict[str, Any]] = []
    blocks_total = 0
    blocks_done = 0
    blocks_missed = 0
    events_total = 0
    minutes_planned = 0
    minutes_done = 0
    current_ids: list[str] = []

    for entry in agenda_entries:
        if entry["kind"] == "block":
            block = entry["block"]
            task = entry["task"]
            blocks_total += 1
            duration = time_to_minutes(block.end) - time_to_minutes(block.start)
            minutes_planned += duration

            if target_date < today_val:
                phase = "past"
            elif target_date > today_val:
                phase = "upcoming"
            else:
                if now_str is not None:
                    if block.end <= now_str:
                        phase = "past"
                    elif block.start <= now_str < block.end:
                        phase = "current"
                    else:
                        phase = "upcoming"
                else:
                    phase = "upcoming"

            status = getattr(block, "status", "planned")
            if status == "done":
                blocks_done += 1
                minutes_done += duration
                missed = False
            else:
                missed = phase == "past"
                if missed:
                    blocks_missed += 1

            if phase == "current":
                current_ids.append(block.id)

            items.append(
                {
                    "kind": "block",
                    "id": block.id,
                    "task_id": task.id,
                    "title": task.title,
                    "start": block.start,
                    "end": block.end,
                    "status": status,
                    "completed_at": getattr(block, "completed_at", None),
                    "phase": phase,
                    "missed": missed,
                }
            )
        else:
            event = entry["event"]
            events_total += 1
            if target_date < today_val:
                phase = "past"
            elif target_date > today_val:
                phase = "upcoming"
            else:
                if now_str is not None:
                    if event.end <= now_str:
                        phase = "past"
                    elif event.start <= now_str < event.end:
                        phase = "current"
                    else:
                        phase = "upcoming"
                else:
                    phase = "upcoming"

            if phase == "current":
                current_ids.append(event.id)

            items.append(
                {
                    "kind": "event",
                    "id": event.id,
                    "title": event.title,
                    "start": event.start,
                    "end": event.end,
                    "phase": phase,
                    "recurring": getattr(event, "recurrence", None) is not None,
                }
            )

    # Gaps inside review window
    settings = load_settings()
    window_start = settings.get("review_window_start", "09:00")
    window_end = settings.get("review_window_end", "18:00")

    occupied: list[tuple[str, str]] = []
    for item in items:
        s = max(item["start"], window_start)
        e = min(item["end"], window_end)
        if s < e:
            occupied.append((s, e))
    occupied.sort()

    merged: list[tuple[str, str]] = []
    for s, e in occupied:
        if not merged:
            merged.append((s, e))
        else:
            prev_s, prev_e = merged[-1]
            if s <= prev_e:
                merged[-1] = (prev_s, max(prev_e, e))
            else:
                merged.append((s, e))

    gaps_list: list[dict[str, Any]] = []
    cursor = window_start
    for s, e in merged:
        if cursor < s:
            dur = time_to_minutes(s) - time_to_minutes(cursor)
            if target_date < today_val:
                gphase = "past"
            elif target_date > today_val:
                gphase = "upcoming"
            else:
                if now_str is not None:
                    if s <= now_str:
                        gphase = "past"
                    elif cursor <= now_str < s:
                        gphase = "current"
                    else:
                        gphase = "upcoming"
                else:
                    gphase = "upcoming"
            gaps_list.append(
                {
                    "start": cursor,
                    "end": s,
                    "duration_minutes": dur,
                    "phase": gphase,
                }
            )
        cursor = max(cursor, e)

    if cursor < window_end:
        dur = time_to_minutes(window_end) - time_to_minutes(cursor)
        if target_date < today_val:
            gphase = "past"
        elif target_date > today_val:
            gphase = "upcoming"
        else:
            if now_str is not None:
                if window_end <= now_str:
                    gphase = "past"
                elif cursor <= now_str < window_end:
                    gphase = "current"
                else:
                    gphase = "upcoming"
            else:
                gphase = "upcoming"
        gaps_list.append(
            {
                "start": cursor,
                "end": window_end,
                "duration_minutes": dur,
                "phase": gphase,
            }
        )

    next_item = next((it for it in items if it["phase"] != "past"), None)

    return {
        "date": target_date.isoformat(),
        "is_today": is_today,
        "now": now_str,
        "items": items,
        "gaps": gaps_list,
        "summary": {
            "blocks_total": blocks_total,
            "blocks_done": blocks_done,
            "blocks_missed": blocks_missed,
            "events_total": events_total,
            "minutes_planned": minutes_planned,
            "minutes_done": minutes_done,
            "next_item": next_item,
            "current_ids": current_ids,
        },
    }


def _is_block_visible(task: Task, block: ScheduledBlock) -> bool:
    """Return whether a block should appear in views and load calculations.

    A block is visible if its task is not deleted and either:
    - the block status is 'done' (preserved as history even if task is done), or
    - the task is pending (not done).
    """
    if task.deleted:
        return False
    return getattr(block, "status", "planned") == "done" or not task.done


def get_day_agenda(block_date: str) -> list[AgendaEntry]:
    requested_date = _validate_date(block_date)
    block_entries: list[AgendaEntry] = [
        {"kind": "block", "block": block, "task": task}
        for task in load_tasks()
        for block in task.blocks
        if block.date == requested_date and _is_block_visible(task, block)
    ]
    event_entries: list[AgendaEntry] = [
        {"kind": "event", "event": event}
        for event in list_events(requested_date)
    ]
    entries = block_entries + event_entries
    return sorted(
        entries,
        key=lambda entry: (
            entry["block"].start if entry["kind"] == "block" else entry["event"].start,
            entry["block"].end if entry["kind"] == "block" else entry["event"].end,
            entry["task"].title if entry["kind"] == "block" else entry["event"].title,
        ),
    )


def get_free_gaps(entries: list[AgendaEntry]) -> list[tuple[str, str]]:
    gaps: list[tuple[str, str]] = []
    previous_end: str | None = None
    for entry in entries:
        start = entry["block"].start if entry["kind"] == "block" else entry["event"].start
        end = entry["block"].end if entry["kind"] == "block" else entry["event"].end
        if previous_end is not None and start > previous_end:
            gaps.append((previous_end, start))
        if previous_end is None or end > previous_end:
            previous_end = end
    return gaps


def get_agenda_timeline(
    entries: list[AgendaEntry],
) -> list[AgendaTimelineEntry]:
    gaps = iter(get_free_gaps(entries))
    next_gap = next(gaps, None)
    timeline: list[AgendaTimelineEntry] = []
    for entry in entries:
        start = entry["block"].start if entry["kind"] == "block" else entry["event"].start
        if next_gap is not None and next_gap[1] == start:
            timeline.append(
                {"kind": "gap", "start": next_gap[0], "end": next_gap[1]}
            )
            next_gap = next(gaps, None)
        timeline.append(entry)
    return timeline


def get_unplanned_tasks() -> list[Task]:
    return [
        task
        for task in pending_tasks()
        if not task.blocks
    ]


def has_overlap(
    block_date: str,
    start_time: str,
    end_time: str,
    exclude_block_id: str | None = None,
    exclude_event_id: str | None = None,
    exclude_occurrence_date: str | date | None = None,
) -> bool:
    return bool(
        find_overlaps(
            block_date,
            start_time,
            end_time,
            exclude_block_id=exclude_block_id,
            exclude_event_id=exclude_event_id,
            exclude_occurrence_date=exclude_occurrence_date,
        )
    )


def find_overlaps(
    block_date: str,
    start_time: str,
    end_time: str,
    exclude_block_id: str | None = None,
    exclude_event_id: str | None = None,
    exclude_occurrence_date: str | date | None = None,
) -> list[AgendaEntry]:
    requested_date = _validate_block_interval(block_date, start_time, end_time)
    overlaps: list[AgendaEntry] = []
    for task in load_tasks():
        for block in task.blocks:
            if not _is_block_visible(task, block):
                continue
            if block.id == exclude_block_id or block.date != requested_date:
                continue
            if start_time < block.end and end_time > block.start:
                overlaps.append({"kind": "block", "block": block, "task": task})
    excluded_date = (
        _coerce_occurrence_date(exclude_occurrence_date)
        if exclude_occurrence_date is not None
        else None
    )
    for event in list_events(requested_date):
        if event.id == exclude_event_id and (
            excluded_date is None or event.occurrence_date == excluded_date
        ):
            continue
        if start_time < event.end and end_time > event.start:
            overlaps.append({"kind": "event", "event": event})
    return sorted(
        overlaps,
        key=lambda entry: (
            entry["block"].start if entry["kind"] == "block" else entry["event"].start,
            entry["block"].end if entry["kind"] == "block" else entry["event"].end,
        ),
    )


def format_overlaps(entries: list[AgendaEntry]) -> str:
    descriptions: list[str] = []
    for entry in entries:
        if entry["kind"] == "block":
            descriptions.append(f'task "{entry["task"].title}"')
        else:
            descriptions.append(f'event "{entry["event"].title}"')
    return ", ".join(descriptions)


def find_event_occurrence_overlaps(
    title: str,
    event_date: str,
    start_time: str,
    end_time: str,
    location: str | None,
    notes: str | None,
    recurrence: dict[str, Any] | None,
    range_start: str | date,
    range_end: str | date,
    exclude_event_id: str | None = None,
) -> list[tuple[date, AgendaEntry]]:
    start_time = normalize_time(start_time, "start")
    end_time = normalize_time(end_time, "end")
    base_date = validate_event_fields(
        title,
        event_date,
        start_time,
        end_time,
        location,
        notes,
    )
    rule = validate_recurrence(recurrence, base_date)
    start = _coerce_occurrence_date(range_start)
    end = _coerce_occurrence_date(range_end)
    candidate = Event(
        id=exclude_event_id or "__new_event__",
        title=title.strip(),
        date=base_date,
        start=start_time,
        end=end_time,
        location=location,
        notes=notes,
        created=clock.now(),
        updated=clock.now(),
        recurrence=rule,
    )
    existing_events = [
        occurrence
        for event in load_events()
        if not event.deleted
        for occurrence in occurrences(event, start, end)
    ]
    all_tasks = load_tasks()
    conflicts: list[tuple[date, AgendaEntry]] = []
    for occurrence in occurrences(candidate, start, end):
        for task in all_tasks:
            for block in task.blocks:
                if not _is_block_visible(task, block):
                    continue
                if (
                    block.date == occurrence.date
                    and occurrence.start < block.end
                    and occurrence.end > block.start
                ):
                    conflicts.append(
                        (
                            occurrence.date,
                            {"kind": "block", "block": block, "task": task},
                        )
                    )
        for existing in existing_events:
            if (
                existing.date == occurrence.date
                and not (
                    existing.id == exclude_event_id
                    and existing.occurrence_date == occurrence.occurrence_date
                )
                and occurrence.start < existing.end
                and occurrence.end > existing.start
            ):
                conflicts.append(
                    (occurrence.date, {"kind": "event", "event": existing})
                )
    return sorted(
        conflicts,
        key=lambda item: (
            item[0],
            item[1]["block"].start
            if item[1]["kind"] == "block"
            else item[1]["event"].start,
        ),
    )


def get_active_task_blocks() -> list[BlockAgendaEntry]:
    entries = [
        {"kind": "block", "block": block, "task": task}
        for task in load_tasks()
        for block in task.blocks
        if _is_block_visible(task, block)
    ]
    return sorted(
        entries,
        key=lambda entry: (
            entry["block"].date,
            entry["block"].start,
            entry["task"].title,
        ),
    )


def create_event(
    title: str,
    date: str,
    start: str,
    end: str,
    location: str | None = None,
    notes: str | None = None,
    recurrence: dict[str, Any] | None = None,
) -> Event:
    start = normalize_time(start, "start")
    end = normalize_time(end, "end")
    event_date = validate_event_fields(title, date, start, end, location, notes)
    recurrence = _validate_event_recurrence(
        recurrence,
        event_date,
        title,
        start,
        end,
        location,
        notes,
    )
    with record_action(f'Created event "{title.strip()}"'):
        now = clock.now()
        event = Event(
            id=uuid.uuid4().hex,
            title=title.strip(),
            date=event_date,
            start=start,
            end=end,
            location=location,
            notes=notes,
            created=now,
            updated=now,
            recurrence=recurrence,
        )
        events = load_events()
        events.append(event)
        save_events(events)
        return event


def _find_event(events: list[Event], identifier: str) -> Event:
    for event in events:
        if event.id == identifier and not event.deleted:
            return event
    raise ValueError("No active event found with that ID.")


def get_event(identifier: str) -> Event:
    return _find_event(load_events(), identifier)


def _coerce_occurrence_date(value: str | date | None) -> date:
    if type(value) is date:
        return value
    if isinstance(value, str):
        return _validate_date(value, "Event")
    raise ValueError("An occurrence date is required for this recurrence scope.")


def _event_for_occurrence(
    event: Event,
    occurrence_date: date,
) -> EventOccurrence:
    if event.deleted:
        raise ValueError("No active event occurrence found on that date.")
    original_date = occurrence_date.isoformat()
    rule = event.recurrence
    if rule is None:
        if occurrence_date != event.date:
            raise ValueError("No active event occurrence found on that date.")
        override: dict[str, Any] = {}
    else:
        if original_date in rule["skipped"] or not recurrence_rules.occurrence_dates(
            event.date,
            rule,
            occurrence_date,
            occurrence_date,
        ):
            raise ValueError("No active event occurrence found on that date.")
        override = rule["overrides"].get(original_date, {})
    effective_date = _validate_date(override.get("date", original_date), "Event")
    values = {
        "title": override.get("title", event.title),
        "start": override.get("start", event.start),
        "end": override.get("end", event.end),
        "location": override.get("location", event.location),
        "notes": override.get("notes", event.notes),
    }
    validate_event_fields(
        values["title"],
        effective_date.isoformat(),
        values["start"],
        values["end"],
        values["location"],
        values["notes"],
    )
    return EventOccurrence(
        id=event.id,
        title=values["title"].strip(),
        date=effective_date,
        start=values["start"],
        end=values["end"],
        location=values["location"],
        notes=values["notes"],
        recurring=rule is not None,
        occurrence_date=occurrence_date,
    )


def edit_event(
    identifier: str,
    *,
    scope: str = "all",
    occurrence_date: str | date | None = None,
    **changes: Any,
) -> Event:
    if scope not in {"this", "all", "this_and_future"}:
        raise ValueError("Event scope must be 'this', 'this_and_future', or 'all'.")
    editable_fields = {
        "title",
        "date",
        "start",
        "end",
        "location",
        "notes",
        "recurrence",
    }
    unknown_fields = changes.keys() - editable_fields
    if unknown_fields:
        raise ValueError(
            f"Unsupported event field(s): {', '.join(sorted(unknown_fields))}."
        )
    if "start" in changes:
        changes["start"] = normalize_time(changes["start"], "start")
    if "end" in changes:
        changes["end"] = normalize_time(changes["end"], "end")

    events = load_events()
    event = _find_event(events, identifier)
    with record_action(lambda: f'Edited event "{event.title}"'):
        if scope == "this":
            if event.recurrence is None:
                raise ValueError("Only a recurring event occurrence can be edited with scope 'this'.")
            requested_date = _coerce_occurrence_date(occurrence_date)
            occurrence = _event_for_occurrence(event, requested_date)
            if "recurrence" in changes:
                raise ValueError("Recurrence rules cannot be changed for a single occurrence.")
            current_override = dict(event.recurrence["overrides"].get(requested_date.isoformat(), {}))
            current_values = {
                "title": occurrence.title,
                "date": occurrence.date.isoformat(),
                "start": occurrence.start,
                "end": occurrence.end,
                "location": occurrence.location,
                "notes": occurrence.notes,
            }
            updated_values = {**current_values, **current_override, **changes}
            updated_values["date"] = (
                updated_values["date"].isoformat()
                if type(updated_values["date"]) is date
                else updated_values["date"]
            )
            updated_date = validate_event_fields(
                updated_values["title"],
                updated_values["date"],
                updated_values["start"],
                updated_values["end"],
                updated_values["location"],
                updated_values["notes"],
            )
            current_override.update(
                {
                    "title": updated_values["title"].strip(),
                    "date": updated_date.isoformat(),
                    "start": updated_values["start"],
                    "end": updated_values["end"],
                    "location": updated_values["location"],
                    "notes": updated_values["notes"],
                }
            )
            event.recurrence["overrides"][requested_date.isoformat()] = current_override
            event.updated = clock.now()
            save_events(events)
            return event

        if scope == "this_and_future":
            if event.recurrence is None:
                raise ValueError("Only a recurring event supports scope 'this_and_future'.")
            requested_date = _coerce_occurrence_date(occurrence_date)
            occurrence = _event_for_occurrence(event, requested_date)
            return _split_event_series(events, event, occurrence, changes)

        updated_title = changes.get("title", event.title)
        updated_date = changes.get("date", event.date.isoformat())
        if type(updated_date) is date:
            updated_date = updated_date.isoformat()
        updated_start = changes.get("start", event.start)
        updated_end = changes.get("end", event.end)
        updated_location = changes.get("location", event.location)
        updated_notes = changes.get("notes", event.notes)
        updated_recurrence = changes.get("recurrence", event.recurrence)

        updated_event_date = validate_event_fields(
            updated_title,
            updated_date,
            updated_start,
            updated_end,
            updated_location,
            updated_notes,
        )
        updated_recurrence = _validate_event_recurrence(
            updated_recurrence,
            updated_event_date,
            updated_title,
            updated_start,
            updated_end,
            updated_location,
            updated_notes,
        )

        if changes:
            event.title = updated_title.strip()
            event.date = updated_event_date
            event.start = updated_start
            event.end = updated_end
            event.location = updated_location
            event.notes = updated_notes
            event.recurrence = updated_recurrence
            event.updated = clock.now()
            save_events(events)
        return event


def _split_event_series(
    events: list[Event],
    event: Event,
    occurrence: EventOccurrence,
    changes: dict[str, Any],
) -> Event:
    split_date = occurrence.occurrence_date
    original_rule = dict(event.recurrence or {})
    if "recurrence" in changes:
        new_rule = changes["recurrence"]
    else:
        new_rule = {
            key: value
            for key, value in original_rule.items()
            if key not in {"skipped", "overrides", "until", "count"}
        }
        if original_rule.get("count") is not None:
            earlier = (
                recurrence_rules.occurrence_dates(
                    event.date,
                    original_rule,
                    event.date,
                    split_date - timedelta(days=1),
                )
                if split_date > event.date
                else []
            )
            new_rule["count"] = original_rule["count"] - len(earlier)
        elif original_rule.get("until") is not None:
            new_rule["until"] = original_rule["until"]
    base_date_value = changes.get("date", occurrence.date)
    if isinstance(base_date_value, str):
        new_base_date = _validate_date(base_date_value, "Event")
    elif type(base_date_value) is date:
        new_base_date = base_date_value
    else:
        raise ValueError("Event date must use YYYY-MM-DD format.")
    if (
        isinstance(new_rule, dict)
        and new_rule.get("until") is not None
        and _validate_date(new_rule["until"], "recurrence end") <= new_base_date
    ):
        new_rule = {
            key: value
            for key, value in new_rule.items()
            if key not in {"until", "count"}
        }
        new_rule["count"] = 1
    updated_values = {
        "title": changes.get("title", occurrence.title),
        "date": new_base_date.isoformat(),
        "start": changes.get("start", occurrence.start),
        "end": changes.get("end", occurrence.end),
        "location": changes.get("location", occurrence.location),
        "notes": changes.get("notes", occurrence.notes),
    }
    new_base_date = validate_event_fields(
        updated_values["title"],
        updated_values["date"],
        updated_values["start"],
        updated_values["end"],
        updated_values["location"],
        updated_values["notes"],
    )
    new_rule = _validate_event_recurrence(
        new_rule,
        new_base_date,
        updated_values["title"],
        updated_values["start"],
        updated_values["end"],
        updated_values["location"],
        updated_values["notes"],
    )
    now = clock.now()

    if split_date <= event.date:
        event.deleted = True
    else:
        earlier_skips = [
            skipped for skipped in original_rule.get("skipped", [])
            if date.fromisoformat(skipped) < split_date
        ]
        earlier_overrides = {
            override_date: override
            for override_date, override in original_rule.get("overrides", {}).items()
            if date.fromisoformat(override_date) < split_date
        }
        old_rule = {
            key: value
            for key, value in original_rule.items()
            if key not in {"until", "count", "skipped", "overrides"}
        }
        previous_day = split_date - timedelta(days=1)
        if previous_day > event.date:
            old_rule.update(until=previous_day.isoformat(), count=None)
        else:
            old_rule.update(
                until=None,
                count=len(
                    recurrence_rules.occurrence_dates(
                        event.date,
                        original_rule,
                        event.date,
                        previous_day,
                    )
                ),
            )
        old_rule.update(skipped=earlier_skips, overrides=earlier_overrides)
        event.recurrence = old_rule
    event.updated = now

    new_event = Event(
        id=uuid.uuid4().hex,
        title=updated_values["title"].strip(),
        date=new_base_date,
        start=updated_values["start"],
        end=updated_values["end"],
        location=updated_values["location"],
        notes=updated_values["notes"],
        created=now,
        updated=now,
        recurrence=new_rule,
    )
    events.append(new_event)
    save_events(events)
    return new_event


def delete_event(
    identifier: str,
    *,
    scope: str = "all",
    occurrence_date: str | date | None = None,
) -> Event:
    if scope not in {"this", "all", "this_and_future"}:
        raise ValueError("Event scope must be 'this', 'this_and_future', or 'all'.")
    events = load_events()
    event = _find_event(events, identifier)
    with record_action(f'Deleted event "{event.title}"'):
        if scope == "this":
            if event.recurrence is None:
                raise ValueError("Only a recurring event occurrence can be deleted with scope 'this'.")
            requested_date = _coerce_occurrence_date(occurrence_date)
            _event_for_occurrence(event, requested_date)
            event.recurrence["skipped"].append(requested_date.isoformat())
            event.recurrence["skipped"] = sorted(set(event.recurrence["skipped"]))
            event.recurrence["overrides"].pop(requested_date.isoformat(), None)
        elif scope == "this_and_future":
            if event.recurrence is None:
                raise ValueError("Only a recurring event supports scope 'this_and_future'.")
            requested_date = _coerce_occurrence_date(occurrence_date)
            _event_for_occurrence(event, requested_date)
            if requested_date <= event.date:
                event.deleted = True
            else:
                previous_day = requested_date - timedelta(days=1)
                if previous_day > event.date:
                    event.recurrence["until"] = previous_day.isoformat()
                    event.recurrence["count"] = None
                else:
                    prior_occurrences = recurrence_rules.occurrence_dates(
                        event.date,
                        event.recurrence,
                        event.date,
                        previous_day,
                    )
                    event.recurrence["until"] = None
                    event.recurrence["count"] = len(prior_occurrences)
                event.recurrence["skipped"] = [
                    skipped for skipped in event.recurrence["skipped"]
                    if date.fromisoformat(skipped) < requested_date
                ]
                event.recurrence["overrides"] = {
                    day: override
                    for day, override in event.recurrence["overrides"].items()
                    if date.fromisoformat(day) < requested_date
                }
        else:
            event.deleted = True
        event.updated = clock.now()
        save_events(events)
        return event


def occurrences(
    event: Event,
    start_date: str | date,
    end_date: str | date,
) -> list[EventOccurrence]:
    start = _coerce_occurrence_date(start_date)
    end = _coerce_occurrence_date(end_date)
    if start > end:
        raise ValueError("Occurrence start date must not be after end date.")
    if event.deleted:
        return []
    rule = event.recurrence
    dates = set(recurrence_rules.occurrence_dates(event.date, rule, start, end))
    if rule is not None:
        for override_date, override in rule["overrides"].items():
            original_date = date.fromisoformat(override_date)
            if original_date not in recurrence_rules.occurrence_dates(
                event.date, rule, original_date, original_date
            ):
                continue
            effective_date = _validate_date(override.get("date", override_date), "Event")
            if start <= effective_date <= end:
                dates.add(original_date)

    skipped = set(rule["skipped"]) if rule is not None else set()
    result: list[EventOccurrence] = []
    for original_date in sorted(dates):
        key = original_date.isoformat()
        if key in skipped:
            continue
        override = rule["overrides"].get(key, {}) if rule is not None else {}
        effective = {
            "title": event.title,
            "date": key,
            "start": event.start,
            "end": event.end,
            "location": event.location,
            "notes": event.notes,
            **override,
        }
        effective_date = _validate_date(effective["date"], "Event")
        if not start <= effective_date <= end:
            continue
        validate_event_fields(
            effective["title"],
            effective_date.isoformat(),
            effective["start"],
            effective["end"],
            effective["location"],
            effective["notes"],
        )
        result.append(
            EventOccurrence(
                id=event.id,
                title=effective["title"].strip(),
                date=effective_date,
                start=effective["start"],
                end=effective["end"],
                location=effective["location"],
                notes=effective["notes"],
                recurring=rule is not None,
                occurrence_date=original_date,
            )
        )
    return sorted(result, key=lambda item: (item.date, item.start, item.end, item.title))


def _coerce_event_date(value: str | date | None, label: str) -> date | None:
    if value is None:
        return None
    if type(value) is date:
        return value
    if isinstance(value, str):
        return _validate_date(value, label)
    raise ValueError(f"{label} date must be a YYYY-MM-DD string or a date.")


def list_events(
    event_date: str | date | None = None,
    end_date: str | date | None = None,
) -> list[EventOccurrence]:
    unbounded_query = event_date is None and end_date is None
    start = _coerce_event_date(event_date, "Event")
    end = _coerce_event_date(end_date, "Event")
    if start is None:
        start = clock.today()
    if end is None:
        end = start if event_date is not None else start + timedelta(days=365)
    if start > end:
        raise ValueError("Event start date must not be after end date.")

    listed_occurrences: list[EventOccurrence] = []
    for event in load_events():
        if event.deleted:
            continue
        if unbounded_query and event.recurrence is None:
            listed_occurrences.extend(occurrences(event, event.date, event.date))
        else:
            listed_occurrences.extend(occurrences(event, start, end))
    return sorted(
        listed_occurrences,
        key=lambda item: (item.date, item.start, item.end, item.title),
    )


def validate_task_fields(
    title: str,
    due: date | None = None,
    priority: str = "media",
    recurrence: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if not isinstance(title, str) or not title.strip():
        raise ValueError("Task title cannot be empty.")
    if due is not None and type(due) is not date:
        raise ValueError("Due date must be a date without a time.")
    if not isinstance(priority, str) or priority not in VALID_PRIORITIES:
        raise ValueError("Priority must be 'alta', 'media', or 'baja'.")
    if recurrence is not None and due is None:
        raise ValueError("A recurring task must have a due date.")
    return validate_recurrence(recurrence, due) if due is not None else None


def _new_task(
    title: str,
    due: date | None,
    priority: str,
    recurrence: dict[str, Any] | None,
    notes: str | None = None,
    project_id: str | None = None,
) -> Task:
    recurrence = validate_task_fields(title, due, priority, recurrence)
    if notes is not None and not isinstance(notes, str):
        raise ValueError("Task notes must be text or None.")
    if project_id is not None and not isinstance(project_id, str):
        raise ValueError("Task project_id must be text or None.")

    now = clock.now()
    identifier = uuid.uuid4().hex
    task = Task(
        id=identifier,
        title=title.strip(),
        done=False,
        created=now,
        updated=now,
        deleted=False,
        due=due,
        priority=priority,
        recurrence=recurrence,
        series_id=identifier if recurrence is not None else None,
        series_start=due if recurrence is not None else None,
        notes=notes,
        project_id=project_id,
    )
    return task


def create_task(
    title: str,
    due: date | None = None,
    priority: str = "media",
    recurrence: dict[str, Any] | None = None,
    notes: str | None = None,
    project_id: str | None = None,
) -> Task:
    with record_action(f'Created task "{title.strip()}"'):
        task = _new_task(
            title,
            due,
            priority,
            recurrence,
            notes=notes,
            project_id=project_id,
        )
        tasks = load_tasks()
        tasks.append(task)
        save_tasks(tasks)
        return task


def create_task_with_block(
    title: str,
    block_date: str,
    start_time: str,
    end_time: str,
    due: date | None = None,
    priority: str = "media",
    recurrence: dict[str, Any] | None = None,
    notes: str | None = None,
    project_id: str | None = None,
) -> Task:
    parsed_date = _validate_block_interval(block_date, start_time, end_time)
    with record_action(f'Created task "{title.strip()}" with block'):
        task = _new_task(
            title,
            due,
            priority,
            recurrence,
            notes=notes,
            project_id=project_id,
        )
        task.blocks.append(
            ScheduledBlock(
                id=uuid.uuid4().hex,
                date=parsed_date,
                start=start_time,
                end=end_time,
            )
        )
        tasks = load_tasks()
        tasks.append(task)
        save_tasks(tasks)
        return task


add_task_with_block = create_task_with_block


def _find_task(tasks: list[Task], identifier: str) -> Task:
    for task in tasks:
        if task.id == identifier and not task.deleted:
            return task
    raise ValueError("No active task found with that ID.")


def get_task(identifier: str) -> Task:
    """Retrieve an active non-deleted task by ID."""
    return _find_task(load_tasks(), identifier)


def load_notes() -> list[dict[str, Any]]:
    """Load notes from storage."""
    from planner import storage
    return storage.load_notes()


def edit_task(identifier: str, title: str) -> Task:
    title = title.strip()
    if not title:
        raise ValueError("Task title cannot be empty.")

    tasks = load_tasks()
    task = _find_task(tasks, identifier)
    with record_action(f'Edited task "{title}"'):
        task.title = title
        task.updated = clock.now()
        save_tasks(tasks)
        return task


def edit_task_details(identifier: str, **changes: Any) -> Task:
    allowed_fields = {"title", "due", "priority", "recurrence", "notes", "project_id"}
    unknown_fields = changes.keys() - allowed_fields
    if unknown_fields:
        raise ValueError(
            f"Unsupported task field(s): {', '.join(sorted(unknown_fields))}."
        )

    tasks = load_tasks()
    task = _find_task(tasks, identifier)
    title = changes.get("title", task.title)
    due = changes.get("due", task.due)
    priority = changes.get("priority", task.priority)
    recurrence = changes.get("recurrence", task.recurrence)
    recurrence_changed = recurrence != task.recurrence
    if not isinstance(title, str) or not title.strip():
        raise ValueError("Task title cannot be empty.")
    if due is not None and type(due) is not date:
        raise ValueError("Due date must be a date without a time.")
    if not isinstance(priority, str) or priority not in VALID_PRIORITIES:
        raise ValueError("Priority must be 'alta', 'media', or 'baja'.")
    if recurrence is not None and due is None:
        raise ValueError("A recurring task must have a due date.")
    recurrence = validate_recurrence(recurrence, due) if due is not None else None

    notes = changes.get("notes", task.notes)
    if notes is not None and not isinstance(notes, str):
        raise ValueError("Task notes must be text or None.")
    project_id = changes.get("project_id", task.project_id)
    if project_id is not None and not isinstance(project_id, str):
        raise ValueError("Task project_id must be text or None.")

    with record_action(f'Edited task "{title.strip()}"'):
        if changes:
            task.title = title.strip()
            task.due = due
            task.priority = priority
            task.recurrence = recurrence
            task.notes = notes
            task.project_id = project_id
            if recurrence is not None and task.series_id is None:
                task.series_id = task.id
            if recurrence is not None and recurrence_changed:
                task.series_start = due
            elif recurrence is None:
                task.series_id = None
                task.series_start = None
            task.updated = clock.now()
            save_tasks(tasks)
        return task


def _next_task_due(
    tasks: list[Task],
    task: Task,
    reference_date: date,
) -> date | None:
    if task.recurrence is None or task.due is None:
        return None
    series_id = task.series_id or task.id
    series_tasks = [
        item
        for item in tasks
        if item.series_id == series_id and item.due is not None and not item.deleted
    ]
    base_task = min(series_tasks, key=lambda item: item.due or date.max)
    base_date = task.series_start or base_task.series_start or base_task.due
    if base_date is None:
        return None
    after_date = max(task.due, reference_date)
    return recurrence_rules.next_occurrence_date(
        base_date,
        task.recurrence,
        after_date,
    )


def set_task_done(
    identifier: str,
    done: bool,
    reference_date: date | None = None,
    now: datetime | None = None,
) -> Task:
    if type(done) is not bool:
        raise ValueError("Task done state must be a boolean.")
    if reference_date is not None and type(reference_date) is not date:
        raise ValueError("Reference date must be a date without a time.")
    tasks = load_tasks()
    task = _find_task(tasks, identifier)
    label = f"Marked done: {task.title}" if done else f"Marked pending: {task.title}"
    cur_today = reference_date or clock.today()
    cur_now = now or clock.now()
    cur_time = cur_now.strftime("%H:%M")
    with record_action(label):
        if task.done != done:
            task.done = done
            task.updated = cur_now
            if done:
                for block in task.blocks:
                    if (
                        block.date == cur_today
                        and block.start <= cur_time
                        and getattr(block, "status", "planned") == "planned"
                    ):
                        block.status = "done"
                        block.completed_at = cur_now.isoformat()
                next_due = _next_task_due(tasks, task, cur_today)
                if next_due is not None:
                    tasks.append(
                        Task(
                            id=uuid.uuid4().hex,
                            title=task.title,
                            done=False,
                            created=cur_now,
                            updated=cur_now,
                            deleted=False,
                            due=next_due,
                            priority=task.priority,
                            recurrence=task.recurrence,
                            series_id=task.series_id or task.id,
                            series_start=task.series_start or task.due,
                        )
                    )
            save_tasks(tasks)
        return task


def complete_task(
    identifier: str,
    reference_date: date | None = None,
    now: datetime | None = None,
) -> Task:
    return set_task_done(identifier, True, reference_date, now=now)


def delete_task(identifier: str) -> Task:
    tasks = load_tasks()
    task = _find_task(tasks, identifier)
    with record_action(f'Deleted task "{task.title}"'):
        task.deleted = True
        task.updated = clock.now()
        save_tasks(tasks)
        return task


from planner import review as _review


def review_candidates(
    value: date | None = None,
    *,
    unscheduled_limit: int | None = None,
) -> list[_review.ReviewCandidate]:
    return _review.review_candidates(value, unscheduled_limit=unscheduled_limit)


def review_candidate_summary(
    value: date | None = None,
) -> _review.ReviewCandidateSummary:
    return _review.review_candidate_summary(value)


def suggest_slot(
    value: date,
    duration_minutes: int,
    day_start: str = DEFAULT_DAY_START,
    day_end: str = DEFAULT_DAY_END,
) -> tuple[str, str] | None:
    return _review.suggest_slot(value, duration_minutes, day_start, day_end)


def suggest_next_slot(
    value: date,
    duration_minutes: int,
    day_start: str = DEFAULT_DAY_START,
    day_end: str = DEFAULT_DAY_END,
) -> tuple[date, str, str] | None:
    return _review.suggest_next_slot(value, duration_minutes, day_start, day_end)


def missed_blocks(value: date | None = None) -> list[BlockAgendaEntry]:
    return _review.missed_blocks(value)


def reschedule_block(
    task_id: str,
    block_id: str,
    new_date: date | str,
    start: str,
    end: str,
) -> ScheduledBlock:
    return _review.reschedule_block(task_id, block_id, new_date, start, end)


def defer_task(task_id: str, new_due: date) -> Task:
    return _review.defer_task(task_id, new_due)


def day_review_summary(value: date | None = None) -> _review.DayReviewSummary:
    return _review.day_review_summary(value)


def day_review_overview(
    value: date,
    day_start: str = DEFAULT_DAY_START,
    day_end: str = DEFAULT_DAY_END,
) -> _review.DayOverview:
    return _review.day_review_overview(value, day_start, day_end)


def format_hours(minutes: int) -> str:
    return _review.format_hours(minutes)


def due_tasks_summary(target_date: date) -> dict[str, int]:
    return _review.due_tasks_summary(target_date)


def review_timeline(
    overview: _review.DayOverview,
    suggested_slot: tuple[str, str] | None = None,
    preview: tuple[str, str, str, list[AgendaEntry]] | None = None,
) -> list[_review.ReviewTimelineItem]:
    return _review.review_timeline(overview, suggested_slot, preview)


DayOverview = _review.DayOverview
ReviewTimelineItem = _review.ReviewTimelineItem


# ============================================================================
# Projects Domain Logic
# ============================================================================

def create_project(
    name: str,
    description: str | None = None,
    target_date: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """Create a new project and persist it in projects.json."""
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Project name cannot be empty.")
    name = name.strip()
    if target_date is not None:
        if not isinstance(target_date, str):
            raise ValueError("Target date must be text or None.")
        try:
            date.fromisoformat(target_date)
        except Exception as e:
            raise ValueError(f"Invalid target date: {target_date}") from e

    from planner import storage

    now = clock.now().isoformat()
    project = {
        "id": uuid.uuid4().hex,
        "name": name,
        "description": description,
        "status": "active",
        "target_date": target_date,
        "created": now,
        "updated": now,
        "deleted": False,
        "notes": notes,
    }
    with record_action(f'Created project "{name}"'):
        projects = storage.load_projects()
        projects.append(project)
        storage.save_projects(projects)
        return dict(project)


def list_projects(status: str | None = None) -> list[dict[str, Any]]:
    """List all non-deleted projects, optionally filtered by status."""
    from planner import storage

    projects = storage.load_projects()
    result = [dict(p) for p in projects if not p.get("deleted", False)]
    if status is not None:
        result = [p for p in result if p.get("status") == status]
    return result


def get_project(project_id: str) -> dict[str, Any]:
    """Get project details including non-archived notes assigned to it."""
    from planner import storage

    projects = storage.load_projects()
    found = None
    for p in projects:
        if p.get("id") == project_id and not p.get("deleted", False):
            found = p
            break
    if found is None:
        raise ValueError(f"Project not found: {project_id}")

    res = dict(found)
    res["notes"] = list_notes(project_id=project_id, archived=False)
    return res


def edit_project(project_id: str, **changes: Any) -> dict[str, Any]:
    """Edit project fields and update updated timestamp."""
    from planner import storage

    allowed = {"name", "description", "status", "target_date", "notes"}
    unknown = changes.keys() - allowed
    if unknown:
        raise ValueError(f"Unsupported project field(s): {', '.join(sorted(unknown))}.")

    projects = storage.load_projects()
    project = None
    for p in projects:
        if p.get("id") == project_id and not p.get("deleted", False):
            project = p
            break
    if project is None:
        raise ValueError(f"Project not found: {project_id}")

    has_changes = False
    for k, v in changes.items():
        if k == "name":
            if not isinstance(v, str) or not v.strip():
                raise ValueError("Project name cannot be empty.")
            v = v.strip()
        if k == "target_date" and v is not None:
            try:
                date.fromisoformat(v)
            except Exception as e:
                raise ValueError(f"Invalid target date: {v}") from e
        if project.get(k) != v:
            has_changes = True

    if not has_changes:
        return dict(project)

    with record_action(f'Edited project "{changes.get("name", project["name"])}"'):
        for k, v in changes.items():
            if k == "name":
                project[k] = v.strip()
            else:
                project[k] = v
        project["updated"] = clock.now().isoformat()
        storage.save_projects(projects)
        return dict(project)


def delete_project(project_id: str) -> dict[str, Any]:
    """Logically delete project and unassign its tasks and notes in a single undoable action."""
    from planner import storage

    projects = storage.load_projects()
    project = None
    for p in projects:
        if p.get("id") == project_id and not p.get("deleted", False):
            project = p
            break
    if project is None:
        raise ValueError(f"Project not found: {project_id}")

    with record_action(f'Deleted project "{project["name"]}"'):
        project["deleted"] = True
        project["updated"] = clock.now().isoformat()
        storage.save_projects(projects)

        tasks = load_tasks()
        tasks_changed = False
        for t in tasks:
            if t.project_id == project_id:
                t.project_id = None
                t.updated = clock.now()
                tasks_changed = True
        if tasks_changed:
            save_tasks(tasks)

        notes = storage.load_notes()
        notes_changed = False
        now_iso = clock.now().isoformat()
        for n in notes:
            if n.get("project_id") == project_id:
                n["project_id"] = None
                n["updated"] = now_iso
                notes_changed = True
        if notes_changed:
            storage.save_notes(notes)

        return dict(project)


def project_progress(project_id: str) -> dict[str, Any]:
    """Calculate progress for a project based on completed vs total tasks. Notes do not count."""
    get_project(project_id)  # Validate project exists
    tasks = [t for t in load_tasks() if t.project_id == project_id and not t.deleted]
    total = len(tasks)
    completed = sum(1 for t in tasks if t.done)
    percentage = round((completed / total) * 100) if total > 0 else 0
    return {"total": total, "completed": completed, "percentage": percentage}


# ============================================================================
# Notes Domain Logic
# ============================================================================

def _note_preview(body: str | None) -> str:
    """Return the first non-empty line of the body truncated to 80 chars."""
    if not body:
        return ""
    for line in body.splitlines():
        line = line.strip()
        if line:
            return line[:80]
    return ""


def _validate_note_title_body(title: Any, body: Any) -> tuple[str, str]:
    if title is None:
        title = ""
    if not isinstance(title, str):
        raise ValueError("Note title must be text.")
    if body is None:
        body = ""
    if not isinstance(body, str):
        raise ValueError("Note body must be text.")

    title = title.strip()
    if len(title) > 120:
        raise ValueError("Note title exceeds 120 characters.")
    if len(body) > 100000:
        raise ValueError("Note body exceeds 100,000 characters.")
    if not title and not body.strip():
        raise ValueError("A note must have a non-empty title or body.")
    return title, body


def _validate_note_date(date_val: Any, reference_date: Any | None = None) -> str:
    if date_val is None:
        ref = reference_date or clock.today()
        return ref.isoformat() if hasattr(ref, "isoformat") else str(ref)
    if hasattr(date_val, "strftime"):
        return date_val.strftime("%Y-%m-%d")
    if isinstance(date_val, str):
        date_str = date_val.strip()
        try:
            return date.fromisoformat(date_str).isoformat()
        except Exception:
            try:
                return parse_date(date_str, reference_date=reference_date).isoformat()
            except Exception as e:
                raise ValueError(f"Invalid date format: {date_val}") from e
    raise ValueError(f"Invalid date: {date_val}")


def _normalize_tags(tags: Any) -> list[str]:
    if tags is None:
        return []
    if isinstance(tags, str):
        raw_items = [t.strip().lstrip("#") for t in re.split(r"[\s,]+", tags) if t.strip()]
    elif isinstance(tags, (list, tuple, set)):
        raw_items = []
        for item in tags:
            if not isinstance(item, str):
                raise ValueError("Tag must be text.")
            item_clean = item.strip().lstrip("#")
            if item_clean:
                raw_items.append(item_clean)
    else:
        raise ValueError("Tags must be a list of strings or string.")

    normalized: list[str] = []
    for item in raw_items:
        lower = item.lower()
        if not re.match(r"^[a-zA-Z0-9_\-]+$", lower):
            raise ValueError(
                f"Invalid tag: '{item}'. Only letters, numbers, hyphens, and underscores are allowed."
            )
        if lower not in normalized:
            normalized.append(lower)
    return normalized


def create_note(
    title: str = "",
    body: str = "",
    tags: list[str] | str | None = None,
    project_id: str | None = None,
    date: date | str | None = None,
    pinned: bool = False,
    reference_date: date | None = None,
) -> dict[str, Any]:
    """Create an independent note and persist it in notes.json."""
    title, body = _validate_note_title_body(title, body)
    date_iso = _validate_note_date(date, reference_date=reference_date)
    norm_tags = _normalize_tags(tags)
    pinned_bool = bool(pinned)

    if project_id is not None and not isinstance(project_id, str):
        raise ValueError("project_id must be a string or None.")

    from planner import storage

    now = clock.now().isoformat()
    note = {
        "id": uuid.uuid4().hex,
        "title": title,
        "body": body,
        "tags": norm_tags,
        "project_id": project_id,
        "date": date_iso,
        "pinned": pinned_bool,
        "archived": False,
        "created": now,
        "updated": now,
        "deleted": False,
    }
    label = f'Created note "{title or _note_preview(body)}"'
    with record_action(label):
        notes = storage.load_notes()
        notes.append(note)
        storage.save_notes(notes)
        return dict(note)


def edit_note(note_id: str, **changes: Any) -> dict[str, Any]:
    """Edit note fields and update updated timestamp if changed."""
    allowed = {"title", "body", "tags", "project_id", "date", "pinned", "archived"}
    unknown = changes.keys() - allowed
    if unknown:
        raise ValueError(f"Unsupported note field(s): {', '.join(sorted(unknown))}.")

    from planner import storage

    notes = storage.load_notes()
    note = None
    for n in notes:
        if n.get("id") == note_id and not n.get("deleted", False):
            note = n
            break
    if note is None:
        raise ValueError(f"Note not found: {note_id}")

    new_title = changes.get("title", note.get("title", ""))
    new_body = changes.get("body", note.get("body", ""))
    new_title, new_body = _validate_note_title_body(new_title, new_body)

    new_date = _validate_note_date(changes["date"]) if "date" in changes else note.get("date")
    new_tags = _normalize_tags(changes["tags"]) if "tags" in changes else list(note.get("tags", []))
    new_project_id = changes.get("project_id", note.get("project_id"))
    if new_project_id is not None and not isinstance(new_project_id, str):
        raise ValueError("project_id must be a string or None.")

    new_archived = bool(changes.get("archived", note.get("archived", False)))
    new_pinned = bool(changes.get("pinned", note.get("pinned", False)))

    if "archived" in changes and new_archived:
        new_pinned = False
    elif new_pinned and (new_archived or note.get("archived", False)):
        raise ValueError("Cannot pin an archived note.")

    has_changes = (
        new_title != note.get("title", "")
        or new_body != note.get("body", "")
        or new_date != note.get("date")
        or new_tags != note.get("tags", [])
        or new_project_id != note.get("project_id")
        or new_pinned != note.get("pinned", False)
        or new_archived != note.get("archived", False)
    )

    if not has_changes:
        return dict(note)

    label = f'Edited note "{new_title or _note_preview(new_body)}"'
    with record_action(label):
        note["title"] = new_title
        note["body"] = new_body
        note["date"] = new_date
        note["tags"] = new_tags
        note["project_id"] = new_project_id
        note["pinned"] = new_pinned
        note["archived"] = new_archived
        note["updated"] = clock.now().isoformat()
        storage.save_notes(notes)
        return dict(note)


def delete_note(note_id: str) -> dict[str, Any]:
    """Logically delete a note."""
    from planner import storage

    notes = storage.load_notes()
    note = None
    for n in notes:
        if n.get("id") == note_id and not n.get("deleted", False):
            note = n
            break
    if note is None:
        raise ValueError(f"Note not found: {note_id}")

    label = f'Deleted note "{note.get("title") or _note_preview(note.get("body"))}"'
    with record_action(label):
        note["deleted"] = True
        note["updated"] = clock.now().isoformat()
        storage.save_notes(notes)
        return dict(note)


def pin_note(note_id: str, pinned: bool = True) -> dict[str, Any]:
    """Pin or unpin a note. Cannot pin an archived note."""
    from planner import storage

    notes = storage.load_notes()
    note = None
    for n in notes:
        if n.get("id") == note_id and not n.get("deleted", False):
            note = n
            break
    if note is None:
        raise ValueError(f"Note not found: {note_id}")

    pinned_bool = bool(pinned)
    if pinned_bool and note.get("archived", False):
        raise ValueError("Cannot pin an archived note.")

    if note.get("pinned", False) == pinned_bool:
        return dict(note)

    action_name = "Pinned" if pinned_bool else "Unpinned"
    label = f'{action_name} note "{note.get("title") or _note_preview(note.get("body"))}"'
    with record_action(label):
        note["pinned"] = pinned_bool
        note["updated"] = clock.now().isoformat()
        storage.save_notes(notes)
        return dict(note)


def archive_note(note_id: str, archived: bool = True) -> dict[str, Any]:
    """Archive or unarchive a note. Archiving unpins the note."""
    from planner import storage

    notes = storage.load_notes()
    note = None
    for n in notes:
        if n.get("id") == note_id and not n.get("deleted", False):
            note = n
            break
    if note is None:
        raise ValueError(f"Note not found: {note_id}")

    archived_bool = bool(archived)
    if note.get("archived", False) == archived_bool:
        return dict(note)

    action_name = "Archived" if archived_bool else "Unarchived"
    label = f'{action_name} note "{note.get("title") or _note_preview(note.get("body"))}"'
    with record_action(label):
        note["archived"] = archived_bool
        if archived_bool:
            note["pinned"] = False
        note["updated"] = clock.now().isoformat()
        storage.save_notes(notes)
        return dict(note)


def get_note(note_id: str) -> dict[str, Any]:
    """Get a single note by ID with project_name and preview."""
    from planner import storage

    notes = storage.load_notes()
    note = None
    for n in notes:
        if n.get("id") == note_id and not n.get("deleted", False):
            note = n
            break
    if note is None:
        raise ValueError(f"Note not found: {note_id}")

    res = dict(note)
    pid = res.get("project_id")
    pname = None
    if pid:
        for p in storage.load_projects():
            if p.get("id") == pid and not p.get("deleted", False):
                pname = p.get("name")
                break
    res["project_name"] = pname
    res["preview"] = _note_preview(res.get("body"))
    return res


def list_notes(
    date: date | str | None = None,
    project_id: str | None = None,
    tag: str | None = None,
    pinned: bool | None = None,
    archived: bool | None = False,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """List notes matching filters, ordered: pinned first, date desc, updated desc."""
    from planner import storage

    notes = storage.load_notes()
    projects = {p["id"]: p["name"] for p in storage.load_projects() if not p.get("deleted", False)}

    if date is not None:
        date_str = date.strftime("%Y-%m-%d") if hasattr(date, "strftime") else str(date)
    else:
        date_str = None

    if tag is not None:
        tag_norm = tag.lower().strip().lstrip("#")
    else:
        tag_norm = None

    results: list[dict[str, Any]] = []
    for n in notes:
        if n.get("deleted", False):
            continue
        if archived is not None:
            if n.get("archived", False) != archived:
                continue
        if date_str is not None and n.get("date") != date_str:
            continue
        if project_id is not None and n.get("project_id") != project_id:
            continue
        if tag_norm is not None and tag_norm not in [t.lower() for t in n.get("tags", [])]:
            continue
        if pinned is not None and bool(n.get("pinned", False)) != pinned:
            continue

        item = dict(n)
        pid = item.get("project_id")
        item["project_name"] = projects.get(pid) if pid else None
        item["preview"] = _note_preview(item.get("body"))
        results.append(item)

    def _sort_key(item: dict[str, Any]) -> tuple[int, str, str]:
        return (
            1 if item.get("pinned", False) else 0,
            item.get("date", "") or "",
            item.get("updated", "") or "",
        )

    results.sort(key=_sort_key, reverse=True)
    if limit is not None and limit >= 0:
        results = results[:limit]
    return results


def notes_for_day(date: date | str) -> list[dict[str, Any]]:
    """Return non-archived, non-deleted notes for the given day, with list_notes ordering."""
    date_str = date.strftime("%Y-%m-%d") if hasattr(date, "strftime") else str(date)
    return list_notes(date=date_str, archived=False)


# ============================================================================
# Tags Management
# ============================================================================

def set_tags(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Set tags on a note or other entity with normalization and validation."""
    kind = kwargs.get("kind")
    item_id = kwargs.get("note_id") or kwargs.get("item_id")
    tags = kwargs.get("tags")

    if len(args) == 3:
        kind, item_id, tags = args
    elif len(args) == 2:
        if args[0] in ("note", "task"):
            kind, item_id = args
        else:
            item_id, tags = args
            kind = kind or "note"
    elif len(args) == 1:
        item_id = args[0]
        kind = kind or "note"

    kind = (kind or "note").lower()
    if kind != "note":
        raise ValueError(f"Unsupported entity kind for tags: {kind}")

    norm_tags = _normalize_tags(tags)
    return edit_note(item_id, tags=norm_tags)


def list_tags(kind: str | None = None) -> list[dict[str, Any]]:
    """List tags and their counts across active entities."""
    from collections import Counter
    from planner import storage

    counts: Counter[str] = Counter()
    if kind is None or kind.lower() == "note":
        for note in storage.load_notes():
            if not note.get("deleted", False):
                for t in note.get("tags", []):
                    counts[t] += 1

    sorted_tags = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [{"tag": t, "name": t, "count": c} for t, c in sorted_tags]


# ============================================================================
# Search & Query Parser
# ============================================================================

def _normalize_search_string(text: str | None) -> str:
    """Normalize text by converting to lowercase and stripping accents."""
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(c for c in normalized if not unicodedata.combining(c)).lower()


def parse_query(query: str) -> dict[str, Any]:
    """Parse search query string into structured filter terms."""
    terms: list[str] = []
    tags: list[str] = []
    project: str | None = None
    entity_type: str | None = None
    is_pinned: bool | None = None
    is_archived: bool | None = None
    is_pending: bool | None = None
    is_done: bool | None = None
    date_filter: str | None = None

    tokens = query.strip().split()
    for token in tokens:
        if token.startswith("#"):
            tag_val = token[1:].strip().lower()
            if tag_val:
                tags.append(tag_val)
        elif ":" in token:
            prefix, val = token.split(":", 1)
            p_lower = prefix.lower()
            v_lower = val.lower().strip()
            if p_lower == "type":
                entity_type = v_lower
            elif p_lower == "project":
                project = val.strip()
            elif p_lower == "tag":
                if v_lower:
                    tags.append(v_lower)
            elif p_lower == "is":
                if v_lower == "pinned":
                    is_pinned = True
                elif v_lower == "archived":
                    is_archived = True
                elif v_lower == "pending":
                    is_pending = True
                elif v_lower == "done":
                    is_done = True
                else:
                    terms.append(token)
            elif p_lower == "date":
                date_filter = v_lower
            else:
                terms.append(token)
        else:
            terms.append(token)

    return {
        "terms": terms,
        "tags": tags,
        "project": project,
        "type": entity_type,
        "is_pinned": is_pinned,
        "is_archived": is_archived,
        "is_pending": is_pending,
        "is_done": is_done,
        "date": date_filter,
        "raw_query": query,
    }


def _extract_body_snippet(body: str, terms: list[str]) -> str | None:
    """Extract up to 120 chars around the first matching term in body."""
    if not body:
        return None
    norm_body = _normalize_search_string(body)
    first_idx = -1
    matched_term_len = 0
    for t in terms:
        norm_t = _normalize_search_string(t)
        if not norm_t:
            continue
        idx = norm_body.find(norm_t)
        if idx != -1:
            if first_idx == -1 or idx < first_idx:
                first_idx = idx
                matched_term_len = len(norm_t)

    if first_idx == -1:
        return None

    center = first_idx + matched_term_len // 2
    start = max(0, center - 55)
    end = min(len(body), start + 115)
    if end - start < 115 and start > 0:
        start = max(0, end - 115)

    snippet = body[start:end].replace("\r", "").replace("\n", " ")
    snippet = " ".join(snippet.split())
    if start > 0:
        snippet = "..." + snippet
    if end < len(body):
        snippet = snippet + "..."
    return snippet[:120]


def search(query: str, reference_date: date | None = None) -> list[dict[str, Any]]:
    """Search tasks and notes using search syntax.

    An empty query returns pending tasks.
    Notes are matched by title, body, tags, and project name.
    """
    if not query.strip():
        return [_task_to_data(t) for t in pending_tasks()]

    parsed = parse_query(query)
    ref = reference_date or clock.today()

    results: list[dict[str, Any]] = []

    # 1. Search Notes (unless excluded)
    can_search_notes = not (parsed["is_pending"] or parsed["is_done"])
    if parsed["type"] is not None and parsed["type"] != "note":
        can_search_notes = False

    if can_search_notes:
        from planner import storage
        notes = storage.load_notes()
        projects = {p["id"]: p["name"] for p in storage.load_projects() if not p.get("deleted", False)}

        for n in notes:
            if n.get("deleted", False):
                continue
            if parsed["is_archived"]:
                if not n.get("archived", False):
                    continue
            else:
                if n.get("archived", False):
                    continue

            if parsed["is_pinned"] and not n.get("pinned", False):
                continue

            if parsed["date"]:
                n_date = n.get("date", "")
                if parsed["date"] == "today":
                    if n_date != ref.isoformat():
                        continue
                elif parsed["date"] == "yesterday":
                    if n_date != (ref - timedelta(days=1)).isoformat():
                        continue
                elif parsed["date"] == "week":
                    w_start = week_start(ref)
                    w_end = w_start + timedelta(days=6)
                    if not (w_start.isoformat() <= n_date <= w_end.isoformat()):
                        continue
                else:
                    if n_date != parsed["date"]:
                        continue

            note_tags = [t.lower() for t in n.get("tags", [])]
            if parsed["tags"]:
                if not all(t in note_tags for t in parsed["tags"]):
                    continue

            pid = n.get("project_id")
            pname = projects.get(pid, "") if pid else ""
            if parsed["project"]:
                proj_query = _normalize_search_string(parsed["project"])
                if proj_query not in _normalize_search_string(pname):
                    continue

            title_norm = _normalize_search_string(n.get("title", ""))
            body_norm = _normalize_search_string(n.get("body", ""))
            tags_norm = [_normalize_search_string(t) for t in note_tags]
            proj_norm = _normalize_search_string(pname)

            all_terms_matched = True
            matched_fields_set: set[str] = set()
            for term in parsed["terms"]:
                t_norm = _normalize_search_string(term)
                term_matched = False
                if t_norm in title_norm:
                    term_matched = True
                    matched_fields_set.add("title")
                if t_norm in body_norm:
                    term_matched = True
                    matched_fields_set.add("body")
                if any(t_norm in tag for tag in tags_norm):
                    term_matched = True
                    matched_fields_set.add("tags")
                if t_norm in proj_norm:
                    term_matched = True
                    matched_fields_set.add("project")
                if not term_matched:
                    all_terms_matched = False
                    break

            if not all_terms_matched:
                continue

            if parsed["tags"] and not parsed["terms"]:
                matched_fields_set.add("tags")
            if parsed["project"] and not parsed["terms"]:
                matched_fields_set.add("project")

            matched_in = sorted(matched_fields_set)
            snippet = _extract_body_snippet(n.get("body", ""), parsed["terms"]) if "body" in matched_in else None

            results.append({
                "kind": "note",
                "id": n["id"],
                "title": n.get("title", ""),
                "preview": _note_preview(n.get("body")),
                "body": n.get("body", ""),
                "date": n.get("date"),
                "project_id": pid,
                "project_name": pname or None,
                "tags": n.get("tags", []),
                "pinned": n.get("pinned", False),
                "archived": n.get("archived", False),
                "matched_in": matched_in,
                "snippet": snippet,
            })

    # 2. Search Tasks (unless excluded)
    can_search_tasks = (
        parsed["type"] != "note"
        and not parsed["is_pinned"]
        and not (parsed["date"] and re.match(r"^\d{4}-\d{2}-\d{2}$", parsed["date"]))
        and not parsed["is_archived"]
    )
    if can_search_tasks:
        from planner import storage
        projects = {p["id"]: p["name"] for p in storage.load_projects() if not p.get("deleted", False)}
        tasks = load_tasks()

        for t in tasks:
            if t.deleted:
                continue
            if parsed["is_pending"] and t.done:
                continue
            if parsed["is_done"] and not t.done:
                continue

            if parsed["date"]:
                if t.due is None:
                    continue
                if parsed["date"] == "today":
                    if t.due != ref:
                        continue
                elif parsed["date"] == "yesterday":
                    if t.due != ref - timedelta(days=1):
                        continue
                elif parsed["date"] == "week":
                    w_start = week_start(ref)
                    w_end = w_start + timedelta(days=6)
                    if not (w_start <= t.due <= w_end):
                        continue

            t_proj_name = projects.get(t.project_id, "") if t.project_id else ""
            if parsed["project"]:
                proj_query = _normalize_search_string(parsed["project"])
                if proj_query not in _normalize_search_string(t_proj_name):
                    continue

            title_norm = _normalize_search_string(t.title)
            notes_norm = _normalize_search_string(t.notes or "")
            proj_norm = _normalize_search_string(t_proj_name)

            all_terms_matched = True
            matched_fields_set: set[str] = set()
            for term in parsed["terms"]:
                t_norm = _normalize_search_string(term)
                term_matched = False
                if t_norm in title_norm:
                    term_matched = True
                    matched_fields_set.add("title")
                if t_norm in notes_norm:
                    term_matched = True
                    matched_fields_set.add("notes")
                if t_norm in proj_norm:
                    term_matched = True
                    matched_fields_set.add("project")
                if not term_matched:
                    all_terms_matched = False
                    break

            if not all_terms_matched:
                continue

            t_data = _task_to_data(t)
            t_data["kind"] = "task"
            t_data["project_name"] = t_proj_name or None
            t_data["matched_in"] = sorted(matched_fields_set)
            results.append(t_data)

    return results


# =============================================================================
# Habits Domain Logic
# =============================================================================

VALID_HABIT_WEEKDAYS: tuple[str, ...] = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
VALID_HABIT_STATUSES: tuple[str, ...] = ("done", "missed", "skipped")


def _format_date_label(target_date: date) -> str:
    return f"{target_date.strftime('%a')} {target_date.day} {target_date.strftime('%b')}"


def _validate_habit_name(name: Any) -> str:
    if not isinstance(name, str):
        raise ValueError("Habit name must be a string.")
    cleaned = name.strip()
    if not (1 <= len(cleaned) <= 80):
        raise ValueError("Habit name must be between 1 and 80 characters.")
    return cleaned


def _validate_habit_schedule(days: Any = None, schedule: Any = None) -> dict[str, Any]:
    if schedule is not None:
        if not isinstance(schedule, dict) or "type" not in schedule:
            raise ValueError("Invalid habit schedule format.")
        stype = schedule["type"]
        if stype == "daily":
            return {"type": "daily"}
        if stype == "weekdays":
            return _validate_habit_schedule(days=schedule.get("days"))
        raise ValueError(f"Unknown schedule type: {stype}")

    if days is None:
        return {"type": "daily"}

    if not isinstance(days, (list, tuple)):
        raise ValueError("Days list must contain at least one day.")
    if len(days) == 0:
        raise ValueError("Days list must contain at least one day.")

    normalized_days: list[str] = []
    seen: set[str] = set()
    for d in days:
        if not isinstance(d, str):
            raise ValueError(f"Invalid weekday: {d}")
        low = d.strip().lower()
        if low not in VALID_HABIT_WEEKDAYS:
            raise ValueError(f"Invalid weekday: {d}")
        if low in seen:
            raise ValueError("Days list cannot contain duplicates.")
        seen.add(low)
        normalized_days.append(low)

    # Sort days by calendar weekday order (mon -> sun)
    sorted_days = sorted(normalized_days, key=lambda d: VALID_HABIT_WEEKDAYS.index(d))
    return {"type": "weekdays", "days": sorted_days}


def _is_habit_scheduled(habit: dict[str, Any], target_date: date) -> bool:
    start_date = parse_date(habit["start_date"])
    if target_date < start_date:
        return False
    if habit.get("archived") and habit.get("archived_on"):
        archived_on = parse_date(habit["archived_on"])
        if target_date > archived_on:
            return False

    sched = habit.get("schedule", {"type": "daily"})
    if sched.get("type") == "daily":
        return True
    if sched.get("type") == "weekdays":
        w = VALID_HABIT_WEEKDAYS[target_date.weekday()]
        return w in sched.get("days", [])
    return False


def _calculate_habit_streaks(
    habit: dict[str, Any],
    logs_by_date: dict[str, dict[str, Any]],
    today: date,
) -> tuple[int, int]:
    """Calculate (current_streak, best_streak) according to standard domain rules."""
    start = parse_date(habit["start_date"])
    limit = today
    if habit.get("archived") and habit.get("archived_on"):
        arch_on = parse_date(habit["archived_on"])
        if arch_on < limit:
            limit = arch_on

    if start > limit:
        return 0, 0

    # Determine last accountable date:
    # Today is accountable ONLY if scheduled and has an active log.
    # Scheduled days strictly before today (< today) are always accountable.
    last_accountable_date: date | None = None
    if limit == today:
        if _is_habit_scheduled(habit, today) and today.isoformat() in logs_by_date:
            last_accountable_date = today
        else:
            check_d = today - timedelta(days=1)
            while check_d >= start:
                if _is_habit_scheduled(habit, check_d):
                    last_accountable_date = check_d
                    break
                check_d -= timedelta(days=1)
    else:
        check_d = limit
        while check_d >= start:
            if _is_habit_scheduled(habit, check_d):
                last_accountable_date = check_d
                break
            check_d -= timedelta(days=1)

    if last_accountable_date is None or last_accountable_date < start:
        return 0, 0

    # 1. Current streak: walking backwards from last_accountable_date
    current_streak = 0
    curr_d = last_accountable_date
    while curr_d >= start:
        if _is_habit_scheduled(habit, curr_d):
            log = logs_by_date.get(curr_d.isoformat())
            status = log["status"] if log else "missed"
            if status == "done":
                current_streak += 1
            elif status == "skipped":
                pass  # does not add, does not break
            elif status == "missed":
                break
        curr_d -= timedelta(days=1)

    # 2. Best streak: walking forward from start up to last_accountable_date
    best_streak = 0
    running_streak = 0
    curr_d = start
    while curr_d <= last_accountable_date:
        if _is_habit_scheduled(habit, curr_d):
            log = logs_by_date.get(curr_d.isoformat())
            status = log["status"] if log else "missed"
            if status == "done":
                running_streak += 1
                if running_streak > best_streak:
                    best_streak = running_streak
            elif status == "skipped":
                pass
            elif status == "missed":
                running_streak = 0
        curr_d += timedelta(days=1)

    return current_streak, best_streak


def _calculate_rate_window(
    habit: dict[str, Any],
    logs_by_date: dict[str, dict[str, Any]],
    end_date: date,
    days: int | None = None,
) -> int | None:
    """Calculate integer percentage [0, 100] or None for a habit over a window ending on end_date."""
    start = parse_date(habit["start_date"])
    limit = end_date
    if habit.get("archived") and habit.get("archived_on"):
        arch_on = parse_date(habit["archived_on"])
        if arch_on < limit:
            limit = arch_on

    if start > limit:
        return None

    if days is None:
        window_start = start
    else:
        window_start = max(start, end_date - timedelta(days=days - 1))

    done = 0
    missed = 0
    curr_d = window_start
    while curr_d <= limit:
        if _is_habit_scheduled(habit, curr_d):
            # Accountable day: < end_date, or == end_date if logged
            is_accountable = (curr_d < end_date) or (
                curr_d == end_date and curr_d.isoformat() in logs_by_date
            )
            if is_accountable:
                log = logs_by_date.get(curr_d.isoformat())
                st = log["status"] if log else "missed"
                if st == "done":
                    done += 1
                elif st == "missed":
                    missed += 1
                # skipped does not count into done or missed
        curr_d += timedelta(days=1)

    if done + missed == 0:
        return None
    return round(done * 100 / (done + missed))


def create_habit(
    name: str,
    description: str | None = None,
    days: list[str] | None = None,
    start_date: str | date | None = None,
    reference_date: date | None = None,
) -> dict[str, Any]:
    """Create a new habit and persist it in habits.json."""
    from planner import storage

    cleaned_name = _validate_habit_name(name)
    sched = _validate_habit_schedule(days=days)

    ref = reference_date or clock.today()
    if start_date is None:
        s_date_iso = ref.isoformat()
    elif isinstance(start_date, date):
        s_date_iso = start_date.isoformat()
    else:
        s_date_iso = parse_date(start_date, reference_date=ref).isoformat()

    desc = description.strip() if isinstance(description, str) and description.strip() else None

    habits = storage.load_habits()
    for h in habits:
        if not h.get("deleted", False) and h["name"].casefold() == cleaned_name.casefold():
            raise ValueError(f'A habit named "{cleaned_name}" already exists.')

    now_iso = clock.now().isoformat()
    habit = {
        "id": uuid.uuid4().hex,
        "name": cleaned_name,
        "description": desc,
        "schedule": sched,
        "start_date": s_date_iso,
        "archived": False,
        "archived_on": None,
        "created": now_iso,
        "updated": now_iso,
        "deleted": False,
    }

    label = f'Created habit "{cleaned_name}"'
    with record_action(label):
        habits.append(habit)
        storage.save_habits(habits)
        return dict(habit)


def edit_habit(habit_id: str, **changes: Any) -> dict[str, Any]:
    """Edit habit fields with validation."""
    from planner import storage

    allowed = {"name", "description", "days", "schedule", "start_date", "archived", "archived_on"}
    unknown = changes.keys() - allowed
    if unknown:
        raise ValueError(f"Unsupported habit field(s): {', '.join(sorted(unknown))}.")

    habits = storage.load_habits()
    habit = next((h for h in habits if h.get("id") == habit_id and not h.get("deleted", False)), None)
    if habit is None:
        raise ValueError(f"Habit not found: {habit_id}")

    modified = False

    if "name" in changes:
        new_name = _validate_habit_name(changes["name"])
        for h in habits:
            if h["id"] != habit_id and not h.get("deleted", False) and h["name"].casefold() == new_name.casefold():
                raise ValueError(f'A habit named "{new_name}" already exists.')
        if new_name != habit["name"]:
            habit["name"] = new_name
            modified = True

    if "description" in changes:
        new_desc_raw = changes["description"]
        new_desc = new_desc_raw.strip() if isinstance(new_desc_raw, str) and new_desc_raw.strip() else None
        if new_desc != habit.get("description"):
            habit["description"] = new_desc
            modified = True

    if "days" in changes or "schedule" in changes:
        new_sched = _validate_habit_schedule(days=changes.get("days"), schedule=changes.get("schedule"))
        if new_sched != habit.get("schedule"):
            habit["schedule"] = new_sched
            modified = True

    if "start_date" in changes:
        raw_sd = changes["start_date"]
        parsed_sd = raw_sd.isoformat() if isinstance(raw_sd, date) else parse_date(raw_sd).isoformat()
        if parsed_sd != habit.get("start_date"):
            habit["start_date"] = parsed_sd
            modified = True

    if "archived" in changes:
        new_archived = bool(changes["archived"])
        if new_archived != habit.get("archived", False):
            habit["archived"] = new_archived
            modified = True
            if not new_archived:
                habit["archived_on"] = None
            elif not habit.get("archived_on"):
                habit["archived_on"] = clock.today().isoformat()

    if "archived_on" in changes:
        raw_ao = changes["archived_on"]
        parsed_ao = raw_ao.isoformat() if isinstance(raw_ao, date) else (parse_date(raw_ao).isoformat() if raw_ao else None)
        if parsed_ao != habit.get("archived_on"):
            habit["archived_on"] = parsed_ao
            modified = True

    if not modified:
        return dict(habit)

    habit["updated"] = clock.now().isoformat()
    label = f'Edited habit "{habit["name"]}"'
    with record_action(label):
        storage.save_habits(habits)
        return dict(habit)


def archive_habit(
    habit_id: str,
    archived: bool = True,
    on_date: str | date | None = None,
    reference_date: date | None = None,
) -> dict[str, Any]:
    """Archive or unarchive a habit."""
    from planner import storage

    habits = storage.load_habits()
    habit = next((h for h in habits if h.get("id") == habit_id and not h.get("deleted", False)), None)
    if habit is None:
        raise ValueError(f"Habit not found: {habit_id}")

    ref = reference_date or clock.today()
    if archived:
        if on_date is None:
            arch_on_iso = ref.isoformat()
        elif isinstance(on_date, date):
            arch_on_iso = on_date.isoformat()
        else:
            arch_on_iso = parse_date(on_date, reference_date=ref).isoformat()

        if habit.get("archived") and habit.get("archived_on") == arch_on_iso:
            return dict(habit)

        habit["archived"] = True
        habit["archived_on"] = arch_on_iso
        habit["updated"] = clock.now().isoformat()
        label = f'Archived habit "{habit["name"]}"'
    else:
        if not habit.get("archived", False):
            return dict(habit)
        habit["archived"] = False
        habit["archived_on"] = None
        habit["updated"] = clock.now().isoformat()
        label = f'Unarchived habit "{habit["name"]}"'

    with record_action(label):
        storage.save_habits(habits)
        return dict(habit)


def delete_habit(habit_id: str) -> dict[str, Any]:
    """Logically delete a habit. Its logs are preserved but no longer count."""
    from planner import storage

    habits = storage.load_habits()
    habit = next((h for h in habits if h.get("id") == habit_id and not h.get("deleted", False)), None)
    if habit is None:
        raise ValueError(f"Habit not found: {habit_id}")

    habit["deleted"] = True
    habit["updated"] = clock.now().isoformat()
    label = f'Deleted habit "{habit["name"]}"'
    with record_action(label):
        storage.save_habits(habits)
        return dict(habit)


def set_habit_status(
    habit_id: str,
    date: str | date,
    status: str | None,
    reference_date: date | None = None,
) -> dict[str, Any] | None:
    """Record status for a habit on a given date ('done', 'missed', 'skipped', or None to clear)."""
    from planner import storage

    if status is not None and status not in VALID_HABIT_STATUSES:
        raise ValueError(f"Invalid habit status: {status}")

    today = reference_date or clock.today()
    target_date = date if isinstance(date, _Date) else parse_date(date, reference_date=today)
    if target_date > today:
        raise ValueError("Cannot log habits for future dates.")

    habits = storage.load_habits()
    habit = next((h for h in habits if h.get("id") == habit_id and not h.get("deleted", False)), None)
    if habit is None:
        raise ValueError(f"Habit not found: {habit_id}")

    if not _is_habit_scheduled(habit, target_date):
        raise ValueError("Habit is not scheduled on this date.")

    logs = storage.load_habit_logs()
    target_date_iso = target_date.isoformat()

    active_log = next(
        (l for l in logs if l.get("habit_id") == habit_id and l.get("date") == target_date_iso and not l.get("deleted", False)),
        None,
    )
    deleted_log = next(
        (l for l in logs if l.get("habit_id") == habit_id and l.get("date") == target_date_iso and l.get("deleted", False)),
        None,
    )

    now_iso = clock.now().isoformat()
    date_lbl = _format_date_label(target_date)

    if active_log is not None:
        if active_log.get("status") == status:
            return dict(active_log)

        if status is None:
            active_log["deleted"] = True
            active_log["updated"] = now_iso
            label = f'Habit cleared: {habit["name"]} ({date_lbl})'
            with record_action(label):
                storage.save_habit_logs(logs)
                return dict(active_log)
        else:
            active_log["status"] = status
            active_log["updated"] = now_iso
            label = f'Habit {status}: {habit["name"]} ({date_lbl})'
            with record_action(label):
                storage.save_habit_logs(logs)
                return dict(active_log)

    # No active log exists
    if status is None:
        return None

    if deleted_log is not None:
        deleted_log["deleted"] = False
        deleted_log["status"] = status
        deleted_log["updated"] = now_iso
        label = f'Habit {status}: {habit["name"]} ({date_lbl})'
        with record_action(label):
            storage.save_habit_logs(logs)
            return dict(deleted_log)

    new_log = {
        "id": uuid.uuid4().hex,
        "habit_id": habit_id,
        "date": target_date_iso,
        "status": status,
        "created": now_iso,
        "updated": now_iso,
        "deleted": False,
    }
    label = f'Habit {status}: {habit["name"]} ({date_lbl})'
    with record_action(label):
        logs.append(new_log)
        storage.save_habit_logs(logs)
        return dict(new_log)


def habits_for_day(date: str | date | None = None) -> list[dict[str, Any]]:
    """Return habits scheduled on a given day with current status and current streak."""
    from planner import storage

    target_date = date if isinstance(date, _Date) else (parse_date(date) if date else clock.today())
    target_date_iso = target_date.isoformat()

    habits = storage.load_habits()
    all_logs = storage.load_habit_logs()

    results: list[dict[str, Any]] = []
    for h in habits:
        if h.get("deleted", False):
            continue
        if not _is_habit_scheduled(h, target_date):
            continue

        logs_by_date = {
            l["date"]: l
            for l in all_logs
            if l.get("habit_id") == h["id"] and not l.get("deleted", False)
        }
        active_log = logs_by_date.get(target_date_iso)
        status = active_log["status"] if active_log else "unlogged"
        current_streak, _ = _calculate_habit_streaks(h, logs_by_date, target_date)

        h_copy = dict(h)
        h_copy["status"] = status
        h_copy["current_streak"] = current_streak
        results.append(h_copy)

    results.sort(key=lambda item: item["created"])
    return results


def list_habits(
    include_archived: bool = False,
    date: str | date | None = None,
) -> list[dict[str, Any]]:
    """List habits with today's schedule, status, current streak, and 30-day rate."""
    from planner import storage

    target_date = date if isinstance(date, _Date) else (parse_date(date) if date else clock.today())
    target_date_iso = target_date.isoformat()

    habits = storage.load_habits()
    all_logs = storage.load_habit_logs()

    results: list[dict[str, Any]] = []
    for h in habits:
        if h.get("deleted", False):
            continue
        if not include_archived and h.get("archived", False):
            continue

        logs_by_date = {
            l["date"]: l
            for l in all_logs
            if l.get("habit_id") == h["id"] and not l.get("deleted", False)
        }
        scheduled_today = _is_habit_scheduled(h, target_date)
        if not scheduled_today:
            status_today = "not_scheduled"
        else:
            active_log = logs_by_date.get(target_date_iso)
            status_today = active_log["status"] if active_log else "unlogged"

        current_streak, _ = _calculate_habit_streaks(h, logs_by_date, target_date)
        rate_30d = _calculate_rate_window(h, logs_by_date, end_date=target_date, days=30)

        h_copy = dict(h)
        h_copy["scheduled_today"] = scheduled_today
        h_copy["status_today"] = status_today
        h_copy["current_streak"] = current_streak
        h_copy["rate_30d"] = rate_30d
        results.append(h_copy)

    results.sort(key=lambda item: (item.get("archived", False), item["name"].casefold()))
    return results


def habits_unlogged(
    days: int = 3,
    end_date: str | date | None = None,
) -> list[dict[str, Any]]:
    """List unlogged scheduled habits for each of the last `days` before end_date."""
    from planner import storage

    target_end = end_date if isinstance(end_date, _Date) else (parse_date(end_date) if end_date else clock.today())
    habits = [h for h in storage.load_habits() if not h.get("deleted", False)]
    all_logs = storage.load_habit_logs()

    logs_map: dict[tuple[str, str], dict[str, Any]] = {
        (l["habit_id"], l["date"]): l
        for l in all_logs
        if not l.get("deleted", False)
    }

    results: list[dict[str, Any]] = []
    for offset in range(days, 0, -1):
        day = target_end - timedelta(days=offset)
        day_iso = day.isoformat()
        unlogged_for_day: list[dict[str, Any]] = []
        for h in habits:
            if _is_habit_scheduled(h, day):
                if (h["id"], day_iso) not in logs_map:
                    h_copy = dict(h)
                    h_copy["status"] = "unlogged"
                    unlogged_for_day.append(h_copy)
        if unlogged_for_day:
            unlogged_for_day.sort(key=lambda item: item["created"])
            results.append({
                "date": day_iso,
                "habits": unlogged_for_day,
            })

    return results


def habit_stats(
    habit_id: str,
    end_date: str | date | None = None,
) -> dict[str, Any]:
    """Return detailed statistics for a habit up to end_date."""
    from planner import storage

    target_date = end_date if isinstance(end_date, _Date) else (parse_date(end_date) if end_date else clock.today())
    habits = storage.load_habits()
    habit = next((h for h in habits if h.get("id") == habit_id and not h.get("deleted", False)), None)
    if habit is None:
        raise ValueError(f"Habit not found: {habit_id}")

    all_logs = storage.load_habit_logs()
    logs_by_date = {
        l["date"]: l
        for l in all_logs
        if l.get("habit_id") == habit_id and not l.get("deleted", False)
    }

    current_streak, best_streak = _calculate_habit_streaks(habit, logs_by_date, target_date)
    rate_7d = _calculate_rate_window(habit, logs_by_date, target_date, 7)
    rate_30d = _calculate_rate_window(habit, logs_by_date, target_date, 30)
    rate_all = _calculate_rate_window(habit, logs_by_date, target_date, None)

    start = parse_date(habit["start_date"])
    limit = target_date
    if habit.get("archived") and habit.get("archived_on"):
        arch_on = parse_date(habit["archived_on"])
        if arch_on < limit:
            limit = arch_on

    total_done = 0
    total_missed = 0
    total_skipped = 0
    last_done_date: date | None = None

    weekday_counts: dict[str, list[int]] = {w: [0, 0] for w in VALID_HABIT_WEEKDAYS}  # [done, missed]

    if start <= limit:
        curr_d = start
        while curr_d <= limit:
            if _is_habit_scheduled(habit, curr_d):
                is_accountable = (curr_d < target_date) or (
                    curr_d == target_date and curr_d.isoformat() in logs_by_date
                )
                if is_accountable:
                    log = logs_by_date.get(curr_d.isoformat())
                    st = log["status"] if log else "missed"
                    w = VALID_HABIT_WEEKDAYS[curr_d.weekday()]
                    if st == "done":
                        total_done += 1
                        weekday_counts[w][0] += 1
                        if last_done_date is None or curr_d > last_done_date:
                            last_done_date = curr_d
                    elif st == "missed":
                        total_missed += 1
                        weekday_counts[w][1] += 1
                    elif st == "skipped":
                        total_skipped += 1
            curr_d += timedelta(days=1)

    by_weekday: dict[str, int | None] = {}
    for w in VALID_HABIT_WEEKDAYS:
        w_done, w_missed = weekday_counts[w]
        if w_done + w_missed > 0:
            by_weekday[w] = round(w_done * 100 / (w_done + w_missed))
        else:
            by_weekday[w] = None

    return {
        "current_streak": current_streak,
        "best_streak": best_streak,
        "rate_7d": rate_7d,
        "rate_30d": rate_30d,
        "rate_all": rate_all,
        "total_done": total_done,
        "total_missed": total_missed,
        "total_skipped": total_skipped,
        "last_done": last_done_date.isoformat() if last_done_date else None,
        "by_weekday": by_weekday,
    }


def habit_calendar(
    habit_id: str,
    start_date: str | date,
    end_date: str | date,
    reference_date: date | None = None,
) -> list[dict[str, Any]]:
    """Daily status list from start_date to end_date (max 400 days)."""
    from planner import storage

    today = reference_date or clock.today()
    s_date = start_date if isinstance(start_date, _Date) else parse_date(start_date, reference_date=today)
    e_date = end_date if isinstance(end_date, _Date) else parse_date(end_date, reference_date=today)

    if s_date > e_date:
        raise ValueError("start_date must be before or equal to end_date.")

    if (e_date - s_date).days + 1 > 400:
        raise ValueError("Date range cannot exceed 400 days.")

    habits = storage.load_habits()
    habit = next((h for h in habits if h.get("id") == habit_id and not h.get("deleted", False)), None)
    if habit is None:
        raise ValueError(f"Habit not found: {habit_id}")

    all_logs = storage.load_habit_logs()
    logs_by_date = {
        l["date"]: l
        for l in all_logs
        if l.get("habit_id") == habit_id and not l.get("deleted", False)
    }

    h_start = parse_date(habit["start_date"])
    h_arch_on = parse_date(habit["archived_on"]) if habit.get("archived") and habit.get("archived_on") else None

    result: list[dict[str, Any]] = []
    curr_d = s_date
    while curr_d <= e_date:
        curr_d_iso = curr_d.isoformat()
        if curr_d < h_start or (h_arch_on is not None and curr_d > h_arch_on):
            st = "out_of_range"
        elif not _is_habit_scheduled(habit, curr_d):
            st = "not_scheduled"
        else:
            log = logs_by_date.get(curr_d_iso)
            if log is not None:
                st = log["status"]
            else:
                if curr_d == today:
                    st = "unlogged"
                elif curr_d < today:
                    st = "missed"
                else:
                    st = "unlogged"
        result.append({"date": curr_d_iso, "status": st})
        curr_d += timedelta(days=1)

    return result


def habits_series(
    start_date: str | date,
    end_date: str | date,
    habit_ids: list[str] | None = None,
    reference_date: date | None = None,
) -> list[dict[str, Any]]:
    """Daily aggregated series: scheduled, done, missed, skipped, percent."""
    from planner import storage

    today = reference_date or clock.today()
    s_date = start_date if isinstance(start_date, _Date) else parse_date(start_date, reference_date=today)
    e_date = end_date if isinstance(end_date, _Date) else parse_date(end_date, reference_date=today)

    if s_date > e_date:
        raise ValueError("start_date must be before or equal to end_date.")

    habits = [h for h in storage.load_habits() if not h.get("deleted", False)]
    if habit_ids is not None:
        target_ids = set(habit_ids)
        habits = [h for h in habits if h["id"] in target_ids]

    all_logs = storage.load_habit_logs()
    logs_map: dict[tuple[str, str], dict[str, Any]] = {
        (l["habit_id"], l["date"]): l
        for l in all_logs
        if not l.get("deleted", False)
    }

    result: list[dict[str, Any]] = []
    curr_d = s_date
    while curr_d <= e_date:
        curr_d_iso = curr_d.isoformat()
        scheduled_count = 0
        done_count = 0
        missed_count = 0
        skipped_count = 0

        for h in habits:
            if _is_habit_scheduled(h, curr_d):
                scheduled_count += 1
                is_accountable = (curr_d < today) or (
                    curr_d == today and (h["id"], curr_d_iso) in logs_map
                )
                if is_accountable:
                    log = logs_map.get((h["id"], curr_d_iso))
                    st = log["status"] if log else "missed"
                    if st == "done":
                        done_count += 1
                    elif st == "missed":
                        missed_count += 1
                    elif st == "skipped":
                        skipped_count += 1

        percent = (
            round(done_count * 100 / (done_count + missed_count))
            if (done_count + missed_count) > 0
            else None
        )

        result.append({
            "date": curr_d_iso,
            "scheduled": scheduled_count,
            "done": done_count,
            "missed": missed_count,
            "skipped": skipped_count,
            "percent": percent,
        })
        curr_d += timedelta(days=1)

    return result


def habits_summary(end_date: str | date | None = None) -> dict[str, Any]:
    """Summary of habit performance: 7d/30d global rate, habit breakdown, best and worst habit."""
    from planner import storage

    target_date = end_date if isinstance(end_date, _Date) else (parse_date(end_date) if end_date else clock.today())
    habits = [h for h in storage.load_habits() if not h.get("deleted", False)]
    all_logs = storage.load_habit_logs()

    logs_by_habit: dict[str, dict[str, dict[str, Any]]] = {}
    for l in all_logs:
        if not l.get("deleted", False):
            logs_by_habit.setdefault(l["habit_id"], {})[l["date"]] = l

    # Global 7-day rate
    s_7d = target_date - timedelta(days=6)
    done_7d = 0
    missed_7d = 0
    curr_d = s_7d
    while curr_d <= target_date:
        for h in habits:
            if _is_habit_scheduled(h, curr_d):
                h_logs = logs_by_habit.get(h["id"], {})
                is_accountable = (curr_d < target_date) or (
                    curr_d == target_date and curr_d.isoformat() in h_logs
                )
                if is_accountable:
                    st = h_logs[curr_d.isoformat()]["status"] if curr_d.isoformat() in h_logs else "missed"
                    if st == "done":
                        done_7d += 1
                    elif st == "missed":
                        missed_7d += 1
        curr_d += timedelta(days=1)
    rate_7d = round(done_7d * 100 / (done_7d + missed_7d)) if (done_7d + missed_7d) > 0 else None

    # Global 30-day rate
    s_30d = target_date - timedelta(days=29)
    done_30d = 0
    missed_30d = 0
    curr_d = s_30d
    while curr_d <= target_date:
        for h in habits:
            if _is_habit_scheduled(h, curr_d):
                h_logs = logs_by_habit.get(h["id"], {})
                is_accountable = (curr_d < target_date) or (
                    curr_d == target_date and curr_d.isoformat() in h_logs
                )
                if is_accountable:
                    st = h_logs[curr_d.isoformat()]["status"] if curr_d.isoformat() in h_logs else "missed"
                    if st == "done":
                        done_30d += 1
                    elif st == "missed":
                        missed_30d += 1
        curr_d += timedelta(days=1)
    rate_30d = round(done_30d * 100 / (done_30d + missed_30d)) if (done_30d + missed_30d) > 0 else None

    # Per habit stats
    habits_list: list[dict[str, Any]] = []
    for h in habits:
        h_logs = logs_by_habit.get(h["id"], {})
        current_streak, best_streak = _calculate_habit_streaks(h, h_logs, target_date)
        r30 = _calculate_rate_window(h, h_logs, target_date, 30)
        habits_list.append({
            "id": h["id"],
            "name": h["name"],
            "rate_30d": r30,
            "current_streak": current_streak,
            "best_streak": best_streak,
        })

    # Sort best to worst 30-day rate (None sorted last)
    habits_list.sort(
        key=lambda item: (
            0 if item["rate_30d"] is not None else 1,
            -(item["rate_30d"] or 0),
            -item["current_streak"],
            item["name"].casefold(),
        )
    )

    habits_with_data = [item for item in habits_list if item["rate_30d"] is not None]
    if len(habits_with_data) >= 2:
        best_habit: dict[str, Any] | None = {
            "id": habits_with_data[0]["id"],
            "name": habits_with_data[0]["name"],
            "rate_30d": habits_with_data[0]["rate_30d"],
        }
        worst_habit: dict[str, Any] | None = {
            "id": habits_with_data[-1]["id"],
            "name": habits_with_data[-1]["name"],
            "rate_30d": habits_with_data[-1]["rate_30d"],
        }
    else:
        best_habit = None
        worst_habit = None

    return {
        "rate_7d": rate_7d,
        "rate_30d": rate_30d,
        "habits": habits_list,
        "best_habit": best_habit,
        "worst_habit": worst_habit,
    }


