"""Month view screen for Planner."""

from __future__ import annotations

import time
from datetime import date, timedelta
from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Grid, Horizontal, Vertical, VerticalScroll
from textual.events import Click, Resize
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, Label, ListItem, ListView, Static

from planner import calendar_view, clock, core
from planner.tui.screens.event_form import EventForm
from planner.tui.screens.task_form import TaskForm

LOAD_SYMBOLS = {
    "none": "○",
    "light": "◔",
    "medium": "◑",
    "heavy": "●",
}


class MonthDayCell(Static):
    """Clickable cell representing a single day in the month grid."""

    def __init__(self, day_info: dict[str, Any], is_selected: bool) -> None:
        super().__init__()
        self.day_info = day_info
        self.is_selected = is_selected
        self.can_focus = True

    def on_key(self, event) -> None:
        if event.key == "enter":
            screen = self.screen
            if isinstance(screen, MonthScreen):
                screen.action_open_selected_day()
                event.stop()

    def render(self) -> str:
        d = self.day_info
        dt = core.parse_date(d["date"])
        symbol = LOAD_SYMBOLS.get(d.get("load", "none"), "○")
        due_marker = " !" if d.get("due_count", 0) > 0 else ""

        lines = [f"{dt.day} {symbol}{due_marker}"]

        for p in d.get("preview", []):
            rec = " ↻" if p.get("recurring") else ""
            lines.append(f"{p['start']} {p['title']}{rec}")

        more = d.get("more", 0)
        if more > 0:
            lines.append(f"+{more} more")

        return "\n".join(lines)


