"""Dialog for asking whether to complete the whole task when completing its last block."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Grid, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label


class CompleteTaskDialog(ModalScreen[str]):
    """Modal dialog prompting to mark the entire task as done."""

    def __init__(self, task_title: str) -> None:
        super().__init__()
        self.task_title = task_title

    def compose(self) -> ComposeResult:
        with Vertical(id="complete-task-dialog"):
            yield Label(
                f'Mark the whole task "{self.task_title}" as done?',
                id="complete-task-prompt",
            )
            with Horizontal(id="complete-task-actions"):
                yield Button("Yes", id="btn-yes", variant="success")
                yield Button("No, just this block", id="btn-no", variant="primary")
                yield Button("Cancel", id="btn-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-yes":
            self.dismiss("yes")
        elif event.button.id == "btn-no":
            self.dismiss("no")
        elif event.button.id == "btn-cancel":
            self.dismiss("cancel")

    def action_cancel(self) -> None:
        self.dismiss("cancel")

