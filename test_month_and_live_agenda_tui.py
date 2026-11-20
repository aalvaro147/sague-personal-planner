import asyncio
from datetime import date, datetime, timedelta
from unittest.mock import patch

import pytest
from textual.widgets import Button, Static

from planner import clock, core
from planner.tui.app import PlannerApp
from planner.tui.screens.agenda import AgendaScreen
from planner.tui.screens.complete_task_dialog import CompleteTaskDialog
from planner.tui.screens.month import MonthScreen
from planner.tui.screens.review import ReviewScreen
from planner.tui.screens.task_form import TaskForm
from planner.tui.screens.week import WeekScreen


@pytest.fixture(autouse=True)
def setup_test_environment(tmp_path, monkeypatch):
    data_dir = tmp_path / "planner-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("PLANNER_DATA_DIR", str(data_dir))
    monkeypatch.setattr(core, "TASKS_FILE", data_dir / "tasks.json")
    monkeypatch.setattr(core, "EVENTS_FILE", data_dir / "events.json")
    monkeypatch.setattr(core, "LEGACY_TASKS_FILE", tmp_path / "legacy.jsonl")
    monkeypatch.setattr(core, "SETTINGS_FILE", data_dir / "settings.json")
    core.configure_data_dir()
    clock.reset_clock()
    yield data_dir
    clock.reset_clock()


def test_agenda_live_view_progress_and_completion_dialog():
    asyncio.run(_run_agenda_live_view())


async def _run_agenda_live_view():
    today = date(2026, 11, 20)
    clock.set_clock(datetime(2026, 11, 20, 10, 15))

    task = core.create_task("Write report")
    b1 = core.plan_block(task.id, today.isoformat(), "09:00", "10:00")
    b2 = core.plan_block(task.id, today.isoformat(), "11:00", "12:00")
    event = core.create_event("Team Standup", today.isoformat(), "10:00", "10:30")

    app = PlannerApp()
    async with app.run_test(size=(120, 50)) as pilot:
        await pilot.pause()
        assert isinstance(app.screen, AgendaScreen)

        # Progress header should show blocks count and total time
        progress_text = str(app.screen.query_one("#agenda-progress-bar", Static).render())
        assert "0/2 blocks" in progress_text
        assert "of 2h" in progress_text

        # List should contain our items and a now line
        list_view = app.screen.query_one("#agenda-list")
        assert len(list_view.children) >= 3

        # Select first block row and toggle to done with 'x' (it has another planned block b2, so no dialog)
        target_idx1 = None
        for i, row in enumerate(app.screen.agenda_rows):
            if row.get("id") == b1.id:
                target_idx1 = i
                break
        assert target_idx1 is not None
        list_view.index = target_idx1
        app.screen.selected_agenda_entry = app.screen._find_matching_entry(app.screen.agenda_rows[target_idx1])
        await pilot.press("x")
        await pilot.pause()

        reloaded_task = core.get_task(task.id)
        assert reloaded_task.blocks[0].status == "done"
        assert not reloaded_task.done

        progress_text = str(app.screen.query_one("#agenda-progress-bar", Static).render())
        assert "1/2 blocks" in progress_text

        # Navigate to second block and press 'x'
        # Since this is the last planned block for the task, CompleteTaskDialog appears
        target_idx2 = None
        for i, row in enumerate(app.screen.agenda_rows):
            if row.get("id") == b2.id:
                target_idx2 = i
                break
        assert target_idx2 is not None
        list_view.index = target_idx2
        app.screen.selected_agenda_entry = app.screen._find_matching_entry(app.screen.agenda_rows[target_idx2])
        await pilot.press("x")
        await pilot.pause()

        assert isinstance(app.screen, CompleteTaskDialog)
        # Select "No" button: marks block done but keeps task open
        await pilot.click("#btn-no")
        await pilot.pause()

        reloaded_task2 = core.get_task(task.id)
        assert reloaded_task2.blocks[1].status == "done"
        assert not reloaded_task2.done

        # Now test capital 'X' to mark done and complete task immediately
        task2 = core.create_task("Review PRs")
        b3 = core.plan_block(task2.id, today.isoformat(), "14:00", "15:00")
        await app.screen.refresh_data()
        await pilot.pause()

        target_idx3 = None
        for i, row in enumerate(app.screen.agenda_rows):
            if row.get("id") == b3.id:
                target_idx3 = i
                break
        assert target_idx3 is not None
        list_view.index = target_idx3
        app.screen.selected_agenda_entry = app.screen._find_matching_entry(app.screen.agenda_rows[target_idx3])
        await pilot.press("X")
        await pilot.pause()

        reloaded_task3 = core.get_task(task2.id)
        assert reloaded_task3.blocks[0].status == "done"
        assert reloaded_task3.done


def test_agenda_event_cannot_be_completed_notice():
    asyncio.run(_run_agenda_event_notice())


