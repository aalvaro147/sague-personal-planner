import asyncio
from datetime import date, timedelta
from pathlib import Path

import pytest
from textual.widgets import Button, Checkbox, DataTable, Input, Label, ListView, Sparkline, Static

from planner import core, storage
from planner.tui.app import PlannerApp
from planner.tui.screens.confirm_dialog import ConfirmDialog
from planner.tui.screens.habit_detail import HabitDetailModal
from planner.tui.screens.habit_form import HabitForm
from planner.tui.screens.habits import HabitsScreen
from planner.tui.screens.review import ReviewScreen


@pytest.fixture(autouse=True)
def isolated_planner_env(tmp_path, monkeypatch):
    data_dir = tmp_path / "planner-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("PLANNER_DATA_DIR", str(data_dir))
    monkeypatch.setattr(core, "TASKS_FILE", data_dir / "tasks.json")
    monkeypatch.setattr(core, "EVENTS_FILE", data_dir / "events.json")
    monkeypatch.setattr(core, "SETTINGS_FILE", data_dir / "settings.json")


def test_tui_create_habit_and_mark_done():
    asyncio.run(_workflow_create_habit_and_mark_done())


async def _workflow_create_habit_and_mark_done():
    app = PlannerApp()
    async with app.run_test(size=(100, 50)) as pilot:
        await pilot.pause()
        # Open habits screen via 'b'
        await pilot.press("b")
        await pilot.pause()
        assert isinstance(app.screen, HabitsScreen)

        # Press 'a' to open HabitForm
        await pilot.press("a")
        await pilot.pause()
        assert isinstance(app.screen, HabitForm)

        # Fill name
        app.screen.query_one("#habit-name", Input).value = "Read 30 minutes"
        # Save habit
        app.screen.query_one("#save", Button).press()
        await pilot.pause()

        # Returned to HabitsScreen
        assert isinstance(app.screen, HabitsScreen)
        habits = core.list_habits()
        assert len(habits) == 1
        assert habits[0]["name"] == "Read 30 minutes"
        assert habits[0]["current_streak"] == 0

        # Mark as done using key 'd'
        await pilot.press("d")
        await pilot.pause()

        # Check streak updated to 1
        habits_after = core.list_habits()
        assert habits_after[0]["current_streak"] == 1
        assert habits_after[0]["status_today"] == "done"


def test_tui_date_navigation():
    asyncio.run(_workflow_date_navigation())


async def _workflow_date_navigation():
    today = date.today()
    # Create habit started 5 days ago
    core.create_habit("Jogging", start_date=today - timedelta(days=5))

    app = PlannerApp()
    async with app.run_test(size=(100, 50)) as pilot:
        await pilot.pause()
        await pilot.press("b")
        await pilot.pause()
        assert isinstance(app.screen, HabitsScreen)

        # Cannot navigate into future: press ']' should remain today
        await pilot.press("]")
        await pilot.pause()
        assert app.screen.selected_date == today

        # Navigate to yesterday with '['
        await pilot.press("[")
        await pilot.pause()
        assert app.screen.selected_date == today - timedelta(days=1)

        # Mark yesterday as done with 'd'
        await pilot.press("d")
        await pilot.pause()

        stats = core.habit_stats(core.list_habits()[0]["id"], end_date=today)
        assert stats["total_done"] >= 1

        # Press '0' to return to today
        await pilot.press("0")
        await pilot.pause()
        assert app.screen.selected_date == today


def test_tui_habit_detail_view():
    asyncio.run(_workflow_habit_detail_view())


async def _workflow_habit_detail_view():
    today = date.today()
    # Habit with no logs
    h = core.create_habit("Floss", start_date=today)

    app = PlannerApp()
    async with app.run_test(size=(100, 50)) as pilot:
        await pilot.pause()
        await pilot.press("b")
        await pilot.pause()

        # Open detail view via Enter
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, HabitDetailModal)

        # Verify cards, heatmap and sparkline exist and rendered
        assert app.screen.query_one("#card-streak") is not None
        assert app.screen.query_one("#card-rates") is not None
        assert app.screen.query_one("#card-weekdays") is not None
        assert app.screen.query_one("#habit-heatmap", Static) is not None
        assert app.screen.query_one("#habit-sparkline", Sparkline) is not None

        # Close detail view via Escape
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, HabitsScreen)


def test_tui_overview_tab():
    asyncio.run(_workflow_overview_tab())


async def _workflow_overview_tab():
    today = date.today()
    h1 = core.create_habit("Habit 1", start_date=today - timedelta(days=5))
    h2 = core.create_habit("Habit 2", start_date=today - timedelta(days=5))
    core.set_habit_status(h1["id"], today - timedelta(days=1), "done")
    core.set_habit_status(h2["id"], today - timedelta(days=1), "missed")

    app = PlannerApp()
    async with app.run_test(size=(100, 50)) as pilot:
        await pilot.pause()
        await pilot.press("b")
        await pilot.pause()

        # Switch to Overview tab
        tabs = app.screen.query_one("#habits-tabs")
        tabs.active = "tab-overview"
        await pilot.pause()

        # Verify chart bar renders and table rows exist
        chart = str(app.screen.query_one("#overview-chart-bar", Static).render())
        assert chart is not None
        table = app.screen.query_one("#overview-table", DataTable)
        assert table.row_count == 2

        # Switch range to 7 days
        app.screen.query_one("#range-7", Button).press()
        await pilot.pause()
        assert app.screen.overview_range_days == 7

        # Switch range to 90 days
        app.screen.query_one("#range-90", Button).press()
        await pilot.pause()
        assert app.screen.overview_range_days == 90


