from datetime import date
from typing import Any

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Select, Static, TextArea

from planner import clock, core
from planner.tui.screens.confirm_dialog import ConfirmDialog


class NoteForm(ModalScreen[bool]):
    """Modal screen for creating and editing notes."""

    def __init__(
        self,
        note: dict[str, Any] | None = None,
        default_date: date | None = None,
        default_project_id: str | None = None,
    ) -> None:
        super().__init__()
        self.note_data = note
        self.default_date = default_date or clock.today()
        self.default_project_id = default_project_id

        # Record initial values for unsaved change detection
        self._initial_title = note.get("title", "") if note else ""
        self._initial_body = note.get("body", "") if note else ""
        self._initial_date = note.get("date", self.default_date.isoformat()) if note else self.default_date.isoformat()
        self._initial_project = note.get("project_id") if note else default_project_id
        tags_list = note.get("tags", []) if note else []
        self._initial_tags = ", ".join(tags_list)

    def compose(self) -> ComposeResult:
        note = self.note_data
        projects = core.list_projects()
        project_options: list[tuple[str, str]] = [("No project", "")]
        for p in projects:
            project_options.append((p["name"], p["id"]))

        current_project = note.get("project_id", "") if note else (self.default_project_id or "")
        current_date_val = note.get("date", self.default_date.isoformat()) if note else self.default_date.isoformat()
        current_tags_val = ", ".join(note.get("tags", [])) if note else ""

        with Vertical(classes="dialog form-dialog"):
            yield Label("Edit note" if note else "New note", classes="dialog-title")
            yield Label("Title (optional, max 120 chars)")
            yield Input(
                value=note.get("title", "") if note else "",
                placeholder="Note title",
                id="note-title",
            )
            yield Static("", classes="field-error", id="note-title-error")

            yield Label("Date (YYYY-MM-DD, today, tomorrow, or weekday)")
            yield Input(
                value=current_date_val,
                placeholder="Date",
                id="note-date",
            )
            yield Static("", classes="field-error", id="note-date-error")

            yield Label("Project")
            yield Select(
                project_options,
                value=current_project or "",
                prompt="Select project",
                id="note-project",
            )

            yield Label("Tags (comma or space separated)")
            yield Input(
                value=current_tags_val,
                placeholder="tags, e.g. home, finance",
                id="note-tags",
            )
            yield Static("", classes="field-error", id="note-tags-error")

            yield Label("Content (Markdown supported, max 100,000 chars)")
            yield TextArea(
                note.get("body", "") if note else "",
                id="note-body",
            )
            yield Static("", classes="field-error", id="note-body-error")
            yield Static("", classes="form-feedback", id="note-feedback")

            with Horizontal(classes="form-actions"):
                yield Button("Cancel", id="cancel")
                yield Button("Save note", variant="primary", id="save")

    def _has_unsaved_changes(self) -> bool:
        cur_title = self.query_one("#note-title", Input).value.strip()
        cur_body = self.query_one("#note-body", TextArea).text
        cur_date = self.query_one("#note-date", Input).value.strip()
        cur_project_val = self.query_one("#note-project", Select).value
        cur_project = None if cur_project_val in ("", Select.BLANK) else str(cur_project_val)
        cur_tags = self.query_one("#note-tags", Input).value.strip()

        return (
            cur_title != self._initial_title.strip()
            or cur_body != self._initial_body
            or cur_date != self._initial_date
            or (cur_project or None) != (self._initial_project or None)
            or cur_tags != self._initial_tags.strip()
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            if self._has_unsaved_changes():
                self.app.push_screen(
                    ConfirmDialog("Discard unsaved changes?"),
                    self._on_discard_confirm,
                )
            else:
                self.dismiss(False)
            return

        if event.button.id == "save":
            self._save()

    def _on_discard_confirm(self, confirmed: bool) -> None:
        if confirmed:
            self.dismiss(False)

    def _save(self) -> None:
        self._clear_errors()
        title = self.query_one("#note-title", Input).value.strip()
        date_text = self.query_one("#note-date", Input).value.strip()
        project_val = self.query_one("#note-project", Select).value
        project_id = None if project_val in ("", Select.BLANK) else str(project_val)
        tags_text = self.query_one("#note-tags", Input).value.strip()
        body = self.query_one("#note-body", TextArea).text

        try:
            if self.note_data is not None:
                core.edit_note(
                    self.note_data["id"],
                    title=title,
                    body=body,
                    date=date_text,
                    project_id=project_id,
                    tags=tags_text,
                )
            else:
                core.create_note(
                    title=title,
                    body=body,
                    date=date_text,
                    project_id=project_id,
                    tags=tags_text,
                )
            self.dismiss(True)
        except (ValueError, OSError) as error:
            msg = str(error)
            field_id = (
                "note-title-error"
                if "title" in msg.casefold() and "empty" not in msg.casefold()
                else "note-body-error"
                if "body" in msg.casefold() and "empty" not in msg.casefold()
                else "note-date-error"
                if "date" in msg.casefold()
                else "note-tags-error"
                if "tag" in msg.casefold()
                else "note-feedback"
            )
            self._show_error(field_id, msg)

    def _show_error(self, field_id: str, message: str) -> None:
        widget = self.query_one(f"#{field_id}", Static)
        widget.update(message)
        widget.display = True

    def _clear_errors(self) -> None:
        for fid in ("note-title-error", "note-date-error", "note-tags-error", "note-body-error", "note-feedback"):
            widgets = self.query(f"#{fid}")
            if widgets:
                w = widgets.first()
                w.update("")
                w.display = False

