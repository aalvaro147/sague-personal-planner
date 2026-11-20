from datetime import date, timedelta
from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.events import Resize
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Sparkline, Static

from planner import clock, core
from planner.tui.screens.habit_form import HabitForm


def _render_heatmap_grid(calendar_items: list[dict[str, Any]], num_weeks: int) -> str:
    """Render a 7-row (Mon-Sun) by num_weeks-column ASCII heatmap."""
    items_by_date = {item["date"]: item["status"] for item in calendar_items}
    if not calendar_items:
        return "No calendar data available."

    end_d = core.parse_date(calendar_items[-1]["date"])
    # Align end_d to end of its week (Sunday)
    days_to_sun = 6 - end_d.weekday()
    cal_end = end_d + timedelta(days=days_to_sun)
    cal_start = cal_end - timedelta(days=num_weeks * 7 - 1)

    symbols = {
        "done": "[green]■[/green]",
        "missed": "[red]■[/red]",
        "skipped": "[cyan]■[/cyan]",
        "unlogged": "[yellow]○[/yellow]",
        "not_scheduled": "[dim]·[/dim]",
        "out_of_range": " ",
    }

    weekday_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    lines: list[str] = []

    for w_idx in range(7):
        row_str = f"{weekday_labels[w_idx]} "
        for week_idx in range(num_weeks):
            cell_date = cal_start + timedelta(days=week_idx * 7 + w_idx)
            cell_iso = cell_date.isoformat()
            st = items_by_date.get(cell_iso, "out_of_range")
            sym = symbols.get(st, " ")
            row_str += sym + " "
        lines.append(row_str)

    return "\n".join(lines)


def _render_trend_sparkline_data(calendar_items: list[dict[str, Any]]) -> list[float]:
    """Convert daily statuses into numerical points for Sparkline."""
    data: list[float] = []
    for it in calendar_items:
        st = it["status"]
        if st == "done":
            data.append(100.0)
        elif st == "skipped":
            data.append(50.0)
        elif st == "missed":
            data.append(0.0)
        else:
            data.append(0.0)
    return data


