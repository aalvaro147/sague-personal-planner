from datetime import date, timedelta

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.events import Resize
from textual.screen import Screen
from textual.widgets import Button, Input, Label, ListItem, ListView, Static

from planner import core
from planner.tui.screens.block_form import BlockForm
from planner.tui.screens.confirm_dialog import ConfirmDialog
from planner.tui.screens.event_form import EventForm
from planner.tui.screens.recurrence_scope import RecurrenceScopeDialog
from planner.tui.screens.task_form import TaskForm

HEAVY_DAY_MINUTES = 6 * 60
PRIORITY_LABELS = {"alta": "High", "media": "Medium", "baja": "Low"}


class WeekScreen(Screen):
    BINDINGS = [
        ("[", "previous_week", "Previous week"),
        ("]", "next_week", "Next week"),
        ("0", "current_week", "Current week"),
        ("left", "previous_day", "Previous day"),
        ("right", "next_day", "Next day"),
        ("enter", "open_selected_day", "Open day"),
        ("p", "plan_selected_task", "Plan"),
        ("e", "edit_item", "Edit"),
        ("d", "delete_item", "Delete"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.selected_date = date.today()
        self.selected_day: date | None = date.today()
        self.first_weekday = "mon"
        self.week_days: list[dict[str, object]] = []
        self.due_tasks: list[core.Task] = []
        self.selected_task: core.Task | None = None
        self.selected_entry: tuple[date, core.AgendaEntry] | None = None

    def compose(self) -> ComposeResult:
        with Horizontal(classes="top-nav"):
            yield Label("WEEKLY AGENDA", classes="brand")
            yield Button("Day", id="open-day")
            yield Button("Add task", id="add-task", variant="primary")
            yield Button("Tasks", id="open-tasks")
            yield Button("Events", id="open-events")
        with Horizontal(classes="date-toolbar"):
            yield Button("Previous week", id="previous-week")
            yield Button("This week", id="current-week")
            yield Button("Next week", id="next-week")
            yield Input(placeholder="YYYY-MM-DD or today / tomorrow / monday", id="week-date")
            yield Button("Go", id="jump-week", variant="primary")
            yield Button("Week starts: Monday", id="toggle-week-start")
        yield Horizontal(id="week-grid", classes="week-grid")
        with VerticalScroll(id="week-compact", classes="week-compact"):
            pass
        with Vertical(id="week-due-panel"):
            yield Label("Due this week without a planned block", classes="section-heading")
            yield ListView(id="week-due-list", initial_index=None)
            yield Static("Select a day, then press p to plan a task.", id="week-status", classes="status")
        yield Horizontal(id="week-actions", classes="action-bar")

    def _day_panel(self, day: date, prefix: str, index: int) -> Vertical:
        key = str(index)
        return Vertical(
            Button(day.strftime("%a %d"), id=f"{prefix}-heading-{key}"),
            Static("", id=f"{prefix}-summary-{key}", classes="week-summary"),
            ListView(id=f"{prefix}-items-{key}", initial_index=None),
            classes="week-day",
            id=f"{prefix}-panel-{key}",
        )

    async def on_mount(self) -> None:
        for index, day in enumerate(self._dates()):
            await self.query_one("#week-grid", Horizontal).mount(
                self._day_panel(day, "grid", index)
            )
            await self.query_one("#week-compact", VerticalScroll).mount(
                self._day_panel(day, "compact", index)
            )
        self._adapt_layout(self.size.width)
        await self.refresh_data()

    def on_resize(self, event: Resize) -> None:
        self._adapt_layout(event.size.width)

    def _adapt_layout(self, width: int) -> None:
        compact = width < 140
        self.query_one("#week-grid", Horizontal).display = not compact
        self.query_one("#week-compact", VerticalScroll).display = compact

    def _dates(self) -> list[date]:
        start = core.week_start(self.selected_date, self.first_weekday)
        return [start + timedelta(days=index) for index in range(7)]

    def on_screen_resume(self) -> None:
        self.run_worker(self.refresh_data, exclusive=True)

    async def refresh_data(self) -> None:
        try:
            self.first_weekday = core.load_settings()["first_weekday"]
            self.week_days = core.week_agenda(self.selected_date, self.first_weekday)
            summary_by_date = {
                item["date"]: item
                for item in core.week_summary(self.selected_date, self.first_weekday)
            }
            self.due_tasks = core.week_due_without_block(
                self.selected_date,
                self.first_weekday,
            )
            self.selected_entry = None
            self.selected_task = None
            start = core.week_start(self.selected_date, self.first_weekday)
            end = start + timedelta(days=6)
            self.query_one("#week-date", Input).value = self.selected_date.isoformat()
            self.query_one("#toggle-week-start", Button).label = (
                "Week starts: Monday" if self.first_weekday == "mon"
                else "Week starts: Sunday"
            )
            await self._render_due_tasks()
            for index, day_info in enumerate(self.week_days):
                day = day_info["date"]
                agenda = day_info["agenda"]
                day_summary = summary_by_date[day]
                for prefix in ("grid", "compact"):
                    day_key = str(index)
                    heading = self.query_one(f"#{prefix}-heading-{day_key}", Button)
                    heading.label = day.strftime("%a %d")
                    heading.variant = (
                        "primary" if day == self.selected_day
                        else "success" if day == date.today()
                        else "default"
                    )
                    summary = self.query_one(f"#{prefix}-summary-{day_key}", Static)
                    minutes = day_summary["occupied_minutes"]
                    summary.update(
                        f"{day_summary['item_count']} item(s) · "
                        f"{minutes // 60}h {minutes % 60:02d}m"
                    )
                    summary.set_class(minutes >= HEAVY_DAY_MINUTES, "heavy-load")
                    items = self.query_one(f"#{prefix}-items-{day_key}", ListView)
                    await items.clear()
                    for entry in agenda:
                        await items.append(
                            ListItem(Static(self._entry_label(entry)))
                        )
            self.query_one("#week-status", Static).update(
                f"Week of {start:%b %d} – {end:%b %d, %Y} · "
                f"{len(self.due_tasks)} task(s) due without a block"
            )
        except (OSError, ValueError) as error:
            self.app.notify(str(error), title="Could not load weekly agenda", severity="error")

    @staticmethod
    def _entry_label(entry: core.AgendaEntry) -> str:
        if entry["kind"] == "block":
            task = entry["task"]
            block = entry["block"]
            priority = PRIORITY_LABELS.get(task.priority, task.priority)
            marker = " ↻" if task.recurrence else ""
            return f"{block.start} [T] {task.title}{marker} · {priority}"
        event = entry["event"]
        marker = " ↻" if event.recurring else ""
        return f"{event.start} [E] {event.title}{marker}"

    async def _render_due_tasks(self) -> None:
        task_list = self.query_one("#week-due-list", ListView)
        await task_list.clear()
        for task in self.due_tasks:
            due = task.due.isoformat() if task.due else "No due date"
            marker = " ↻" if task.recurrence else ""
            await task_list.append(ListItem(Static(f"{due} · {task.title}{marker}")))

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        self._select_day_list_entry(event.list_view, event.list_view.index)

    def _select_day_list_entry(
        self,
        list_view: ListView,
        index: int | None,
    ) -> None:
        list_id = list_view.id or ""
        if list_id == "week-due-list":
            if index is not None and index < len(self.due_tasks):
                self.selected_task = self.due_tasks[index]
            return
        if not list_id.startswith(("grid-items-", "compact-items-")):
            return
        day_index = int(list_id.rsplit("-", 1)[-1])
        if day_index >= len(self.week_days):
            return
        selected_day = self.week_days[day_index]["date"]
        self.selected_day = selected_day
        if index is None:
            self.selected_entry = None
            return
        day_info = next(
            (item for item in self.week_days if item["date"] == selected_day),
            None,
        )
        if day_info is not None and index < len(day_info["agenda"]):
            self.selected_entry = (
                selected_day,
                day_info["agenda"][index],
            )

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        list_id = event.list_view.id or ""
        if list_id == "week-due-list":
            if event.index < len(self.due_tasks):
                self.selected_task = self.due_tasks[event.index]
            return
        self._select_day_list_entry(event.list_view, event.index)
        self.open_selected_day()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id == "previous-week":
            self.action_previous_week()
        elif button_id == "next-week":
            self.action_next_week()
        elif button_id == "current-week":
            self.action_current_week()
        elif button_id == "jump-week":
            self.jump_to_date()
        elif button_id == "toggle-week-start":
            self.toggle_week_start()
        elif button_id.startswith(("grid-heading-", "compact-heading-")):
            day_index = int(button_id.rsplit("-", 1)[-1])
            if day_index < len(self.week_days):
                self.selected_day = self.week_days[day_index]["date"]
                self.run_worker(self.refresh_data, exclusive=True)
        elif button_id == "open-day":
            self.open_selected_day()
        elif button_id == "add-task":
            self.add_task()
        elif button_id == "open-tasks":
            self.app.switch_mode("tasks")
        elif button_id == "open-events":
            self.app.switch_mode("events")

    def action_previous_week(self) -> None:
        self.selected_date -= timedelta(days=7)
        if self.selected_day is not None:
            self.selected_day -= timedelta(days=7)
        self.run_worker(self.refresh_data, exclusive=True)

    def action_next_week(self) -> None:
        self.selected_date += timedelta(days=7)
        if self.selected_day is not None:
            self.selected_day += timedelta(days=7)
        self.run_worker(self.refresh_data, exclusive=True)

    def action_current_week(self) -> None:
        self.selected_date = date.today()
        self.selected_day = date.today()
        self.run_worker(self.refresh_data, exclusive=True)

    def action_previous_day(self) -> None:
        self._move_selected_day(-1)

    def action_next_day(self) -> None:
        self._move_selected_day(1)

    def _move_selected_day(self, offset: int) -> None:
        if self.selected_day is None:
            self.selected_day = self.selected_date
        else:
            self.selected_day += timedelta(days=offset)
        self.selected_date = self.selected_day
        self.run_worker(self.refresh_data, exclusive=True)

    def jump_to_date(self) -> None:
        try:
            self.selected_date = core.parse_date(
                self.query_one("#week-date", Input).value.strip()
            )
        except ValueError as error:
            self.query_one("#week-status", Static).update(str(error))
            return
        self.selected_day = self.selected_date
        self.run_worker(self.refresh_data, exclusive=True)

    def toggle_week_start(self) -> None:
        self.first_weekday = "sun" if self.first_weekday == "mon" else "mon"
        try:
            core.save_settings(self.first_weekday)
        except (OSError, ValueError) as error:
            self.app.notify(str(error), title="Could not save settings", severity="error")
            return
        self.run_worker(self.refresh_data, exclusive=True)

    def open_selected_day(self) -> None:
        if self.selected_day is None:
            self.app.notify("Select a day first.", severity="warning")
            return
        agenda_screen = self.app.get_screen("agenda")
        if isinstance(agenda_screen, Screen):
            agenda_screen.selected_date = self.selected_day
        self.app.switch_mode("default")

    def add_task(self) -> None:
        self.app.push_screen(
            TaskForm(default_date=self.selected_day),
            self._after_change,
        )

    def edit_item(self) -> None:
        self.action_edit_item()

    def delete_item(self) -> None:
        self.action_delete_item()

    def plan_selected_task(self) -> None:
        self.action_plan_selected_task()

    def action_edit_item(self) -> None:
        if self.selected_entry is None:
            self.app.notify("Select an agenda item first.", severity="warning")
            return
        day, entry = self.selected_entry
        if entry["kind"] == "block":
            self.app.push_screen(
                BlockForm(block_entry=entry, selected_date=day),
                self._after_change,
            )
        elif entry["event"].recurring:
            self.app.push_screen(
                RecurrenceScopeDialog("Edit"),
                lambda scope: self._edit_recurring(entry["event"], scope),
            )
        else:
            self.app.push_screen(
                EventForm(core.get_event(entry["event"].id)),
                self._after_change,
            )

    def action_delete_item(self) -> None:
        if self.selected_entry is None:
            self.app.notify("Select an agenda item first.", severity="warning")
            return
        _, entry = self.selected_entry
        if entry["kind"] == "event" and entry["event"].recurring:
            self.app.push_screen(
                RecurrenceScopeDialog("Delete"),
                lambda scope: self._delete_recurring(entry["event"], scope),
            )
            return
        label = (
            f'task "{entry["task"].title}" block'
            if entry["kind"] == "block"
            else f'event "{entry["event"].title}"'
        )
        self.app.push_screen(
            ConfirmDialog(f"Delete {label}?", "Delete"),
            lambda confirmed: self._delete_confirmed(entry, confirmed),
        )

    def _edit_recurring(
        self,
        occurrence: core.EventOccurrence,
        scope: str | None,
    ) -> None:
        if scope is None:
            return
        self.app.push_screen(
            EventForm(
                core.get_event(occurrence.id),
                occurrence if scope != "all" else None,
                scope,
            ),
            self._after_change,
        )

    def _delete_recurring(
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
            self.app.notify(str(error), title="Could not delete event", severity="error")
            return
        self.run_worker(self.refresh_data, exclusive=True)

    def _delete_confirmed(
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
            self.app.notify(str(error), title="Could not delete item", severity="error")
            return
        self.run_worker(self.refresh_data, exclusive=True)

    def action_plan_selected_task(self) -> None:
        if self.selected_task is None:
            self.app.notify("Select a due task first.", severity="warning")
            return
        if self.selected_day is None:
            self.app.notify("Select a day to plan the task.", severity="warning")
            return
        self.app.push_screen(
            BlockForm(task=self.selected_task, selected_date=self.selected_day),
            self._after_change,
        )

    def _after_change(self, changed: bool) -> None:
        if changed:
            self.run_worker(self.refresh_data, exclusive=True)
