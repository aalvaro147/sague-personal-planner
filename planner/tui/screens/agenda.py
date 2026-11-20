from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.events import Resize
from textual.screen import Screen
from textual.widgets import Button, Input, Label, ListItem, ListView, Static

from planner import clock, core
from planner.tui.screens.block_form import BlockForm
from planner.tui.screens.complete_task_dialog import CompleteTaskDialog
from planner.tui.screens.confirm_dialog import ConfirmDialog
from planner.tui.screens.event_form import EventForm
from planner.tui.screens.note_detail import NoteDetailModal
from planner.tui.screens.note_form import NoteForm
from planner.tui.screens.recurrence_scope import RecurrenceScopeDialog
from planner.tui.screens.task_form import TaskForm

PRIORITY_LABELS = {"alta": "High", "media": "Medium", "baja": "Low"}


class AgendaScreen(Screen):
    BINDINGS = [
        ("left", "previous_day", "Previous day"),
        ("right", "next_day", "Next day"),
        ("h", "today", "Today"),
        ("x", "toggle_block_status", "Toggle done"),
        ("X", "complete_block_and_task", "Complete block & task"),
    ]

    def __init__(self, selected_date: date | None = None) -> None:
        super().__init__()
        self.selected_date = selected_date or clock.today()
        self.entries: list[core.AgendaEntry] = []
        self.agenda_rows: list[dict[str, Any]] = []
        self.unplanned_tasks: list[core.Task] = []
        self.notes: list[dict[str, Any]] = []
        self.selected_agenda_entry: core.AgendaEntry | None = None
        self.selected_unplanned_task: core.Task | None = None
        self.selected_item_id: str | None = None
        self._target_refresh_id: str | None = None
        self.initial_mount = True

    def compose(self) -> ComposeResult:
        with Horizontal(classes="top-nav"):
            yield Label("PERSONAL PLANNER", classes="brand")
            yield Button("Undo", id="undo")
            yield Button("Redo", id="redo")
            yield Button("Add task", id="add-task", variant="primary")
            yield Button("Month", id="open-month")
            yield Button("Week", id="open-week")
            yield Button("Tasks", id="open-tasks")
            yield Button("Events", id="open-events")
            yield Button("Notes", id="open-notes")
            yield Button("Habits", id="open-habits")
        with Horizontal(classes="date-toolbar", id="date-toolbar"):
            yield Button("Previous", id="previous-day")
            yield Button("Today", id="today")
            yield Button("Next", id="next-day")
            yield Button("Go", id="jump-date", variant="primary")
        with Horizontal(id="agenda-layout"):
            with Vertical(id="agenda-main"):
                yield Label("", id="agenda-heading", classes="section-heading")
                yield Static("", id="agenda-progress-bar", classes="agenda-progress-bar")
                yield Static("✓ Done  ! Missed  ▶ Current  · Upcoming", id="agenda-legend", classes="agenda-legend")
                yield ListView(id="agenda-list", initial_index=None)
                with Horizontal(classes="action-bar"):
                    yield Button("Add event", id="add-event", variant="primary")
                    yield Button("Plan selected task", id="schedule-task")
                    yield Button("Move / edit selected", id="edit-agenda-item")
                    yield Button("Remove selected", id="remove-agenda-item", variant="error")
                with Vertical(id="agenda-notes-container"):
                    with Horizontal(classes="action-bar notes-header-bar"):
                        yield Label("Notes", classes="section-heading")
                        yield Button("Add note", id="add-agenda-note", variant="primary")
                    yield ListView(id="agenda-notes-list", initial_index=None)
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
        self.set_interval(30.0, self._auto_refresh)
        await self.refresh_data()

    def _auto_refresh(self) -> None:
        self.run_worker(self._async_refresh_preserved, exclusive=True)

    async def _async_refresh_preserved(self) -> None:
        await self.refresh_data(preserve_selection=True)

    async def _refresh_with_target_id(self) -> None:
        await self.refresh_data(preserve_selection_id=self._target_refresh_id)

    def _trigger_refresh_target(self, target_id: str | None = None) -> None:
        self._target_refresh_id = target_id
        self.run_worker(self._refresh_with_target_id, exclusive=True)

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

        notes_lists = self.query("#agenda-notes-list")
        if notes_lists:
            nl = notes_lists.first()
            is_narrow = width < 90
            for idx, item in enumerate(nl.children):
                if idx < len(self.notes):
                    n = self.notes[idx]
                    t = n.get("title") or n.get("preview") or "Untitled Note"
                    if is_narrow:
                        lbl = t
                    else:
                        pinned = "[PINNED] " if n.get("pinned") else ""
                        proj = f" · {n['project_name']}" if n.get("project_name") else ""
                        tags = " · " + " ".join(f"#{tag}" for tag in n.get("tags", [])) if n.get("tags") else ""
                        lbl = f"{pinned}{t}{proj}{tags}"
                    statics = item.query(Static)
                    if statics:
                        statics.first().update(lbl)

    def on_screen_resume(self) -> None:
        self.run_worker(self._async_refresh_preserved, exclusive=True)

    async def refresh_data(
        self,
        preserve_selection: bool = False,
        preserve_selection_id: str | None = None,
    ) -> None:
        try:
            target_id = preserve_selection_id or (self.selected_item_id if preserve_selection else None)
            timeline = core.day_timeline(self.selected_date)
            self.entries = core.get_day_agenda(self.selected_date.isoformat())
            self.unplanned_tasks = core.get_unplanned_tasks()

            items = timeline["items"]
            gaps = timeline["gaps"]
            summary = timeline["summary"]
            is_today = timeline["is_today"]
            now_str = timeline["now"]

            # Format Progress Header
            blocks_total = summary["blocks_total"]
            blocks_done = summary["blocks_done"]
            m_done = summary["minutes_done"]
            m_plan = summary["minutes_planned"]
            hd, md = divmod(m_done, 60)
            hp, mp = divmod(m_plan, 60)
            done_dur = f"{hd}h{md:02d}" if md else f"{hd}h"
            plan_dur = f"{hp}h{mp:02d}" if mp else f"{hp}h"
            next_it = summary["next_item"]
            next_part = f" · next: {next_it['title']} {next_it['start']}" if next_it else ""
            progress_text = f"{blocks_done}/{blocks_total} blocks · {done_dur} of {plan_dur}{next_part}"
            self.query_one("#agenda-progress-bar", Static).update(progress_text)
            self.query_one("#agenda-legend", Static).display = True

            agenda_list = self.query_one("#agenda-list", ListView)
            unplanned_list = self.query_one("#unplanned-list", ListView)
            await agenda_list.clear()
            await unplanned_list.clear()

            # Merge items and gaps into chronological rows
            raw_rows: list[dict[str, Any]] = []
            for it in items:
                raw_rows.append(it)
            for g in gaps:
                raw_rows.append({
                    "kind": "gap",
                    "start": g["start"],
                    "end": g["end"],
                    "duration_minutes": g["duration_minutes"],
                    "phase": g["phase"],
                })
            raw_rows.sort(key=lambda r: (r["start"], r["end"]))

            self.agenda_rows = []
            now_inserted = False
            is_narrow = self.size.width < 90

            for row in raw_rows:
                if is_today and now_str and not now_inserted and row["start"] > now_str:
                    now_item = ListItem(
                        Static(f"──────── {now_str} ────────", classes="now-line-text"),
                        classes="now-line",
                        disabled=True,
                    )
                    await agenda_list.append(now_item)
                    self.agenda_rows.append({"kind": "now_line", "start": now_str, "end": now_str})
                    now_inserted = True

                if row["kind"] == "gap":
                    gap_item = ListItem(
                        Static(f"   FREE  {row['start']} - {row['end']}"),
                        classes="free-gap",
                    )
                    await agenda_list.append(gap_item)
                    self.agenda_rows.append(row)
                else:
                    symbol = self._entry_symbol(row)
                    phase_class = f"phase-{row.get('phase', 'upcoming')}"
                    item_classes = ["agenda-item-row", phase_class]
                    if row.get("phase") == "current":
                        item_classes.append("current-item")
                    if row.get("status") == "done":
                        item_classes.append("done-item")
                    if row.get("missed"):
                        item_classes.append("missed-item")

                    if is_narrow:
                        lbl = f"{symbol} {row['start']} {row['title']}"
                    else:
                        label_text = self._row_label(row)
                        lbl = f"{symbol} {row['start']} - {row['end']}   {label_text}"

                    list_item = ListItem(
                        Static(lbl),
                        classes=" ".join(item_classes),
                    )
                    await agenda_list.append(list_item)
                    self.agenda_rows.append(row)

            if is_today and now_str and not now_inserted:
                now_item = ListItem(
                    Static(f"──────── {now_str} ────────", classes="now-line-text"),
                    classes="now-line",
                    disabled=True,
                )
                await agenda_list.append(now_item)
                self.agenda_rows.append({"kind": "now_line", "start": now_str, "end": now_str})

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

            # Determine item to highlight/select
            selected_idx = None
            if target_id is not None:
                for idx, r in enumerate(self.agenda_rows):
                    if r.get("id") == target_id:
                        selected_idx = idx
                        break

            if selected_idx is None and self.initial_mount and is_today:
                for idx, r in enumerate(self.agenda_rows):
                    if r.get("phase") == "current":
                        selected_idx = idx
                        break
                if selected_idx is None:
                    for idx, r in enumerate(self.agenda_rows):
                        if r.get("phase") != "past":
                            selected_idx = idx
                            break

            if selected_idx is not None and selected_idx < len(self.agenda_rows):
                agenda_list.index = selected_idx
                self.selected_agenda_entry = self._find_matching_entry(self.agenda_rows[selected_idx])
                self.selected_item_id = self.agenda_rows[selected_idx].get("id")
            elif self.agenda_rows:
                if not preserve_selection:
                    agenda_list.index = 0
                    self.selected_agenda_entry = self._find_matching_entry(self.agenda_rows[0])
                    self.selected_item_id = self.agenda_rows[0].get("id")

            self.initial_mount = False

            # Render notes for day
            self.notes = core.notes_for_day(self.selected_date)
            notes_list = self.query_one("#agenda-notes-list", ListView)
            await notes_list.clear()
            for n in self.notes:
                t = n.get("title") or n.get("preview") or "Untitled Note"
                if is_narrow:
                    lbl = t
                else:
                    pinned = "[PINNED] " if n.get("pinned") else ""
                    proj = f" · {n['project_name']}" if n.get("project_name") else ""
                    tags = " · " + " ".join(f"#{tag}" for tag in n.get("tags", [])) if n.get("tags") else ""
                    lbl = f"{pinned}{t}{proj}{tags}"
                await notes_list.append(ListItem(Static(lbl), classes="agenda-note-item"))
        except (OSError, ValueError) as error:
            self.app.notify(str(error), title="Could not load agenda", severity="error")

    def _find_matching_entry(self, row: dict[str, Any]) -> core.AgendaEntry | None:
        if row.get("kind") in ("gap", "now_line"):
            return None
        row_id = row.get("id")
        for e in self.entries:
            item = e["block"] if e["kind"] == "block" else e["event"]
            if item.id == row_id:
                return e
        return None

    @staticmethod
    def _entry_symbol(row: dict[str, Any]) -> str:
        if row.get("kind") == "block":
            if row.get("status") == "done":
                return "✓"
            if row.get("missed"):
                return "!"
        if row.get("phase") == "current":
            return "▶"
        return "·"

    @staticmethod
    def _row_label(row: dict[str, Any]) -> str:
        if row.get("kind") == "block":
            return f"[T] {row['title']}"
        marker = " ↻" if row.get("recurring") else ""
        return f"[E] {row['title']}{marker}"

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.list_view.id == "agenda-list":
            if event.list_view.index is not None and event.list_view.index < len(self.agenda_rows):
                row = self.agenda_rows[event.list_view.index]
                self.selected_agenda_entry = self._find_matching_entry(row)
                self.selected_item_id = row.get("id")
        elif event.list_view.id == "unplanned-list":
            if event.list_view.index is not None and event.list_view.index < len(self.unplanned_tasks):
                self.selected_unplanned_task = self.unplanned_tasks[event.list_view.index]

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.id == "agenda-list":
            if event.index < len(self.agenda_rows):
                row = self.agenda_rows[event.index]
                self.selected_agenda_entry = self._find_matching_entry(row)
                self.selected_item_id = row.get("id")
        elif event.list_view.id == "unplanned-list":
            if event.index < len(self.unplanned_tasks):
                self.selected_unplanned_task = self.unplanned_tasks[event.index]
        elif event.list_view.id == "agenda-notes-list":
            if event.index < len(self.notes):
                note = self.notes[event.index]
                self.app.push_screen(
                    NoteDetailModal(note["id"]),
                    lambda _: self.run_worker(self.refresh_data, exclusive=True),
                )

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
        elif button_id == "open-month":
            self.app.switch_mode("month")
        elif button_id == "open-tasks":
            self.app.switch_mode("tasks")
        elif button_id == "open-week":
            self.app.switch_mode("week")
        elif button_id == "open-events":
            self.app.switch_mode("events")
        elif button_id == "open-notes":
            self.app.switch_mode("notes")
        elif button_id == "open-habits":
            self.app.switch_mode("habits")
        elif button_id == "add-event":
            self.add_item()
        elif button_id == "add-task":
            self.add_task()
        elif button_id == "add-agenda-note":
            self.action_add_agenda_note()
        elif button_id in {"schedule-task", "schedule-unplanned"}:
            self.plan_selected_task()
        elif button_id == "edit-agenda-item":
            self.edit_item()
        elif button_id == "remove-agenda-item":
            self.remove_item()

    def action_toggle_block_status(self) -> None:
        entry = self.selected_agenda_entry
        if entry is None:
            self.app.notify("Select an item first.", severity="warning")
            return
        if entry["kind"] == "event":
            self.app.notify("Events can't be completed", severity="warning")
            return

        task = entry["task"]
        block = entry["block"]
        current_status = getattr(block, "status", "planned")

        if current_status == "done":
            try:
                core.set_block_status(task.id, block.id, "planned")
                self._trigger_refresh_target(block.id)
            except ValueError as error:
                self.app.notify(str(error), severity="warning")
        else:
            try:
                res = core.complete_block(task.id, block.id, complete_task=False)
                if res["suggest_complete_task"]:
                    self.app.push_screen(
                        CompleteTaskDialog(task.title),
                        lambda choice: self._handle_complete_task_choice(task.id, block.id, choice),
                    )
                else:
                    self._trigger_refresh_target(block.id)
            except ValueError as error:
                self.app.notify(str(error), severity="warning")

    def _handle_complete_task_choice(self, task_id: str, block_id: str, choice: str) -> None:
        if choice == "yes":
            try:
                core.complete_task(task_id)
            except ValueError as error:
                self.app.notify(str(error), severity="warning")
        elif choice == "cancel":
            try:
                core.undo()
            except ValueError:
                pass
        self._trigger_refresh_target(block_id)

    def action_complete_block_and_task(self) -> None:
        entry = self.selected_agenda_entry
        if entry is None or entry["kind"] != "block":
            return
        task = entry["task"]
        block = entry["block"]
        try:
            core.complete_block(task.id, block.id, complete_task=True)
            self._trigger_refresh_target(block.id)
        except ValueError as error:
            self.app.notify(str(error), severity="warning")

    def action_add_agenda_note(self) -> None:
        self.app.push_screen(
            NoteForm(default_date=self.selected_date),
            lambda res: self.run_worker(self.refresh_data, exclusive=True) if res else None,
        )

    def action_previous_day(self) -> None:
        self.selected_date -= timedelta(days=1)
        self.run_worker(self.refresh_data, exclusive=True)

    def action_next_day(self) -> None:
        self.selected_date += timedelta(days=1)
        self.run_worker(self.refresh_data, exclusive=True)

    def action_today(self) -> None:
        self.selected_date = clock.today()
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
