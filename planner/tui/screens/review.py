from datetime import date, timedelta
from typing import Any, Literal

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.events import Resize
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, Footer, Input, Label, Static

from planner import clock, core, review
from planner.review import ReviewCandidate, ReviewCandidateSummary, ReviewSession
from planner.tui.screens.confirm_dialog import ConfirmDialog
from planner.tui.screens.habit_form import HabitForm
from planner.tui.screens.task_form import TaskForm

ReviewMode = Literal["plan", "close"]

REASON_LABELS = {
    "overdue": "Overdue",
    "due_today": "Due today",
    "due_soon": "Due within three days",
    "high_priority": "High priority and unplanned",
    "unscheduled": "Unscheduled",
}
PRIORITY_LABELS = {"alta": "High", "media": "Medium", "baja": "Low"}


class ReviewSettingsDialog(ModalScreen[bool]):
    def __init__(self, settings: dict[str, object]) -> None:
        super().__init__()
        self.settings = settings

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog form-dialog"):
            yield Label("Review settings", classes="dialog-title")
            yield Label("Planning day starts (HH:MM)")
            yield Input(
                value=str(self.settings["day_start"]),
                id="review-day-start",
            )
            yield Label("Planning day ends (HH:MM)")
            yield Input(value=str(self.settings["day_end"]), id="review-day-end")
            yield Label("Default block duration (minutes)")
            yield Input(
                value=str(self.settings["default_duration_minutes"]),
                id="review-default-duration",
            )
            yield Label("Unscheduled tasks per page")
            yield Input(
                value=str(self.settings["max_candidates"]),
                id="review-max-candidates",
            )
            yield Static("", classes="field-error", id="review-settings-error")
            with Horizontal(classes="form-actions"):
                yield Button("Cancel", id="cancel")
                yield Button(
                    "Save settings",
                    id="save-review-settings",
                    variant="primary",
                )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(False)
            return
        if event.button.id != "save-review-settings":
            return
        duration_text = self.query_one("#review-default-duration", Input).value.strip()
        max_candidates_text = self.query_one(
            "#review-max-candidates",
            Input,
        ).value.strip()
        try:
            if not duration_text.isascii() or not duration_text.isdigit():
                raise ValueError(
                    "Default duration must be a positive number of minutes."
                )
            if not max_candidates_text.isascii() or not max_candidates_text.isdigit():
                raise ValueError("Unscheduled task limit must be a positive integer.")
            core.save_settings(
                day_start=self.query_one("#review-day-start", Input).value.strip(),
                day_end=self.query_one("#review-day-end", Input).value.strip(),
                default_duration_minutes=int(duration_text),
                max_candidates=int(max_candidates_text),
            )
        except (OSError, ValueError) as error:
            self.query_one("#review-settings-error", Static).update(str(error))
            return
        self.dismiss(True)