async def _run_agenda_event_notice():
    today = date(2026, 11, 20)
    clock.set_clock(datetime(2026, 11, 20, 10, 0))
    event = core.create_event("Webinar", today.isoformat(), "10:00", "11:00")

    app = PlannerApp()
    async with app.run_test(size=(120, 50)) as pilot:
        await pilot.pause()
        list_view = app.screen.query_one("#agenda-list")
        target_idx = None
        for i, row in enumerate(app.screen.agenda_rows):
            if row.get("kind") == "event":
                target_idx = i
                break
        assert target_idx is not None
        list_view.index = target_idx
        app.screen.selected_agenda_entry = app.screen._find_matching_entry(app.screen.agenda_rows[target_idx])

        # Press 'x' on event: should trigger notification
        with patch.object(app, "notify") as mock_notify:
            await pilot.press("x")
            await pilot.pause()
            mock_notify.assert_called_with("Events can't be completed", severity="warning")


def test_close_the_day_worked_on_key_and_summary():
    asyncio.run(_run_close_the_day_worked_on())


async def _run_close_the_day_worked_on():
    today = date(2026, 11, 20)
    clock.set_clock(datetime(2026, 11, 20, 18, 0))

    # Task with missed block today
    task = core.create_task("Long Project Task")
    block = core.plan_block(task.id, today.isoformat(), "14:00", "16:00")

    app = PlannerApp()
    async with app.run_test(size=(120, 50)) as pilot:
        await pilot.pause()
        # Open Close the day screen via 'c'
        await pilot.press("c")
        await pilot.pause()
        assert isinstance(app.screen, ReviewScreen)

        # Candidate in close mode is the missed block for task
        assert len(app.screen.session.missed) == 1

        # Press 'w' for "Worked on it"
        await pilot.press("w")
        await pilot.pause()

        # Task block should now be done, but task remains pending
        reloaded = core.get_task(task.id)
        assert reloaded.blocks[0].status == "done"
        assert not reloaded.done

        # Reached summary screen: check that summary starts with 'Today: X/Y blocks done'
        summary_panel = app.screen.query_one("#review-final", Static)
        summary_text = str(summary_panel.render())
        assert "Today: 1/1 blocks done" in summary_text


def test_week_screen_shows_checkmark_for_done_blocks():
    asyncio.run(_run_week_done_blocks())


async def _run_week_done_blocks():
    today = date(2026, 11, 20)  # Friday (day index 4)
    clock.set_clock(datetime(2026, 11, 20, 12, 0))

    task = core.create_task("Draft proposal")
    b = core.plan_block(task.id, today.isoformat(), "09:00", "10:00")
    core.set_block_status(task.id, b.id, "done")

    app = PlannerApp()
    async with app.run_test(size=(120, 50)) as pilot:
        await pilot.pause()
        await pilot.press("w")
        await pilot.pause()
        assert isinstance(app.screen, WeekScreen)

        # Friday is grid-items-4
        friday_list = app.screen.query_one("#grid-items-4")
        assert len(friday_list.children) >= 1
        rendered = str(friday_list.children[0].query_one(Static).render())
        assert "✓" in rendered


def test_month_screen_navigation_and_shortcuts():
    asyncio.run(_run_month_screen_tests())


async def _run_month_screen_tests():
    today = date(2026, 11, 20)
    clock.set_clock(datetime(2026, 11, 20, 12, 0))

    t = core.create_task("Month Task")
    core.plan_block(t.id, today.isoformat(), "10:00", "12:00")
    core.create_note(title="Nov note", date=today.isoformat())

    app = PlannerApp()
    async with app.run_test(size=(120, 50)) as pilot:
        await pilot.pause()
        # Open MonthScreen with 'M' (Shift+M)
        await pilot.press("M")
        await pilot.pause()
        assert isinstance(app.screen, MonthScreen)

        # Verify selected date starts on today
        assert app.screen.selected_date == today
        side_agenda = str(app.screen.query_one("#month-sidebar-agenda", Static).render())
        assert "Month Task" in side_agenda

        # Navigate right with 'l' -> Nov 21
        await pilot.press("l")
        await pilot.pause()
        assert app.screen.selected_date == date(2026, 11, 21)

        # Jump back to today with '0'
        await pilot.press("0")
        await pilot.pause()
        assert app.screen.selected_date == today

        # Navigate month next with ']' -> Dec 20
        await pilot.press("]")
        await pilot.pause()
        assert app.screen.selected_date == date(2026, 12, 20)

        # Navigate month prev with '[' -> Nov 20
        await pilot.press("[")
        await pilot.pause()
        assert app.screen.selected_date == today

        # Press 'Enter' -> opens AgendaScreen on the selected date
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, AgendaScreen)
        assert app.screen.selected_date == today

        # Return to month screen
        await pilot.press("M")
        await pilot.pause()
        assert isinstance(app.screen, MonthScreen)

        # Press 'a' -> opens TaskForm preloaded with selected date
        await pilot.press("a")
        await pilot.pause()
        assert isinstance(app.screen, TaskForm)
