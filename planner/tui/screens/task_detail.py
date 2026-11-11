from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Static

from planner import core


PRIORITY_LABELS = {"alta": "High", "media": "Medium", "baja": "Low"}


class TaskDetailDialog(ModalScreen[None]):
    def __init__(self, task: core.Task) -> None:
        super().__init__()
        self.task_data = task

    def compose(self) -> ComposeResult:
        task = self.task_data
        due = task.due.isoformat() if task.due else "No due date"
        state = "Done" if task.done else "Pending"
        priority = PRIORITY_LABELS.get(task.priority, task.priority)
        recurrence = (
            f"\nRepeats: {task.recurrence['freq']} every "
            f"{task.recurrence['interval']}"
            if task.recurrence
            else "\nDoes not repeat"
        )
        with Vertical(classes="dialog"):
            yield Label(
                f"{task.title}{' ↻' if task.recurrence else ''}",
                classes="dialog-title",
            )
            yield Static(
                f"Status: {state}\nPriority: {priority}\nDue: {due}{recurrence}",
                id="task-details",
            )
            yield Label("Scheduled blocks", classes="section-heading")
            if task.blocks:
                for block in sorted(task.blocks, key=lambda item: (item.date, item.start)):
                    yield Static(
                        f"{block.date.isoformat()}  {block.start}-{block.end}"
                    )
            else:
                yield Static("No scheduled blocks.")
            yield Button("Close", id="close")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "close":
            self.dismiss()
