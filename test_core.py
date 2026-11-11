import json
import sys
from datetime import date as Date
from datetime import datetime

import pytest

from planner import cli, core
from planner.tui.app import main as app_main


@pytest.fixture(autouse=True)
def task_files(tmp_path, monkeypatch):
    task_file = tmp_path / "tasks.json"
    monkeypatch.setattr(core, "TASKS_FILE", task_file)
    monkeypatch.setattr(core, "EVENTS_FILE", tmp_path / "events.json")
    monkeypatch.setattr(core, "LEGACY_TASKS_FILE", tmp_path / "legacy.jsonl")
    monkeypatch.setattr(core, "SETTINGS_FILE", tmp_path / "settings.json")
    return task_file


def test_create_task_saves_task(task_files):
    task = core.create_task("Buy bread")

    saved_tasks = core.load_tasks()

    assert task_files.is_file()
    assert task.title == "Buy bread"
    assert task.priority == "media"
    assert saved_tasks == [task]


def test_get_data_dir_uses_environment_and_creates_absolute_path(tmp_path, monkeypatch):
    requested_dir = tmp_path / "nested" / "planner-data"
    monkeypatch.setenv("PLANNER_DATA_DIR", str(requested_dir))

    data_dir = core.get_data_dir()

    assert data_dir == requested_dir.resolve()
    assert data_dir.is_dir()
    assert data_dir.is_absolute()


