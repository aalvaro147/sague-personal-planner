import asyncio
from datetime import date, datetime, timedelta

import pytest
from textual.widgets import Button, Input, Label, Static

from planner import core, review
from planner.tui.app import PlannerApp
from planner.tui.screens.review import ReviewScreen


@pytest.fixture(autouse=True)
def isolated_data_files(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "TASKS_FILE", tmp_path / "tasks.json")
    monkeypatch.setattr(core, "EVENTS_FILE", tmp_path / "events.json")
    monkeypatch.setattr(core, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(core, "LEGACY_TASKS_FILE", tmp_path / "legacy.jsonl")


def test_plan_tomorrow_schedules_skips_and_defers_tasks():
    asyncio.run(_run_plan_tomorrow())


def test_plan_tomorrow_proposes_medium_priority_task_without_due_date():
    asyncio.run(_run_undated_task_review())


async def _run_undated_task_review():
    task = core.create_task("An undated task")
    app = PlannerApp()

    async with app.run_test(size=(120, 50)) as pilot:
        await pilot.pause()
        await pilot.press("n")
        await pilot.pause()

        assert isinstance(app.screen, ReviewScreen)
        assert len(app.screen.candidates) == 1
        assert app.screen.candidates[0]["task"].id == task.id
        assert app.screen.candidates[0]["reason"] == "unscheduled"
        assert "Reason: Unscheduled" in str(
            app.screen.query_one("#review-item", Static).render()
        )


def test_plan_tomorrow_can_show_more_unscheduled_tasks():
    asyncio.run(_run_show_more())


async def _run_show_more():
    core.save_settings(max_candidates=2)
    tasks = [core.create_task(f"Undated {index}") for index in range(5)]
    app = PlannerApp()

    async with app.run_test(size=(120, 50)) as pilot:
        await pilot.pause()
        await pilot.press("n")
        await pilot.pause()
        assert len(app.screen.candidates) == 2

        await pilot.press("k")
        await pilot.pause()
        await pilot.press("k")
        await pilot.pause()
        assert app.screen.finished
        assert app.screen.query_one("#show-more", Button).display

        await pilot.click("#show-more")
        await pilot.pause()
        assert not app.screen.finished
        assert app.screen.candidates[2]["task"].id == tasks[2].id
        assert app.screen.candidates[2]["reason"] == "unscheduled"
        assert "3 / 5" in str(
            app.screen.query_one("#review-progress", Label).render()
        )


async def _run_plan_tomorrow():
    tomorrow = date.today() + timedelta(days=1)
    core.create_task("Schedule this", tomorrow)
    core.create_task("Skip this", tomorrow)
    core.create_task("Defer this", tomorrow)
    app = PlannerApp()

    async with app.run_test(size=(120, 50)) as pilot:
        await pilot.pause()
        await pilot.press("n")
        await pilot.pause()
        assert isinstance(app.screen, ReviewScreen)
        assert app.screen.mode == "plan"
        assert "1 / 3" in str(app.screen.query_one("#review-progress", Label).render())
        assert app.screen.query_one("#review-start", Input).value == "09:00"
        assert "Fixed events: 0" in str(
            app.screen.query_one("#review-agenda", Static).render()
        )

        await pilot.press("s")
        await pilot.pause()
        await pilot.press("k")
        await pilot.pause()
        due_input = app.screen.query_one("#review-due", Input)
        due_input.value = (tomorrow + timedelta(days=5)).isoformat()
        await pilot.press("d")
        await pilot.pause()

        assert app.screen.finished
        assert "Planning complete" in str(
            app.screen.query_one("#review-final", Static).render()
        )
        assert core.load_tasks()[0].blocks[0].date == tomorrow
        assert core.load_tasks()[1].blocks == []
        assert core.load_tasks()[2].due == tomorrow + timedelta(days=5)
        assert "Schedule this" in str(
            app.screen.query_one("#review-agenda", Static).render()
        )


def test_close_day_marks_done_reschedules_and_shows_summary(monkeypatch):
    asyncio.run(_run_close_day(monkeypatch))


async def _run_close_day(monkeypatch):
    today = date.today()

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(today.year, today.month, today.day, 12, 0)

    monkeypatch.setattr(review, "datetime", FixedDateTime)
    done_task = core.create_task("Mark complete")
    move_task = core.create_task("Move forward")
    core.plan_block(done_task.id, today.isoformat(), "09:00", "10:00")
    core.plan_block(move_task.id, today.isoformat(), "10:00", "11:00")
    app = PlannerApp()

    async with app.run_test(size=(120, 50)) as pilot:
        await pilot.pause()
        await pilot.press("c")
        await pilot.pause()
        assert isinstance(app.screen, ReviewScreen)
        assert "1 / 2" in str(app.screen.query_one("#review-progress", Label).render())

        await pilot.press("m")
        await pilot.pause()
        await pilot.press("s")
        await pilot.pause()

        assert app.screen.finished
        assert core.load_tasks()[0].done is True
        moved = core.load_tasks()[1].blocks[0]
        assert moved.date == today
        assert moved.start == "12:00"
        assert moved.end == "13:00"
        summary = str(app.screen.query_one("#review-final", Static).render())
        assert "Tasks done: 1" in summary
        assert "Minutes planned: 120" in summary
        assert "Minutes completed: 60" in summary
        assert "Tasks rescheduled: 1" in summary


def test_exiting_mid_review_keeps_each_saved_decision():
    asyncio.run(_run_exit_mid_review())


async def _run_exit_mid_review():
    tomorrow = date.today() + timedelta(days=1)
    task = core.create_task("Saved before exit", tomorrow)
    app = PlannerApp()

    async with app.run_test(size=(120, 50)) as pilot:
        await pilot.pause()
        await pilot.press("n")
        await pilot.pause()
        await pilot.click("#schedule")
        await pilot.pause()
        await pilot.press("q")
        await pilot.pause()

        saved = next(item for item in core.load_tasks() if item.id == task.id)
        assert saved.blocks[0].date == tomorrow
        assert app.screen.__class__.__name__ == "AgendaScreen"


def test_review_settings_can_be_changed_from_the_flow():
    asyncio.run(_run_review_settings())


async def _run_review_settings():
    core.create_task("Use updated settings", date.today() + timedelta(days=1))
    app = PlannerApp()

    async with app.run_test(size=(120, 50)) as pilot:
        await pilot.pause()
        await pilot.press("n")
        await pilot.pause()
        await pilot.click("#review-settings")
        await pilot.pause()
        app.screen.query_one("#review-day-start", Input).value = "08:00"
        app.screen.query_one("#review-day-end", Input).value = "17:00"
        app.screen.query_one("#review-default-duration", Input).value = "45"
        app.screen.query_one("#review-max-candidates", Input).value = "5"
        await pilot.click("#save-review-settings")
        await pilot.pause()

        assert core.load_settings()["day_start"] == "08:00"
        assert core.load_settings()["day_end"] == "17:00"
        assert core.load_settings()["default_duration_minutes"] == 45
        assert core.load_settings()["max_candidates"] == 5
        assert app.screen.query_one("#review-start", Input).value == "08:00"
        assert app.screen.query_one("#review-end", Input).value == "08:45"


def test_close_day_with_no_missed_blocks_shows_clear_message():
    asyncio.run(_run_empty_close_day())


async def _run_empty_close_day():
    app = PlannerApp()
    async with app.run_test(size=(120, 50)) as pilot:
        await pilot.pause()
        await pilot.press("c")
        await pilot.pause()

        assert app.screen.finished
        assert "No pending blocks to review" in str(
            app.screen.query_one("#review-final", Static).render()
        )


def test_plan_tomorrow_explains_empty_candidates():
    asyncio.run(_run_explained_empty_plan())


async def _run_explained_empty_plan():
    tomorrow = date.today() + timedelta(days=1)
    task = core.create_task("Already scheduled")
    core.plan_block(task.id, tomorrow.isoformat(), "09:00", "10:00")
    app = PlannerApp()

    async with app.run_test(size=(120, 50)) as pilot:
        await pilot.pause()
        await pilot.press("n")
        await pilot.pause()

        assert app.screen.finished
        message = str(app.screen.query_one("#review-final", Static).render())
        assert "all 1 pending tasks already have a planned block" in message


def test_plan_tomorrow_says_when_there_are_no_pending_tasks():
    asyncio.run(_run_no_pending_plan())


async def _run_no_pending_plan():
    app = PlannerApp()

    async with app.run_test(size=(120, 50)) as pilot:
        await pilot.pause()
        await pilot.press("n")
        await pilot.pause()

        assert app.screen.finished
        assert "No pending tasks to plan" in str(
            app.screen.query_one("#review-final", Static).render()
        )


def test_plan_tomorrow_shows_existing_blocks_events_and_gaps_ordered():
    asyncio.run(_run_existing_items_ordered())


async def _run_existing_items_ordered():
    tomorrow = date.today() + timedelta(days=1)
    planned_task = core.create_task("Existing block")
    core.plan_block(planned_task.id, tomorrow.isoformat(), "10:00", "11:00")
    core.create_event(
        "Recurring team sync",
        tomorrow.isoformat(),
        "14:00",
        "15:00",
        recurrence={"freq": "weekly"},
    )
    core.create_task("Candidate task")
    app = PlannerApp()

    async with app.run_test(size=(120, 50)) as pilot:
        await pilot.pause()
        await pilot.press("n")
        await pilot.pause()

        rendered = str(app.screen.query_one("#review-agenda", Static).render())
        # Check title date format
        assert f"{tomorrow:%a %d %b}" in rendered
        # Check items with markers [T], [E], recurrence ↻
        assert "[T] Existing block" in rendered
        assert "[E] Recurring team sync ↻" in rendered
        # Check free gaps
        assert "FREE" in rendered
        # Check chronological order: 10:00 before 14:00
        idx_block = rendered.index("[T] Existing block")
        idx_event = rendered.index("[E] Recurring team sync ↻")
        assert idx_block < idx_event


def test_plan_tomorrow_recurring_events_and_skipped():
    asyncio.run(_run_recurring_and_skipped())


async def _run_recurring_and_skipped():
    tomorrow = date.today() + timedelta(days=1)
    base_date = date.today()
    core.create_event(
        "Active Standup",
        base_date.isoformat(),
        "09:30",
        "10:00",
        recurrence={"freq": "daily"},
    )
    skipped_ev = core.create_event(
        "Cancelled Sync",
        base_date.isoformat(),
        "11:00",
        "11:30",
        recurrence={"freq": "daily"},
    )
    core.delete_event(skipped_ev.id, scope="this", occurrence_date=tomorrow)
    core.create_task("Candidate task")
    app = PlannerApp()

    async with app.run_test(size=(120, 50)) as pilot:
        await pilot.pause()
        await pilot.press("n")
        await pilot.pause()

        rendered = str(app.screen.query_one("#review-agenda", Static).render())
        assert "[E] Active Standup ↻" in rendered
        assert "Cancelled Sync" not in rendered


def test_plan_tomorrow_empty_day_shows_message():
    asyncio.run(_run_empty_day_message())


async def _run_empty_day_message():
    core.create_task("Single candidate")
    app = PlannerApp()

    async with app.run_test(size=(120, 50)) as pilot:
        await pilot.pause()
        await pilot.press("n")
        await pilot.pause()

        rendered = str(app.screen.query_one("#review-agenda", Static).render())
        assert "Nothing planned for tomorrow yet" in rendered


def test_plan_tomorrow_schedule_updates_instantly_and_next_suggestion_skips():
    asyncio.run(_run_schedule_instant_update())


async def _run_schedule_instant_update():
    core.create_task("Task One")
    core.create_task("Task Two")
    app = PlannerApp()

    async with app.run_test(size=(120, 50)) as pilot:
        await pilot.pause()
        await pilot.press("n")
        await pilot.pause()

        assert app.screen.query_one("#review-start", Input).value == "09:00"
        assert app.screen.query_one("#review-end", Input).value == "10:00"

        # Schedule Task One
        await pilot.press("s")
        await pilot.pause()

        rendered = str(app.screen.query_one("#review-agenda", Static).render())
        assert "[T] Task One" in rendered
        # Task Two should be suggested after 10:00 (outside Task One's block)
        assert app.screen.query_one("#review-start", Input).value == "10:00"
        assert app.screen.query_one("#review-end", Input).value == "11:00"
        assert "10:00 - 11:00   FREE  [Suggested]" in rendered


def test_plan_tomorrow_booked_and_free_hours_summary_counts_overlaps_once():
    asyncio.run(_run_summary_overlaps_once())


async def _run_summary_overlaps_once():
    tomorrow = date.today() + timedelta(days=1)
    # Event 1: 10:00 - 12:00 (2h)
    # Event 2: 11:00 - 13:00 (2h, overlapping 11:00-12:00)
    # Overlap counted once -> 10:00 to 13:00 = 3h booked, 6h free (in 09:00-18:00)
    core.create_event("Event A", tomorrow.isoformat(), "10:00", "12:00")
    core.create_event("Event B", tomorrow.isoformat(), "11:00", "13:00")
    core.create_task("Candidate")
    app = PlannerApp()

    async with app.run_test(size=(120, 50)) as pilot:
        await pilot.pause()
        await pilot.press("n")
        await pilot.pause()

        rendered = str(app.screen.query_one("#review-agenda", Static).render())
        assert "3h booked · 6h free" in rendered
        assert "[!] overlaps with" in rendered or "[!]" in rendered
        assert "Warning: 1 overlap(s) in this agenda." in rendered


def test_plan_tomorrow_suggested_slot_marked_and_edited_preview_warns_collision():
    asyncio.run(_run_suggested_slot_and_collision_preview())


async def _run_suggested_slot_and_collision_preview():
    tomorrow = date.today() + timedelta(days=1)
    core.create_event("Team Meeting", tomorrow.isoformat(), "11:00", "12:00")
    core.create_task("Write Specs")
    app = PlannerApp()

    async with app.run_test(size=(120, 50)) as pilot:
        await pilot.pause()
        await pilot.press("n")
        await pilot.pause()

        rendered = str(app.screen.query_one("#review-agenda", Static).render())
        # Suggested slot marked in the panel
        assert "[Suggested]" in rendered
        assert "09:00 - 10:00   FREE  [Suggested]" in rendered

        # Now edit times to collide with Team Meeting (11:00 - 12:00)
        start_input = app.screen.query_one("#review-start", Input)
        end_input = app.screen.query_one("#review-end", Input)
        start_input.value = "11:30"
        end_input.value = "12:30"
        await pilot.pause()

        # Check preview shows collision and indicates what it collides with
        rendered = str(app.screen.query_one("#review-agenda", Static).render())
        assert '[?] 11:30 - 12:30   [T] Write Specs  [!] overlaps with event "Team Meeting"' in rendered
        # Status message also warns
        message = str(app.screen.query_one("#review-message", Static).render())
        assert 'overlaps with event "Team Meeting"' in message


def test_plan_tomorrow_compact_mode_on_narrow_terminal():
    asyncio.run(_run_compact_mode())


async def _run_compact_mode():
    tomorrow = date.today() + timedelta(days=1)
    core.create_event("Short Event", tomorrow.isoformat(), "10:00", "11:00")
    core.create_task("Candidate")
    app = PlannerApp()

    async with app.run_test(size=(75, 30)) as pilot:
        await pilot.pause()
        await pilot.press("n")
        await pilot.pause()

        layout = app.screen.query_one("#review-layout")
        sidebar = app.screen.query_one("#review-sidebar")
        main = app.screen.query_one("#review-main")

        assert layout.has_class("compact")
        # Sidebar is placed before main (above the card)
        assert list(layout.children).index(sidebar) < list(layout.children).index(main)

        rendered = str(app.screen.query_one("#review-agenda", Static).render())
        # Compact format: time and title
        assert "10:00-11:00 [E] Short Event" in rendered
        assert "1h booked · 8h free" in rendered
        assert "Free" in rendered


def test_plan_tomorrow_open_agenda_shortcut():
    asyncio.run(_run_open_agenda_shortcut())


async def _run_open_agenda_shortcut():
    tomorrow = date.today() + timedelta(days=1)
    core.create_task("Quick Task")
    app = PlannerApp()

    async with app.run_test(size=(120, 50)) as pilot:
        await pilot.pause()
        await pilot.press("n")
        await pilot.pause()

        # Skip the candidate to finish
        await pilot.press("k")
        await pilot.pause()

        assert app.screen.finished
        open_agenda_btn = app.screen.query_one("#open-agenda", Button)
        assert open_agenda_btn.display

        # Click Open agenda
        await pilot.click("#open-agenda")
        await pilot.pause()

        from planner.tui.screens.agenda import AgendaScreen
        assert isinstance(app.screen, AgendaScreen)
        assert app.screen.selected_date == tomorrow

