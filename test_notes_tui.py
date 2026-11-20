import asyncio
from datetime import date
from pathlib import Path

import pytest
from textual.widgets import Button, Input, ListView, Select, Static, TextArea

from planner import core
from planner.tui.app import PlannerApp
from planner.tui.screens.agenda import AgendaScreen
from planner.tui.screens.confirm_dialog import ConfirmDialog
from planner.tui.screens.note_detail import NoteDetailModal
from planner.tui.screens.note_form import NoteForm
from planner.tui.screens.notes import NotesScreen
from planner.tui.screens.projects import ProjectDetailScreen, ProjectForm
from planner.tui.screens.search import SearchModal


@pytest.fixture(autouse=True)
def isolated_planner_env(tmp_path, monkeypatch):
    data_dir = tmp_path / "planner-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("PLANNER_DATA_DIR", str(data_dir))
    monkeypatch.setattr(core, "TASKS_FILE", data_dir / "tasks.json")
    monkeypatch.setattr(core, "EVENTS_FILE", data_dir / "events.json")
    monkeypatch.setattr(core, "SETTINGS_FILE", data_dir / "settings.json")


def test_tui_create_note_from_notes_screen():
    asyncio.run(_workflow_create_note())


async def _workflow_create_note():
    app = PlannerApp()
    async with app.run_test(size=(100, 50)) as pilot:
        await pilot.pause()
        # Open notes screen via shortcut 'm'
        await pilot.press("m")
        await pilot.pause()
        assert isinstance(app.screen, NotesScreen)

        # Open NoteForm via 'a'
        await pilot.press("a")
        await pilot.pause()
        assert isinstance(app.screen, NoteForm)

        # Check default date is today
        date_input = app.screen.query_one("#note-date", Input).value
        assert date_input == date.today().isoformat()

        # Fill title and body
        app.screen.query_one("#note-title", Input).value = "Call with the landlord"
        app.screen.query_one("#note-body", TextArea).text = "- deposit back by Dec"
        await pilot.click("#save")
        await pilot.pause()

        # Check returned to NotesScreen and note is in list
        assert isinstance(app.screen, NotesScreen)
        notes = core.list_notes()
        assert len(notes) == 1
        assert notes[0]["title"] == "Call with the landlord"

        note_list = app.screen.query_one("#note-list", ListView)
        assert len(note_list.children) == 1


def test_tui_unsaved_changes_confirmation_on_cancel():
    asyncio.run(_workflow_unsaved_changes())


async def _workflow_unsaved_changes():
    note = core.create_note(title="Original", body="Original body")
    app = PlannerApp()
    async with app.run_test(size=(100, 50)) as pilot:
        await pilot.pause()
        # Push NoteForm with existing note
        form = NoteForm(note=note)
        await app.push_screen(form)
        await pilot.pause()

        # Edit body
        app.screen.query_one("#note-body", TextArea).text = "Modified unsaved body text"

        # Cancel should ask confirmation
        await pilot.click("#cancel")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmDialog)

        # Confirm discard
        await pilot.click("#confirm")
        await pilot.pause()
        # Dismissed back to previous screen
        assert not isinstance(app.screen, (ConfirmDialog, NoteForm))
        # Note content was not modified
        assert core.get_note(note["id"])["body"] == "Original body"


def test_tui_pin_and_archive_notes():
    asyncio.run(_workflow_pin_and_archive())


async def _workflow_pin_and_archive():
    n1 = core.create_note(title="Normal note", body="Body 1", date="2026-11-20")
    n2 = core.create_note(title="To pin note", body="Body 2", date="2026-11-19")
    app = PlannerApp()
    async with app.run_test(size=(100, 50)) as pilot:
        await pilot.pause()
        await pilot.press("m")
        await pilot.pause()
        assert isinstance(app.screen, NotesScreen)

        # Select second note and pin it via 'p'
        notes_screen: NotesScreen = app.screen
        notes_screen.selected_note = next(n for n in notes_screen.notes if n["id"] == n2["id"])
        notes_screen.action_toggle_pin()
        await pilot.pause()

        # Now n2 is pinned, so it appears first
        assert notes_screen.notes[0]["id"] == n2["id"]
        assert notes_screen.notes[0]["pinned"] is True

        # Archive n2 via 'x'
        notes_screen.selected_note = notes_screen.notes[0]
        notes_screen.action_toggle_archive()
        await pilot.pause()

        # By default, archived notes are hidden from the list
        assert not any(n["id"] == n2["id"] for n in notes_screen.notes)

        # Toggle "Show archived"
        await pilot.click("#toggle-archived")
        await pilot.pause()
        assert any(n["id"] == n2["id"] for n in notes_screen.notes)


def test_tui_create_note_from_today_agenda():
    asyncio.run(_workflow_agenda_notes())


