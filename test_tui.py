import asyncio
from datetime import date, timedelta

import pytest
from textual.widgets import Input, ListView, Select, Static

from planner import core
from planner.tui.app import PlannerApp
from planner.tui.screens.agenda import AgendaScreen
from planner.tui.screens.events import EventsScreen
from planner.tui.screens.event_form import EventForm
from planner.tui.screens.recurrence_scope import RecurrenceScopeDialog
from planner.tui.screens.task_form import TaskForm
from planner.tui.screens.tasks import TasksScreen
from planner.tui.screens.week import WeekScreen


@pytest.fixture(autouse=True)
def isolated_data_files(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "TASKS_FILE", tmp_path / "tasks.json")
    monkeypatch.setattr(core, "EVENTS_FILE", tmp_path / "events.json")
    monkeypatch.setattr(core, "LEGACY_TASKS_FILE", tmp_path / "legacy.jsonl")
    monkeypatch.setattr(core, "SETTINGS_FILE", tmp_path / "settings.json")


def test_app_starts_navigates_creates_and_schedules_task():
    asyncio.run(_run_app_workflow())


def test_app_uses_environment_data_directory_and_included_styles(tmp_path, monkeypatch):
    asyncio.run(_run_app_data_directory_workflow(tmp_path, monkeypatch))


async def _run_app_data_directory_workflow(tmp_path, monkeypatch):
    data_dir = tmp_path / "planner-data"
    monkeypatch.setenv("PLANNER_DATA_DIR", str(data_dir))
    app = PlannerApp()

    async with app.run_test(size=(100, 50)) as pilot:
        await pilot.pause()
        assert app.CSS_PATH.is_file()
        assert core.TASKS_FILE == data_dir / "tasks.json"
        assert core.EVENTS_FILE == data_dir / "events.json"
        core.create_task("Stored in configured folder")
        assert (data_dir / "tasks.json").is_file()


async def _run_app_workflow():
    app = PlannerApp()

    async with app.run_test(size=(100, 50)) as pilot:
        await pilot.pause()
        assert isinstance(app.screen, AgendaScreen)

        await pilot.press("t")
        await pilot.pause()
        assert isinstance(app.screen, TasksScreen)
        await pilot.press("v")
        await pilot.pause()
        assert isinstance(app.screen, EventsScreen)
        await pilot.press("t")
        await pilot.pause()
        assert isinstance(app.screen, TasksScreen)

        await pilot.press("a")
        await pilot.pause()
        assert isinstance(app.screen, TaskForm)
        app.screen.query_one("#task-title", Input).value = "Prepare demo"
        await pilot.click("#save")
        await pilot.pause()
        task = core.list_tasks()[0]
        assert task.title == "Prepare demo"

        await pilot.click("#open-agenda")
        await pilot.pause()
        assert isinstance(app.screen, AgendaScreen)
        await pilot.click("#unplanned-list")
        await pilot.press("enter")
        await pilot.pause()
        await pilot.click("#schedule-unplanned")
        await pilot.pause()
        app.screen.query_one("#block-start", Input).value = "15:00"
        app.screen.query_one("#block-end", Input).value = "16:00"
        await pilot.click("#save")
        await pilot.pause()

        agenda = core.get_day_agenda(date.today().isoformat())
        assert len(agenda) == 1
        assert agenda[0]["kind"] == "block"
        assert agenda[0]["task"].title == "Prepare demo"
        assert isinstance(app.screen, AgendaScreen)


def test_task_validation_error_stays_visible_without_closing_app():
    asyncio.run(_run_validation_workflow())


def test_add_task_from_agenda_prefills_date_and_creates_planned_block():
    asyncio.run(_run_agenda_task_workflow())


