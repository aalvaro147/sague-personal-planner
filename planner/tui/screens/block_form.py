from datetime import date

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Select, Static

from planner import core


class BlockForm(ModalScreen[bool]):
    def __init__(
        self,
        task: core.Task | None = None,
        block_entry: core.BlockAgendaEntry | None = None,
        selected_date: date | None = None,
    ) -> None:
        super().__init__()
        self.task_data = task
        self.block_entry = block_entry
        self.selected_date = selected_date or date.today()
        self._pending_values: tuple[str, str, str, str] | None = None

    def compose(self) -> ComposeResult:
        tasks = core.pending_tasks()
        choices = [(task.title, task.id) for task in tasks]
        selected_task_id = (
            self.block_entry["task"].id
            if self.block_entry
            else self.task_data.id
            if self.task_data
            else choices[0][1]
            if choices
            else Select.BLANK
        )
        block = self.block_entry["block"] if self.block_entry else None
        with Vertical(classes="dialog form-dialog"):
            yield Label("Move task block" if block else "Schedule a task", classes="dialog-title")
            yield Label("Task")
            yield Select(choices, value=selected_task_id, id="block-task")
            yield Static("", classes="field-error", id="block-task-error")
            yield Label("Date (YYYY-MM-DD, today, tomorrow, or weekday)")
            yield Input(
                value=block.date.isoformat() if block else self.selected_date.isoformat(),
                placeholder="2026-11-12",
                id="block-date",
            )
            yield Static("", classes="field-error", id="block-date-error")
            yield Label("Start (HH:MM)")
            yield Input(
                value=block.start if block else "",
                placeholder="10:30",
                id="block-start",
            )
            yield Static("", classes="field-error", id="block-start-error")
            yield Label("End (HH:MM)")
            yield Input(
                value=block.end if block else "",
                placeholder="11:15",
                id="block-end",
            )
            yield Static("", classes="field-error", id="block-end-error")
            yield Static("", classes="form-feedback", id="block-feedback")
            with Horizontal(classes="form-actions"):
                yield Button("Cancel", id="cancel")
                yield Button("Save block", variant="primary", id="save")
                yield Button(
                    "Schedule anyway",
                    variant="warning",
                    id="confirm-save",
                    classes="confirm-overlap",
                )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(False)
        elif event.button.id in {"save", "confirm-save"}:
            if event.button.id == "confirm-save" and self._pending_values:
                self._save(self._pending_values)
            else:
                self._validate()

    def _validate(self) -> None:
        self._clear_errors()
        task_id = self.query_one("#block-task", Select).value
        date_text = self.query_one("#block-date", Input).value.strip()
        start = self.query_one("#block-start", Input).value.strip()
        end = self.query_one("#block-end", Input).value.strip()
        if task_id is Select.BLANK:
            self._show_message(
                "block-task-error",
                "Create a pending task before scheduling a block.",
            )
            return
        try:
            parsed_date = core.parse_date(date_text)
            overlaps = core.find_overlaps(
                parsed_date.isoformat(),
                start,
                end,
                exclude_block_id=(
                    self.block_entry["block"].id if self.block_entry else None
                ),
            )
        except ValueError as error:
            self._show_interval_error(str(error))
            return
        values = (str(task_id), parsed_date.isoformat(), start, end)
        if overlaps:
            self._pending_values = values
            descriptions = [
                f'task "{entry["task"].title}"'
                if entry["kind"] == "block"
                else f'event "{entry["event"].title}"'
                for entry in overlaps
            ]
            self._show_message(
                "block-feedback",
                f"Overlap with {', '.join(descriptions)}. Save anyway?",
            )
            self.query_one("#save", Button).display = False
            self.query_one("#confirm-save", Button).display = True
            return
        self._save(values)

    def _save(self, values: tuple[str, str, str, str]) -> None:
        task_id, date_text, start, end = values
        try:
            if self.block_entry is None:
                core.plan_block(task_id, date_text, start, end)
            else:
                core.move_block(
                    task_id,
                    self.block_entry["block"].id,
                    date_text,
                    start,
                    end,
                )
        except ValueError as error:
            self._show_interval_error(str(error))
            return
        self.dismiss(True)

    def _show_interval_error(self, message: str) -> None:
        field_id = (
            "block-date-error"
            if "date" in message.casefold()
            else "block-start-error"
            if "start" in message.casefold()
            else "block-end-error"
            if "end" in message.casefold() or "later than" in message.casefold()
            else "block-feedback"
        )
        self._show_message(field_id, message)

    def _show_message(self, field_id: str, message: str) -> None:
        widget = self.query_one(f"#{field_id}", Static)
        widget.update(message)
        widget.display = True

    def _clear_errors(self) -> None:
        for field_id in (
            "block-task-error",
            "block-date-error",
            "block-start-error",
            "block-end-error",
            "block-feedback",
        ):
            widget = self.query_one(f"#{field_id}", Static)
            widget.update("")
            widget.display = False
