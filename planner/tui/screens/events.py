from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import Button, Label, ListItem, ListView, Static

from planner import core
from planner.tui.screens.confirm_dialog import ConfirmDialog
from planner.tui.screens.event_form import EventForm
from planner.tui.screens.recurrence_scope import RecurrenceScopeDialog


class EventsScreen(Screen):
    def __init__(self) -> None:
        super().__init__()
        self.events: list[core.EventOccurrence] = []
        self.selected_event: core.EventOccurrence | None = None

    def compose(self) -> ComposeResult:
        with Horizontal(classes="top-nav"):
            yield Label("UPCOMING EVENTS", classes="brand")
            yield Button("Agenda", id="open-agenda")
            yield Button("Week", id="open-week")
            yield Button("Tasks", id="open-tasks")
        with Horizontal(classes="filter-toolbar"):
            yield Static("Events today and later", classes="status")
            yield Button("Add event", id="add-event", variant="primary")
        yield ListView(id="event-list", initial_index=None)
        with Horizontal(classes="action-bar"):
            yield Button("Edit", id="edit-event")
            yield Button("Delete", id="delete-event", variant="error")

    async def on_mount(self) -> None:
        await self.refresh_data()

    def on_screen_resume(self) -> None:
        self.run_worker(self.refresh_data, exclusive=True)

    async def refresh_data(self) -> None:
        try:
            self.events = core.upcoming_events()
            self.selected_event = None
            event_list = self.query_one("#event-list", ListView)
            await event_list.clear()
            for item in self.events:
                details = f"{item.date.isoformat()}  {item.start}-{item.end}"
                if item.location:
                    details += f"  ·  {item.location}"
                marker = " ↻" if item.recurring else ""
                await event_list.append(
                    ListItem(
                        Static(f"{item.title}{marker}\n{details}"),
                        classes="event-row",
                    )
                )
        except (OSError, ValueError) as error:
            self.app.notify(str(error), title="Could not load events", severity="error")

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.id == "event-list" and event.index < len(self.events):
            self.selected_event = self.events[event.index]

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "open-agenda":
            self.app.switch_mode("default")
        elif button_id == "open-tasks":
            self.app.switch_mode("tasks")
        elif button_id == "open-week":
            self.app.switch_mode("week")
        elif button_id == "add-event":
            self.add_item()
        elif button_id == "edit-event":
            self.edit_item()
        elif button_id == "delete-event":
            self.delete_item()

    def add_item(self) -> None:
        self.app.push_screen(EventForm(), self._after_form)

    def edit_item(self) -> None:
        event = self.selected_event
        if event is None:
            self.app.notify("Select an event first.", severity="warning")
            return
        if event.recurring:
            self.app.push_screen(
                RecurrenceScopeDialog("Edit"),
                lambda scope: self._edit_scoped(event, scope),
            )
        else:
            self.app.push_screen(
                EventForm(core.get_event(event.id)),
                self._after_form,
            )

    def _edit_scoped(
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

    def delete_item(self) -> None:
        event = self.selected_event
        if event is None:
            self.app.notify("Select an event first.", severity="warning")
            return
        if event.recurring:
            self.app.push_screen(
                RecurrenceScopeDialog("Delete"),
                lambda scope: self._delete_scoped(event, scope),
            )
            return
        self.app.push_screen(
            ConfirmDialog(f'Delete event "{event.title}"?', "Delete"),
            lambda confirmed: self._delete_confirmed(event, confirmed),
        )

    def _delete_scoped(
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
        event: core.EventOccurrence,
        confirmed: bool,
    ) -> None:
        if not confirmed:
            return
        try:
            core.delete_event(event.id)
        except (OSError, ValueError) as error:
            self.app.notify(str(error), title="Could not delete event", severity="error")
            return
        self.run_worker(self.refresh_data, exclusive=True)

    def _after_form(self, changed: bool) -> None:
        if changed:
            self.run_worker(self.refresh_data, exclusive=True)
