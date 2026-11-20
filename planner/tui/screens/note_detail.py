from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, ScrollableContainer
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Markdown, Static

from planner import core


class NoteDetailModal(ModalScreen[bool]):
    """Modal screen displaying note details with rendered Markdown."""

    BINDINGS = [
        ("escape", "close", "Close"),
        ("e", "edit", "Edit"),
        ("p", "toggle_pin", "Pin/Unpin"),
        ("x", "toggle_archive", "Archive/Unarchive"),
    ]

    def __init__(self, note_id: str) -> None:
        super().__init__()
        self.note_id = note_id
        self.note: dict[str, Any] = {}

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog note-detail-dialog"):
            yield Label("", id="detail-title", classes="dialog-title")
            yield Static("", id="detail-meta", classes="status")
            with ScrollableContainer(id="detail-body-container"):
                yield Markdown("", id="detail-markdown")
            with Horizontal(classes="form-actions"):
                yield Button("Edit", id="edit-note", variant="primary")
                yield Button("Pin", id="pin-note")
                yield Button("Archive", id="archive-note")
                yield Button("Close", id="close")

    def on_mount(self) -> None:
        self._load_note()

    def _load_note(self) -> None:
        try:
            self.note = core.get_note(self.note_id)
        except Exception as e:
            self.app.notify(str(e), severity="error")
            self.dismiss(False)
            return

        title_text = self.note.get("title") or self.note.get("preview") or "Untitled Note"
        if self.note.get("pinned"):
            title_text = f"[PINNED] {title_text}"
        if self.note.get("archived"):
            title_text = f"[ARCHIVED] {title_text}"
        self.query_one("#detail-title", Label).update(title_text)

        meta_parts: list[str] = [f"Date: {self.note.get('date', '')}"]
        if self.note.get("project_name"):
            meta_parts.append(f"Project: {self.note.get('project_name')}")
        if self.note.get("tags"):
            tags_str = " ".join(f"#{t}" for t in self.note.get("tags", []))
            meta_parts.append(tags_str)

        self.query_one("#detail-meta", Static).update(" · ".join(meta_parts))

        body = self.note.get("body", "")
        self.query_one("#detail-markdown", Markdown).update(body or "*No content*")

        pin_btn = self.query_one("#pin-note", Button)
        pin_btn.label = "Unpin" if self.note.get("pinned") else "Pin"

        archive_btn = self.query_one("#archive-note", Button)
        archive_btn.label = "Unarchive" if self.note.get("archived") else "Archive"

    def action_close(self) -> None:
        self.dismiss(True)

    def action_edit(self) -> None:
        from planner.tui.screens.note_form import NoteForm
        self.app.push_screen(NoteForm(note=self.note), self._on_edit_closed)

    def _on_edit_closed(self, result: bool) -> None:
        if result:
            self._load_note()

    def action_toggle_pin(self) -> None:
        try:
            new_pinned = not self.note.get("pinned", False)
            self.note = core.pin_note(self.note_id, pinned=new_pinned)
            self._load_note()
        except ValueError as err:
            self.app.notify(str(err), severity="warning")

    def action_toggle_archive(self) -> None:
        try:
            new_archived = not self.note.get("archived", False)
            self.note = core.archive_note(self.note_id, archived=new_archived)
            self._load_note()
        except ValueError as err:
            self.app.notify(str(err), severity="warning")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "close":
            self.action_close()
        elif event.button.id == "edit-note":
            self.action_edit()
        elif event.button.id == "pin-note":
            self.action_toggle_pin()
        elif event.button.id == "archive-note":
            self.action_toggle_archive()

