from datetime import date, timedelta
from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.events import Resize
from textual.screen import Screen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Label,
    ListItem,
    ListView,
    Sparkline,
    Static,
    TabbedContent,
    TabPane,
)

from planner import clock, core
from planner.tui.screens.confirm_dialog import ConfirmDialog
from planner.tui.screens.habit_detail import HabitDetailModal
from planner.tui.screens.habit_form import HabitForm

STATUS_SYMBOLS = {
    "done": "[green]●[/green]",
    "missed": "[red]✕[/red]",
    "skipped": "[cyan]–[/cyan]",
    "unlogged": "[yellow]○[/yellow]",
    "not_scheduled": "[dim]·[/dim]",
}

BLOCK_LEVELS = [" ", " ", "▂", "▃", "▄", "▅", "▆", "▇", "█"]


def _format_rate_bar(percent: int | None) -> str:
    if percent is None:
        return "[dim] [/dim]"
    idx = min(8, max(1, round(percent * 8 / 100)))
    return f"[green]{BLOCK_LEVELS[idx]}[/green]"


class HabitsScreen(Screen):
    """Main screen for habits tracking, logging, detail, and overview."""

    BINDINGS = [
        ("[", "previous_day", "Previous day"),
        ("]", "next_day", "Next day"),
        ("0", "today", "Today"),
        ("d", "mark_done", "Done"),
        ("m", "mark_missed", "Missed"),
        ("e", "mark_excused", "Excused"),
        ("x", "clear_record", "Clear"),
        ("a", "add_habit", "New habit"),
        ("E", "edit_habit", "Edit"),
        ("r", "toggle_archive", "Archive"),
        ("delete", "delete_habit", "Delete"),
        ("enter", "detail", "Detail"),
    ]

    def __init__(self, selected_date: date | None = None) -> None:
        super().__init__()
        self.selected_date = selected_date or clock.today()
        self.habits: list[dict[str, Any]] = []
        self.selected_habit: dict[str, Any] | None = None
        self.show_archived: bool = False
        self.overview_range_days: int = 30
        self._compact: bool = False

    def compose(self) -> ComposeResult:
        with Horizontal(classes="top-nav"):
            yield Label("HABITS", classes="brand")
            yield Button("Agenda", id="open-agenda")
            yield Button("Week", id="open-week")
            yield Button("Tasks", id="open-tasks")
            yield Button("Events", id="open-events")
            yield Button("Notes", id="open-notes")
            yield Button("Undo", id="undo")
            yield Button("Redo", id="redo")

        with TabbedContent(id="habits-tabs"):
            with TabPane("Habits", id="tab-habits"):
                with Horizontal(classes="filter-toolbar", id="habits-nav-bar"):
                    yield Button("◀ [", id="prev-day")
                    yield Label("", id="selected-date-label", classes="section-heading")
                    yield Button("] ▶", id="next-day")
                    yield Button("Today (0)", id="today-btn")
                    yield Button("New habit (a)", id="add-habit", variant="primary")
                    yield Button("Show archived", id="toggle-archived")
                    yield Static("", id="habits-count", classes="status")

                yield Static(
                    "Legend: [green]●[/green] done  [red]✕[/red] missed  [cyan]–[/cyan] excused  [yellow]○[/yellow] unlogged  [dim]·[/dim] not scheduled",
                    id="habits-legend",
                )

                yield ListView(id="habit-list", initial_index=None)

                with Horizontal(classes="action-bar", id="habits-actions"):
                    yield Button("Done (d)", id="btn-done", variant="success")
                    yield Button("Missed (m)", id="btn-missed", variant="error")
                    yield Button("Excused (e)", id="btn-excused")
                    yield Button("Clear (x)", id="btn-clear")
                    yield Button("Detail (Enter)", id="btn-detail", variant="primary")
                    yield Button("Edit (E)", id="btn-edit")
                    yield Button("Archive (r)", id="btn-archive")
                    yield Button("Delete (Del)", id="btn-delete", variant="error")

            with TabPane("Overview", id="tab-overview"):
                with Horizontal(classes="filter-toolbar", id="overview-toolbar"):
                    yield Label("Range:")
                    yield Button("7 days", id="range-7")
                    yield Button("30 days", id="range-30", variant="primary")
                    yield Button("90 days", id="range-90")
                    yield Static("", id="overview-rates", classes="status")

                yield Static("", id="overview-highlight", classes="review-item")

                yield Label("Global Daily Completion", classes="section-heading")
                yield Sparkline([], id="overview-sparkline")
                yield Static("", id="overview-chart-bar", markup=True)

                yield Label("Habit Performance Table", classes="section-heading")
                yield DataTable(id="overview-table")

        yield Footer()

    async def on_mount(self) -> None:
        self.query_one("#overview-table", DataTable).add_columns(
            "Habit", "30-Day Rate", "Current Streak", "Best Streak"
        )
        self._adapt_layout(self.size.width)
        await self.refresh_data()
        self.query_one("#habit-list", ListView).focus()

    def on_resize(self, event: Resize) -> None:
        self._adapt_layout(event.size.width)

    def _adapt_layout(self, width: int) -> None:
        is_compact = width < 90
        if is_compact != self._compact:
            self._compact = is_compact
            self.run_worker(self.refresh_data, exclusive=True)

    def on_screen_resume(self) -> None:
        self.run_worker(self.refresh_data, exclusive=True)

    async def refresh_data(self) -> None:
        try:
            self.habits = core.list_habits(
                include_archived=self.show_archived,
                date=self.selected_date,
            )
            # Update date label
            date_str = self.selected_date.strftime("%A, %B %d, %Y")
            if self.selected_date == clock.today():
                date_str += " (Today)"
            self.query_one("#selected-date-label", Label).update(date_str)

            # Next day disabled if today
            self.query_one("#next-day", Button).disabled = self.selected_date >= clock.today()

            # Populate habit list
            habit_list = self.query_one("#habit-list", ListView)
            await habit_list.clear()

            today_val = clock.today()
            for h in self.habits:
                sym = STATUS_SYMBOLS.get(h["status_today"], "[dim]·[/dim]")
                status_name = h["status_today"].replace("_", " ")

                # Compute last 7 days symbols up to selected_date
                s_7d = self.selected_date - timedelta(days=6)
                cal_7d = core.habit_calendar(
                    h["id"],
                    start_date=s_7d,
                    end_date=self.selected_date,
                    reference_date=today_val,
                )
                symbols_7d = " ".join(STATUS_SYMBOLS.get(item["status"], "·") for item in cal_7d)

                rate_str = f"{h['rate_30d']}%" if h.get("rate_30d") is not None else "N/A"
                streak_str = f"{h['current_streak']}-day streak"

                arch_badge = "[ARCHIVED] " if h.get("archived") else ""
                title_line = f"{sym} {arch_badge}{h['name']}"

                if self._compact:
                    row_text = f"{title_line} · {streak_str} · {rate_str}\n{symbols_7d}"
                else:
                    row_text = (
                        f"{title_line} · Status: {status_name} · {streak_str} · 30d: {rate_str}\n"
                        f"  Last 7d: {symbols_7d}"
                    )

                classes = "habit-row archived" if h.get("archived") else "habit-row"
                await habit_list.append(ListItem(Static(row_text, markup=True), classes=classes))

            self.query_one("#habits-count", Static).update(f"{len(self.habits)} habit(s)")

            # Select previous or first item if available
            if self.habits:
                habit_list.index = 0
                self.selected_habit = self.habits[0]
            else:
                self.selected_habit = None

            await self._refresh_overview()
        except (OSError, ValueError) as error:
            self.app.notify(str(error), title="Could not load habits", severity="error")

    async def _refresh_overview(self) -> None:
        today_val = clock.today()
        summary = core.habits_summary(end_date=today_val)

        r7 = f"{summary['rate_7d']}%" if summary.get("rate_7d") is not None else "N/A"
        r30 = f"{summary['rate_30d']}%" if summary.get("rate_30d") is not None else "N/A"
        self.query_one("#overview-rates", Static).update(f"Global 7d: {r7} · 30d: {r30}")

        best = summary.get("best_habit")
        worst = summary.get("worst_habit")
        if best and worst:
            hl_text = (
                f"Best: [green]{best['name']}[/green] ({best['rate_30d']}%)  ·  "
                f"Worst: [red]{worst['name']}[/red] ({worst['rate_30d']}%)"
            )
        else:
            hl_text = "Best/Worst: Requires at least 2 habits with data."
        self.query_one("#overview-highlight", Static).update(hl_text)

        # Overview chart
        start_d = today_val - timedelta(days=self.overview_range_days - 1)
        series = core.habits_series(start_d, today_val, reference_date=today_val)

        spark_points = [
            float(item["percent"]) if item["percent"] is not None else 0.0
            for item in series
        ]
        self.query_one("#overview-sparkline", Sparkline).data = spark_points

        chart_bars = "".join(_format_rate_bar(item["percent"]) for item in series)
        self.query_one("#overview-chart-bar", Static).update(chart_bars)

        # Overview Table
        table = self.query_one("#overview-table", DataTable)
        table.clear()
        for item in summary.get("habits", []):
            rate_disp = f"{item['rate_30d']}%" if item["rate_30d"] is not None else "N/A"
            table.add_row(
                item["name"],
                rate_disp,
                f"{item['current_streak']} days",
                f"{item['best_streak']} days",
            )

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        idx = event.list_view.index
        if idx is not None and idx < len(self.habits):
            self.selected_habit = self.habits[idx]

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        idx = event.list_view.index
        if idx is not None and idx < len(self.habits):
            self.selected_habit = self.habits[idx]
            self.action_detail()

    def action_previous_day(self) -> None:
        self.selected_date -= timedelta(days=1)
        self.run_worker(self.refresh_data, exclusive=True)

    def action_next_day(self) -> None:
        if self.selected_date < clock.today():
            self.selected_date += timedelta(days=1)
            self.run_worker(self.refresh_data, exclusive=True)

    def action_today(self) -> None:
        self.selected_date = clock.today()
        self.run_worker(self.refresh_data, exclusive=True)

    def action_mark_done(self) -> None:
        self._set_selected_status("done")

    def action_mark_missed(self) -> None:
        self._set_selected_status("missed")

    def action_mark_excused(self) -> None:
        self._set_selected_status("skipped")

    def action_clear_record(self) -> None:
        self._set_selected_status(None)

    def _set_selected_status(self, status: str | None) -> None:
        if not self.selected_habit:
            return
        hid = self.selected_habit["id"]
        try:
            core.set_habit_status(hid, self.selected_date, status, reference_date=self.selected_date)
            self.run_worker(self.refresh_data, exclusive=True)
            self.app._update_history_bindings()
        except ValueError as err:
            self.app.notify(str(err), severity="warning")

    def action_add_habit(self) -> None:
        self.app.push_screen(
            HabitForm(default_date=self.selected_date),
            lambda res: self.run_worker(self.refresh_data, exclusive=True) if res else None,
        )

    def action_edit_habit(self) -> None:
        if not self.selected_habit:
            return
        self.app.push_screen(
            HabitForm(habit=self.selected_habit),
            lambda res: self.run_worker(self.refresh_data, exclusive=True) if res else None,
        )

    def action_toggle_archive(self) -> None:
        if not self.selected_habit:
            return
        try:
            new_arch = not self.selected_habit.get("archived", False)
            core.archive_habit(self.selected_habit["id"], archived=new_arch)
            self.run_worker(self.refresh_data, exclusive=True)
            self.app._update_history_bindings()
        except ValueError as err:
            self.app.notify(str(err), severity="warning")

    def action_delete_habit(self) -> None:
        if not self.selected_habit:
            return
        h = self.selected_habit
        self.app.push_screen(
            ConfirmDialog(
                f'Delete habit "{h["name"]}"?\nLog records will be preserved.',
                confirm_label="Delete",
            ),
            lambda confirmed: self._on_delete_confirmed(h["id"]) if confirmed else None,
        )

    def _on_delete_confirmed(self, habit_id: str) -> None:
        try:
            core.delete_habit(habit_id)
            self.run_worker(self.refresh_data, exclusive=True)
            self.app._update_history_bindings()
        except ValueError as err:
            self.app.notify(str(err), severity="warning")

    def action_detail(self) -> None:
        if not self.selected_habit:
            return
        self.app.push_screen(
            HabitDetailModal(self.selected_habit["id"], reference_date=self.selected_date),
            lambda res: self.run_worker(self.refresh_data, exclusive=True),
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if btn_id == "undo":
            self.app.action_undo()
        elif btn_id == "redo":
            self.app.action_redo()
        elif btn_id == "open-agenda":
            self.app.switch_mode("default")
        elif btn_id == "open-week":
            self.app.switch_mode("week")
        elif btn_id == "open-tasks":
            self.app.switch_mode("tasks")
        elif btn_id == "open-events":
            self.app.switch_mode("events")
        elif btn_id == "open-notes":
            self.app.switch_mode("notes")
        elif btn_id == "prev-day":
            self.action_previous_day()
        elif btn_id == "next-day":
            self.action_next_day()
        elif btn_id == "today-btn":
            self.action_today()
        elif btn_id == "add-habit":
            self.action_add_habit()
        elif btn_id == "toggle-archived":
            self.show_archived = not self.show_archived
            event.button.label = "Hide archived" if self.show_archived else "Show archived"
            self.run_worker(self.refresh_data, exclusive=True)
        elif btn_id == "btn-done":
            self.action_mark_done()
        elif btn_id == "btn-missed":
            self.action_mark_missed()
        elif btn_id == "btn-excused":
            self.action_mark_excused()
        elif btn_id == "btn-clear":
            self.action_clear_record()
        elif btn_id == "btn-detail":
            self.action_detail()
        elif btn_id == "btn-edit":
            self.action_edit_habit()
        elif btn_id == "btn-archive":
            self.action_toggle_archive()
        elif btn_id == "btn-delete":
            self.action_delete_habit()
        elif btn_id in ("range-7", "range-30", "range-90"):
            self._set_range(int(btn_id.split("-")[1]))

    def _set_range(self, days: int) -> None:
        self.overview_range_days = days
        for r in (7, 30, 90):
            btn = self.query_one(f"#range-{r}", Button)
            btn.variant = "primary" if r == days else "default"
        self.run_worker(self._refresh_overview, exclusive=True)