def test_data_files_are_independent_of_current_working_directory(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    working_dir = tmp_path / "working"
    working_dir.mkdir()
    monkeypatch.setenv("PLANNER_DATA_DIR", str(data_dir))
    monkeypatch.chdir(working_dir)
    core.configure_data_dir()

    core.create_task("Stored task")
    core.create_event("Appointment", "2026-11-12", "09:00", "10:00")
    core.save_settings("sun")

    assert core.TASKS_FILE == data_dir / "tasks.json"
    assert core.EVENTS_FILE == data_dir / "events.json"
    assert core.SETTINGS_FILE == data_dir / "settings.json"
    assert all((data_dir / name).is_file() for name in (
        "tasks.json",
        "events.json",
        "settings.json",
    ))
    assert list(working_dir.iterdir()) == []


def test_data_migration_copies_existing_files_and_never_overwrites(
    tmp_path,
    monkeypatch,
):
    project_dir = tmp_path / "project"
    (project_dir / "planner").mkdir(parents=True)
    legacy_dir = project_dir / "planificador"
    legacy_dir.mkdir()
    data_dir = tmp_path / "user-data"
    data_dir.mkdir()
    existing_tasks = '[{"id":"destination"}]'
    (data_dir / "tasks.json").write_text(existing_tasks, encoding="utf-8")
    (legacy_dir / "tareas.json").write_text(
        '[{"id":"legacy"}]',
        encoding="utf-8",
    )
    (legacy_dir / "tareas.json.bak").write_text(
        '[{"id":"legacy-backup"}]',
        encoding="utf-8",
    )
    (legacy_dir / "events.json").write_text("[]", encoding="utf-8")
    (legacy_dir / "events.json.bak").write_text("[]", encoding="utf-8")
    (legacy_dir / "settings.json").write_text(
        '{"first_weekday":"sun"}',
        encoding="utf-8",
    )
    monkeypatch.setattr(core, "__file__", str(project_dir / "planner" / "core.py"))
    monkeypatch.setenv("PLANNER_DATA_DIR", str(data_dir))

    migrated_dir, migrated = core.initialize_data_storage()

    assert migrated_dir == data_dir
    assert set(migrated) == {data_dir / "events.json", data_dir / "settings.json"}
    assert (data_dir / "tasks.json").read_text(encoding="utf-8") == existing_tasks
    assert not (data_dir / "tasks.json.bak").exists()
    assert (data_dir / "events.json").read_text(encoding="utf-8") == "[]"
    assert (data_dir / "events.json.bak").read_text(encoding="utf-8") == "[]"
    assert (data_dir / "settings.json").is_file()


def test_data_migration_does_nothing_without_legacy_files(tmp_path, monkeypatch):
    project_dir = tmp_path / "project"
    (project_dir / "planner").mkdir(parents=True)
    monkeypatch.setattr(core, "__file__", str(project_dir / "planner" / "core.py"))
    monkeypatch.setenv("PLANNER_DATA_DIR", str(tmp_path / "user-data"))

    data_dir, migrated = core.initialize_data_storage()

    assert data_dir.is_dir()
    assert migrated == []
    assert list(data_dir.iterdir()) == []


def test_data_migration_imports_legacy_tasks_json(tmp_path, monkeypatch):
    project_dir = tmp_path / "project"
    planner_dir = project_dir / "planner"
    legacy_dir = project_dir / "planificador"
    planner_dir.mkdir(parents=True)
    legacy_dir.mkdir()
    legacy_tasks = '[{"id":"legacy","title":"Old task"}]'
    (legacy_dir / "tareas.json").write_text(legacy_tasks, encoding="utf-8")
    (legacy_dir / "tareas.json.bak").write_text("[]", encoding="utf-8")
    monkeypatch.setattr(core, "__file__", str(planner_dir / "core.py"))
    monkeypatch.setenv("PLANNER_DATA_DIR", str(tmp_path / "user-data"))

    data_dir, migrated = core.initialize_data_storage()

    assert migrated == [data_dir / "tasks.json"]
    assert (data_dir / "tasks.json").read_text(encoding="utf-8") == legacy_tasks
    assert (data_dir / "tasks.json.bak").read_text(encoding="utf-8") == "[]"


def test_data_dir_command_prints_resolved_location(tmp_path, monkeypatch, capsys):
    data_dir = tmp_path / "planner-data"
    monkeypatch.setenv("PLANNER_DATA_DIR", str(data_dir))
    monkeypatch.setattr(sys, "argv", ["planificador", "--data-dir"])

    app_main()

    assert capsys.readouterr().out.strip() == str(data_dir.resolve())


def test_version_command_prints_version(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["planificador", "--version"])

    with pytest.raises(SystemExit) as error:
        app_main()

    assert error.value.code == 0
    assert capsys.readouterr().out.strip() == "planificador 0.1.0"


def test_cli_option_starts_legacy_interface(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(cli, "main", lambda: called.append(True))
    monkeypatch.setattr(sys, "argv", ["planificador", "--cli"])
    monkeypatch.setenv("PLANNER_DATA_DIR", str(tmp_path / "cli-data"))

    app_main()

    assert called == [True]


def test_create_task_with_block_saves_both_atomically(task_files):
    task = core.create_task_with_block(
        "Prepare report",
        "2026-11-12",
        "18:00",
        "19:00",
    )

    assert task.blocks[0].date == Date(2026, 11, 12)
    assert task.blocks[0].start == "18:00"
    assert task.blocks[0].end == "19:00"
    assert task_files.is_file()
    assert core.load_tasks() == [task]


def test_create_task_with_invalid_block_does_not_save_task(task_files):
    with pytest.raises(ValueError, match="later than"):
        core.create_task_with_block(
            "Prepare report",
            "2026-11-12",
            "19:00",
            "18:00",
        )

    assert not task_files.exists()


def test_edit_task_updates_title(task_files):
    task = core.create_task("Old title")

    updated_task = core.edit_task(task.id, "New title")

    assert task_files.is_file()
    assert updated_task.title == "New title"
    assert core.load_tasks()[0].title == "New title"
    assert updated_task.updated >= task.updated


def test_delete_task_marks_task_deleted(task_files):
    task = core.create_task("Temporary task")

    deleted_task = core.delete_task(task.id)

    assert task_files.is_file()
    assert deleted_task.deleted is True
    assert core.list_tasks() == []
    assert core.load_tasks()[0].deleted is True


def test_tasks_due_today_includes_overdue_and_today_only(monkeypatch):
    fixed_today = Date(2026, 11, 9)

    class FixedDate(Date):
        @classmethod
        def today(cls):
            return fixed_today

    now = datetime(2026, 11, 9, 12, 0)
    tasks = [
        core.Task("overdue", "Overdue", False, now, now, False, Date(2026, 11, 8)),
        core.Task("today", "Due today", False, now, now, False, fixed_today),
        core.Task("tomorrow", "Due tomorrow", False, now, now, False, Date(2026, 11, 10)),
        core.Task("done", "Completed overdue", True, now, now, False, Date(2026, 11, 8)),
        core.Task("no-date", "No due date", False, now, now, False),
    ]
    monkeypatch.setattr(core, "date", FixedDate)
    monkeypatch.setattr(core, "list_tasks", lambda: tasks)

    due_tasks = core.tasks_due_today()

    assert [task.id for task in due_tasks] == ["overdue", "today"]


def test_plan_move_and_remove_block(task_files):
    task = core.create_task("Prepare report")

    block = core.plan_block(task.id, "2026-11-10", "18:00", "19:00")
    assert block.id
    assert block.date == Date(2026, 11, 10)

    moved = core.move_block(
        task.id,
        block.id,
        "2026-11-11",
        "19:00",
        "20:00",
    )
    assert moved.date == Date(2026, 11, 11)
    assert moved.start == "19:00"
    assert moved.end == "20:00"
    assert core.load_tasks()[0].updated >= task.updated

    removed = core.remove_block(task.id, block.id)
    assert task_files.is_file()
    assert removed.id == block.id
    assert core.load_tasks()[0].blocks == []


def test_task_can_have_multiple_blocks(task_files):
    task = core.create_task("Work on report")

    first = core.plan_block(task.id, "2026-11-10", "18:00", "19:00")
    second = core.plan_block(task.id, "2026-11-11", "18:30", "20:00")

    loaded_task = core.load_tasks()[0]
    assert task_files.is_file()
    assert [block.id for block in loaded_task.blocks] == [first.id, second.id]


@pytest.mark.parametrize(
    ("start", "end", "message"),
    [
        ("6pm", "19:00", "start time"),
        ("18:00", "7pm", "end time"),
        ("19:00", "19:00", "later than"),
        ("20:00", "19:00", "later than"),
    ],
)
def test_plan_rejects_invalid_times(task_files, start, end, message):
    task = core.create_task("Invalid block")

    with pytest.raises(ValueError, match=message):
        core.plan_block(task.id, "2026-11-10", start, end)
    assert task_files.is_file()


def test_overlap_detection_and_excluding_block(task_files):
    first_task = core.create_task("First")
    second_task = core.create_task("Second")
    first = core.plan_block(first_task.id, "2026-11-10", "18:00", "19:00")
    core.plan_block(second_task.id, "2026-11-10", "19:30", "20:30")

    assert core.has_overlap("2026-11-10", "18:30", "19:15")
    assert not core.has_overlap("2026-11-10", "19:00", "19:30")
    assert not core.has_overlap(
        "2026-11-10",
        "18:00",
        "19:00",
        exclude_block_id=first.id,
    )
    assert task_files.is_file()


def test_agenda_is_sorted_and_omits_done_or_deleted_tasks(task_files):
    early_task = core.create_task("Early")
    late_task = core.create_task("Late")
    done_task = core.create_task("Done")
    deleted_task = core.create_task("Deleted")
    core.plan_block(late_task.id, "2026-11-10", "20:00", "21:00")
    core.plan_block(early_task.id, "2026-11-10", "18:00", "19:00")
    core.plan_block(done_task.id, "2026-11-10", "17:00", "17:30")
    core.plan_block(deleted_task.id, "2026-11-10", "16:00", "16:30")
    core.complete_task(done_task.id)
    core.delete_task(deleted_task.id)

    entries = core.get_day_agenda("2026-11-10")

    assert [entry["task"].title for entry in entries] == ["Early", "Late"]
    assert [entry["block"].start for entry in entries] == ["18:00", "20:00"]
    assert len(core.load_tasks()[2].blocks) == 1
    assert len(core.load_tasks()[3].blocks) == 1
    assert task_files.is_file()


def test_tasks_without_planning_only_returns_pending_unplanned(task_files):
    unplanned_task = core.create_task("Unplanned")
    planned_task = core.create_task("Planned")
    completed_task = core.create_task("Completed")
    deleted_task = core.create_task("Deleted")
    core.plan_block(planned_task.id, "2026-11-10", "18:00", "19:00")
    core.plan_block(completed_task.id, "2026-11-10", "19:00", "20:00")
    core.complete_task(completed_task.id)
    core.delete_task(deleted_task.id)

    assert task_files.is_file()
    assert [task.id for task in core.get_unplanned_tasks()] == [unplanned_task.id]


def test_old_task_without_blocks_loads_as_unplanned(task_files):
    task_files.write_text(
        '[{"id":"old","title":"Old task","done":false,'
        '"created":"2026-11-09T10:00:00","updated":"2026-11-09T10:00:00",'
        '"deleted":false,"due":null,"prioridad":"media"}]',
        encoding="utf-8",
    )

    tasks = core.load_tasks()

    assert tasks[0].blocks == []
    assert [task.id for task in core.get_unplanned_tasks()] == ["old"]


def test_legacy_spanish_block_data_loads_and_is_saved_in_english(task_files):
    task_files.write_text(
        '[{"id":"legacy","title":"Legacy task","done":false,'
        '"created":"2026-11-09T10:00:00","updated":"2026-11-09T10:00:00",'
        '"deleted":false,"bloques":[{"id":"block-1","fecha":"2026-11-10",'
        '"inicio":"18:00","fin":"19:00"}]}]',
        encoding="utf-8",
    )

    task = core.load_tasks()[0]

    assert task.blocks[0].date == Date(2026, 11, 10)
    assert task.blocks[0].start == "18:00"
    saved_data = json.loads(task_files.read_text(encoding="utf-8"))
    assert saved_data[0]["blocks"][0] == {
        "id": "block-1",
        "date": "2026-11-10",
        "start": "18:00",
        "end": "19:00",
    }


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("today", Date(2026, 11, 9)),
        ("tomorrow", Date(2026, 11, 10)),
        ("monday", Date(2026, 11, 16)),
        ("tuesday", Date(2026, 11, 10)),
        ("wednesday", Date(2026, 11, 11)),
        ("thursday", Date(2026, 11, 12)),
        ("friday", Date(2026, 11, 13)),
        ("saturday", Date(2026, 11, 14)),
        ("sunday", Date(2026, 11, 15)),
    ],
)
def test_parse_date_with_fixed_reference(text, expected):
    assert core.parse_date(text, reference_date=Date(2026, 11, 9)) == expected