async def _run_agenda_task_workflow():
    selected_date = date(2026, 11, 12)
    planned_date = date(2026, 11, 13)
    app = PlannerApp()

    async with app.run_test(size=(110, 50)) as pilot:
        await pilot.pause()
        agenda = app.screen
        agenda.selected_date = selected_date
        await agenda.refresh_data()
        await pilot.click("#add-task")
        await pilot.pause()

        assert isinstance(app.screen, TaskForm)
        assert app.screen.query_one("#task-block-date", Input).value == selected_date.isoformat()
        assert app.screen.query_one("#task-due", Input).value == ""
        app.screen.query_one("#task-title", Input).value = "Prepare report"
        app.screen.query_one("#task-block-date", Input).value = selected_date.isoformat()
        app.screen.query_one("#task-block-start", Input).value = "18:00"
        app.screen.query_one("#task-block-end", Input).value = "19:00"
        await pilot.click("#save")
        await pilot.pause()

        assert isinstance(app.screen, AgendaScreen)
        entry = core.get_day_agenda(selected_date.isoformat())[0]
        assert entry["kind"] == "block"
        assert entry["task"].title == "Prepare report"
        assert entry["block"].start == "18:00"
        assert any(item["task"].title == "Prepare report" for item in app.screen.entries)

        await pilot.click("#add-event")
        await pilot.pause()
        assert isinstance(app.screen, EventForm)
        assert app.screen.query_one("#event-date", Input).value == selected_date.isoformat()
        await pilot.click("#cancel")
        await pilot.pause()

        await pilot.click("#add-task")
        await pilot.pause()
        assert isinstance(app.screen, TaskForm)
        app.screen.query_one("#task-title", Input).value = "Review report"
        app.screen.query_one("#task-block-date", Input).value = planned_date.isoformat()
        app.screen.query_one("#task-block-start", Input).value = "20:00"
        app.screen.query_one("#task-block-end", Input).value = "21:00"
        await pilot.click("#save")
        await pilot.pause()
        moved_date_entry = core.get_day_agenda(planned_date.isoformat())[0]
        assert moved_date_entry["task"].title == "Review report"


def test_add_task_without_times_creates_task_without_block():
    asyncio.run(_run_task_without_block_workflow())


async def _run_task_without_block_workflow():
    app = PlannerApp()

    async with app.run_test(size=(100, 50)) as pilot:
        await pilot.pause()
        await pilot.press("t")
        await pilot.pause()
        await pilot.click("#add-task")
        await pilot.pause()
        assert isinstance(app.screen, TaskForm)
        assert app.screen.query_one("#task-block-date", Input).value == ""
        app.screen.query_one("#task-title", Input).value = "Read book"
        await pilot.click("#save")
        await pilot.pause()

        task = core.list_tasks()[0]
        assert task.title == "Read book"
        assert task.blocks == []


def test_add_task_rejects_only_one_block_time_without_closing_form():
    asyncio.run(_run_partial_block_time_workflow())


async def _run_partial_block_time_workflow():
    app = PlannerApp()

    async with app.run_test(size=(100, 50)) as pilot:
        await pilot.pause()
        await pilot.press("t")
        await pilot.pause()
        await pilot.click("#add-task")
        await pilot.pause()
        assert isinstance(app.screen, TaskForm)
        app.screen.query_one("#task-title", Input).value = "Read book"
        app.screen.query_one("#task-block-start", Input).value = "10:00"
        await pilot.click("#save")
        await pilot.pause()

        error = app.screen.query_one("#task-block-end-error", Static)
        assert "Both start and end times are required" in str(error.render())
        assert isinstance(app.screen, TaskForm)
        assert core.list_tasks() == []


def test_add_task_warns_about_block_overlap_and_allows_confirmation():
    asyncio.run(_run_task_block_overlap_workflow())


async def _run_task_block_overlap_workflow():
    selected_date = date.today()
    core.create_event(
        "Appointment",
        selected_date.isoformat(),
        "10:00",
        "11:00",
    )
    app = PlannerApp()

    async with app.run_test(size=(110, 50)) as pilot:
        await pilot.pause()
        await pilot.click("#add-task")
        await pilot.pause()
        assert isinstance(app.screen, TaskForm)
        app.screen.query_one("#task-title", Input).value = "Work"
        app.screen.query_one("#task-block-date", Input).value = selected_date.isoformat()
        app.screen.query_one("#task-block-start", Input).value = "10:30"
        app.screen.query_one("#task-block-end", Input).value = "11:30"
        await pilot.click("#save")
        await pilot.pause()

        assert "event \"Appointment\"" in str(
            app.screen.query_one("#task-feedback", Static).render()
        )
        assert core.list_tasks() == []
        await pilot.click("#confirm-save")
        await pilot.pause()

        task = core.list_tasks()[0]
        assert task.title == "Work"
        assert task.blocks[0].start == "10:30"


def test_task_form_date_context_from_tasks_and_week_screens():
    asyncio.run(_run_task_form_date_context_workflow())