class MonthScreen(Screen):
    """Monthly calendar overview screen."""

    AUTO_FOCUS = None
    BINDINGS = [
        ("left", "previous_day", "Previous day"),
        Binding("h", "previous_day", "Previous day", show=False),
        ("right", "next_day", "Next day"),
        Binding("l", "next_day", "Next day", show=False),
        ("up", "previous_week", "Previous week"),
        Binding("k", "previous_week", "Previous week", show=False),
        ("down", "next_week", "Next week"),
        Binding("j", "next_week", "Next week", show=False),
        ("[", "previous_month", "Previous month"),
        ("]", "next_month", "Next month"),
        ("0", "today", "Today"),
        ("enter", "open_selected_day", "Open day"),
        ("a", "add_task", "Add task"),
        ("v", "add_event", "Add event"),
    ]

    def __init__(self, selected_date: date | None = None) -> None:
        super().__init__()
        self.selected_date = selected_date or clock.today()
        self.overview_data: dict[str, Any] = {}
        self._last_click_time: float = 0.0
        self._last_clicked_date: date | None = None

    def compose(self) -> ComposeResult:
        with Horizontal(classes="top-nav"):
            yield Label("MONTHLY OVERVIEW", classes="brand")
            yield Button("Undo", id="undo")
            yield Button("Redo", id="redo")
            yield Button("Add task", id="add-task", variant="primary")
            yield Button("Agenda", id="open-agenda")
            yield Button("Week", id="open-week")
            yield Button("Tasks", id="open-tasks")
            yield Button("Events", id="open-events")
            yield Button("Notes", id="open-notes")
            yield Button("Habits", id="open-habits")

        with Horizontal(classes="date-toolbar", id="month-toolbar"):
            yield Button("Previous month", id="previous-month")
            yield Button("Today", id="today")
            yield Button("Next month", id="next-month")
            yield Input(
                placeholder="YYYY-MM-DD or date name",
                id="month-date-input",
            )
            yield Button("Go", id="jump-date", variant="primary")

        with Horizontal(id="month-container"):
            with Vertical(id="month-main"):
                yield Label("", id="month-heading", classes="section-heading")
                with Grid(id="month-grid-headers"):
                    pass
                with Grid(id="month-grid"):
                    pass
                yield ListView(id="month-compact-list")

            with Vertical(id="month-sidebar"):
                yield Label("", id="month-sidebar-heading", classes="section-heading")
                yield Static("", id="month-sidebar-summary", classes="month-sidebar-summary")
                with VerticalScroll(id="month-sidebar-agenda-container"):
                    yield Label("Agenda", classes="subsection-heading")
                    yield Static("", id="month-sidebar-agenda", classes="month-sidebar-agenda")
                    yield Label("Notes", classes="subsection-heading")
                    yield Static("", id="month-sidebar-notes", classes="month-sidebar-notes")

        yield Footer()

    async def on_mount(self) -> None:
        self.can_focus = True
        self.focus()
        self._adapt_layout(self.size.width)
        await self.refresh_data()

    def on_resize(self, event: Resize) -> None:
        self._adapt_layout(event.size.width)

    def _adapt_layout(self, width: int) -> None:
        sidebar = self.query_one("#month-sidebar", Vertical)
        grid = self.query_one("#month-grid", Grid)
        headers = self.query_one("#month-grid-headers", Grid)
        compact = self.query_one("#month-compact-list", ListView)

        if width < 90:
            sidebar.styles.display = "none"
            grid.styles.display = "none"
            headers.styles.display = "none"
            compact.styles.display = "block"
        else:
            sidebar.styles.display = "block"
            grid.styles.display = "block"
            headers.styles.display = "block"
            compact.styles.display = "none"

    def on_screen_resume(self) -> None:
        self.run_worker(self.refresh_data, exclusive=True)

    async def refresh_data(self) -> None:
        try:
            self.overview_data = calendar_view.month_overview(self.selected_date)
            year = self.overview_data["year"]
            month = self.overview_data["month"]
            month_date = date(year, month, 1)
            self.query_one("#month-heading", Label).update(
                f"{month_date:%B %Y}"
            )
            self.query_one("#month-date-input", Input).value = self.selected_date.isoformat()

            # Render Headers
            headers_grid = self.query_one("#month-grid-headers", Grid)
            await headers_grid.remove_children()
            first_w = self.overview_data.get("first_weekday", "mon")
            day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"] if first_w == "mon" else ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
            for name in day_names:
                await headers_grid.mount(Static(name, classes="month-weekday-header"))

            # Render Grid
            grid = self.query_one("#month-grid", Grid)
            await grid.remove_children()

            compact_list = self.query_one("#month-compact-list", ListView)
            await compact_list.clear()

            today_val = clock.today()
            weeks = self.overview_data.get("weeks", [])

            selected_idx = 0
            compact_idx = 0

            for week in weeks:
                for day_info in week:
                    day_d = core.parse_date(day_info["date"])
                    is_selected = day_d == self.selected_date
                    cell = MonthDayCell(day_info, is_selected)
                    cell.add_class("month-cell")
                    if not day_info.get("in_month"):
                        cell.add_class("out-of-month")
                    if day_info.get("is_today"):
                        cell.add_class("today-cell")
                    if is_selected:
                        cell.add_class("selected-cell")
                        cell.focus()

                    await grid.mount(cell)

                    # Compact list item for days in month
                    if day_info.get("in_month"):
                        symbol = LOAD_SYMBOLS.get(day_info.get("load", "none"), "○")
                        due_marker = " !" if day_info.get("due_count", 0) > 0 else ""
                        compact_lbl = (
                            f"{day_d:%a %d} {symbol}{due_marker} · "
                            f"{day_info.get('block_count', 0)} block(s), "
                            f"{day_info.get('event_count', 0)} event(s)"
                        )
                        citem = ListItem(Static(compact_lbl), id=f"compact-{day_info['date']}")
                        if is_selected:
                            selected_idx = compact_idx
                        await compact_list.append(citem)
                        compact_idx += 1

            if compact_idx > 0:
                compact_list.index = selected_idx

            await self._render_sidebar()
        except (OSError, ValueError) as error:
            self.app.notify(str(error), title="Could not load month view", severity="error")

    async def _render_sidebar(self) -> None:
        weekday = self.selected_date.strftime("%A")
        self.query_one("#month-sidebar-heading", Label).update(
            f"{weekday}, {self.selected_date:%B %d, %Y}"
        )

        timeline = core.day_timeline(self.selected_date)
        summary = timeline["summary"]
        minutes = summary["minutes_planned"]
        h, m = divmod(minutes, 60)
        time_lbl = f"{h}h {m:02d}m" if m else f"{h}h"
        load_summary_text = (
            f"{summary['blocks_total']} blocks ({time_lbl}) · "
            f"{summary['events_total']} events"
        )
        self.query_one("#month-sidebar-summary", Static).update(load_summary_text)

        # Agenda items
        agenda_lines = []
        for it in timeline["items"]:
            sym = "✓" if it.get("status") == "done" else ("!" if it.get("missed") else "·")
            agenda_lines.append(f"{sym} {it['start']} - {it['end']} {it['title']}")
        if not agenda_lines:
            agenda_lines = ["No scheduled items."]
        self.query_one("#month-sidebar-agenda", Static).update("\n".join(agenda_lines))

        # Notes
        notes = core.notes_for_day(self.selected_date)
        notes_lines = []
        for n in notes:
            t = n.get("title") or n.get("preview") or "Untitled Note"
            notes_lines.append(f"- {t}")
        if not notes_lines:
            notes_lines = ["No notes."]
        self.query_one("#month-sidebar-notes", Static).update("\n".join(notes_lines))

    def on_click(self, event: Click) -> None:
        target = event.target
        while target is not None and not isinstance(target, MonthDayCell):
            target = getattr(target, "parent", None)
        if isinstance(target, MonthDayCell):
            clicked_date = core.parse_date(target.day_info["date"])
            cur_time = time.time()
            if self._last_clicked_date == clicked_date and (cur_time - self._last_click_time) < 0.4:
                self.selected_date = clicked_date
                self.action_open_selected_day()
                return

            self._last_click_time = cur_time
            self._last_clicked_date = clicked_date
            self.selected_date = clicked_date
            self.run_worker(self.refresh_data, exclusive=True)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.id == "month-compact-list":
            item = event.item
            if item and item.id and item.id.startswith("compact-"):
                date_str = item.id.replace("compact-", "")
                try:
                    self.selected_date = core.parse_date(date_str)
                    self.open_selected_day()
                except ValueError:
                    pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id == "previous-month":
            self.action_previous_month()
        elif button_id == "next-month":
            self.action_next_month()
        elif button_id == "today":
            self.action_today()
        elif button_id == "jump-date":
            self.jump_to_date()
        elif button_id == "open-agenda":
            self.action_open_selected_day()
        elif button_id == "open-week":
            self.app.switch_mode("week")
        elif button_id == "open-tasks":
            self.app.switch_mode("tasks")
        elif button_id == "open-events":
            self.app.switch_mode("events")
        elif button_id == "open-notes":
            self.app.switch_mode("notes")
        elif button_id == "open-habits":
            self.app.switch_mode("habits")
        elif button_id == "add-task":
            self.action_add_task()

    def action_previous_day(self) -> None:
        self.selected_date = calendar_view.shift_date(self.selected_date, days=-1)
        self.run_worker(self.refresh_data, exclusive=True)

    def action_next_day(self) -> None:
        self.selected_date = calendar_view.shift_date(self.selected_date, days=1)
        self.run_worker(self.refresh_data, exclusive=True)

    def action_previous_week(self) -> None:
        self.selected_date = calendar_view.shift_date(self.selected_date, days=-7)
        self.run_worker(self.refresh_data, exclusive=True)

    def action_next_week(self) -> None:
        self.selected_date = calendar_view.shift_date(self.selected_date, days=7)
        self.run_worker(self.refresh_data, exclusive=True)

    def action_previous_month(self) -> None:
        self.selected_date = calendar_view.shift_date(self.selected_date, months=-1)
        self.run_worker(self.refresh_data, exclusive=True)

    def action_next_month(self) -> None:
        self.selected_date = calendar_view.shift_date(self.selected_date, months=1)
        self.run_worker(self.refresh_data, exclusive=True)

    def action_today(self) -> None:
        self.selected_date = clock.today()
        self.run_worker(self.refresh_data, exclusive=True)

    def jump_to_date(self) -> None:
        val = self.query_one("#month-date-input", Input).value.strip()
        try:
            self.selected_date = core.parse_date(val)
            self.run_worker(self.refresh_data, exclusive=True)
        except ValueError as err:
            self.app.notify(str(err), severity="warning")

    def action_open_selected_day(self) -> None:
        agenda_screen = self.app.get_screen("agenda")
        if isinstance(agenda_screen, Screen):
            agenda_screen.selected_date = self.selected_date
            if hasattr(agenda_screen, "refresh_data"):
                agenda_screen.run_worker(agenda_screen.refresh_data, exclusive=True)
        self.app.switch_mode("default")

    open_selected_day = action_open_selected_day

    def action_add_task(self) -> None:
        self.app.push_screen(
            TaskForm(default_date=self.selected_date),
            lambda changed: self.run_worker(self.refresh_data, exclusive=True) if changed else None,
        )

    def action_add_event(self) -> None:
        self.app.push_screen(
            EventForm(default_date=self.selected_date),
            lambda changed: self.run_worker(self.refresh_data, exclusive=True) if changed else None,
        )

