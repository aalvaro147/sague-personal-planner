from datetime import date

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import Button, Label, ListItem, ListView, Select, Static

from planner import core
from planner.tui.screens.confirm_dialog import ConfirmDialog
from planner.tui.screens.task_detail import TaskDetailDialog
from planner.tui.screens.task_form import TaskForm


FILTERS = [
    ("Pending", "pending"),
    ("Today / overdue", "today"),
    ("This week", "this_week"),
    ("No due date", "no_date"),
    ("Done", "done"),
]
PRIORITY_LABELS = {"alta": "High", "media": "Medium", "baja": "Low"}


class TasksScreen(Screen):
    def __init__(self) -> None:
        super().__init__()
        self.filter_name = "pending"
        self.tasks: list[core.Task] = []
        self.selected_task: core.Task | None = None

    def compose(self) -> ComposeResult:
        with Horizontal(classes="top-nav"):
            yield Label("TASKS", classes="brand")
            yield Button("Agenda", id="open-agenda")
            yield Button("Week", id="open-week")
            yield Button("Events", id="open-events")
        with Horizontal(classes="filter-toolbar"):
            yield Label("Show")
            yield Select(FILTERS, value="pending", id="task-filter")
            yield Button("Add task", id="add-task", variant="primary")
            yield Static("", id="task-count", classes="status")
        yield ListView(id="task-list", initial_index=None)
        with Horizontal(classes="action-bar"):
            yield Button("Edit", id="edit-task")
            yield Button("Details", id="task-details")
            yield Button("Mark done", id="mark-done", variant="success")
            yield Button("Mark pending", id="mark-pending")
            yield Button("Delete", id="delete-task", variant="error")

    async def on_mount(self) -> None:
        await self.refresh_data()

    def on_screen_resume(self) -> None:
        self.run_worker(self.refresh_data, exclusive=True)

    async def refresh_data(self) -> None:
        try:
            self.tasks = core.list_tasks_by_filter(self.filter_name)
            self.selected_task = None
            task_list = self.query_one("#task-list", ListView)
            await task_list.clear()
            today = date.today()
            for task in self.tasks:
                status = "DONE" if task.done else "PENDING"
                due = task.due.isoformat() if task.due else "No due date"
                marker = " ↻" if task.recurrence else ""
                label = (
                    f"[{status}]  {task.title}{marker}\n"
                    f"Due: {due}  ·  Priority: "
                    f"{PRIORITY_LABELS.get(task.priority, task.priority)}  ·  "
                    f"{len(task.blocks)} block(s)"
                )
                classes = "task-row overdue" if task.due and task.due < today and not task.done else "task-row"
                await task_list.append(ListItem(Static(label), classes=classes))
            self.query_one("#task-count", Static).update(
                f"{len(self.tasks)} task(s)"
            )
        except (OSError, ValueError) as error:
            self.app.notify(str(error), title="Could not load tasks", severity="error")

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id != "task-filter" or event.value is Select.BLANK:
            return
        self.filter_name = str(event.value)
        self.run_worker(self.refresh_data, exclusive=True)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.id == "task-list" and event.index < len(self.tasks):
            self.selected_task = self.tasks[event.index]

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "open-agenda":
            self.app.switch_mode("default")
        elif button_id == "open-events":
            self.app.switch_mode("events")
        elif button_id == "open-week":
            self.app.switch_mode("week")
        elif button_id == "add-task":
            self.add_item()
        elif button_id == "edit-task":
            self.edit_item()
        elif button_id == "task-details":
            self.show_details()
        elif button_id == "mark-done":
            self.set_done(True)
        elif button_id == "mark-pending":
            self.set_done(False)
        elif button_id == "delete-task":
            self.delete_item()

    def add_item(self) -> None:
        self.app.push_screen(TaskForm(), self._after_form)

    def edit_item(self) -> None:
        task = self._selected_task()
        if task is None:
            return
        self.app.push_screen(TaskForm(task), self._after_form)

    def show_details(self) -> None:
        task = self._selected_task()
        if task is not None:
            self.app.push_screen(TaskDetailDialog(task))

    def set_done(self, done: bool) -> None:
        task = self._selected_task()
        if task is None:
            return
        try:
            previous_ids = {item.id for item in core.load_tasks()} if done else set()
            core.set_task_done(task.id, done)
        except (OSError, ValueError) as error:
            self.app.notify(str(error), title="Could not update task", severity="error")
            return
        if done and task.recurrence:
            try:
                new_instances = [
                    item
                    for item in core.load_tasks()
                    if item.id not in previous_ids
                    and item.series_id == (task.series_id or task.id)
                ]
            except (OSError, ValueError) as error:
                self.app.notify(str(error), title="Could not check task recurrence", severity="error")
            else:
                if new_instances and new_instances[0].due is not None:
                    self.app.notify(
                        f"Next task occurrence created for {new_instances[0].due.isoformat()}."
                    )
                else:
                    self.app.notify("This recurring task series has ended.")
        self.run_worker(self.refresh_data, exclusive=True)

    def delete_item(self) -> None:
        task = self._selected_task()
        if task is None:
            return
        self.app.push_screen(
            ConfirmDialog(f'Delete task "{task.title}"?', "Delete"),
            lambda confirmed: self._delete_confirmed(task, confirmed),
        )

    def _delete_confirmed(self, task: core.Task, confirmed: bool) -> None:
        if not confirmed:
            return
        try:
            core.delete_task(task.id)
        except (OSError, ValueError) as error:
            self.app.notify(str(error), title="Could not delete task", severity="error")
            return
        self.run_worker(self.refresh_data, exclusive=True)

    def _selected_task(self) -> core.Task | None:
        if self.selected_task is None:
            self.app.notify("Select a task first.", severity="warning")
        return self.selected_task

    def _after_form(self, changed: bool) -> None:
        if changed:
            self.run_worker(self.refresh_data, exclusive=True)