@pytest.mark.parametrize("text", ["hoy", "mañana", "lunes"])
def test_parse_date_rejects_spanish_terms(text):
    with pytest.raises(ValueError, match="Invalid date"):
        core.parse_date(text, reference_date=Date(2026, 11, 9))


def test_planning_allows_overlap_for_confirmation_in_cli(task_files):
    first_task = core.create_task("First")
    second_task = core.create_task("Second")
    core.plan_block(first_task.id, "2026-11-10", "18:00", "19:00")

    overlapping_block = core.plan_block(
        second_task.id,
        "2026-11-10",
        "18:30",
        "19:30",
    )

    assert overlapping_block.id
    assert core.has_overlap("2026-11-10", "18:45", "19:15")
    assert task_files.is_file()


def test_moving_block_allows_overlap_when_excluding_own_id(task_files):
    moving_task = core.create_task("Move this")
    other_task = core.create_task("Keep this")
    moving_block = core.plan_block(
        moving_task.id,
        "2026-11-10",
        "18:00",
        "19:00",
    )
    core.plan_block(other_task.id, "2026-11-10", "19:00", "20:00")

    assert not core.has_overlap(
        "2026-11-10",
        "18:00",
        "19:00",
        exclude_block_id=moving_block.id,
    )
    moved = core.move_block(
        moving_task.id,
        moving_block.id,
        "2026-11-10",
        "18:45",
        "19:15",
    )

    assert moved.start == "18:45"
    assert core.has_overlap("2026-11-10", "18:45", "19:15")
    assert task_files.is_file()


def test_create_edit_and_delete_event():
    event = core.create_event(
        "Dentist",
        "2026-11-12",
        "10:30",
        "11:15",
        location="Clinic",
        notes="Annual checkup",
    )
    original_updated = event.updated

    updated = core.edit_event(
        event.id,
        title="Doctor",
        start="11:00",
        location=None,
    )

    assert updated.title == "Doctor"
    assert updated.start == "11:00"
    assert updated.location is None
    assert updated.notes == "Annual checkup"
    assert updated.updated >= original_updated
    assert core.load_events() == [updated]

    deleted = core.delete_event(event.id)
    assert deleted.deleted is True
    assert core.list_events() == []
    assert core.load_events()[0].deleted is True
    assert core.EVENTS_FILE.is_file()


