from datetime import date, timedelta
from typing import Literal

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.events import Resize
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, Input, Label, Static

from planner import core
from planner.review import ReviewCandidate, ReviewCandidateSummary
from planner.tui.screens.confirm_dialog import ConfirmDialog

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
        ("s", "schedule_or_reschedule", "Schedule / reschedule"),
        ("k", "skip_or_leave", "Skip / leave"),
        ("d", "defer", "Defer"),
        ("x", "drop_task", "Drop"),
        ("g", "show_more", "Show more"),
        ("m", "mark_done", "Done"),
        ("l", "leave_block", "Leave"),
        ("o", "open_agenda", "Open agenda"),
    ]

    def __init__(
        self,
        mode: ReviewMode,
        review_date: date | None = None,
    ) -> None:
        super().__init__()
        self.mode = mode
        self.review_date = review_date or (
            date.today() + timedelta(days=1) if mode == "plan" else date.today()
        )
        self.settings: dict[str, object] = {}
        self.candidates: list[ReviewCandidate] = []
        self.candidate_summary: ReviewCandidateSummary = {
            "pending_count": 0,
            "scheduled_count": 0,
            "urgent_count": 0,
            "unscheduled_count": 0,
        }
        self.unscheduled_limit = core.MAX_CANDIDATES
        self.missed: list[core.BlockAgendaEntry] = []
        self.index = 0
        self.finished = False
        self.rescheduled: list[str] = []
        self.suggested_slot: tuple[str, str] | None = None
        self._compact: bool = False

    def compose(self) -> ComposeResult:
        title = "PLAN TOMORROW" if self.mode == "plan" else "CLOSE THE DAY"
        with Horizontal(classes="top-nav"):
            yield Label(title, classes="brand")
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
                    yield Button("Reschedule", id="reschedule", variant="primary")
                    yield Button("Defer", id="close-defer")
                    yield Button("Leave", id="leave")
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

    async def on_mount(self) -> None:
        self.query_one("#plan-actions", Horizontal).display = self.mode == "plan"
        self.query_one("#close-actions", Horizontal).display = self.mode == "close"
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
            if self.mode == "plan":
                self.unscheduled_limit = int(self.settings["max_candidates"])
                self.candidate_summary = core.review_candidate_summary(
                    self.review_date
                )
                self.candidates = core.review_candidates(self.review_date)
                self.query_one("#review-sidebar-heading", Label).update(
                    f"Tomorrow · {self.review_date:%a %d %b}"
                )
                self._show_plan_candidate()
            else:
                self.missed = core.missed_blocks(self.review_date)
                self.query_one("#review-sidebar-heading", Label).update(
                    f"Today · {self.review_date:%a %d %b}"
                )
                self._show_missed_block()
            self._adapt_layout(self.size.width)
            self._refresh_sidebar()
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
        if button_id == "review-settings":
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
        elif button_id == "close-defer":
            self.action_defer()
        elif button_id == "leave":
            self.action_leave_block()
        elif button_id == "plan-tomorrow":
            self.app.push_screen(ReviewScreen("plan"))
        elif button_id == "show-more":
            self.action_show_more()

    def action_show_more(self) -> None:
        if self.mode != "plan" or not self.finished:
            return
        try:
            self.unscheduled_limit += int(self.settings["max_candidates"])
            self.candidate_summary = core.review_candidate_summary(
                self.review_date
            )
            candidates = core.review_candidates(
                self.review_date,
                unscheduled_limit=self.unscheduled_limit,
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
            self.index = len(self.candidates) - len(new_candidates)
            self.finished = False
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
                self.rescheduled.append(
                    f"{task.title} → {block_date.isoformat()} {start}-{end}"
                )
                self.index += 1
                self._show_missed_block()
                self._refresh_sidebar()
            else:
                core.plan_block(task.id, block_date.isoformat(), start, end)
                self.index += 1
                self._show_plan_candidate()
                self._refresh_sidebar()
        except (OSError, ValueError) as error:
            self._warn(str(error))

    def action_skip_or_leave(self) -> None:
        if self.finished:
            return
        if self.mode == "plan":
            self.index += 1
            self._show_plan_candidate()
        else:
            self.action_leave_block()

    def action_defer(self) -> None:
        if self.finished:
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
            self.index += 1
            if self.mode == "plan":
                self._show_plan_candidate()
            else:
                self._show_missed_block()
            self._refresh_sidebar()
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
        entry = self.missed[self.index]
        try:
            core.complete_task(entry["task"].id, self.review_date)
            for missed_entry in self.missed:
                if missed_entry["task"].id == entry["task"].id:
                    missed_entry["task"].done = True
            self.index += 1
            self._show_missed_block()
            self._refresh_sidebar()
        except (OSError, ValueError) as error:
            self._warn(str(error))

    def action_leave_block(self) -> None:
        if self.mode != "close" or self.finished:
            return
        self.index += 1
        self._show_missed_block()

    def _drop_confirmed(self, task: core.Task, confirmed: bool | None) -> None:
        if not confirmed:
            return
        try:
            core.delete_task(task.id)
            self.index += 1
            self._show_plan_candidate()
            self._refresh_sidebar()
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
        )
        self.query_one("#review-progress", Label).update(
            f"{self.index + 1} / {total_candidates}"
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
            and self.missed[self.index]["task"].done
        ):
            self.index += 1
        if self.index >= len(self.missed):
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
        self.query_one("#review-progress", Label).update(
            f"Plan for {self.review_date:%A, %B %d}"
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
        lines = [
            f"Tasks done: {summary['done_tasks']}",
            f"Tasks not done: {summary['not_done_tasks']}",
            f"Blocks completed: {summary['completed_blocks']}",
            f"Minutes planned: {summary['planned_minutes']}",
            f"Minutes completed: {summary['completed_minutes']}",
            f"Tasks rescheduled: {len(self.rescheduled)}",
        ]
        lines.extend(self.rescheduled)
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
