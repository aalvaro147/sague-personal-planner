from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import Button, Label, ListItem, ListView, Select, Static

from planner import core
from planner.tui.screens.confirm_dialog import ConfirmDialog
from planner.tui.screens.note_detail import NoteDetailModal
from planner.tui.screens.note_form import NoteForm


class NotesScreen(Screen):
    """Main screen for browsing, filtering, and managing notes."""

    BINDINGS = [
        ("a", "add_item", "Add note"),
        ("e", "edit_item", "View/Edit"),
        ("p", "toggle_pin", "Pin/Unpin"),
        ("x", "toggle_archive", "Archive/Unarchive"),
        ("d", "delete_item", "Delete"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.notes: list[dict[str, Any]] = []
        self.selected_note: dict[str, Any] | None = None
        self.selected_project_id: str | None = None
        self.selected_tag: str | None = None
        self.show_archived: bool = False

    def compose(self) -> ComposeResult:
        with Horizontal(classes="top-nav"):
            yield Label("NOTES", classes="brand")
            yield Button("Agenda", id="open-agenda")
            yield Button("Week", id="open-week")
            yield Button("Tasks", id="open-tasks")
            yield Button("Events", id="open-events")
            yield Button("Undo", id="undo")
            yield Button("Redo", id="redo")

        with Horizontal(classes="filter-toolbar"):
            yield Label("Project:")
            yield Select([("All projects", "")], value="", id="filter-project")
            yield Label("Tag:")
            yield Select([("All tags", "")], value="", id="filter-tag")
            yield Button("Show archived", id="toggle-archived")
            yield Button("New note", id="add-note", variant="primary")
            yield Static("", id="notes-count", classes="status")

        yield ListView(id="note-list", initial_index=None)

        with Horizontal(classes="action-bar"):
            yield Button("View / Edit", id="view-note")
            yield Button("Pin / Unpin", id="pin-note")
            yield Button("Archive / Unarchive", id="archive-note")
            yield Button("Delete", id="delete-note", variant="error")

    async def on_mount(self) -> None:
        self._update_filters()
        await self.refresh_data()

    def on_screen_resume(self) -> None:
        self._update_filters()
        self.run_worker(self.refresh_data, exclusive=True)

    def _update_filters(self) -> None:
        projects = core.list_projects()
        proj_options = [("All projects", "")] + [(p["name"], p["id"]) for p in projects]
        proj_select = self.query_one("#filter-project", Select)
        proj_select.set_options(proj_options)

        tags = core.list_tags(kind="note")
        tag_options = [("All tags", "")] + [(f"#{t['tag']} ({t['count']})", t["tag"]) for t in tags]
        tag_select = self.query_one("#filter-tag", Select)
        tag_select.set_options(tag_options)

    async def refresh_data(self) -> None:
        try:
            self.notes = core.list_notes(
                project_id=self.selected_project_id,
                tag=self.selected_tag,
                archived=self.show_archived,
            )
            self.selected_note = None
            note_list = self.query_one("#note-list", ListView)
            await note_list.clear()

            for note in self.notes:
                title = note.get("title") or note.get("preview") or "Untitled Note"
                pinned_badge = "[PINNED] " if note.get("pinned") else ""
                archived_badge = "[ARCHIVED] " if note.get("archived") else ""
                date_str = note.get("date", "")
                proj_name = f" · {note['project_name']}" if note.get("project_name") else ""
                tags_str = " · " + " ".join(f"#{t}" for t in note.get("tags", [])) if note.get("tags") else ""

                label = f"{pinned_badge}{archived_badge}{title}\nDate: {date_str}{proj_name}{tags_str}"
                classes = "note-row pinned" if note.get("pinned") else "note-row"
                await note_list.append(ListItem(Static(label), classes=classes))

            self.query_one("#notes-count", Static).update(f"{len(self.notes)} note(s)")
        except (OSError, ValueError) as error:
            self.app.notify(str(error), title="Could not load notes", severity="error")

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "filter-project":
            val = str(event.value) if event.value not in ("", Select.BLANK) else None
            self.selected_project_id = val
            self.run_worker(self.refresh_data, exclusive=True)
        elif event.select.id == "filter-tag":
            val = str(event.value) if event.value not in ("", Select.BLANK) else None
            self.selected_tag = val
            self.run_worker(self.refresh_data, exclusive=True)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.id == "note-list" and event.index < len(self.notes):
            self.selected_note = self.notes[event.index]
            self.action_edit_item()

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.list_view.id == "note-list" and event.index is not None and event.index < len(self.notes):
            self.selected_note = self.notes[event.index]

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "open-agenda":
            self.app.switch_mode("default")
        elif bid == "open-week":
            self.app.switch_mode("week")
        elif bid == "open-tasks":
            self.app.switch_mode("tasks")
        elif bid == "open-events":
            self.app.switch_mode("events")
        elif bid == "toggle-archived":
            self.show_archived = not self.show_archived
            event.button.label = "Hide archived" if self.show_archived else "Show archived"
            self.run_worker(self.refresh_data, exclusive=True)
        elif bid == "add-note":
            self.action_add_item()
        elif bid == "view-note":
            self.action_edit_item()
        elif bid == "pin-note":
            self.action_toggle_pin()
        elif bid == "archive-note":
            self.action_toggle_archive()
        elif bid == "delete-note":
            self.action_delete_item()

    def action_add_item(self) -> None:
        self.app.push_screen(NoteForm(), self._on_form_closed)

    def action_edit_item(self) -> None:
        if not self.selected_note:
            self.app.notify("Select a note first.", severity="warning")
            return
        self.app.push_screen(
            NoteDetailModal(self.selected_note["id"]),
            self._on_detail_closed,
        )

    def _on_form_closed(self, result: bool) -> None:
        if result:
            self._update_filters()
            self.run_worker(self.refresh_data, exclusive=True)

    def _on_detail_closed(self, result: bool) -> None:
        self._update_filters()
        self.run_worker(self.refresh_data, exclusive=True)

    def action_toggle_pin(self) -> None:
        if not self.selected_note:
            self.app.notify("Select a note first.", severity="warning")
            return
        try:
            new_pinned = not self.selected_note.get("pinned", False)
            core.pin_note(self.selected_note["id"], pinned=new_pinned)
            self.run_worker(self.refresh_data, exclusive=True)
        except ValueError as e:
            self.app.notify(str(e), severity="warning")

    def action_toggle_archive(self) -> None:
        if not self.selected_note:
            self.app.notify("Select a note first.", severity="warning")
            return
        try:
            new_archived = not self.selected_note.get("archived", False)
            core.archive_note(self.selected_note["id"], archived=new_archived)
            self.run_worker(self.refresh_data, exclusive=True)
        except ValueError as e:
            self.app.notify(str(e), severity="warning")

    def action_delete_item(self) -> None:
        if not self.selected_note:
            self.app.notify("Select a note first.", severity="warning")
            return
        title = self.selected_note.get("title") or self.selected_note.get("preview") or "this note"
        self.app.push_screen(
            ConfirmDialog(f'Delete note "{title}"?'),
            self._on_delete_confirmed,
        )

    def _on_delete_confirmed(self, confirmed: bool) -> None:
        if confirmed and self.selected_note:
            core.delete_note(self.selected_note["id"])
            self.selected_note = None
            self.run_worker(self.refresh_data, exclusive=True)

