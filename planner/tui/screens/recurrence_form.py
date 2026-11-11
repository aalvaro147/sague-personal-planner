from datetime import date
from typing import Any, Iterator

from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Input, Label, Select, Static

from planner import core


def compose_recurrence_fields(
    rule: dict[str, Any] | None,
) -> Iterator[Widget]:
    frequency = rule.get("freq", "none") if rule else "none"
    if rule and rule.get("until") is not None:
        ending = "date"
        end_value = rule["until"]
    elif rule and rule.get("count") is not None:
        ending = "count"
        end_value = str(rule["count"])
    else:
        ending = "never"
        end_value = ""
    weekdays = ",".join(rule.get("weekdays", [])) if rule else ""
    yield Label("Frequency")
    yield Select(
        [
            ("Never", "none"),
            ("Daily", "daily"),
            ("Weekly", "weekly"),
            ("Monthly", "monthly"),
        ],
        value=frequency,
        id="recurrence-frequency",
    )
    yield Label("Interval")
    yield Input(
        value=str(rule.get("interval", 1) if rule else 1),
        placeholder="Every N days / weeks / months",
        id="recurrence-interval",
    )
    yield Label("Weekdays (weekly only)")
    yield Input(
        value=weekdays,
        placeholder="Weekly days, e.g. mon,wed",
        id="recurrence-weekdays",
    )
    yield Label("End")
    yield Select(
        [("Never ends", "never"), ("On date", "date"), ("After count", "count")],
        value=ending,
        id="recurrence-ending",
    )
    yield Input(
        value=end_value,
        placeholder="YYYY-MM-DD or number of occurrences",
        id="recurrence-end-value",
    )
    yield Static("", classes="field-error", id="recurrence-error")


def read_recurrence_fields(
    screen: ModalScreen[Any],
    base_date: date | None,
    previous_rule: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    frequency = screen.query_one("#recurrence-frequency", Select).value
    if frequency == "none":
        return None
    if base_date is None:
        raise ValueError("A recurring item must have a date.")
    interval_text = screen.query_one("#recurrence-interval", Input).value.strip()
    try:
        interval = int(interval_text)
    except ValueError as error:
        raise ValueError("Recurrence interval must be an integer of at least 1.") from error
    rule: dict[str, Any] = {"freq": str(frequency), "interval": interval}
    if frequency == "weekly":
        weekday_text = screen.query_one("#recurrence-weekdays", Input).value.strip()
        if weekday_text:
            rule["weekdays"] = [day.strip() for day in weekday_text.split(",")]
    ending = screen.query_one("#recurrence-ending", Select).value
    end_value = screen.query_one("#recurrence-end-value", Input).value.strip()
    if ending == "date":
        until = core.parse_due_date(end_value)
        if until is None:
            raise ValueError("Recurrence end date is required.")
        rule["until"] = until.isoformat()
    elif ending == "count":
        try:
            rule["count"] = int(end_value)
        except ValueError as error:
            raise ValueError("Recurrence count must be a positive integer.") from error
    if previous_rule is not None:
        rule["skipped"] = list(previous_rule.get("skipped", []))
        rule["overrides"] = dict(previous_rule.get("overrides", {}))
    return core.validate_recurrence(rule, base_date)