@pytest.mark.parametrize(
    ("title", "event_date", "start", "end", "message"),
    [
        ("", "2026-11-12", "10:30", "11:15", "title"),
        ("Dentist", "2026-2-12", "10:30", "11:15", "date"),
        ("Dentist", "2026-11-12", "10am", "11:15", "start time"),
        ("Dentist", "2026-11-12", "10:30", "11.15", "end time"),
        ("Dentist", "2026-11-12", "11:15", "11:15", "later than"),
        ("Dentist", "2026-11-12", "12:00", "11:15", "later than"),
    ],
)
def test_create_event_rejects_invalid_data(
    title,
    event_date,
    start,
    end,
    message,
):
    with pytest.raises(ValueError, match=message):
        core.create_event(title, event_date, start, end)

    assert not core.EVENTS_FILE.exists()


def test_create_event_normalizes_short_time_inputs():
    event = core.create_event(
        "Dentist",
        "2026-11-12",
        "9:00",
        "10",
    )

    assert event.start == "09:00"
    assert event.end == "10:00"
    assert core.load_events() == [event]


def test_edit_event_rejects_invalid_interval_without_saving_changes():
    event = core.create_event("Dentist", "2026-11-12", "10:30", "11:15")

    with pytest.raises(ValueError, match="later than"):
        core.edit_event(event.id, end="10:00")

    saved_event = core.load_events()[0]
    assert saved_event.end == "11:15"
    assert saved_event.updated == event.updated


def test_list_events_filters_and_sorts_by_date_and_start():
    later = core.create_event("Later", "2026-11-12", "13:00", "14:00")
    core.create_event("Earlier", "2026-11-12", "09:00", "10:00")
    other_day = core.create_event("Other day", "2026-11-13", "08:00", "09:00")
    deleted = core.create_event("Deleted", "2026-11-12", "07:00", "08:00")
    core.delete_event(deleted.id)

    assert [event.title for event in core.list_events()] == [
        "Earlier",
        "Later",
        "Other day",
    ]
    assert [
        event.title for event in core.list_events("2026-11-12")
    ] == ["Earlier", "Later"]
    assert [event.title for event in core.list_events(Date(2026, 11, 13))] == [
        other_day.title
    ]
    assert later.title == "Later"
    assert not core.TASKS_FILE.exists()


def test_day_agenda_mixes_blocks_and_events_and_omits_inactive_items(task_files):
    task = core.create_task("Task block")
    completed = core.create_task("Completed block")
    core.plan_block(task.id, "2026-11-12", "11:30", "12:00")
    core.plan_block(completed.id, "2026-11-12", "08:00", "08:30")
    core.complete_task(completed.id)
    core.create_event("Morning event", "2026-11-12", "09:00", "10:00")
    core.create_event("Afternoon event", "2026-11-12", "13:00", "13:30")
    deleted_event = core.create_event(
        "Deleted event",
        "2026-11-12",
        "07:00",
        "07:30",
    )
    core.delete_event(deleted_event.id)

    entries = core.get_day_agenda("2026-11-12")

    assert [entry["kind"] for entry in entries] == ["event", "block", "event"]
    assert [entry["event"].title if entry["kind"] == "event" else entry["task"].title
            for entry in entries] == ["Morning event", "Task block", "Afternoon event"]
    assert core.get_free_gaps(entries) == [("10:00", "11:30"), ("12:00", "13:00")]
    assert task_files.is_file()


def test_overlaps_include_task_blocks_and_events_and_can_exclude_items(task_files):
    task = core.create_task("Writing")
    block = core.plan_block(task.id, "2026-11-12", "10:00", "11:00")
    event = core.create_event("Meeting", "2026-11-12", "10:30", "11:30")
    core.create_event("Interview", "2026-11-12", "10:45", "11:15")
    core.create_event("Lunch", "2026-11-12", "12:00", "13:00")

    conflicts = core.find_overlaps("2026-11-12", "10:45", "11:15")

    assert core.has_overlap("2026-11-12", "10:45", "11:15")
    assert [(entry["kind"], entry["task"].title if entry["kind"] == "block"
             else entry["event"].title) for entry in conflicts] == [
        ("block", "Writing"),
        ("event", "Meeting"),
        ("event", "Interview"),
    ]
    remaining_after_block_exclusion = core.find_overlaps(
        "2026-11-12",
        "10:00",
        "11:00",
        exclude_block_id=block.id,
    )
    assert [
        (entry["kind"], entry["event"].title)
        for entry in remaining_after_block_exclusion
    ] == [
        ("event", "Meeting"),
        ("event", "Interview"),
    ]
    remaining_after_event_exclusion = core.find_overlaps(
        "2026-11-12",
        "10:30",
        "11:30",
        exclude_event_id=event.id,
    )
    assert [
        (
            entry["kind"],
            entry["task"].title if entry["kind"] == "block" else entry["event"].title,
        )
        for entry in remaining_after_event_exclusion
    ] == [
        ("block", "Writing"),
        ("event", "Interview"),
    ]
    assert core.has_overlap("2026-11-12", "12:30", "13:15")
    assert task_files.is_file()


def test_missing_events_file_is_treated_as_empty():
    assert not core.EVENTS_FILE.exists()
    assert core.load_events() == []
    assert core.list_events() == []
    assert core.get_day_agenda("2026-11-12") == []


def test_atomic_task_save_keeps_previous_json_in_backup(task_files):
    task = core.create_task("Original")
    original_json = task_files.read_text(encoding="utf-8")

    core.edit_task(task.id, "Updated")

    backup_path = task_files.with_name(f"{task_files.name}.bak")
    assert task_files.is_file()
    assert json.loads(task_files.read_text(encoding="utf-8"))[0]["title"] == "Updated"
    assert backup_path.read_text(encoding="utf-8") == original_json
    assert not list(task_files.parent.glob(f".{task_files.name}.*.tmp"))