class ReviewScreen(Screen):
    BINDINGS = [
        ("escape", "exit_review", "Exit review"),
        ("q", "exit_review", "Exit review"),
        ("a", "add_item", "Add task"),
        ("s", "schedule_or_reschedule", "Schedule / reschedule"),
        ("k", "skip_or_leave", "Skip / leave"),
        ("d", "defer", "Defer"),
        ("x", "drop_task", "Drop"),
        ("g", "show_more", "Show more"),
        ("m", "mark_done", "Done"),
        ("w", "worked_on", "Worked on it"),
        ("e", "excused", "Excused"),
        ("c", "catch_up", "Catch up"),
        ("l", "leave_block", "Leave"),
        ("o", "open_agenda", "Open agenda"),
        Binding("u", "undo", "Undo", id="undo"),
        Binding("U", "redo", "Redo", id="redo"),
        Binding("ctrl+r", "redo", "Redo", show=False),
    ]

    def __init__(
        self,
        mode: ReviewMode,
        review_date: date | None = None,
    ) -> None:
        super().__init__()
        self.mode = mode
        self.review_date = review_date or (
            clock.today() + timedelta(days=1) if mode == "plan" else clock.today()
        )
        self.session = ReviewSession(self.mode, self.review_date)
        self.settings: dict[str, object] = {}
        self.suggested_slot: tuple[str, str] | None = None
        self._compact: bool = False

    @property
    def candidates(self) -> list[ReviewCandidate]:
        return self.session.candidates

    @candidates.setter
    def candidates(self, val: list[ReviewCandidate]) -> None:
        self.session.candidates = val

    @property
    def candidate_summary(self) -> ReviewCandidateSummary:
        return self.session.candidate_summary

    @candidate_summary.setter
    def candidate_summary(self, val: ReviewCandidateSummary) -> None:
        self.session.candidate_summary = val

    @property
    def unscheduled_limit(self) -> int:
        return self.session.unscheduled_limit

    @unscheduled_limit.setter
    def unscheduled_limit(self, val: int) -> None:
        self.session.unscheduled_limit = val

    @property
    def missed(self) -> list[core.BlockAgendaEntry]:
        return self.session.missed

    @missed.setter
    def missed(self, val: list[core.BlockAgendaEntry]) -> None:
        self.session.missed = val

    @property
    def index(self) -> int:
        return self.session.current_index

    @index.setter
    def index(self, val: int) -> None:
        self.session.current_index = val

    @property
    def finished(self) -> bool:
        return self.session.finished

    @finished.setter
    def finished(self, val: bool) -> None:
        self.session.finished = val

    @property
    def rescheduled(self) -> list[str]:
        return self.session.rescheduled

    @rescheduled.setter
    def rescheduled(self, val: list[str]) -> None:
        self.session.rescheduled = val

    @property
    def created_count(self) -> int:
        return self.session.created_count

    def compose(self) -> ComposeResult:
        title = "PLAN TOMORROW" if self.mode == "plan" else "CLOSE THE DAY"
        with Horizontal(classes="top-nav"):
            yield Label(title, classes="brand")
            yield Button("Undo", id="undo")
            yield Button("Redo", id="redo")
            if self.mode == "plan":
                yield Button("Add task", id="review-add-task", variant="primary")
            yield Button("Review settings", id="review-settings")
            yield Button("Exit", id="exit-review")
        with Horizontal(id="review-layout"):
            with Vertical(id="review-main"):
                yield Label("", id="review-progress", classes="section-heading")
                yield Static("", id="review-item", classes="review-item")
                with Horizontal(classes="review-fields"):
                    yield Label("Date", id="review-date-label")
                    yield Input(placeholder="YYYY-MM-DD", id="review-date")
                    yield Label("Start")
                    yield Input(placeholder="09:00", id="review-start")
                    yield Label("End")
                    yield Input(placeholder="10:00", id="review-end")
                    yield Label("Duration (minutes)")
                    yield Input(value="60", id="review-duration")
                    yield Button("Suggest", id="suggest-slot")
                yield Label("New due date (YYYY-MM-DD)", id="review-due-label")
                yield Input(placeholder="YYYY-MM-DD", id="review-due")
                with Horizontal(classes="action-bar", id="plan-actions"):
                    yield Button("Schedule", id="schedule", variant="primary")
                    yield Button("Skip", id="skip")
                    yield Button("Defer", id="defer")
                    yield Button("Drop", id="drop", variant="error")
                with Horizontal(classes="action-bar", id="close-actions"):
                    yield Button("Done", id="done", variant="success")
                    yield Button("Worked on it", id="worked-on")
                    yield Button("Reschedule", id="reschedule", variant="primary")
                    yield Button("Defer", id="close-defer")
                    yield Button("Leave", id="leave")
                with Horizontal(classes="action-bar", id="habit-actions"):
                    yield Button("Done (d)", id="habit-done", variant="success")
                    yield Button("Missed (m)", id="habit-missed", variant="error")
                    yield Button("Excused (e)", id="habit-excused")
                    yield Button("Later (k)", id="habit-later")
                    yield Button("Add habit (a)", id="habit-add")
                    yield Button("Catch up (c)", id="habit-catch-up")
                yield Static("", id="review-message", classes="status")
                yield Static("", id="review-final", classes="review-final")
                with Horizontal(classes="action-bar", id="final-actions"):
                    yield Button("Show more", id="show-more", variant="primary")
                    yield Button("Plan tomorrow", id="plan-tomorrow", variant="primary")
                    yield Button("Open agenda", id="open-agenda", variant="primary")
                    yield Button("Return", id="return")
            with VerticalScroll(id="review-sidebar", can_focus=True):
                yield Label("", id="review-sidebar-heading", classes="section-heading")
                yield Static("", id="review-agenda", classes="review-agenda", markup=False)
        yield Footer()

    async def on_mount(self) -> None:
        self.query_one("#plan-actions", Horizontal).display = self.mode == "plan"
        self.query_one("#close-actions", Horizontal).display = False
        self.query_one("#habit-actions", Horizontal).display = False
        self.query_one("#review-date-label", Label).display = self.mode == "close"
        self.query_one("#review-date", Input).display = self.mode == "close"
        self.query_one("#review-date", Input).value = self.review_date.isoformat()
        self.query_one("#review-due-label", Label).display = False
        self.query_one("#review-due", Input).display = False
        self.query_one("#final-actions", Horizontal).display = False
        self.query_one("#show-more", Button).display = False
        self.query_one("#open-agenda", Button).display = False
        try:
            self.settings = core.load_settings()
            self.session.unscheduled_limit = int(self.settings["max_candidates"])
            self.session.initialize()
            if self.mode == "plan":
                self.query_one("#review-sidebar-heading", Label).update(
                    f"Tomorrow · {self.review_date:%a %d %b}"
                )
                self._show_plan_candidate()
            else:
                self.query_one("#review-sidebar-heading", Label).update(
                    f"Today · {self.review_date:%a %d %b}"
                )
                if self.session.phase == "blocks":
                    self.query_one("#close-actions", Horizontal).display = True
                    self._show_missed_block()
                elif self.session.phase == "habits":
                    self._show_habit_step()
                else:
                    self._finish_close()
            self._adapt_layout(self.size.width)
            self._refresh_sidebar()
            self.app._update_history_bindings()
        except (OSError, ValueError) as error:
            self.query_one("#review-progress", Label).update("Review unavailable")
            self.query_one("#review-item", Static).update(str(error))
            self._warn(str(error))

    def on_resize(self, event: Resize) -> None:
        self._adapt_layout(event.size.width)

    def _adapt_layout(self, width: int) -> None:
        layout = self.query_one("#review-layout", Horizontal)
        sidebar = self.query_one("#review-sidebar")
        main = self.query_one("#review-main")
        is_compact = width < 90
        if is_compact != self._compact:
            self._compact = is_compact
            if is_compact:
                layout.add_class("compact")
                layout.move_child(sidebar, before=main)
            else:
                layout.remove_class("compact")
                layout.move_child(sidebar, after=main)
            self._refresh_sidebar()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id in {"review-start", "review-end"}:
            self._refresh_sidebar()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "undo":
            self.action_undo()
        elif button_id == "redo":
            self.action_redo()
        elif button_id == "review-add-task":
            self.action_add_item()
        elif button_id == "review-settings":
            self.app.push_screen(
                ReviewSettingsDialog(self.settings),
                self._settings_saved,
            )
        elif button_id == "exit-review" or button_id == "return":
            self.action_exit_review()
        elif button_id == "open-agenda":
            self.action_open_agenda()
        elif button_id == "suggest-slot":
            self._suggest_current_slot()
        elif button_id in {"schedule", "reschedule"}:
            self.action_schedule_or_reschedule()
        elif button_id == "skip":
            self.action_skip_or_leave()
        elif button_id == "defer":
            self.action_defer()
        elif button_id == "drop":
            self.action_drop_task()
        elif button_id == "done":
            self.action_mark_done()
        elif button_id == "worked-on":
            self.action_worked_on()
        elif button_id == "close-defer":
            self.action_defer()
        elif button_id == "leave":
            self.action_leave_block()
        elif button_id == "habit-done":
            self.action_habit_done()
        elif button_id == "habit-missed":
            self.action_habit_missed()
        elif button_id == "habit-excused":
            self.action_habit_excused()
        elif button_id == "habit-later":
            self.action_habit_later()
        elif button_id == "habit-add":
            self.action_add_item()
        elif button_id == "habit-catch-up":
            self.action_catch_up()
        elif button_id == "plan-tomorrow":
            self.app.push_screen(ReviewScreen("plan"))
        elif button_id == "show-more":
            self.action_show_more()

    def action_undo(self) -> None:
        self.app.action_undo()

    def action_redo(self) -> None:
        self.app.action_redo()

    def action_add_item(self) -> None:
        if self.mode == "close" and self.session.phase == "habits":
            self.app.push_screen(
                HabitForm(default_date=self.review_date),
                self._after_habit_form,
            )
        else:
            self.add_item()

    def _after_habit_form(self, habit: dict[str, Any] | None) -> None:
        if not habit:
            return
        self.session.record_habit_created(habit)
        self._show_habit_step()
        self.app._update_history_bindings()

    def add_item(self) -> None:
        self.app.push_screen(
            TaskForm(default_date=self.review_date),
            self._after_task_form,
        )

    def _after_task_form(self, saved: bool | None) -> None:
        if not saved:
            return
        all_tasks = core.load_tasks()
        known_ids = {c["task"].id for c in self.candidates}
        for task in reversed(all_tasks):
            if task.id not in known_ids and not task.deleted:
                self.session.record_task_created(task)
                break
        self._show_plan_candidate()
        self._refresh_sidebar()
        self.app._update_history_bindings()

    def on_history_action(self, action_type: str, result: core.HistoryResult) -> None:
        if action_type == "undo":
            self.session.handle_undo(result.affected_ids)
        else:
            self.session.handle_redo(result.affected_ids)

        if self.mode == "plan":
            if self.session.finished:
                self._finish_plan()
            else:
                self.finished = False
                self.query_one("#final-actions", Horizontal).display = False
                self.query_one("#review-item", Static).display = True
                self.query_one(".review-fields", Horizontal).display = True
                self.query_one("#plan-actions", Horizontal).display = True
                self.query_one("#review-due-label", Label).display = True
                self.query_one("#review-due", Input).display = True
                self._show_plan_candidate()
        else:
            if self.session.finished:
                self._finish_close()
            else:
                self.finished = False
                self.query_one("#final-actions", Horizontal).display = False
                if self.session.phase == "blocks":
                    self.query_one("#review-item", Static).display = True
                    self.query_one(".review-fields", Horizontal).display = True
                    self.query_one("#close-actions", Horizontal).display = True
                    self.query_one("#habit-actions", Horizontal).display = False
                    self.query_one("#review-due-label", Label).display = True
                    self.query_one("#review-due", Input).display = True
                    self._show_missed_block()
                else:
                    self._show_habit_step()
        self._refresh_sidebar()

    def action_show_more(self) -> None:
        if self.mode != "plan" or not self.finished:
            return
        try:
            self.session.unscheduled_limit += int(self.settings["max_candidates"])
            self.session.candidate_summary = core.review_candidate_summary(
                self.review_date
            )
            candidates = core.review_candidates(
                self.review_date,
                unscheduled_limit=self.session.unscheduled_limit,
            )
            known_ids = {candidate["task"].id for candidate in self.candidates}
            new_candidates = [
                candidate
                for candidate in candidates
                if candidate["task"].id not in known_ids
            ]
            if not new_candidates:
                self._finish_plan()
                return
            self.candidates.extend(new_candidates)
            self.session.current_index = len(self.candidates) - len(new_candidates)
            self.session.finished = False
            self.query_one("#final-actions", Horizontal).display = False
            self.query_one("#review-item", Static).display = True
            self.query_one(".review-fields", Horizontal).display = True
            self.query_one("#plan-actions", Horizontal).display = True
            self.query_one("#review-due-label", Label).display = True
            self.query_one("#review-due", Input).display = True
            self._show_plan_candidate()
        except (OSError, ValueError) as error:
            self._warn(str(error))

    def action_exit_review(self) -> None:
        self.app.pop_screen()

    def action_schedule_or_reschedule(self) -> None:
        if self.finished:
            return
        if self.mode == "plan":
            candidate = self.candidates[self.index]
            task = candidate["task"]
            block_date = self.review_date
            reschedule = False
        else:
            entry = self.missed[self.index]
            task = entry["task"]
            block = entry["block"]
            block_date_text = self.query_one("#review-date", Input).value.strip()
            try:
                block_date = core.parse_date(block_date_text)
            except ValueError as error:
                self._warn(str(error))
                return
            reschedule = True

        start = self.query_one("#review-start", Input).value.strip()
        end = self.query_one("#review-end", Input).value.strip()
        try:
            if reschedule:
                core.reschedule_block(task.id, block.id, block_date, start, end)
                summary_str = f"{task.title} → {block_date.isoformat()} {start}-{end}"
                self.session.record_reschedule(task.id, block.id, summary_str)
                self._show_missed_block()
                self._refresh_sidebar()
            else:
                core.plan_block(task.id, block_date.isoformat(), start, end)
                self.session.record_schedule(task.id)
                self._show_plan_candidate()
                self._refresh_sidebar()
            self.app._update_history_bindings()
        except (OSError, ValueError) as error:
            self._warn(str(error))

    def action_skip_or_leave(self) -> None:
        if self.finished:
            return
        if self.mode == "plan":
            candidate = self.candidates[self.index]
            self.session.record_skip(candidate["task"].id)
            self._show_plan_candidate()
        else:
            if self.session.phase == "habits" or self.session.in_catch_up:
                self.action_habit_later()
            else:
                self.action_leave_block()

    def action_defer(self) -> None:
        if self.finished:
            return
        if self.mode == "close" and (self.session.phase == "habits" or self.session.in_catch_up):
            self.action_habit_done()
            return
        due_text = self.query_one("#review-due", Input).value.strip()
        try:
            due_date = core.parse_due_date(due_text)
            if due_date is None:
                raise ValueError("Enter a new due date to defer this task.")
            if self.mode == "plan":
                task = self.candidates[self.index]["task"]
            else:
                task = self.missed[self.index]["task"]
            core.defer_task(task.id, due_date)
            self.session.record_defer(task.id)
            if self.mode == "plan":
                self._show_plan_candidate()
            else:
                self._show_missed_block()
            self._refresh_sidebar()
            self.app._update_history_bindings()
        except (OSError, ValueError) as error:
            self._warn(str(error))

    def action_drop_task(self) -> None:
        if self.mode != "plan" or self.finished:
            return
        task = self.candidates[self.index]["task"]
        self.app.push_screen(
            ConfirmDialog(f'Delete task "{task.title}"?', "Delete"),
            lambda confirmed: self._drop_confirmed(task, confirmed),
        )

    def action_mark_done(self) -> None:
        if self.mode != "close" or self.finished:
            return
        if self.session.phase == "habits" or self.session.in_catch_up:
            self.action_habit_missed()
            return
        entry = self.missed[self.index]
        try:
            core.complete_block(
                entry["task"].id,
                entry["block"].id,
                complete_task=True,
                reference_date=self.review_date,
            )
            for missed_entry in self.missed:
                if missed_entry["task"].id == entry["task"].id:
                    missed_entry["task"].done = True
                if missed_entry["block"].id == entry["block"].id:
                    missed_entry["block"].status = "done"
            self.session.record_done(entry["task"].id)
            self._show_missed_block()
            self._refresh_sidebar()
            self.app._update_history_bindings()
        except (OSError, ValueError) as error:
            self._warn(str(error))

    def action_worked_on(self) -> None:
        if self.mode != "close" or self.finished:
            return
        if self.session.phase != "blocks":
            return
        entry = self.missed[self.index]
        try:
            core.complete_block(
                entry["task"].id,
                entry["block"].id,
                complete_task=False,
                reference_date=self.review_date,
            )
            for missed_entry in self.missed:
                if missed_entry["block"].id == entry["block"].id:
                    missed_entry["block"].status = "done"
            self.session.record_worked_on(entry["task"].id, entry["block"].id)
            self._show_missed_block()
            self._refresh_sidebar()
            self.app._update_history_bindings()
        except (OSError, ValueError) as error:
            self._warn(str(error))

    def action_leave_block(self) -> None:
        if self.mode != "close" or self.finished:
            return
        entry = self.missed[self.index]
        self.session.record_leave(entry["task"].id)
        self._show_missed_block()

    def action_habit_done(self) -> None:
        self._record_habit_choice("done")

    def action_habit_missed(self) -> None:
        self._record_habit_choice("missed")

    def action_habit_excused(self) -> None:
        self._record_habit_choice("skipped")

    def action_habit_later(self) -> None:
        if self.session.in_catch_up:
            if self.session.catch_up_index < len(self.session.catch_up_items):
                item = self.session.catch_up_items[self.session.catch_up_index]
                self.session.record_catch_up_skip(item["habit"]["id"], item["date"])
        else:
            if self.session.habit_index < len(self.session.habits):
                h = self.session.habits[self.session.habit_index]
                self.session.record_habit_skip(h["id"])
        self._show_habit_step()

    def action_excused(self) -> None:
        if self.mode == "close" and (self.session.phase == "habits" or self.session.in_catch_up):
            self.action_habit_excused()

    def action_catch_up(self) -> None:
        if self.mode == "close" and self.session.phase == "habits":
            items = self.session.start_catch_up()
            if items:
                self._clear_message()
                self._show_habit_step()

    def _record_habit_choice(self, status: str) -> None:
        try:
            if self.session.in_catch_up:
                if self.session.catch_up_index < len(self.session.catch_up_items):
                    item = self.session.catch_up_items[self.session.catch_up_index]
                    core.set_habit_status(
                        item["habit"]["id"],
                        item["date"],
                        status,
                        reference_date=self.review_date,
                    )
                    self.session.record_catch_up_decision(item["habit"]["id"], item["date"], status)
            else:
                if self.session.habit_index < len(self.session.habits):
                    h = self.session.habits[self.session.habit_index]
                    core.set_habit_status(
                        h["id"],
                        self.review_date,
                        status,
                        reference_date=self.review_date,
                    )
                    self.session.record_habit_decision(h["id"], status)
            self._show_habit_step()
            self.app._update_history_bindings()
        except (OSError, ValueError) as error:
            self._warn(str(error))

    def _drop_confirmed(self, task: core.Task, confirmed: bool | None) -> None:
        if not confirmed:
            return
        try:
            core.delete_task(task.id)
            self.session.record_drop(task.id)
            self._show_plan_candidate()
            self._refresh_sidebar()
            self.app._update_history_bindings()
        except (OSError, ValueError) as error:
            self._warn(str(error))

    def _show_plan_candidate(self) -> None:
        if self.index >= len(self.candidates):
            self._finish_plan()
            return
        candidate = self.candidates[self.index]
        task = candidate["task"]
        total_candidates = (
            self.candidate_summary["urgent_count"]
            + self.candidate_summary["unscheduled_count"]
            + self.session.created_count
        )
        created_badge = (
            f" (+{self.session.created_count} created)"
            if self.session.created_count > 0
            else ""
        )
        self.query_one("#review-progress", Label).update(
            f"{self.index + 1} / {total_candidates}{created_badge}"
        )
        due = task.due.isoformat() if task.due else "No due date"
        self.query_one("#review-item", Static).update(
            f"{task.title}\nDue: {due} · Priority: "
            f"{PRIORITY_LABELS.get(task.priority, task.priority)} · "
            f"Reason: {REASON_LABELS[candidate['reason']]}"
        )
        self.query_one("#review-duration", Input).value = str(
            self.settings["default_duration_minutes"]
        )
        self.query_one("#review-due-label", Label).display = True
        self.query_one("#review-due", Input).display = True
        self.query_one("#review-due", Input).value = (
            (task.due or self.review_date) + timedelta(days=1)
        ).isoformat()
        self._clear_message()
        self._suggest_current_slot()

    def _show_missed_block(self) -> None:
        while (
            self.index < len(self.missed)
            and (
                self.missed[self.index]["task"].done
                or getattr(self.missed[self.index]["block"], "status", "planned") == "done"
            )
        ):
            self.index += 1
        if self.index >= len(self.missed):
            if self.session.habits:
                self._show_habit_step()
            else:
                self._finish_close()
            return
        entry = self.missed[self.index]
        task = entry["task"]
        block = entry["block"]
        self.query_one("#review-progress", Label).update(
            f"{self.index + 1} / {len(self.missed)}"
        )
        self.query_one("#review-item", Static).update(
            f"{task.title}\nPlanned: {block.date.isoformat()} · "
            f"{block.start}-{block.end}"
        )
        self.query_one("#review-due-label", Label).display = True
        self.query_one("#review-due", Input).display = True
        self.query_one("#review-due", Input).value = (
            self.review_date + timedelta(days=1)
        ).isoformat()
        self.query_one("#review-duration", Input).value = str(
            core.duration_minutes(block.start, block.end)
        )
        self._clear_message()
        self._suggest_reschedule_slot()

    def _show_habit_step(self) -> None:
        if self.session.in_catch_up:
            if self.session.catch_up_index >= len(self.session.catch_up_items):
                self.session.in_catch_up = False
                self._show_habit_step()
                return
            item = self.session.catch_up_items[self.session.catch_up_index]
            h = item["habit"]
            d_str = item["date"]
            self.query_one("#review-progress", Label).update(
                f"Catching up ({d_str}) · {self.session.catch_up_index + 1} / {len(self.session.catch_up_items)}"
            )
            self.query_one("#review-item", Static).update(
                f"{h['name']}\nDate: {d_str} · Status: unlogged"
            )
        else:
            if self.session.habit_index >= len(self.session.habits):
                self._finish_close()
                return
            h = self.session.habits[self.session.habit_index]
            status_str = h.get("status", "unlogged")
            streak = h.get("current_streak", 0)
            self.query_one("#review-progress", Label).update(
                f"Habits {self.session.habit_index + 1} / {len(self.session.habits)}"
            )
            self.query_one("#review-item", Static).update(
                f"{h['name']}\nCurrent streak: {streak}-day streak · Status: {status_str}"
            )

        self.query_one("#review-item", Static).display = True
        self.query_one(".review-fields", Horizontal).display = False
        self.query_one("#review-date-label", Label).display = False
        self.query_one("#review-date", Input).display = False
        self.query_one("#review-due-label", Label).display = False
        self.query_one("#review-due", Input).display = False
        self.query_one("#plan-actions", Horizontal).display = False
        self.query_one("#close-actions", Horizontal).display = False
        self.query_one("#habit-actions", Horizontal).display = True

        if not self.session.in_catch_up and self.session.habit_index == 0:
            unlogged = core.habits_unlogged(days=3, end_date=self.review_date)
            if unlogged:
                count_days = len(unlogged)
                day_word = "day" if count_days == 1 else "days"
                self._set_message(
                    f"{count_days} earlier {day_word} have unlogged habits. Press [c] to catch up."
                )
                self.query_one("#habit-catch-up", Button).display = True
            else:
                self.query_one("#habit-catch-up", Button).display = False
        else:
            self.query_one("#habit-catch-up", Button).display = False

    def action_open_agenda(self) -> None:
        target_date = self.review_date
        self.app.pop_screen()
        from planner.tui.screens.agenda import AgendaScreen

        if isinstance(self.app.screen, AgendaScreen):
            self.app.screen.selected_date = target_date
            self.app.screen.run_worker(self.app.screen.refresh_data, exclusive=True)
        else:
            self.app.push_screen(AgendaScreen(selected_date=target_date))

    def _suggest_current_slot(self) -> None:
        try:
            duration = self._duration()
            slot = core.suggest_slot(
                self.review_date,
                duration,
                str(self.settings["day_start"]),
                str(self.settings["day_end"]),
            )
        except (OSError, ValueError) as error:
            self._warn(str(error))
            return
        self.suggested_slot = slot
        if slot is None:
            self.query_one("#review-start", Input).value = ""
            self.query_one("#review-end", Input).value = ""
            self._set_message(
                "No free slot fits this duration. Adjust the duration or "
                "enter times manually."
            )
            self._refresh_sidebar()
            return
        self.query_one("#review-start", Input).value = slot[0]
        self.query_one("#review-end", Input).value = slot[1]
        self._clear_message()
        self._refresh_sidebar()

    def _suggest_reschedule_slot(self) -> None:
        try:
            suggestion = core.suggest_next_slot(
                self.review_date,
                self._duration(),
                str(self.settings["day_start"]),
                str(self.settings["day_end"]),
            )
        except (OSError, ValueError) as error:
            self._warn(str(error))
            return
        if suggestion is None:
            self.query_one("#review-start", Input).value = ""
            self.query_one("#review-end", Input).value = ""
            self.query_one("#review-message", Static).update(
                "No free slot found within the next year. Enter a date and "
                "times manually."
            )
            return
        target_date, start, end = suggestion
        self.query_one("#review-date", Input).value = target_date.isoformat()
        self.query_one("#review-start", Input).value = start
        self.query_one("#review-end", Input).value = end

    def _duration(self) -> int:
        duration_text = self.query_one("#review-duration", Input).value.strip()
        if not duration_text.isascii() or not duration_text.isdigit():
            raise ValueError("Duration must be a positive number of minutes.")
        duration = int(duration_text)
        if duration <= 0:
            raise ValueError("Duration must be a positive number of minutes.")
        return duration

    def _refresh_sidebar(self) -> None:
        try:
            overview = core.day_review_overview(
                self.review_date,
                str(self.settings["day_start"]),
                str(self.settings["day_end"]),
            )
        except (OSError, ValueError) as error:
            self._warn(str(error))
            return

        date_str = f"{self.review_date:%a %d %b}"
        if self.mode == "plan":
            self.query_one("#review-sidebar-heading", Label).update(
                f"Tomorrow · {date_str}"
            )
        else:
            self.query_one("#review-sidebar-heading", Label).update(
                f"Today · {date_str}"
            )

        preview_info: tuple[str, str, str, list[core.AgendaEntry]] | None = None
        if not self.finished:
            task_title = ""
            exclude_block_id = None
            if self.mode == "plan" and self.index < len(self.candidates):
                task_title = self.candidates[self.index]["task"].title
            elif self.mode == "close" and self.index < len(self.missed):
                task_title = self.missed[self.index]["task"].title
                exclude_block_id = self.missed[self.index]["block"].id

            if task_title:
                start_val = self.query_one("#review-start", Input).value.strip()
                end_val = self.query_one("#review-end", Input).value.strip()
                try:
                    norm_start = core.normalize_time(start_val, "start")
                    norm_end = core.normalize_time(end_val, "end")
                    if core._time_minutes(norm_start) < core._time_minutes(norm_end):
                        overlaps = core.find_overlaps(
                            self.review_date.isoformat(),
                            norm_start,
                            norm_end,
                            exclude_block_id=exclude_block_id,
                        )
                        preview_info = (norm_start, norm_end, task_title, overlaps)
                        if overlaps:
                            conflict_str = core.format_overlaps(overlaps)
                            self._set_message(
                                f"Warning: proposed time overlaps with {conflict_str}."
                            )
                        else:
                            current_msg = str(
                                self.query_one("#review-message", Static).render()
                            )
                            if "Warning: proposed time overlaps with" in current_msg:
                                self._clear_message()
                except ValueError:
                    pass

        lines: list[str] = []
        if self.mode == "plan":
            lines.append(f"Tomorrow · {date_str}")
            due_summary = core.due_tasks_summary(self.review_date)
            lines.append(
                f"Due tomorrow: {due_summary['total']} ({due_summary['planned']} planned, {due_summary['unplanned']} unplanned)"
            )
            booked_str = core.format_hours(overview["booked_minutes"])
            free_str = core.format_hours(overview["free_minutes"])
            if self._compact:
                lines.append(f"{booked_str} booked · {free_str} free")
            else:
                lines.append(
                    f"{booked_str} booked · {free_str} free · Fixed events: {len(overview['events'])}"
                )
        else:
            lines.append(f"Today · {date_str}")
            booked_str = core.format_hours(overview["booked_minutes"])
            free_str = core.format_hours(overview["free_minutes"])
            lines.append(
                f"{booked_str} booked · {free_str} free · Fixed events: {len(overview['events'])}"
            )

        if not overview["agenda"]:
            empty_msg = (
                "Nothing planned for tomorrow yet"
                if self.mode == "plan"
                else "No items scheduled."
            )
            lines.append(empty_msg)

        timeline = core.review_timeline(
            overview,
            suggested_slot=self.suggested_slot,
            preview=preview_info,
        )
        for item in timeline:
            if self._compact:
                if item["kind"] == "gap":
                    sug = " [Suggested]" if item.get("suggested") else ""
                    lines.append(f"{item['start']}-{item['end']} Free{sug}")
                elif item["kind"] == "block":
                    ov = " [!]" if item.get("overlap") else ""
                    lines.append(f"{item['start']}-{item['end']} [T] {item['title']}{ov}")
                elif item["kind"] == "event":
                    rec = " ↻" if item.get("recurring") else ""
                    ov = " [!]" if item.get("overlap") else ""
                    lines.append(f"{item['start']}-{item['end']} [E] {item['title']}{rec}{ov}")
                elif item["kind"] == "preview":
                    ov = f" [!] {item['conflict_with']}" if item.get("overlap") else ""
                    sug = (
                        " [Suggested]"
                        if item.get("suggested") and not item.get("overlap")
                        else ""
                    )
                    lines.append(
                        f"[?] {item['start']}-{item['end']} [T] {item['title']}{sug}{ov}"
                    )
            else:
                if item["kind"] == "gap":
                    sug = "  [Suggested]" if item.get("suggested") else ""
                    lines.append(f"{item['start']} - {item['end']}   FREE{sug}")
                elif item["kind"] == "block":
                    ov = "  [!]" if item.get("overlap") else ""
                    lines.append(
                        f"{item['start']} - {item['end']}   [T] {item['title']}{ov}"
                    )
                elif item["kind"] == "event":
                    rec = " ↻" if item.get("recurring") else ""
                    ov = "  [!]" if item.get("overlap") else ""
                    lines.append(
                        f"{item['start']} - {item['end']}   [E] {item['title']}{rec}{ov}"
                    )
                elif item["kind"] == "preview":
                    ov = (
                        f"  [!] overlaps with {item['conflict_with']}"
                        if item.get("overlap")
                        else ""
                    )
                    sug = (
                        "  [Suggested]"
                        if item.get("suggested") and not item.get("overlap")
                        else ""
                    )
                    lines.append(
                        f"[?] {item['start']} - {item['end']}   [T] {item['title']}{sug}{ov}"
                    )

        if overview["overlaps"]:
            lines.append("")
            lines.append(
                f"Warning: {len(overview['overlaps'])} overlap(s) in this agenda."
            )
        self.query_one("#review-agenda", Static).update("\n".join(lines))

    def _finish_plan(self) -> None:
        self.finished = True
        self.suggested_slot = None
        created_badge = (
            f" (+{self.session.created_count} created)"
            if self.session.created_count > 0
            else ""
        )
        self.query_one("#review-progress", Label).update(
            f"Plan for {self.review_date:%A, %B %d}{created_badge}"
        )
        self.query_one("#review-item", Static).display = False
        self.query_one(".review-fields", Horizontal).display = False
        self.query_one("#review-due-label", Label).display = False
        self.query_one("#review-due", Input).display = False
        self.query_one("#plan-actions", Horizontal).display = False
        if self.candidates:
            message = "Planning complete. Your choices have been saved as you went."
        elif self.candidate_summary["pending_count"] == 0:
            message = "No pending tasks to plan."
        else:
            message = (
                f"No tasks to add: all {self.candidate_summary['pending_count']} "
                f"pending tasks already have a planned block on or after "
                f"{self.review_date.isoformat()}."
            )
        self.query_one("#review-final", Static).update(message)
        self.query_one("#final-actions", Horizontal).display = True
        has_more = (
            self.candidate_summary["unscheduled_count"] > self.unscheduled_limit
        )
        self.query_one("#show-more", Button).display = has_more
        if has_more:
            remaining = (
                self.candidate_summary["unscheduled_count"] - self.unscheduled_limit
            )
            self.query_one("#show-more", Button).label = (
                f"Show more ({remaining} unscheduled)"
            )
        self.query_one("#plan-tomorrow", Button).display = False
        self.query_one("#open-agenda", Button).display = True
        self._refresh_sidebar()

    def _finish_close(self) -> None:
        try:
            summary = core.day_review_summary(self.review_date)
        except (OSError, ValueError) as error:
            self._warn(str(error))
            return
        self.finished = True
        self.suggested_slot = None
        self.query_one("#review-progress", Label).update(
            f"Day review · {self.review_date:%A, %B %d}"
        )
        self.query_one("#review-item", Static).display = False
        self.query_one(".review-fields", Horizontal).display = False
        self.query_one("#review-due-label", Label).display = False
        self.query_one("#review-due", Input).display = False
        self.query_one("#close-actions", Horizontal).display = False
        self.query_one("#habit-actions", Horizontal).display = False
        habits_today = core.habits_for_day(self.review_date)
        done_habits = [h for h in habits_today if h.get("status") == "done"]
        total_habits = len(habits_today)

        total_blocks = len([
            b for t in core.load_tasks() if not t.deleted
            for b in t.blocks if b.date == self.review_date
        ])

        lines = [
            f"Today: {summary['completed_blocks']}/{total_blocks} blocks done",
            f"Tasks done: {summary['done_tasks']}",
            f"Tasks not done: {summary['not_done_tasks']}",
            f"Blocks completed: {summary['completed_blocks']}",
            f"Minutes planned: {summary['planned_minutes']}",
            f"Minutes completed: {summary['completed_minutes']}",
            f"Tasks rescheduled: {len(self.rescheduled)}",
        ]
        lines.extend(self.rescheduled)
        if total_habits > 0:
            lines.append(f"Habits: {len(done_habits)}/{total_habits} done")
            for h in habits_today:
                streak = h.get("current_streak", 0)
                if streak > 0:
                    lines.append(f"{h['name']}: {streak}-day streak")

        self.query_one("#review-final", Static).update("\n".join(lines))
        if not self.missed:
            self.query_one("#review-final", Static).update(
                "No pending blocks to review.\n" + "\n".join(lines)
            )
        self.query_one("#final-actions", Horizontal).display = True
        self.query_one("#plan-tomorrow", Button).display = True
        self.query_one("#open-agenda", Button).display = False
        self._refresh_sidebar()

    def _settings_saved(self, saved: bool | None) -> None:
        if not saved:
            return
        try:
            self.settings = core.load_settings()
        except (OSError, ValueError) as error:
            self._warn(str(error))
            return
        if self.mode == "plan" and not self.finished:
            self.query_one("#review-duration", Input).value = str(
                self.settings["default_duration_minutes"]
            )
            self._suggest_current_slot()
        elif self.mode == "close" and not self.finished:
            self._suggest_reschedule_slot()
        self._refresh_sidebar()

    def _warn(self, message: str) -> None:
        self.app.notify(message, title="Review action failed", severity="warning")

    def _set_message(self, message: str) -> None:
        self.query_one("#review-message", Static).update(message)

    def _clear_message(self) -> None:
        self.query_one("#review-message", Static).update("")
