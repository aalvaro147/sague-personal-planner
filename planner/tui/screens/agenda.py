from datetime import date, timedelta

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.events import Resize
from textual.screen import Screen
from textual.widgets import Button, Input, Label, ListItem, ListView, Static

from planner import core
from planner.tui.screens.block_form import BlockForm
from planner.tui.screens.confirm_dialog import ConfirmDialog
from planner.tui.screens.event_form import EventForm
from planner.tui.screens.recurrence_scope import RecurrenceScopeDialog
from planner.tui.screens.task_form import TaskForm

PRIORITY_LABELS = {"alta": "High", "media": "Medium", "baja": "Low"}


class AgendaScreen(Screen):
    BINDINGS = [
        ("left", "previous_day", "Previous day"),
        ("right", "next_day", "Next day"),
        ("h", "today", "Today"),
    ]

    def __init__(self, selected_date: date | None = None) -> None:
        super().__init__()
        self.selected_date = selected_date or date.today()
        self.entries: list[core.AgendaEntry] = []
        self.agenda_rows: list[core.AgendaTimelineEntry] = []
        self.unplanned_tasks: list[core.Task] = []
        self.selected_agenda_entry: core.AgendaEntry | None = None
        self.selected_unplanned_task: core.Task | None = None

    def compose(self) -> ComposeResult:
        with Horizontal(classes="top-nav"):
            yield Label("PERSONAL PLANNER", classes="brand")
            yield Button("Add task", id="add-task", variant="primary")
            yield Button("Week", id="open-week")
            yield Button("Tasks", id="open-tasks")
            yield Button("Events", id="open-events")
        with Horizontal(classes="date-toolbar", id="date-toolbar"):
            yield Button("Previous", id="previous-day")
            yield Button("Today", id="today")
            yield Button("Next", id="next-day")
            yield Button("Go", id="jump-date", variant="primary")
        with Horizontal(id="agenda-layout"):
            with Vertical(id="agenda-main"):
                yield Label("", id="agenda-heading", classes="section-heading")
                yield ListView(id="agenda-list", initial_index=None)
                with Horizontal(classes="action-bar"):
                    yield Button("Add event", id="add-event", variant="primary")
                    yield Button("Plan selected task", id="schedule-task")
                    yield Button("Move / edit selected", id="edit-agenda-item")
                    yield Button("Remove selected", id="remove-agenda-item", variant="error")
            with Vertical(id="agenda-sidebar"):
                yield Label("Unplanned tasks", classes="section-heading")
                yield ListView(id="unplanned-list", initial_index=None)
                yield Button("Schedule selected task", id="schedule-unplanned", variant="primary")
                yield Static("", id="agenda-status", classes="status")

    async def on_mount(self) -> None:
        await self.query_one("#date-toolbar", Horizontal).mount(
            Input(
                placeholder="YYYY-MM-DD or today / tomorrow / monday",
                id="agenda-date",
            ),
            before=self.query_one("#jump-date", Button),
        )
        self._adapt_layout(self.size.width)
        await self.refresh_data()

    def on_resize(self, event: Resize) -> None:
        self._adapt_layout(event.size.width)

    def _adapt_layout(self, width: int) -> None:
        sidebar = self.query_one("#agenda-sidebar", Vertical)
        main = self.query_one("#agenda-main", Vertical)
        if width < 90:
            sidebar.styles.display = "none"
            main.styles.width = "1fr"
        else:
            sidebar.styles.display = "block"
            main.styles.width = "3fr"

    def on_screen_resume(self) -> None:
        self.run_worker(self.refresh_data, exclusive=True)

    async def refresh_data(self) -> None:
        try:
            self.entries = core.get_day_agenda(self.selected_date.isoformat())
            self.unplanned_tasks = core.get_unplanned_tasks()
            self.selected_agenda_entry = None
            self.selected_unplanned_task = None
            agenda_list = self.query_one("#agenda-list", ListView)
            unplanned_list = self.query_one("#unplanned-list", ListView)
            await agenda_list.clear()
            await unplanned_list.clear()
            self.agenda_rows = core.get_agenda_timeline(self.entries)
            for entry in self.agenda_rows:
                if entry["kind"] == "gap":
                    await agenda_list.append(
                        ListItem(
                            Static(f"   FREE  {entry['start']} - {entry['end']}"),
                            classes="free-gap",
                        )
                    )
                else:
                    start = self._entry_time(entry, "start")
                    end = self._entry_time(entry, "end")
                    label = self._entry_label(entry)
                    await agenda_list.append(
                        ListItem(Static(f"{start} - {end}   {label}"))
                    )

            for task in self.unplanned_tasks:
                due_label = task.due.isoformat() if task.due else "No due date"
                await unplanned_list.append(
                    ListItem(
                        Static(
                            f"{task.title}\n{due_label} · "
                            f"{PRIORITY_LABELS.get(task.priority, task.priority)}"
                        )
                    )
                )

            weekday = self.selected_date.strftime("%A")
            self.query_one("#agenda-heading", Label).update(
                f"{weekday}, {self.selected_date:%B %d, %Y}"
            )
            self.query_one("#agenda-date", Input).value = self.selected_date.isoformat()
            status = (
                f"{len(self.entries)} scheduled item(s) · "
                f"{len(self.unplanned_tasks)} unplanned task(s)"
            )
            self.query_one("#agenda-status", Static).update(status)
        except (OSError, ValueError) as error:
            self.app.notify(str(error), title="Could not load agenda", severity="error")

    @staticmethod
    def _entry_time(entry: core.AgendaEntry, field: str) -> str:
        item = entry["block"] if entry["kind"] == "block" else entry["event"]
        return item.start if field == "start" else item.end

    @staticmethod
    def _entry_label(entry: core.AgendaEntry) -> str:
        if entry["kind"] == "block":
            priority = PRIORITY_LABELS.get(
                entry["task"].priority,
                entry["task"].priority,
            )
            return f"[T] {entry['task'].title} [{priority}]"
        location = f" · {entry['event'].location}" if entry["event"].location else ""
        marker = " ↻" if entry["event"].recurring else ""
        return f"[E] {entry['event'].title}{marker}{location}"

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.id == "agenda-list":
            if event.index < len(self.agenda_rows):
                selected = self.agenda_rows[event.index]
                self.selected_agenda_entry = (
                    None if selected["kind"] == "gap" else selected
                )
        elif event.list_view.id == "unplanned-list":
            if event.index < len(self.unplanned_tasks):
                self.selected_unplanned_task = self.unplanned_tasks[event.index]

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "previous-day":
            self.action_previous_day()
        elif button_id == "next-day":
            self.action_next_day()
        elif button_id == "today":
            self.action_today()
        elif button_id == "jump-date":
            self.jump_to_date()
        elif button_id == "open-tasks":
            self.app.switch_mode("tasks")
        elif button_id == "open-week":
            self.app.switch_mode("week")
        elif button_id == "open-events":
            self.app.switch_mode("events")
        elif button_id == "add-event":
            self.add_item()
        elif button_id == "add-task":
            self.add_task()
        elif button_id in {"schedule-task", "schedule-unplanned"}:
            self.plan_selected_task()
        elif button_id == "edit-agenda-item":
            self.edit_item()
        elif button_id == "remove-agenda-item":
            self.remove_item()

    def action_previous_day(self) -> None:
        self.selected_date -= timedelta(days=1)
        self.run_worker(self.refresh_data, exclusive=True)

    def action_next_day(self) -> None:
        self.selected_date += timedelta(days=1)
        self.run_worker(self.refresh_data, exclusive=True)

    def action_today(self) -> None:
        self.selected_date = date.today()
        self.run_worker(self.refresh_data, exclusive=True)

    def jump_to_date(self) -> None:
        text = self.query_one("#agenda-date", Input).value.strip()
        try:
            self.selected_date = core.parse_date(text)
        except ValueError as error:
            self.query_one("#agenda-status", Static).update(str(error))
            return
        self.run_worker(self.refresh_data, exclusive=True)

    def plan_selected_task(self) -> None:
        task = self.selected_unplanned_task
        if task is None:
            self.app.notify("Select an unplanned task first.", severity="warning")
            return
        self.app.push_screen(
            BlockForm(task=task, selected_date=self.selected_date),
            self._after_form,
        )

    def add_item(self) -> None:
        self.app.push_screen(
            EventForm(default_date=self.selected_date),
            self._after_form,
        )

    def add_task(self) -> None:
        self.app.push_screen(
            TaskForm(default_date=self.selected_date),
            self._after_form,
        )

    def edit_item(self) -> None:
        entry = self.selected_agenda_entry
        if entry is None:
            self.app.notify("Select an agenda item first.", severity="warning")
            return
        if entry["kind"] == "block":
            self.app.push_screen(
                BlockForm(block_entry=entry, selected_date=self.selected_date),
                self._after_form,
            )
        else:
            if entry["event"].recurring:
                self.app.push_screen(
                    RecurrenceScopeDialog("Edit"),
                    lambda scope: self._edit_event_scope(entry["event"], scope),
                )
            else:
                self.app.push_screen(
                    EventForm(core.get_event(entry["event"].id)),
                    self._after_form,
                )

    def _edit_event_scope(
        self,
        occurrence: core.EventOccurrence,
        scope: str | None,
    ) -> None:
        if scope is None:
            return
        event = core.get_event(occurrence.id)
        selected_occurrence = occurrence if scope != "all" else None
        self.app.push_screen(
            EventForm(event, selected_occurrence, scope),
            self._after_form,
        )

    def remove_item(self) -> None:
        entry = self.selected_agenda_entry
        if entry is None:
            self.app.notify("Select an agenda item first.", severity="warning")
            return
        if entry["kind"] == "block":
            title = entry["task"].title
            message = f'Remove the scheduled block for "{title}"?'
        else:
            title = entry["event"].title
            if entry["event"].recurring:
                self.app.push_screen(
                    RecurrenceScopeDialog("Delete"),
                    lambda scope: self._remove_recurring_event(
                        entry["event"],
                        scope,
                    ),
                )
                return
            message = f'Delete event "{title}"?'
        self.app.push_screen(
            ConfirmDialog(message, "Remove"),
            lambda confirmed: self._remove_confirmed(entry, confirmed),
        )

    def _remove_confirmed(
        self,
        entry: core.AgendaEntry,
        confirmed: bool,
    ) -> None:
        if not confirmed:
            return
        try:
            if entry["kind"] == "block":
                core.remove_block(entry["task"].id, entry["block"].id)
            else:
                core.delete_event(entry["event"].id)
        except (OSError, ValueError) as error:
            self.app.notify(str(error), title="Could not remove item", severity="error")
            return
        self.run_worker(self.refresh_data, exclusive=True)

    def _remove_recurring_event(
        self,
        occurrence: core.EventOccurrence,
        scope: str | None,
    ) -> None:
        if scope is None:
            return
        try:
            core.delete_event(
                occurrence.id,
                scope=scope,
                occurrence_date=occurrence.occurrence_date,
            )
        except (OSError, ValueError) as error:
            self.app.notify(str(error), title="Could not remove item", severity="error")
            return
        self.run_worker(self.refresh_data, exclusive=True)

    def _after_form(self, changed: bool) -> None:
        if changed:
            self.run_worker(self.refresh_data, exclusive=True)
