from datetime import date
from typing import Any

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, Label, Select, Static

from planner import clock, core
from planner.tui.screens.confirm_dialog import ConfirmDialog


class HabitForm(ModalScreen[dict[str, Any] | None]):
    """Modal screen for creating and editing habits."""

    def __init__(
        self,
        habit: dict[str, Any] | None = None,
        default_date: date | None = None,
    ) -> None:
        super().__init__()
        self.habit_data = habit
        self.default_date = default_date or clock.today()

        # Initial values for unsaved change detection
        self._initial_name = habit.get("name", "") if habit else ""
        self._initial_desc = habit.get("description", "") or "" if habit else ""
        self._initial_start = habit.get("start_date", self.default_date.isoformat()) if habit else self.default_date.isoformat()
        sched = habit.get("schedule", {"type": "daily"}) if habit else {"type": "daily"}
        self._initial_type = sched.get("type", "daily")
        self._initial_days = list(sched.get("days", []))

    def compose(self) -> ComposeResult:
        habit = self.habit_data
        sched = habit.get("schedule", {"type": "daily"}) if habit else {"type": "daily"}
        stype = sched.get("type", "daily")
        days = set(sched.get("days", []))

        with Vertical(classes="dialog form-dialog"):
            yield Label("Edit habit" if habit else "New habit", classes="dialog-title")

            yield Label("Name (1 to 80 characters)")
            yield Input(
                value=habit.get("name", "") if habit else "",
                placeholder="Habit name (e.g. Read 30 minutes)",
                id="habit-name",
            )
            yield Static("", classes="field-error", id="habit-name-error")

            yield Label("Description (optional)")
            yield Input(
                value=habit.get("description", "") or "" if habit else "",
                placeholder="Description",
                id="habit-description",
            )

            yield Label("Frequency")
            yield Select(
                [("Daily", "daily"), ("Specific weekdays", "weekdays")],
                value=stype,
                id="habit-freq-type",
            )

            with Horizontal(id="habit-weekdays-container"):
                yield Checkbox("Mon", value="mon" in days, id="day-mon")
                yield Checkbox("Tue", value="tue" in days, id="day-tue")
                yield Checkbox("Wed", value="wed" in days, id="day-wed")
                yield Checkbox("Thu", value="thu" in days, id="day-thu")
                yield Checkbox("Fri", value="fri" in days, id="day-fri")
                yield Checkbox("Sat", value="sat" in days, id="day-sat")
                yield Checkbox("Sun", value="sun" in days, id="day-sun")
            yield Static("", classes="field-error", id="habit-days-error")

            yield Label("Start date (YYYY-MM-DD or today)")
            yield Input(
                value=habit.get("start_date", self.default_date.isoformat()) if habit else self.default_date.isoformat(),
                placeholder="Start date",
                id="habit-start-date",
            )
            yield Static("", classes="field-error", id="habit-start-error")
            yield Static("", classes="field-error", id="habit-general-error")

            with Horizontal(classes="form-actions"):
                yield Button("Cancel", id="cancel")
                yield Button("Save habit", variant="primary", id="save")

    def on_mount(self) -> None:
        self._update_weekday_visibility()

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "habit-freq-type":
            self._update_weekday_visibility()

    def _update_weekday_visibility(self) -> None:
        val = self.query_one("#habit-freq-type", Select).value
        show_weekdays = val == "weekdays"
        self.query_one("#habit-weekdays-container", Horizontal).display = show_weekdays

    def _get_selected_days(self) -> list[str]:
        selected: list[str] = []
        for day in ("mon", "tue", "wed", "thu", "fri", "sat", "sun"):
            cb = self.query_one(f"#day-{day}", Checkbox)
            if cb.value:
                selected.append(day)
        return selected

    def _has_unsaved_changes(self) -> bool:
        cur_name = self.query_one("#habit-name", Input).value.strip()
        cur_desc = self.query_one("#habit-description", Input).value.strip()
        cur_start = self.query_one("#habit-start-date", Input).value.strip()
        cur_type = self.query_one("#habit-freq-type", Select).value
        cur_days = self._get_selected_days() if cur_type == "weekdays" else []

        return (
            cur_name != self._initial_name
            or cur_desc != self._initial_desc
            or cur_start != self._initial_start
            or cur_type != self._initial_type
            or set(cur_days) != set(self._initial_days)
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            if self._has_unsaved_changes():
                self.app.push_screen(
                    ConfirmDialog("Discard unsaved changes?"),
                    lambda confirmed: self.dismiss(None) if confirmed else None,
                )
            else:
                self.dismiss(None)
            return

        if event.button.id == "save":
            self._save()

    def _save(self) -> None:
        self.query_one("#habit-name-error", Static).update("")
        self.query_one("#habit-days-error", Static).update("")
        self.query_one("#habit-start-error", Static).update("")
        self.query_one("#habit-general-error", Static).update("")

        name = self.query_one("#habit-name", Input).value.strip()
        description = self.query_one("#habit-description", Input).value.strip() or None
        freq_type = self.query_one("#habit-freq-type", Select).value
        start_date_text = self.query_one("#habit-start-date", Input).value.strip()

        if not name:
            self.query_one("#habit-name-error", Static).update("Habit name is required.")
            return

        days = None
        if freq_type == "weekdays":
            days = self._get_selected_days()
            if not days:
                self.query_one("#habit-days-error", Static).update("Select at least one day.")
                return

        try:
            parsed_start = core.parse_date(start_date_text)
        except ValueError as err:
            self.query_one("#habit-start-error", Static).update(str(err))
            return

        try:
            if self.habit_data is None:
                res = core.create_habit(
                    name=name,
                    description=description,
                    days=days,
                    start_date=parsed_start,
                )
            else:
                res = core.edit_habit(
                    self.habit_data["id"],
                    name=name,
                    description=description,
                    days=days,
                    start_date=parsed_start,
                )
            self.dismiss(res)
        except ValueError as err:
            self.query_one("#habit-general-error", Static).update(str(err))

