import json
import os
import shutil
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, TypedDict

from platformdirs import user_data_dir
from planner import recurrence as recurrence_rules


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
    if (
        type(duration) is not int
        or duration <= 0
        or duration > _time_minutes(day_end) - _time_minutes(day_start)
    ):
        raise ValueError("Default duration must fit within the planning day.")
    if type(max_candidates) is not int or max_candidates <= 0:
        raise ValueError("'max_candidates' must be a positive integer.")
    return {
        "first_weekday": data.get("first_weekday", "mon"),
        "day_start": day_start,
        "day_end": day_end,
        "default_duration_minutes": duration,
        "max_candidates": max_candidates,
    }


def save_settings(
    first_weekday: str | None = None,
    *,
    day_start: str | None = None,
    day_end: str | None = None,
    default_duration_minutes: int | None = None,
    max_candidates: int | None = None,
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
    reference_date = reference_date or date.today()
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
    return ScheduledBlock(identifier, parsed_date, start, end)


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
            }
            for block in task.blocks
        ],
        "recurrence": task.recurrence,
        "series_id": task.series_id,
        "series_start": task.series_start.isoformat() if task.series_start else None,
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
    now = datetime.now()

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
    today = reference_date or date.today()
    return [
        task
        for task in list_tasks()
        if not task.done and task.due is not None and task.due <= today
    ]


def tasks_due_this_week(reference_date: date | None = None) -> list[Task]:
    today = reference_date or date.today()
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
    first_date = reference_date or date.today()
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
    block = ScheduledBlock(uuid.uuid4().hex, parsed_date, start_time, end_time)
    task.blocks.append(block)
    task.updated = datetime.now()
    save_tasks(tasks)
    return block


def remove_block(task_id: str, block_id: str) -> ScheduledBlock:
    tasks = load_tasks()
    task = _find_task(tasks, task_id)
    for index, block in enumerate(task.blocks):
        if block.id == block_id:
            removed_block = task.blocks.pop(index)
            task.updated = datetime.now()
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
    for block in task.blocks:
        if block.id == block_id:
            block.date = parsed_date
            block.start = start_time
            block.end = end_time
            task.updated = datetime.now()
            save_tasks(tasks)
            return block
    raise ValueError("Block not found on the specified task.")


def get_day_agenda(block_date: str) -> list[AgendaEntry]:
    requested_date = _validate_date(block_date)
    block_entries: list[AgendaEntry] = [
        {"kind": "block", "block": block, "task": task}
        for task in load_tasks()
        if not task.deleted and not task.done
        for block in task.blocks
        if block.date == requested_date
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
        if task.deleted or task.done:
            continue
        for block in task.blocks:
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
        created=datetime.now(),
        updated=datetime.now(),
        recurrence=rule,
    )
    existing_events = [
        occurrence
        for event in load_events()
        if not event.deleted
        for occurrence in occurrences(event, start, end)
    ]
    active_tasks = [
        task
        for task in load_tasks()
        if not task.deleted and not task.done
    ]
    conflicts: list[tuple[date, AgendaEntry]] = []
    for occurrence in occurrences(candidate, start, end):
        for task in active_tasks:
            for block in task.blocks:
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
        if not task.deleted and not task.done
        for block in task.blocks
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
    now = datetime.now()
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
        event.updated = datetime.now()
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
        event.updated = datetime.now()
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
    now = datetime.now()

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
    event.updated = datetime.now()
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
        start = date.today()
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
) -> Task:
    recurrence = validate_task_fields(title, due, priority, recurrence)

    now = datetime.now()
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
    )
    return task


def create_task(
    title: str,
    due: date | None = None,
    priority: str = "media",
    recurrence: dict[str, Any] | None = None,
) -> Task:
    task = _new_task(title, due, priority, recurrence)
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
) -> Task:
    parsed_date = _validate_block_interval(block_date, start_time, end_time)
    task = _new_task(title, due, priority, recurrence)
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


def _find_task(tasks: list[Task], identifier: str) -> Task:
    for task in tasks:
        if task.id == identifier and not task.deleted:
            return task
    raise ValueError("No active task found with that ID.")


def edit_task(identifier: str, title: str) -> Task:
    title = title.strip()
    if not title:
        raise ValueError("Task title cannot be empty.")

    tasks = load_tasks()
    task = _find_task(tasks, identifier)
    task.title = title
    task.updated = datetime.now()
    save_tasks(tasks)
    return task


def edit_task_details(identifier: str, **changes: Any) -> Task:
    allowed_fields = {"title", "due", "priority", "recurrence"}
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

    if changes:
        task.title = title.strip()
        task.due = due
        task.priority = priority
        task.recurrence = recurrence
        if recurrence is not None and task.series_id is None:
            task.series_id = task.id
        if recurrence is not None and recurrence_changed:
            task.series_start = due
        elif recurrence is None:
            task.series_id = None
            task.series_start = None
        task.updated = datetime.now()
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
) -> Task:
    if type(done) is not bool:
        raise ValueError("Task done state must be a boolean.")
    if reference_date is not None and type(reference_date) is not date:
        raise ValueError("Reference date must be a date without a time.")
    tasks = load_tasks()
    task = _find_task(tasks, identifier)
    if task.done != done:
        task.done = done
        task.updated = datetime.now()
        if done:
            next_due = _next_task_due(tasks, task, reference_date or date.today())
            if next_due is not None:
                now = datetime.now()
                tasks.append(
                    Task(
                        id=uuid.uuid4().hex,
                        title=task.title,
                        done=False,
                        created=now,
                        updated=now,
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


def complete_task(identifier: str, reference_date: date | None = None) -> Task:
    return set_task_done(identifier, True, reference_date)


def delete_task(identifier: str) -> Task:
    tasks = load_tasks()
    task = _find_task(tasks, identifier)
    task.deleted = True
    task.updated = datetime.now()
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

