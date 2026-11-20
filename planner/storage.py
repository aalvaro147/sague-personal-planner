import json
from pathlib import Path
from typing import Any

from planner import core


def get_projects_file() -> Path:
    from planner import core

    if hasattr(core, "TASKS_FILE") and core.TASKS_FILE is not None:
        return core.TASKS_FILE.parent / "projects.json"
    return core.get_data_dir() / "projects.json"


def load_projects() -> list[dict[str, Any]]:
    projects_file = get_projects_file()
    if not projects_file.exists():
        return []
    try:
        content = projects_file.read_text(encoding="utf-8")
        if not content.strip():
            return []
        data = json.loads(content)
        if not isinstance(data, list):
            raise ValueError(f"Corrupt data file: {projects_file}")
        return data
    except Exception as error:
        if isinstance(error, ValueError) and "Corrupt" in str(error):
            raise
        raise ValueError(f"Corrupt data file: {projects_file}") from error


def save_projects(projects: list[dict[str, Any]]) -> None:
    projects_file = get_projects_file()
    core._atomic_save_json(projects_file, projects)


def get_notes_file() -> Path:
    from planner import core

    if hasattr(core, "TASKS_FILE") and core.TASKS_FILE is not None:
        return core.TASKS_FILE.parent / "notes.json"
    return core.get_data_dir() / "notes.json"


def load_notes() -> list[dict[str, Any]]:
    notes_file = get_notes_file()
    if not notes_file.exists():
        return []
    try:
        content = notes_file.read_text(encoding="utf-8")
        if not content.strip():
            return []
        data = json.loads(content)
        if not isinstance(data, list):
            raise ValueError(f"Corrupt data file: {notes_file}")
        return data
    except Exception as error:
        if isinstance(error, ValueError) and "Corrupt" in str(error):
            raise
        raise ValueError(f"Corrupt data file: {notes_file}") from error


def save_notes(notes: list[dict[str, Any]]) -> None:
    notes_file = get_notes_file()
    core._atomic_save_json(notes_file, notes)


def get_habits_file() -> Path:
    from planner import core

    if hasattr(core, "TASKS_FILE") and core.TASKS_FILE is not None:
        return core.TASKS_FILE.parent / "habits.json"
    return core.get_data_dir() / "habits.json"


def load_habits() -> list[dict[str, Any]]:
    habits_file = get_habits_file()
    if not habits_file.exists():
        return []
    try:
        content = habits_file.read_text(encoding="utf-8")
        if not content.strip():
            return []
        data = json.loads(content)
        if not isinstance(data, list):
            raise ValueError(f"Corrupt data file: {habits_file}")
        return data
    except Exception as error:
        if isinstance(error, ValueError) and "Corrupt" in str(error):
            raise
        raise ValueError(f"Corrupt data file: {habits_file}") from error


def save_habits(habits: list[dict[str, Any]]) -> None:
    habits_file = get_habits_file()
    core._atomic_save_json(habits_file, habits)


def get_habit_logs_file() -> Path:
    from planner import core

    if hasattr(core, "TASKS_FILE") and core.TASKS_FILE is not None:
        return core.TASKS_FILE.parent / "habit_logs.json"
    return core.get_data_dir() / "habit_logs.json"


def load_habit_logs() -> list[dict[str, Any]]:
    logs_file = get_habit_logs_file()
    if not logs_file.exists():
        return []
    try:
        content = logs_file.read_text(encoding="utf-8")
        if not content.strip():
            return []
        data = json.loads(content)
        if not isinstance(data, list):
            raise ValueError(f"Corrupt data file: {logs_file}")
        return data
    except Exception as error:
        if isinstance(error, ValueError) and "Corrupt" in str(error):
            raise
        raise ValueError(f"Corrupt data file: {logs_file}") from error


def save_habit_logs(logs: list[dict[str, Any]]) -> None:
    logs_file = get_habit_logs_file()
    core._atomic_save_json(logs_file, logs)