class HabitDetailModal(ModalScreen[bool]):
    """Modal screen displaying detailed habit stats, 26-week heatmap, and 30-day trend."""

    BINDINGS = [
        ("escape", "close", "Close"),
        ("e", "edit", "Edit"),
        ("r", "toggle_archive", "Archive/Unarchive"),
    ]

    def __init__(self, habit_id: str, reference_date: date | None = None) -> None:
        super().__init__()
        self.habit_id = habit_id
        self.reference_date = reference_date or clock.today()
        self.habit: dict[str, Any] = {}
        self.stats: dict[str, Any] = {}
        self._compact: bool = False

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog note-detail-dialog"):
            yield Label("", id="habit-detail-title", classes="dialog-title")
            yield Static("", id="habit-detail-meta", classes="status")

            with ScrollableContainer(id="habit-detail-body"):
                with Horizontal(id="habit-cards-container"):
                    with Vertical(classes="stat-card", id="card-streak"):
                        yield Label("STREAKS", classes="card-heading")
                        yield Static("", id="card-streak-body")
                    with Vertical(classes="stat-card", id="card-rates"):
                        yield Label("COMPLETION RATES", classes="card-heading")
                        yield Static("", id="card-rates-body")
                    with Vertical(classes="stat-card", id="card-weekdays"):
                        yield Label("BY WEEKDAY", classes="card-heading")
                        yield Static("", id="card-weekdays-body")

                yield Label("Heatmap Calendar", classes="section-heading")
                yield Static(
                    "Legend: [green]■[/green] done  [red]■[/red] missed  [cyan]■[/cyan] excused  [yellow]○[/yellow] unlogged  [dim]·[/dim] not scheduled",
                    id="heatmap-legend",
                )
                yield Static("", id="habit-heatmap", markup=True)

                yield Label("30-Day Trend", classes="section-heading")
                yield Sparkline([], id="habit-sparkline")
                yield Static("", id="habit-trend-text")

            with Horizontal(classes="form-actions"):
                yield Button("Edit (e)", id="edit-habit", variant="primary")
                yield Button("Archive (r)", id="archive-habit")
                yield Button("Close (Esc)", id="close")

    def on_mount(self) -> None:
        self._load_data()

    def on_resize(self, event: Resize) -> None:
        is_compact = event.size.width < 90
        if is_compact != self._compact:
            self._compact = is_compact
            self._render_calendar()

    def _load_data(self) -> None:
        habits = core.list_habits(include_archived=True, date=self.reference_date)
        habit = next((h for h in habits if h["id"] == self.habit_id), None)
        if habit is None:
            self.app.notify(f"Habit not found: {self.habit_id}", severity="error")
            self.dismiss(False)
            return

        self.habit = habit
        self.stats = core.habit_stats(self.habit_id, end_date=self.reference_date)

        title = self.habit["name"]
        if self.habit.get("archived"):
            title = f"[ARCHIVED] {title}"
        self.query_one("#habit-detail-title", Label).update(title)

        sched = self.habit.get("schedule", {"type": "daily"})
        if sched.get("type") == "daily":
            sched_str = "Daily"
        else:
            sched_str = "Weekdays: " + ", ".join(sched.get("days", []))
        desc_str = f" · {self.habit['description']}" if self.habit.get("description") else ""
        start_str = f"Started: {self.habit.get('start_date', '')}"
        self.query_one("#habit-detail-meta", Static).update(
            f"{sched_str}{desc_str} · {start_str}"
        )

        # Card 1: Streaks
        cur_streak = self.stats.get("current_streak", 0)
        best_streak = self.stats.get("best_streak", 0)
        self.query_one("#card-streak-body", Static).update(
            f"Current: {cur_streak} days\nBest: {best_streak} days\nTotal done: {self.stats.get('total_done', 0)}"
        )

        # Card 2: Rates
        r7 = f"{self.stats['rate_7d']}%" if self.stats.get("rate_7d") is not None else "N/A"
        r30 = f"{self.stats['rate_30d']}%" if self.stats.get("rate_30d") is not None else "N/A"
        r_all = f"{self.stats['rate_all']}%" if self.stats.get("rate_all") is not None else "N/A"
        self.query_one("#card-rates-body", Static).update(
            f"7-day: {r7}\n30-day: {r30}\nAll-time: {r_all}"
        )

        # Card 3: By Weekday
        by_w = self.stats.get("by_weekday", {})
        w_lines = []
        for w in ("mon", "tue", "wed", "thu", "fri", "sat", "sun"):
            val = by_w.get(w)
            val_str = f"{val}%" if val is not None else "–"
            w_lines.append(f"{w.capitalize()}: {val_str}")
        self.query_one("#card-weekdays-body", Static).update(
            " · ".join(w_lines[:4]) + "\n" + " · ".join(w_lines[4:])
        )

        # Archive button label
        arch_btn = self.query_one("#archive-habit", Button)
        arch_btn.label = "Unarchive (r)" if self.habit.get("archived") else "Archive (r)"

        self._render_calendar()

    def _render_calendar(self) -> None:
        num_weeks = 12 if self._compact else 26
        start_d = self.reference_date - timedelta(days=num_weeks * 7)
        cal = core.habit_calendar(
            self.habit_id,
            start_date=start_d,
            end_date=self.reference_date,
            reference_date=self.reference_date,
        )

        grid_text = _render_heatmap_grid(cal, num_weeks=num_weeks)
        self.query_one("#habit-heatmap", Static).update(grid_text)

        # 30-Day Trend
        t_start = self.reference_date - timedelta(days=29)
        t_cal = core.habit_calendar(
            self.habit_id,
            start_date=t_start,
            end_date=self.reference_date,
            reference_date=self.reference_date,
        )

        spark_data = _render_trend_sparkline_data(t_cal)
        self.query_one("#habit-sparkline", Sparkline).data = spark_data

        symbols = {
            "done": "[green]●[/green]",
            "missed": "[red]✕[/red]",
            "skipped": "[cyan]–[/cyan]",
            "unlogged": "[yellow]○[/yellow]",
            "not_scheduled": "[dim]·[/dim]",
            "out_of_range": " ",
        }
        trend_symbols = " ".join(symbols.get(item["status"], " ") for item in t_cal)
        self.query_one("#habit-trend-text", Static).update(trend_symbols)

    def action_close(self) -> None:
        self.dismiss(True)

    def action_edit(self) -> None:
        self.app.push_screen(
            HabitForm(habit=self.habit),
            lambda res: self._load_data() if res else None,
        )

    def action_toggle_archive(self) -> None:
        try:
            new_arch = not self.habit.get("archived", False)
            core.archive_habit(self.habit_id, archived=new_arch)
            self._load_data()
        except ValueError as err:
            self.app.notify(str(err), severity="warning")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "close":
            self.action_close()
        elif event.button.id == "edit-habit":
            self.action_edit()
        elif event.button.id == "archive-habit":
            self.action_toggle_archive()