async def _run_task_form_date_context_workflow():
    selected_date = core.week_start(date.today()) + timedelta(days=3)
    app = PlannerApp()

    async with app.run_test(size=(160, 50)) as pilot:
        await pilot.pause()
        await pilot.press("t")
        await pilot.pause()
        await pilot.click("#add-task")
        await pilot.pause()
        assert isinstance(app.screen, TaskForm)
        assert app.screen.query_one("#task-block-date", Input).value == ""
        await pilot.click("#cancel")
        await pilot.pause()

        await pilot.press("w")
        await pilot.pause()
        assert isinstance(app.screen, WeekScreen)
        await pilot.click("#grid-heading-3")
        await pilot.pause()
        assert app.screen.selected_day == selected_date
        await pilot.click("#add-task")
        await pilot.pause()
        assert isinstance(app.screen, TaskForm)
        assert app.screen.query_one("#task-block-date", Input).value == selected_date.isoformat()


async def _run_validation_workflow():
    app = PlannerApp()

    async with app.run_test(size=(100, 50)) as pilot:
        await pilot.pause()
        await pilot.press("t")
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()
        assert isinstance(app.screen, TaskForm)

        await pilot.click("#save")
        await pilot.pause()

        error = app.screen.query_one("#task-title-error", Static)
        assert "Task title cannot be empty." in str(error.render())
        assert isinstance(app.screen, TaskForm)
        assert app.is_running


def test_event_form_warns_about_overlap_and_saves_after_confirmation():
    asyncio.run(_run_event_overlap_workflow())


async def _run_event_overlap_workflow():
    today = date.today().isoformat()
    task = core.create_task("Busy task")
    core.plan_block(task.id, today, "10:00", "11:00")
    app = PlannerApp()

    async with app.run_test(size=(100, 50)) as pilot:
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()
        assert isinstance(app.screen, EventForm)
        app.screen.query_one("#event-title", Input).value = "Appointment"
        app.screen.query_one("#event-date", Input).value = today
        app.screen.query_one("#event-start", Input).value = "10:30"
        app.screen.query_one("#event-end", Input).value = "11:30"

        await pilot.click("#save")
        await pilot.pause()

        feedback = app.screen.query_one("#event-feedback", Static)
        assert 'Busy task' in str(feedback.render())
        assert isinstance(app.screen, EventForm)
        await pilot.click("#confirm-save")
        await pilot.pause()

        assert [event.title for event in core.list_events()] == ["Appointment"]


def test_event_form_normalizes_short_time_inputs():
    asyncio.run(_run_event_time_normalization_workflow())


async def _run_event_time_normalization_workflow():
    app = PlannerApp()

    async with app.run_test(size=(100, 50)) as pilot:
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()
        assert isinstance(app.screen, EventForm)
        app.screen.query_one("#event-title", Input).value = "Dentist"
        app.screen.query_one("#event-date", Input).value = date.today().isoformat()
        app.screen.query_one("#event-start", Input).value = "9:00"
        app.screen.query_one("#event-end", Input).value = "10"

        await pilot.click("#save")
        await pilot.pause()

        event = core.list_events()[0]
        assert event.start == "09:00"
        assert event.end == "10:00"


def test_narrow_terminal_hides_sidebar_and_keeps_task_form_accessible():
    asyncio.run(_run_narrow_terminal())


async def _run_narrow_terminal():
    app = PlannerApp()

    async with app.run_test(size=(70, 24)) as pilot:
        await pilot.pause()
        assert app.screen.query_one("#agenda-sidebar").styles.display == "none"
        assert app.screen.query_one("#agenda-list").display
        await pilot.press("t")
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()

        save = app.screen.query_one("#save")
        assert save.region.y + save.region.height <= 21
        assert await pilot.click("#save")


def test_weekly_event_can_be_seen_and_deleted_for_one_occurrence():
    asyncio.run(_run_weekly_event_workflow())