def test_atomic_event_save_keeps_previous_json_in_backup():
    event = core.create_event("Original event", "2026-11-12", "10:00", "11:00")
    original_json = core.EVENTS_FILE.read_text(encoding="utf-8")

    core.edit_event(event.id, title="Updated event")

    backup_path = core.EVENTS_FILE.with_name(f"{core.EVENTS_FILE.name}.bak")
    assert json.loads(core.EVENTS_FILE.read_text(encoding="utf-8"))[0]["title"] == "Updated event"
    assert backup_path.read_text(encoding="utf-8") == original_json
    assert not list(core.EVENTS_FILE.parent.glob(f".{core.EVENTS_FILE.name}.*.tmp"))


@pytest.mark.parametrize("data_kind", ["task", "event"])
def test_corrupt_json_reports_path_and_backup_without_overwriting(data_kind):
    path = core.TASKS_FILE if data_kind == "task" else core.EVENTS_FILE
    corrupt_contents = '[{"title": '
    path.write_text(corrupt_contents, encoding="utf-8")
    reader = core.load_tasks if data_kind == "task" else core.load_events

    with pytest.raises(ValueError) as error:
        reader()

    assert str(path) in str(error.value)
    assert "No backup exists" in str(error.value)
    assert path.read_text(encoding="utf-8") == corrupt_contents
    assert not path.with_name(f"{path.name}.bak").exists()


def test_corrupt_json_error_reports_existing_backup():
    core.TASKS_FILE.write_text("{", encoding="utf-8")
    backup_path = core.TASKS_FILE.with_name(f"{core.TASKS_FILE.name}.bak")
    backup_path.write_text("[]\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Backup available"):
        core.load_tasks()


def test_task_filtering_sorting_and_done_state():
    due_later = core.create_task(
        "Later low",
        Date(2026, 11, 12),
        "baja",
    )
    due_earlier = core.create_task(
        "Soon medium",
        Date(2026, 11, 10),
        "media",
    )
    no_due = core.create_task("No due")
    done = core.create_task("Done", Date(2026, 11, 9))
    core.set_task_done(done.id, True)

    assert [
        task.id for task in core.list_tasks_by_filter(
            "pending",
            reference_date=Date(2026, 11, 9),
        )
    ] == [due_earlier.id, due_later.id, no_due.id]
    assert [
        task.id for task in core.list_tasks_by_filter(
            "no_date",
            reference_date=Date(2026, 11, 9),
        )
    ] == [no_due.id]
    assert [
        task.id for task in core.list_tasks_by_filter(
            "done",
            reference_date=Date(2026, 11, 9),
        )
    ] == [done.id]
    assert core.set_task_done(done.id, False).done is False
    assert [
        task.id for task in core.list_tasks_by_filter(
            "today",
            reference_date=Date(2026, 11, 9),
        )
    ] == [done.id]
    assert [
        task.id for task in core.list_tasks_by_filter(
            "this_week",
            reference_date=Date(2026, 11, 9),
        )
    ] == [done.id, due_earlier.id, due_later.id]
    with pytest.raises(ValueError, match="Task filter"):
        core.list_tasks_by_filter("unsupported")


def test_edit_task_details_updates_due_and_priority():
    task = core.create_task("Initial")

    updated = core.edit_task_details(
        task.id,
        title="Updated",
        due=Date(2026, 11, 20),
        priority="alta",
    )

    assert updated.title == "Updated"
    assert updated.due == Date(2026, 11, 20)
    assert updated.priority == "alta"
    assert core.edit_task_details(task.id, due=None).due is None


def test_upcoming_events_uses_fixed_reference_date():
    core.create_event("Yesterday", "2026-11-08", "10:00", "11:00")
    today_event = core.create_event("Today", "2026-11-09", "10:00", "11:00")
    tomorrow_event = core.create_event("Tomorrow", "2026-11-10", "10:00", "11:00")

    assert [
        event.id for event in core.upcoming_events(Date(2026, 11, 9))
    ] == [today_event.id, tomorrow_event.id]


def test_agenda_timeline_inserts_free_gaps_in_order():
    task = core.create_task("Work")
    core.plan_block(task.id, "2026-11-12", "11:00", "12:00")
    core.create_event("Appointment", "2026-11-12", "09:00", "10:00")

    timeline = core.get_agenda_timeline(core.get_day_agenda("2026-11-12"))

    assert [
        (item["kind"], item.get("start"), item.get("end"))
        for item in timeline
    ] == [
        ("event", None, None),
        ("gap", "10:00", "11:00"),
        ("block", None, None),
    ]


def test_cli_agenda_shows_mixed_items_and_free_time(task_files, monkeypatch, capsys):
    task = core.create_task("Write report")
    core.plan_block(task.id, "2026-11-12", "11:00", "12:00")
    core.create_event("Dentist", "2026-11-12", "09:00", "10:00")
    def fixed_input(prompt):
        assert prompt.startswith("Agenda date")
        return "2026-11-12"

    monkeypatch.setattr("builtins.input", fixed_input)

    cli.display_day_agenda()

    output = capsys.readouterr().out
    assert "[E] Dentist" in output
    assert "[T] Write report" in output
    assert "Free time: 10:00-11:00" in output
    assert task_files.is_file()


def test_cli_warns_about_event_overlap_and_asks_for_confirmation(
    task_files,
    monkeypatch,
    capsys,
):
    task = core.create_task("Work session")
    core.plan_block(task.id, "2026-11-12", "10:00", "11:00")
    answers = iter(
        [
            "Dentist",
            "2026-11-12",
            "10",
            "11:30",
            "",
            "",
            "y",
        ]
    )
    prompts = []

    def fake_input(prompt):
        prompts.append(prompt)
        return next(answers)

    monkeypatch.setattr("builtins.input", fake_input)

    cli.create_event()

    output = capsys.readouterr().out
    assert 'task "Work session"' in output
    assert any("Create it anyway?" in prompt for prompt in prompts)
    events = core.list_events()
    assert [event.title for event in events] == ["Dentist"]
    assert events[0].start == "10:00"
    assert task_files.is_file()