def test_tui_close_the_day_flow_with_blocks_and_habits():
    asyncio.run(_workflow_close_the_day())


async def _workflow_close_the_day():
    today = date.today()
    # 1 task with a missed block today
    t = core.create_task("Missed task")
    core.plan_block(t.id, today.isoformat(), "08:00", "09:00")

    # 2 habits scheduled today
    h1 = core.create_habit("Read 30 minutes", start_date=today - timedelta(days=2))
    h2 = core.create_habit("Gym", days=["mon", "wed", "fri"], start_date=today - timedelta(days=10))

    app = PlannerApp()
    async with app.run_test(size=(100, 50)) as pilot:
        await pilot.pause()
        # Open Close the day with 'c'
        await pilot.press("c")
        await pilot.pause()
        assert isinstance(app.screen, ReviewScreen)

        # 1. Blocks phase: mark block leave with 'l'
        await pilot.press("l")
        await pilot.pause()

        # 2. Now entered Habits phase!
        assert app.screen.session.phase == "habits"
        # Progress shows Habits
        prog = str(app.screen.query_one("#review-progress", Label).render())
        assert "Habits" in prog

        # Mark first habit done with 'd'
        await pilot.press("d")
        await pilot.pause()

        # Next habit or finished
        if app.screen.session.phase == "habits":
            # Mark second habit excused with 'e'
            await pilot.press("e")
            await pilot.pause()

        # Flow finished: summary shown
        assert app.screen.finished is True
        final_text = str(app.screen.query_one("#review-final", Static).render())
        assert "Habits:" in final_text
        assert "done" in final_text


def test_tui_close_the_day_without_blocks():
    asyncio.run(_workflow_close_the_day_without_blocks())


async def _workflow_close_the_day_without_blocks():
    today = date.today()
    # No tasks/blocks, only 1 habit scheduled today
    core.create_habit("Daily Walk", start_date=today)

    app = PlannerApp()
    async with app.run_test(size=(100, 50)) as pilot:
        await pilot.pause()
        await pilot.press("c")
        await pilot.pause()
        assert isinstance(app.screen, ReviewScreen)

        # Starts directly in habits phase
        assert app.screen.session.phase == "habits"
        # Skip/later with 'k'
        await pilot.press("k")
        await pilot.pause()

        # Finished
        assert app.screen.finished is True
        final_text = str(app.screen.query_one("#review-final", Static).render())
        assert "Habits:" in final_text


def test_tui_close_the_day_undo_redo():
    asyncio.run(_workflow_close_the_day_undo())


async def _workflow_close_the_day_undo():
    today = date.today()
    h1 = core.create_habit("Stretching", start_date=today)
    h2 = core.create_habit("Water", start_date=today)

    app = PlannerApp()
    async with app.run_test(size=(100, 50)) as pilot:
        await pilot.pause()
        await pilot.press("c")
        await pilot.pause()
        assert isinstance(app.screen, ReviewScreen)

        # First habit: mark done with 'd'
        await pilot.press("d")
        await pilot.pause()
        assert app.screen.session.habit_index == 1

        # Undo with 'u': returns to first habit and habit_index is 0!
        await pilot.press("u")
        await pilot.pause()
        assert app.screen.session.habit_index == 0
        assert app.screen.finished is False

        # Redo with 'U': advances again to index 1
        await pilot.press("U")
        await pilot.pause()
        assert app.screen.session.habit_index == 1


def test_tui_close_the_day_catch_up_and_add_habit():
    asyncio.run(_workflow_catch_up_and_add_habit())


async def _workflow_catch_up_and_add_habit():
    today = date.today()
    # Habit created 3 days ago, unlogged yesterday
    core.create_habit("Meditation", start_date=today - timedelta(days=3))

    app = PlannerApp()
    async with app.run_test(size=(100, 50)) as pilot:
        await pilot.pause()
        await pilot.press("c")
        await pilot.pause()
        assert isinstance(app.screen, ReviewScreen)

        # Unlogged notice is visible
        msg = str(app.screen.query_one("#review-message", Static).render())
        assert "earlier" in msg and "unlogged" in msg

        # Catch up with 'c'
        await pilot.press("c")
        await pilot.pause()
        assert app.screen.session.in_catch_up is True

        # Mark catch up item done with 'd'
        await pilot.press("d")
        await pilot.pause()

        # Open HabitForm from phase via 'a'
        await pilot.press("a")
        await pilot.pause()
        assert isinstance(app.screen, HabitForm)

        # Add new habit for today
        app.screen.query_one("#habit-name", Input).value = "Drink Tea"
        app.screen.query_one("#save", Button).press()
        await pilot.pause()

        # Drink Tea added to session habits queue!
        assert any(h["name"] == "Drink Tea" for h in app.screen.session.habits)


def test_tui_narrow_terminal_responsiveness():
    asyncio.run(_workflow_narrow_terminal())


async def _workflow_narrow_terminal():
    today = date.today()
    core.create_habit("Quick Exercise", start_date=today - timedelta(days=20))

    # Narrow width (70 cols)
    app = PlannerApp()
    async with app.run_test(size=(70, 40)) as pilot:
        await pilot.pause()
        await pilot.press("b")
        await pilot.pause()
        assert isinstance(app.screen, HabitsScreen)
        assert app.screen._compact is True

        # Open detail modal in narrow mode
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, HabitDetailModal)
        assert app.screen._compact is True