async def _run_weekly_event_workflow():
    base_date = date.today()
    weekday = base_date.strftime("%a").casefold()[:3]
    app = PlannerApp()

    async with app.run_test(size=(100, 50)) as pilot:
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()
        assert isinstance(app.screen, EventForm)
        app.screen.query_one("#event-title", Input).value = "Class"
        app.screen.query_one("#event-date", Input).value = base_date.isoformat()
        app.screen.query_one("#event-start", Input).value = "10:00"
        app.screen.query_one("#event-end", Input).value = "11:00"
        app.screen.query_one("#recurrence-frequency", Select).value = "weekly"
        app.screen.query_one("#recurrence-weekdays", Input).value = weekday

        await pilot.click("#save")
        await pilot.pause()

        event = core.load_events()[0]
        first_future = base_date + timedelta(days=7)
        second_future = base_date + timedelta(days=14)
        assert core.list_events(first_future, first_future)[0].title == "Class"
        assert core.list_events(second_future, second_future)[0].title == "Class"

        await pilot.click("#agenda-date")
        app.screen.query_one("#agenda-date", Input).value = first_future.isoformat()
        await pilot.click("#jump-date")
        await pilot.pause()
        agenda_list = app.screen.query_one("#agenda-list", ListView)
        await pilot.click(agenda_list.children[0])
        await pilot.press("down")
        await pilot.press("enter")
        await pilot.pause()
        assert app.screen.selected_agenda_entry is not None
        assert app.screen.selected_agenda_entry["kind"] == "event"
        assert app.screen.selected_agenda_entry["event"].recurring
        await pilot.click("#remove-agenda-item")
        await pilot.pause()
        assert isinstance(app.screen, RecurrenceScopeDialog)
        await pilot.click("#scope-this")
        await pilot.pause()

        assert core.list_events(first_future, first_future) == []
        assert core.list_events(second_future, second_future)[0].id == event.id


def test_week_view_navigation_and_plan_due_task():
    asyncio.run(_run_week_view_workflow())


async def _run_week_view_workflow():
    today = date.today()
    week_start = core.week_start(today)
    thursday = week_start + timedelta(days=3)
    task = core.create_task("Prepare slides", thursday)
    app = PlannerApp()

    async with app.run_test(size=(160, 50)) as pilot:
        await pilot.pause()
        await pilot.press("w")
        await pilot.pause()
        assert isinstance(app.screen, WeekScreen)
        assert app.screen.query_one("#week-grid").display
        assert not app.screen.query_one("#week-compact").display

        await pilot.click("#grid-heading-3")
        await pilot.pause()
        assert app.screen.selected_day == thursday
        await pilot.press("left")
        await pilot.pause()
        assert app.screen.selected_day == thursday - timedelta(days=1)
        await pilot.press("right")
        await pilot.pause()
        assert app.screen.selected_day == thursday
        for _ in range(4):
            await pilot.press("right")
            await pilot.pause()
        assert app.screen.selected_day == week_start + timedelta(days=7)
        assert app.screen.selected_date == app.screen.selected_day
        await pilot.press("left")
        await pilot.pause()
        assert app.screen.selected_day == thursday + timedelta(days=3)
        await pilot.press("left")
        await pilot.pause()
        assert app.screen.selected_day == thursday + timedelta(days=2)
        await pilot.press("left")
        await pilot.pause()
        assert app.screen.selected_day == thursday + timedelta(days=1)
        await pilot.press("left")
        await pilot.pause()
        assert app.screen.selected_day == thursday

        selected_date = app.screen.selected_date
        await pilot.press("]")
        await pilot.pause()
        assert app.screen.selected_date == selected_date + timedelta(days=7)
        assert app.screen.selected_day == thursday + timedelta(days=7)
        await pilot.press("[")
        await pilot.pause()
        assert app.screen.selected_date == selected_date
        assert app.screen.selected_day == thursday
        await pilot.click("#week-due-list")
        await pilot.pause()
        await pilot.press("p")
        await pilot.pause()

        assert app.screen.query_one("#block-task").value == task.id
        assert app.screen.query_one("#block-date", Input).value == thursday.isoformat()
        app.screen.query_one("#block-start", Input).value = "14:00"
        app.screen.query_one("#block-end", Input).value = "15:00"
        await pilot.click("#save")
        await pilot.pause()

        week_screen = app.screen
        assert isinstance(week_screen, WeekScreen)
        assert core.get_day_agenda(thursday.isoformat())[0]["task"].id == task.id
        day_list = week_screen.query_one(
            "#grid-items-3",
            ListView,
        )
        assert len(day_list.children) == 1


def test_week_view_switches_to_vertical_compact_layout():
    asyncio.run(_run_week_compact_workflow())


async def _run_week_compact_workflow():
    app = PlannerApp()

    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause()
        await pilot.press("w")
        await pilot.pause()
        assert isinstance(app.screen, WeekScreen)
        assert not app.screen.query_one("#week-grid").display
        assert app.screen.query_one("#week-compact").display
        assert all(
            app.screen.query_one(f"#compact-panel-{index}")
            for index in range(7)
        )