def test_cli_menu_includes_event_actions(capsys):
    cli.display_menu()

    output = capsys.readouterr().out
    assert "Add event" in output
    assert "Edit event" in output
    assert "Delete event" in output


def test_daily_weekly_and_monthly_recurrence_dates():
    daily = core.recurrence_rules.occurrence_dates(
        Date(2026, 11, 9),
        {"freq": "daily", "interval": 2, "count": 4},
        Date(2026, 11, 9),
        Date(2026, 11, 20),
    )
    weekly = core.recurrence_rules.occurrence_dates(
        Date(2026, 11, 9),
        {
            "freq": "weekly",
            "interval": 2,
            "weekdays": ["mon", "wed"],
        },
        Date(2026, 11, 9),
        Date(2026, 11, 30),
    )
    monthly = core.recurrence_rules.occurrence_dates(
        Date(2026, 1, 31),
        {"freq": "monthly", "interval": 1, "count": 4},
        Date(2026, 1, 1),
        Date(2026, 4, 30),
    )

    assert daily == [
        Date(2026, 11, 9),
        Date(2026, 11, 11),
        Date(2026, 11, 13),
        Date(2026, 11, 15),
    ]
    assert weekly == [
        Date(2026, 11, 9),
        Date(2026, 11, 11),
        Date(2026, 11, 23),
        Date(2026, 11, 25),
    ]
    assert monthly == [
        Date(2026, 1, 31),
        Date(2026, 2, 28),
        Date(2026, 3, 31),
        Date(2026, 4, 30),
    ]


def test_recurrence_until_count_and_validation():
    until_dates = core.recurrence_rules.occurrence_dates(
        Date(2026, 11, 9),
        {"freq": "daily", "interval": 2, "until": "2026-11-15"},
        Date(2026, 11, 9),
        Date(2026, 11, 20),
    )
    count_dates = core.recurrence_rules.occurrence_dates(
        Date(2026, 11, 9),
        {"freq": "daily", "interval": 1, "count": 3},
        Date(2026, 11, 9),
        Date(2026, 11, 20),
    )

    assert until_dates[-1] == Date(2026, 11, 15)
    assert len(count_dates) == 3
    with pytest.raises(ValueError, match="cannot be used together"):
        core.validate_recurrence(
            {"freq": "daily", "until": "2026-11-12", "count": 3},
            Date(2026, 11, 9),
        )
    with pytest.raises(ValueError, match="at least 1"):
        core.validate_recurrence(
            {"freq": "daily", "interval": 0},
            Date(2026, 11, 9),
        )
    with pytest.raises(ValueError, match="later than"):
        core.validate_recurrence(
            {"freq": "daily", "until": "2026-11-09"},
            Date(2026, 11, 9),
        )


def test_event_occurrences_apply_skips_and_overrides():
    event = core.create_event(
        "Class",
        "2026-11-09",
        "10:00",
        "11:00",
        recurrence={
            "freq": "weekly",
            "weekdays": ["mon", "wed"],
            "skipped": ["2026-11-11"],
            "overrides": {
                "2026-11-16": {
                    "date": "2026-11-17",
                    "title": "Rescheduled class",
                    "start": "11:00",
                    "end": "12:00",
                }
            },
        },
    )

    result = core.occurrences(
        event,
        Date(2026, 11, 9),
        Date(2026, 11, 18),
    )

    assert [(item.date, item.title, item.start) for item in result] == [
        (Date(2026, 11, 9), "Class", "10:00"),
        (Date(2026, 11, 17), "Rescheduled class", "11:00"),
        (Date(2026, 11, 18), "Class", "10:00"),
    ]
    assert all(item.id == event.id and item.recurring for item in result)


def test_event_occurrence_scopes_edit_delete_and_split_series():
    event = core.create_event(
        "Class",
        "2026-11-09",
        "10:00",
        "11:00",
        recurrence={"freq": "daily"},
    )
    core.edit_event(
        event.id,
        scope="this",
        occurrence_date="2026-11-10",
        start="11:00",
        end="12:00",
    )
    core.delete_event(
        event.id,
        scope="this",
        occurrence_date="2026-11-11",
    )
    split = core.edit_event(
        event.id,
        scope="this_and_future",
        occurrence_date="2026-11-12",
        title="New class time",
        start="13:00",
        end="14:00",
    )

    original = core.get_event(event.id)
    assert original.recurrence["until"] == "2026-11-11"
    assert [
        (item.date, item.start)
        for item in core.list_events("2026-11-09", "2026-11-13")
    ] == [
        (Date(2026, 11, 9), "10:00"),
        (Date(2026, 11, 10), "11:00"),
        (Date(2026, 11, 12), "13:00"),
        (Date(2026, 11, 13), "13:00"),
    ]
    assert split.id != event.id
    assert split.date == Date(2026, 11, 12)

    core.delete_event(
        split.id,
        scope="this_and_future",
        occurrence_date="2026-11-13",
    )
    assert [
        item.date for item in core.list_events("2026-11-12", "2026-11-14")
    ] == [Date(2026, 11, 12)]


def test_editing_all_scope_updates_the_series():
    event = core.create_event(
        "Class",
        "2026-11-09",
        "10:00",
        "11:00",
        recurrence={"freq": "daily"},
    )
    updated = core.edit_event(event.id, scope="all", title="Lecture")

    assert updated.title == "Lecture"
    assert [
        item.title for item in core.list_events("2026-11-10", "2026-11-11")
    ] == ["Lecture", "Lecture"]


