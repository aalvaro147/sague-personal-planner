from datetime import date, timedelta
from typing import Any

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Collapsible, Input, Label, Static

from planner import core
from planner.tui.screens.recurrence_form import (
    compose_recurrence_fields,
    read_recurrence_fields,
)


class EventForm(ModalScreen[bool]):
    def __init__(
        self,
        event: core.Event | None = None,
        occurrence: core.EventOccurrence | None = None,
        scope: str = "all",
        default_date: date | None = None,
    ) -> None:
        super().__init__()
        self.event = event
        self.occurrence = occurrence
        self.scope = scope
        self.default_date = default_date
        self.occurrence_date = occurrence.occurrence_date if occurrence else None
        self._pending_changes: dict[str, Any] | None = None

    def compose(self) -> ComposeResult:
        item = (
            self.occurrence
            if self.scope in {"this", "this_and_future"} and self.occurrence
            else self.event
        )
        with Vertical(classes="dialog form-dialog"):
            yield Label("Edit event" if item else "New event", classes="dialog-title")
            yield Label("Title")
            yield Input(
                value=item.title if item else "",
                placeholder="Event title",
                id="event-title",
            )
            yield Static("", classes="field-error", id="event-title-error")
            yield Label("Date (YYYY-MM-DD, today, tomorrow, or weekday)")
            yield Input(
                value=(
                    item.date.isoformat()
                    if item
                    else self.default_date.isoformat()
                    if self.default_date
                    else ""
                ),
                placeholder="2026-11-12",
                id="event-date",
            )
            yield Static("", classes="field-error", id="event-date-error")
            yield Label("Start (HH:MM)")
            yield Input(
                value=item.start if item else "",
                placeholder="10:30",
                id="event-start",
            )
            yield Static("", classes="field-error", id="event-start-error")
            yield Label("End (HH:MM)")
            yield Input(
                value=item.end if item else "",
                placeholder="11:15",
                id="event-end",
            )
            yield Static("", classes="field-error", id="event-end-error")
            yield Label("Location (optional)")
            yield Input(
                value=item.location or "" if item else "",
                placeholder="Location",
                id="event-location",
            )
            yield Label("Notes (optional)")
            yield Input(
                value=item.notes or "" if item else "",
                placeholder="Notes",
                id="event-notes",
            )
            if self.scope == "all":
                with Collapsible(
                    title="Repeat",
                    collapsed=True,
                    id="recurrence-section",
                ):
                    yield from compose_recurrence_fields(
                        self.event.recurrence if self.event else None,
                    )
            yield Static("", classes="form-feedback", id="event-feedback")
            with Horizontal(classes="form-actions"):
                yield Button("Cancel", id="cancel")
                yield Button("Save event", variant="primary", id="save")
                yield Button(
                    "Save anyway",
                    variant="warning",
                    id="confirm-save",
                    classes="confirm-overlap",
                )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(False)
            return
        if event.button.id in {"save", "confirm-save"}:
            if event.button.id == "confirm-save" and self._pending_changes is not None:
                self._save(self._pending_changes)
            else:
                self._validate_and_save()

    def _validate_and_save(self) -> None:
        self._clear_errors()
        title = self.query_one("#event-title", Input).value
        date_text = self.query_one("#event-date", Input).value.strip()
        start = self.query_one("#event-start", Input).value.strip()
        end = self.query_one("#event-end", Input).value.strip()
        location = self.query_one("#event-location", Input).value.strip() or None
        notes = self.query_one("#event-notes", Input).value.strip() or None
        try:
            parsed_date = core.parse_date(date_text)
        except ValueError as error:
            self._show_message("event-date-error", str(error))
            return

        changes: dict[str, Any] = {
            "title": title,
            "date": parsed_date.isoformat(),
            "start": start,
            "end": end,
            "location": location,
            "notes": notes,
        }
        try:
            start = core.normalize_time(start, "start")
            end = core.normalize_time(end, "end")
            changes["start"] = start
            changes["end"] = end
        except ValueError as error:
            self._show_interval_error(str(error))
            return
        try:
            if self.scope == "all":
                changes["recurrence"] = read_recurrence_fields(
                    self,
                    parsed_date,
                    self.event.recurrence if self.event else None,
                )
        except ValueError as error:
            self._show_message("recurrence-error", str(error))
            return
        try:
            core.validate_event_fields(
                title,
                parsed_date.isoformat(),
                start,
                end,
                location,
                notes,
            )
            if self.scope == "all":
                overlaps = core.find_event_occurrence_overlaps(
                    title,
                    parsed_date.isoformat(),
                    start,
                    end,
                    location,
                    notes,
                    changes.get("recurrence"),
                    parsed_date,
                    parsed_date + timedelta(
                        days=min(365, (date.max - parsed_date).days)
                    ),
                    exclude_event_id=self.event.id if self.event else None,
                )
            else:
                overlaps = [
                    (parsed_date, entry)
                    for entry in core.find_overlaps(
                        parsed_date.isoformat(),
                        start,
                        end,
                        exclude_event_id=self.event.id if self.event else None,
                        exclude_occurrence_date=(
                            self.occurrence_date
                            if self.scope in {"this", "this_and_future"}
                            else None
                        ),
                    )
                ]
        except ValueError as error:
            self._show_interval_error(str(error))
            return

        if overlaps:
            self._pending_changes = changes
            descriptions = []
            for conflict_date, entry in overlaps:
                description = (
                    f'task "{entry["task"].title}"'
                    if entry["kind"] == "block"
                    else f'event "{entry["event"].title}"'
                )
                descriptions.append(f"{description} on {conflict_date}")
            self._show_message(
                "event-feedback",
                f"Overlap with {', '.join(descriptions)}. Save anyway?",
            )
            self.query_one("#save", Button).display = False
            self.query_one("#confirm-save", Button).display = True
            return
        self._save(changes)

    def _save(self, changes: dict[str, Any]) -> None:
        try:
            if self.event is None:
                core.create_event(
                    changes["title"],
                    changes["date"],
                    changes["start"],
                    changes["end"],
                    changes["location"],
                    changes["notes"],
                    changes.get("recurrence"),
                )
            else:
                core.edit_event(
                    self.event.id,
                    scope=self.scope,
                    occurrence_date=self.occurrence_date,
                    **changes,
                )
        except ValueError as error:
            self._show_interval_error(str(error))
            return
        self.dismiss(True)

    def _show_interval_error(self, message: str) -> None:
        field_id = (
            "event-title-error"
            if "title" in message.casefold()
            else "event-date-error"
            if "date" in message.casefold()
            else "event-start-error"
            if "start" in message.casefold()
            else "event-end-error"
            if "end" in message.casefold() or "later than" in message.casefold()
            else "event-feedback"
        )
        self._show_message(field_id, message)

    def _show_message(self, field_id: str, message: str) -> None:
        if field_id == "recurrence-error":
            self.query_one("#recurrence-section", Collapsible).collapsed = False
        widget = self.query_one(f"#{field_id}", Static)
        widget.update(message)
        widget.display = True

    def _clear_errors(self) -> None:
        for field_id in (
            "event-title-error",
            "event-date-error",
            "event-start-error",
            "event-end-error",
            "event-feedback",
        ):
            widget = self.query_one(f"#{field_id}", Static)
            widget.update("")
            widget.display = False
        recurrence_error = self.query("#recurrence-error")
        if recurrence_error:
            recurrence_error.first().update("")
            recurrence_error.first().display = False
