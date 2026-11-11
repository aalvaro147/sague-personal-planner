from datetime import date
from typing import Any

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Collapsible, Input, Label, Select, Static

from planner import core
from planner.tui.screens.recurrence_form import (
    compose_recurrence_fields,
    read_recurrence_fields,
)


class TaskForm(ModalScreen[bool]):
    def __init__(
        self,
        task: core.Task | None = None,
        default_date: date | None = None,
    ) -> None:
        super().__init__()
        self.task_data = task
        self.default_date = default_date
        self._pending_values: dict[str, Any] | None = None

    def compose(self) -> ComposeResult:
        task = self.task_data
        with Vertical(classes="dialog form-dialog task-form-dialog"):
            yield Label("Edit task" if task else "New task", classes="dialog-title")
            yield Input(
                value=task.title if task else "",
                placeholder="Task title",
                id="task-title",
            )
            yield Static("", classes="field-error", id="task-title-error")
            yield Input(
                value=task.due.isoformat() if task and task.due else "",
                placeholder="Due date YYYY-MM-DD (blank for none)",
                id="task-due",
            )
            yield Static("", classes="field-error", id="task-due-error")
            yield Select(
                [("High", "alta"), ("Medium", "media"), ("Low", "baja")],
                value=task.priority if task else "media",
                prompt="Priority",
                id="task-priority",
            )
            yield Static("", classes="field-error", id="task-priority-error")
            with Collapsible(
                title="Repeat",
                collapsed=True,
                id="recurrence-section",
            ):
                yield from compose_recurrence_fields(task.recurrence if task else None)
            if task is None:
                with Collapsible(
                    title="Schedule a block (optional)",
                    collapsed=self.default_date is None,
                    id="task-schedule-section",
                ):
                    yield Label("Planning date (YYYY-MM-DD, today, tomorrow, or weekday)")
                    yield Input(
                        value=self.default_date.isoformat() if self.default_date else "",
                        placeholder="Used only when start and end are set",
                        id="task-block-date",
                    )
                    yield Static(
                        "Used only if you set a start and end time.",
                        classes="form-help",
                        id="task-block-date-help",
                    )
                    yield Static("", classes="field-error", id="task-block-date-error")
                    yield Label("Start (HH:MM)")
                    yield Input(placeholder="10:30", id="task-block-start")
                    yield Static("", classes="field-error", id="task-block-start-error")
                    yield Label("End (HH:MM)")
                    yield Input(placeholder="11:15", id="task-block-end")
                    yield Static("", classes="field-error", id="task-block-end-error")
            yield Static("", classes="form-feedback", id="task-feedback")
            with Horizontal(classes="form-actions"):
                yield Button("Cancel", id="cancel")
                yield Button("Save task", variant="primary", id="save")
                yield Button(
                    "Save anyway",
                    variant="warning",
                    id="confirm-save",
                    classes="confirm-overlap",
                )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(False)
            return
        if event.button.id not in {"save", "confirm-save"}:
            return
        if event.button.id == "confirm-save" and self._pending_values is not None:
            self._save(self._pending_values)
            return
        self._validate_and_save()

    def _validate_and_save(self) -> None:
        self._clear_errors()
        title = self.query_one("#task-title", Input).value
        due_text = self.query_one("#task-due", Input).value.strip()
        priority = self.query_one("#task-priority", Select).value
        try:
            due = core.parse_due_date(due_text)
            recurrence = read_recurrence_fields(
                self,
                due,
                self.task_data.recurrence if self.task_data else None,
            )
            if self.task_data is not None:
                core.edit_task_details(
                    self.task_data.id,
                    title=title,
                    due=due,
                    priority=priority,
                    recurrence=recurrence,
                )
                self.dismiss(True)
                return

            core.validate_task_fields(title, due, str(priority), recurrence)
            start = self.query_one("#task-block-start", Input).value.strip()
            end = self.query_one("#task-block-end", Input).value.strip()
            if bool(start) != bool(end):
                field_id = "task-block-end-error" if start else "task-block-start-error"
                self._show_message(
                    field_id,
                    "Both start and end times are required to schedule a block.",
                )
                return
            values: dict[str, Any] = {
                "title": title,
                "due": due,
                "priority": str(priority),
                "recurrence": recurrence,
                "block_date": None,
                "start": start,
                "end": end,
            }
            if start:
                block_date_text = self.query_one("#task-block-date", Input).value.strip()
                block_date = core.parse_date(block_date_text)
                values["block_date"] = block_date.isoformat()
                overlaps = core.find_overlaps(block_date.isoformat(), start, end)
                if overlaps:
                    self._pending_values = values
                    descriptions = [
                        f'task "{entry["task"].title}"'
                        if entry["kind"] == "block"
                        else f'event "{entry["event"].title}"'
                        for entry in overlaps
                    ]
                    self._show_message(
                        "task-feedback",
                        f"Overlap with {', '.join(descriptions)}. Save anyway?",
                    )
                    self.query_one("#save", Button).display = False
                    self.query_one("#confirm-save", Button).display = True
                    return
            self._save(values)
        except (OSError, ValueError) as error:
            message = str(error)
            field_id = (
                "task-title-error"
                if "title" in message.casefold()
                else "task-due-error"
                if "due date" in message.casefold() or "must have a date" in message.casefold()
                else "task-priority-error"
                if "priority" in message.casefold()
                else "task-block-date-error"
                if "date" in message.casefold()
                else "task-block-start-error"
                if "start" in message.casefold()
                else "task-block-end-error"
                if "end" in message.casefold() or "later than" in message.casefold()
                else "recurrence-error"
                if "recurrence" in message.casefold()
                else "task-feedback"
            )
            self._show_message(field_id, message)
            return

    def _save(self, values: dict[str, Any]) -> None:
        try:
            if values["block_date"] is None:
                core.create_task(
                    values["title"],
                    values["due"],
                    values["priority"],
                    values["recurrence"],
                )
            else:
                core.create_task_with_block(
                    values["title"],
                    values["block_date"],
                    values["start"],
                    values["end"],
                    values["due"],
                    values["priority"],
                    values["recurrence"],
                )
        except (OSError, ValueError) as error:
            self._show_message("task-feedback", str(error))
            return
        self.dismiss(True)

    def _show_message(self, field_id: str, message: str) -> None:
        if field_id == "recurrence-error":
            self.query_one("#recurrence-section", Collapsible).collapsed = False
        widget = self.query_one(f"#{field_id}", Static)
        widget.update(message)
        widget.display = True

    def _clear_errors(self) -> None:
        for field_id in (
            "task-title-error",
            "task-due-error",
            "task-priority-error",
            "task-block-date-error",
            "task-block-start-error",
            "task-block-end-error",
            "recurrence-error",
            "task-feedback",
        ):
            widgets = self.query(f"#{field_id}")
            if widgets:
                widget = widgets.first()
                widget.update("")
                widget.display = False
        save_button = self.query("#save")
        if save_button:
            save_button.first().display = True
        confirm_button = self.query("#confirm-save")
        if confirm_button:
            confirm_button.first().display = False
        self._pending_values = None