def test_recurring_events_are_in_agenda_gaps_and_overlap_detection():
    task = core.create_task("Follow-up")
    core.plan_block(task.id, "2026-11-11", "11:30", "12:00")
    core.create_event(
        "Class",
        "2026-11-09",
        "10:00",
        "11:00",
        recurrence={"freq": "weekly", "weekdays": ["mon", "wed"]},
    )

    agenda = core.get_day_agenda("2026-11-11")

    assert [entry["kind"] for entry in agenda] == ["event", "block"]
    assert agenda[0]["event"].title == "Class"
    assert core.get_free_gaps(agenda) == [("11:00", "11:30")]
    assert core.find_overlaps("2026-11-11", "10:30", "11:30")[0]["kind"] == "event"


def test_recurring_event_overlap_check_finds_future_occurrences():
    task = core.create_task("Busy Wednesday")
    core.plan_block(task.id, "2026-11-18", "10:30", "11:30")

    overlaps = core.find_event_occurrence_overlaps(
        "Class",
        "2026-11-09",
        "10:00",
        "11:00",
        None,
        None,
        {"freq": "weekly", "weekdays": ["mon", "wed"]},
        Date(2026, 11, 9),
        Date(2026, 11, 25),
    )

    assert len(overlaps) == 1
    assert overlaps[0][0] == Date(2026, 11, 18)
    assert overlaps[0][1]["task"].title == "Busy Wednesday"


def test_completing_recurring_task_creates_next_without_blocks():
    task = core.create_task(
        "Pay rent",
        Date(2026, 11, 9),
        "alta",
        {"freq": "weekly", "weekdays": ["mon", "wed"], "count": 3},
    )
    core.plan_block(task.id, "2026-11-09", "10:00", "11:00")

    core.complete_task(task.id, Date(2026, 11, 9))
    after_first = core.load_tasks()
    next_task = next(item for item in after_first if item.id != task.id)
    assert next_task.due == Date(2026, 11, 11)
    assert next_task.blocks == []
    assert next_task.series_id == task.series_id
    assert next_task.title == task.title
    assert next_task.priority == "alta"

    core.complete_task(next_task.id, Date(2026, 11, 11))
    third_task = next(
        item for item in core.load_tasks()
        if item.id not in {task.id, next_task.id}
    )
    assert third_task.due == Date(2026, 11, 16)
    core.complete_task(third_task.id, Date(2026, 11, 16))
    assert len(core.load_tasks()) == 3


def test_recurring_task_stops_at_until_date():
    task = core.create_task(
        "Daily task",
        Date(2026, 11, 9),
        recurrence={"freq": "daily", "until": "2026-11-11"},
    )

    core.complete_task(task.id, Date(2026, 11, 9))
    next_task = next(item for item in core.load_tasks() if item.id != task.id)
    assert next_task.due == Date(2026, 11, 10)

    core.complete_task(next_task.id, Date(2026, 11, 10))
    last_task = next(item for item in core.load_tasks() if item.id not in {task.id, next_task.id})
    assert last_task.due == Date(2026, 11, 11)
    core.complete_task(last_task.id, Date(2026, 11, 11))
    assert len(core.load_tasks()) == 3


def test_monthly_task_completion_keeps_series_day_and_clamps_short_months():
    task = core.create_task(
        "Pay rent",
        Date(2026, 1, 31),
        recurrence={"freq": "monthly", "count": 3},
    )

    core.complete_task(task.id, Date(2026, 1, 31))
    february_task = next(item for item in core.load_tasks() if item.id != task.id)
    assert february_task.due == Date(2026, 2, 28)

    core.complete_task(february_task.id, Date(2026, 2, 28))
    march_task = next(
        item for item in core.load_tasks()
        if item.id not in {task.id, february_task.id}
    )
    assert march_task.due == Date(2026, 3, 31)


def test_late_recurring_task_moves_next_due_into_future():
    task = core.create_task(
        "Daily review",
        Date(2026, 11, 1),
        recurrence={"freq": "daily"},
    )

    core.complete_task(task.id, Date(2026, 11, 9))

    next_task = next(item for item in core.load_tasks() if item.id != task.id)
    assert next_task.due == Date(2026, 11, 10)


def test_old_task_and_event_without_recurrence_still_load(task_files):
    task_files.write_text(
        '[{"id":"old","title":"Old task","done":false,'
        '"created":"2026-11-09T10:00:00","updated":"2026-11-09T10:00:00",'
        '"deleted":false,"due":null,"priority":"media","blocks":[]}]',
        encoding="utf-8",
    )
    event = core.create_event("Old event", "2026-11-12", "10:00", "11:00")

    assert core.load_tasks()[0].recurrence is None
    assert core.load_events()[0].recurrence is None
    assert core.occurrences(
        event, Date(2026, 11, 12), Date(2026, 11, 12)
    )[0].date == Date(2026, 11, 12)


@pytest.mark.parametrize(
    ("value", "first_weekday", "expected"),
    [
        (Date(2026, 11, 9), "mon", Date(2026, 11, 9)),
        (Date(2026, 11, 15), "mon", Date(2026, 11, 9)),
        (Date(2026, 11, 9), "sun", Date(2026, 11, 8)),
        (Date(2027, 1, 1), "mon", Date(2026, 12, 28)),
        (Date(2027, 1, 1), "sun", Date(2026, 12, 27)),
        (Date(2026, 3, 1), "sun", Date(2026, 3, 1)),
    ],
)
def test_week_start(value, first_weekday, expected):
    assert core.week_start(value, first_weekday) == expected


def test_week_start_rejects_invalid_values():
    with pytest.raises(ValueError, match="First weekday"):
        core.week_start(Date(2026, 11, 9), "tue")


