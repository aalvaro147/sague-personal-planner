from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, ScrollableContainer
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, Input, Label, ListItem, ListView, Static, TextArea

from planner import core
from planner.tui.screens.confirm_dialog import ConfirmDialog
from planner.tui.screens.note_detail import NoteDetailModal
from planner.tui.screens.note_form import NoteForm


class ProjectForm(ModalScreen[bool]):
    """Modal form for creating and editing a project."""

    def __init__(self, project: dict[str, Any] | None = None) -> None:
        super().__init__()
        self.project_data = project

    def compose(self) -> ComposeResult:
        p = self.project_data
        with Vertical(classes="dialog form-dialog"):
            yield Label("Edit project" if p else "New project", classes="dialog-title")
            yield Label("Project Name")
            yield Input(value=p.get("name", "") if p else "", placeholder="Project name", id="proj-name")
            yield Static("", classes="field-error", id="proj-name-error")

            yield Label("Description (optional)")
            yield Input(value=p.get("description", "") if p and p.get("description") else "", placeholder="Description", id="proj-desc")

            yield Label("Target date (YYYY-MM-DD, optional)")
            yield Input(value=p.get("target_date", "") if p and p.get("target_date") else "", placeholder="Target date", id="proj-target")
            yield Static("", classes="field-error", id="proj-target-error")

            yield Label("Notes (optional)")
            yield TextArea(p.get("notes", "") if p and p.get("notes") else "", id="proj-notes")

            yield Static("", classes="form-feedback", id="proj-feedback")
            with Horizontal(classes="form-actions"):
                yield Button("Cancel", id="cancel")
                yield Button("Save project", variant="primary", id="save")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(False)
        elif event.button.id == "save":
            self._save()

    def _save(self) -> None:
        name = self.query_one("#proj-name", Input).value.strip()
        desc = self.query_one("#proj-desc", Input).value.strip() or None
        target = self.query_one("#proj-target", Input).value.strip() or None
        notes = self.query_one("#proj-notes", TextArea).text.strip() or None

        try:
            if self.project_data is not None:
                core.edit_project(
                    self.project_data["id"],
                    name=name,
                    description=desc,
                    target_date=target,
                    notes=notes,
                )
            else:
                core.create_project(
                    name=name,
                    description=desc,
                    target_date=target,
                    notes=notes,
                )
            self.dismiss(True)
        except Exception as error:
            msg = str(error)
            field_id = "proj-name-error" if "name" in msg.casefold() else "proj-target-error" if "date" in msg.casefold() else "proj-feedback"
            w = self.query_one(f"#{field_id}", Static)
            w.update(msg)
            w.display = True


class ProjectDetailScreen(Screen):
    """Screen showing details of a project, its tasks, and its notes."""

    BINDINGS = [
        ("escape", "back", "Back"),
        ("a", "add_note", "Add note"),
        ("d", "delete_project", "Delete project"),
    ]

    def __init__(self, project_id: str) -> None:
        super().__init__()
        self.project_id = project_id
        self.project: dict[str, Any] = {}
        self.notes: list[dict[str, Any]] = []

    def compose(self) -> ComposeResult:
        with Horizontal(classes="top-nav"):
            yield Label("PROJECT DETAIL", classes="brand")
            yield Button("Back", id="btn-back")
            yield Button("Add note", id="btn-add-note", variant="primary")
            yield Button("Delete project", id="btn-delete-project", variant="error")
            yield Button("Undo", id="undo")
            yield Button("Redo", id="redo")

        with Vertical(classes="dialog"):
            yield Label("", id="project-title", classes="dialog-title")
            yield Static("", id="project-meta", classes="status")
            yield Static("", id="project-progress-label")
            yield Static("", id="project-notes-desc")

            yield Label("Project Notes", classes="section-heading")
            yield ListView(id="project-notes-list")

    async def on_mount(self) -> None:
        await self.refresh_data()

    def on_screen_resume(self) -> None:
        self.run_worker(self.refresh_data, exclusive=True)

    async def refresh_data(self) -> None:
        try:
            self.project = core.get_project(self.project_id)
            self.notes = self.project.get("notes", [])
            self.query_one("#project-title", Label).update(self.project.get("name", ""))
            meta = []
            if self.project.get("status"):
                meta.append(f"Status: {self.project['status']}")
            if self.project.get("target_date"):
                meta.append(f"Target: {self.project['target_date']}")
            self.query_one("#project-meta", Static).update(" · ".join(meta))

            progress = core.project_progress(self.project_id)
            self.query_one("#project-progress-label", Static).update(
                f"Tasks: {progress['completed']}/{progress['total']} completed ({progress['percentage']}%)"
            )

            pnotes = self.project.get("notes_text") or self.project.get("notes")
            if isinstance(pnotes, str) and pnotes:
                self.query_one("#project-notes-desc", Static).update(f"Notes:\n{pnotes}")
            else:
                self.query_one("#project-notes-desc", Static).update("")

            lv = self.query_one("#project-notes-list", ListView)
            await lv.clear()
            for n in self.notes:
                t = n.get("title") or n.get("preview") or "Untitled Note"
                await lv.append(ListItem(Static(f"{t} ({n.get('date', '')})")))
        except Exception as e:
            self.app.notify(str(e), severity="error")

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_add_note(self) -> None:
        self.app.push_screen(
            NoteForm(default_project_id=self.project_id),
            self._on_note_created,
        )

    def _on_note_created(self, result: bool) -> None:
        if result:
            self.run_worker(self.refresh_data, exclusive=True)

    def action_delete_project(self) -> None:
        pname = self.project.get("name", "this project")
        self.app.push_screen(
            ConfirmDialog(f'Delete project "{pname}"? Tasks and notes will be unassigned.'),
            self._on_delete_confirmed,
        )

    def _on_delete_confirmed(self, confirmed: bool) -> None:
        if confirmed:
            core.delete_project(self.project_id)
            self.app.notify("Project deleted.")
            self.app.pop_screen()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.id == "project-notes-list" and event.index < len(self.notes):
            note = self.notes[event.index]
            self.app.push_screen(NoteDetailModal(note["id"]), lambda _: self.run_worker(self.refresh_data, exclusive=True))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "btn-back":
            self.action_back()
        elif bid == "btn-add-note":
            self.action_add_note()
        elif bid == "btn-delete-project":
            self.action_delete_project()