async def _workflow_agenda_notes():
    app = PlannerApp()
    async with app.run_test(size=(100, 50)) as pilot:
        await pilot.pause()
        assert isinstance(app.screen, AgendaScreen)

        # Click "Add note" from agenda
        await pilot.click("#add-agenda-note")
        await pilot.pause()
        assert isinstance(app.screen, NoteForm)

        app.screen.query_one("#note-title", Input).value = "Note from agenda"
        app.screen.query_one("#note-body", TextArea).text = "Some details"
        await pilot.click("#save")
        await pilot.pause()

        assert isinstance(app.screen, AgendaScreen)
        agenda_notes = core.notes_for_day(date.today())
        assert len(agenda_notes) == 1
        assert agenda_notes[0]["title"] == "Note from agenda"

        nl = app.screen.query_one("#agenda-notes-list", ListView)
        assert len(nl.children) == 1


def test_tui_create_note_from_project_detail():
    asyncio.run(_workflow_project_detail())


async def _workflow_project_detail():
    p = core.create_project("Flat Hunting", description="Find a new apartment")
    pid = p["id"]

    app = PlannerApp()
    async with app.run_test(size=(100, 50)) as pilot:
        await pilot.pause()
        # Open ProjectDetailScreen
        proj_screen = ProjectDetailScreen(pid)
        await app.push_screen(proj_screen)
        await pilot.pause()
        assert isinstance(app.screen, ProjectDetailScreen)

        # Click Add note
        await pilot.click("#btn-add-note")
        await pilot.pause()
        assert isinstance(app.screen, NoteForm)
        # Check project is preselected
        assert app.screen.default_project_id == pid

        app.screen.query_one("#note-title", Input).value = "Apartment in Elm Street"
        app.screen.query_one("#note-body", TextArea).text = "Visited on Friday"
        await pilot.click("#save")
        await pilot.pause()

        assert isinstance(app.screen, ProjectDetailScreen)
        notes = core.get_project(pid)["notes"]
        assert len(notes) == 1
        assert notes[0]["title"] == "Apartment in Elm Street"
        assert notes[0]["project_id"] == pid


def test_tui_search_notes_and_open_detail():
    asyncio.run(_workflow_search())


async def _workflow_search():
    p = core.create_project("Move")
    core.create_note(
        title="Call with landlord",
        body="Ask about heating system deposit",
        project_id=p["id"],
    )

    app = PlannerApp()
    async with app.run_test(size=(100, 50)) as pilot:
        await pilot.pause()
        # Press '/' to open search modal
        await pilot.press("/")
        await pilot.pause()
        assert isinstance(app.screen, SearchModal)

        # Search for heating
        app.screen.query_one("#search-input", Input).value = "type:note heating"
        await pilot.pause()

        # Check search result has note with [N]
        search_list = app.screen.query_one("#search-results-list", ListView)
        assert len(search_list.children) >= 1

        # Press Enter on result to open note detail
        await pilot.click("#search-results-list")
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, NoteDetailModal)


def test_tui_delete_project_and_undo():
    asyncio.run(_workflow_delete_project_undo())


async def _workflow_delete_project_undo():
    p = core.create_project("Renovation")
    pid = p["id"]
    note = core.create_note("Paint colors", body="Blue and green", project_id=pid)

    app = PlannerApp()
    async with app.run_test(size=(100, 50)) as pilot:
        await pilot.pause()
        proj_screen = ProjectDetailScreen(pid)
        await app.push_screen(proj_screen)
        await pilot.pause()

        # Delete project
        await pilot.click("#btn-delete-project")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmDialog)
        await pilot.click("#confirm")
        await pilot.pause()

        # Project is deleted, note is unassigned
        assert core.get_note(note["id"])["project_id"] is None

        # Undo using 'u'
        await pilot.press("u")
        await pilot.pause()

        # Note is assigned back to project
        assert core.get_note(note["id"])["project_id"] == pid


def test_tui_narrow_terminal_compacts_agenda_notes():
    asyncio.run(_workflow_narrow_terminal())


async def _workflow_narrow_terminal():
    p = core.create_project("Renovation")
    core.create_note("Long Title With Project And Tags", body="Body", project_id=p["id"], tags=["home"])

    # Launch app in narrow terminal (< 90 width, e.g. 80)
    app = PlannerApp()
    async with app.run_test(size=(80, 40)) as pilot:
        await pilot.pause()
        assert isinstance(app.screen, AgendaScreen)
        agenda: AgendaScreen = app.screen

        notes_list = agenda.query_one("#agenda-notes-list", ListView)
        assert len(notes_list.children) == 1

        # In narrow mode, only the title is rendered
        item_text = str(notes_list.children[0].query_one(Static).render())
        assert "Long Title With Project And Tags" in item_text
        assert "Renovation" not in item_text