def test_week_agenda_has_seven_mixed_sorted_days_and_recurring_overrides():
    task = core.create_task("Write report")
    core.plan_block(task.id, "2026-11-11", "12:00", "13:00")
    core.create_event(
        "Class",
        "2026-11-09",
        "10:00",
        "11:00",
        recurrence={
            "freq": "weekly",
            "weekdays": ["mon", "wed"],
            "skipped": ["2026-11-11"],
            "overrides": {
                "2026-11-16": {
                    "start": "11:00",
                    "end": "12:00",
                }
            },
        },
    )
    one_time = core.create_event("Meeting", "2026-11-10", "09:00", "10:00")
    done_task = core.create_task("Done", Date(2026, 11, 10))
    deleted_task = core.create_task("Deleted", Date(2026, 11, 10))
    core.plan_block(done_task.id, "2026-11-10", "08:00", "09:00")
    core.plan_block(deleted_task.id, "2026-11-10", "07:00", "08:00")
    core.complete_task(done_task.id)
    core.delete_task(deleted_task.id)
    deleted_event = core.create_event("Deleted event", "2026-11-10", "06:00", "07:00")
    core.delete_event(deleted_event.id)

    week = core.week_agenda(Date(2026, 11, 12))

    assert len(week) == 7
    assert [item["date"] for item in week] == [
        Date(2026, 11, day) for day in range(9, 16)
    ]
    tuesday = week[1]["agenda"]
    assert [item["kind"] for item in tuesday] == ["event"]
    assert tuesday[0]["event"].id == one_time.id
    assert [item["kind"] for item in week[2]["agenda"]] == ["block"]
    assert week[2]["agenda"][0]["block"].start == "12:00"
    assert week[6]["agenda"] == []


def test_week_agenda_includes_recurrence_override_on_effective_day():
    core.create_event(
        "Class",
        "2026-11-09",
        "10:00",
        "11:00",
        recurrence={
            "freq": "weekly",
            "weekdays": ["mon"],
            "overrides": {
                "2026-11-16": {
                    "date": "2026-11-18",
                    "start": "12:00",
                    "end": "13:00",
                }
            },
        },
    )

    week = core.week_agenda(Date(2026, 11, 18))

    wednesday = next(day for day in week if day["date"] == Date(2026, 11, 18))
    assert len(wednesday["agenda"]) == 1
    assert wednesday["agenda"][0]["event"].start == "12:00"
    monday = next(day for day in week if day["date"] == Date(2026, 11, 16))
    assert monday["agenda"] == []


def test_day_load_counts_overlapping_events_and_blocks_once():
    task = core.create_task("Focus")
    core.plan_block(task.id, "2026-11-10", "09:00", "11:00")
    core.create_event("Meeting", "2026-11-10", "10:00", "12:00")
    core.create_event("Lunch", "2026-11-10", "13:00", "13:30")

    assert core.day_load(Date(2026, 11, 10)) == 210
    assert core.day_load(Date(2026, 11, 11)) == 0


def test_week_summary_counts_items_minutes_and_due_tasks():
    task = core.create_task("Due Wednesday", Date(2026, 11, 11))
    block_task = core.create_task("Scheduled")
    core.plan_block(block_task.id, "2026-11-11", "10:00", "11:30")
    core.create_event("Event", "2026-11-11", "11:00", "12:00")

    summary = core.week_summary(Date(2026, 11, 11))
    wednesday = next(item for item in summary if item["date"] == Date(2026, 11, 11))

    assert len(summary) == 7
    assert wednesday["item_count"] == 2
    assert wednesday["occupied_minutes"] == 120
    assert wednesday["due_tasks"] == [task]


def test_week_due_without_block_excludes_planned_and_completed_tasks():
    unplanned = core.create_task("Unplanned", Date(2026, 11, 11))
    planned = core.create_task("Planned", Date(2026, 11, 12))
    completed = core.create_task("Completed", Date(2026, 11, 13))
    other_week = core.create_task("Next week", Date(2026, 11, 16))
    core.plan_block(planned.id, "2026-11-10", "10:00", "11:00")
    core.complete_task(completed.id)

    assert [task.id for task in core.week_due_without_block(Date(2026, 11, 11))] == [
        unplanned.id
    ]

    core.plan_block(unplanned.id, "2026-11-12", "12:00", "13:00")
    assert core.week_due_without_block(Date(2026, 11, 11)) == []
    assert other_week.id not in {
        task.id for task in core.week_due_without_block(Date(2026, 11, 11))
    }


def test_settings_default_to_monday_and_can_be_changed():
    defaults = {
        "first_weekday": "mon",
        "day_start": "09:00",
        "day_end": "18:00",
        "default_duration_minutes": 60,
        "max_candidates": 10,
    }
    assert core.load_settings() == defaults
    assert not core.SETTINGS_FILE.exists()

    expected = {**defaults, "first_weekday": "sun"}
    assert core.save_settings("sun") == expected
    assert core.load_settings() == expected
    with pytest.raises(ValueError, match="First weekday"):
        core.save_settings("fri")


def test_review_settings_are_saved_and_old_settings_get_defaults():
    core.SETTINGS_FILE.write_text('{"first_weekday": "sun"}', encoding="utf-8")

    assert core.load_settings() == {
        "first_weekday": "sun",
        "day_start": "09:00",
        "day_end": "18:00",
        "default_duration_minutes": 60,
        "max_candidates": 10,
    }
    settings = core.save_settings(
        day_start="08:30",
        day_end="17:30",
        default_duration_minutes=45,
    )

    assert settings == {
        "first_weekday": "sun",
        "day_start": "08:30",
        "day_end": "17:30",
        "default_duration_minutes": 45,
        "max_candidates": 10,
    }
    assert core.load_settings() == settings
    with pytest.raises(ValueError, match="fit within"):
        core.save_settings(default_duration_minutes=600)
    with pytest.raises(ValueError, match="max_candidates"):
        core.save_settings(max_candidates=0)
