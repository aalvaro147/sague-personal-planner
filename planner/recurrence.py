import calendar
from datetime import date, timedelta
from typing import Any


WEEKDAYS = {
    "mon": 0,
    "tue": 1,
    "wed": 2,
    "thu": 3,
    "fri": 4,
    "sat": 5,
    "sun": 6,
}
WEEKDAY_NAMES = {
    "monday": "mon",
    "tuesday": "tue",
    "wednesday": "wed",
    "thursday": "thu",
    "friday": "fri",
    "saturday": "sat",
    "sunday": "sun",
}
FREQUENCIES = {"daily", "weekly", "monthly"}


def _parse_iso_date(value: Any, label: str) -> date:
    if not isinstance(value, str):
        raise ValueError(f"{label} must use YYYY-MM-DD format.")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"Invalid {label}. Use YYYY-MM-DD format.") from error
    if parsed.isoformat() != value:
        raise ValueError(f"Invalid {label}. Use YYYY-MM-DD format.")
    return parsed


def validate_rule(
    rule: dict[str, Any] | None,
    base_date: date,
) -> dict[str, Any] | None:
    if rule is None:
        return None
    if not isinstance(rule, dict):
        raise ValueError("Recurrence must be an object or None.")

    frequency = rule.get("freq")
    if not isinstance(frequency, str) or frequency not in FREQUENCIES:
        raise ValueError("Recurrence frequency must be 'daily', 'weekly', or 'monthly'.")

    interval = rule.get("interval", 1)
    if type(interval) is not int or interval < 1:
        raise ValueError("Recurrence interval must be an integer of at least 1.")

    raw_weekdays = rule.get("weekdays")
    if frequency == "weekly":
        if raw_weekdays is None:
            weekdays = [
                next(name for name, value in WEEKDAYS.items() if value == base_date.weekday())
            ]
        else:
            if (
                not isinstance(raw_weekdays, list)
                or not raw_weekdays
                or any(not isinstance(day, str) for day in raw_weekdays)
            ):
                raise ValueError("Weekly recurrence weekdays must be a non-empty list.")
            weekdays = []
            for day in raw_weekdays:
                normalized = day.casefold()
                normalized = WEEKDAY_NAMES.get(normalized, normalized)
                if normalized not in WEEKDAYS:
                    raise ValueError(
                        "Weekdays must use mon, tue, wed, thu, fri, sat, or sun."
                    )
                if normalized not in weekdays:
                    weekdays.append(normalized)
            weekdays.sort(key=WEEKDAYS.__getitem__)
    else:
        if raw_weekdays is not None:
            raise ValueError("Weekdays can only be set for weekly recurrence.")
        weekdays = None

    until_value = rule.get("until")
    until_date = _parse_iso_date(until_value, "recurrence end date") if until_value is not None else None
    if until_date is not None and until_date <= base_date:
        raise ValueError("Recurrence end date must be later than its base date.")

    count = rule.get("count")
    if count is not None and (type(count) is not int or count < 1):
        raise ValueError("Recurrence count must be a positive integer or None.")
    if until_date is not None and count is not None:
        raise ValueError("Recurrence 'until' and 'count' cannot be used together.")

    raw_skipped = rule.get("skipped", [])
    if not isinstance(raw_skipped, list):
        raise ValueError("Recurrence skipped dates must be a list.")
    skipped = []
    for skipped_date in raw_skipped:
        parsed = _parse_iso_date(skipped_date, "skipped date")
        if parsed.isoformat() not in skipped:
            skipped.append(parsed.isoformat())
    skipped.sort()

    raw_overrides = rule.get("overrides", {})
    if not isinstance(raw_overrides, dict):
        raise ValueError("Recurrence overrides must be an object.")
    overrides: dict[str, dict[str, Any]] = {}
    for override_date, changes in raw_overrides.items():
        parsed = _parse_iso_date(override_date, "override date")
        if not isinstance(changes, dict):
            raise ValueError("Each recurrence override must be an object.")
        if any(key not in {"date", "title", "start", "end", "location", "notes"} for key in changes):
            raise ValueError("Recurrence override contains an unsupported field.")
        if "date" in changes:
            _parse_iso_date(changes["date"], "override date")
        for field in ("title", "start", "end", "location", "notes"):
            if field in changes and changes[field] is not None and not isinstance(changes[field], str):
                raise ValueError(f"Recurrence override '{field}' must be text or None.")
        overrides[parsed.isoformat()] = dict(changes)

    return {
        "freq": frequency,
        "interval": interval,
        **({"weekdays": weekdays} if weekdays is not None else {}),
        "until": until_date.isoformat() if until_date is not None else None,
        "count": count,
        "skipped": skipped,
        "overrides": overrides,
    }


def occurrence_dates(
    base_date: date,
    rule: dict[str, Any] | None,
    start_date: date,
    end_date: date,
) -> list[date]:
    if type(base_date) is not date or type(start_date) is not date or type(end_date) is not date:
        raise ValueError("Occurrence range and base date must be date values.")
    if start_date > end_date:
        raise ValueError("Occurrence start date must not be after end date.")
    normalized = validate_rule(rule, base_date)
    if normalized is None:
        return [base_date] if start_date <= base_date <= end_date else []

    until = date.fromisoformat(normalized["until"]) if normalized["until"] else date.max
    range_end = min(end_date, until)
    if range_end < base_date or range_end < start_date:
        return []
    count = normalized["count"]
    frequency = normalized["freq"]
    interval = normalized["interval"]
    found: list[date] = []

    if frequency == "daily":
        first_index = max(0, (start_date - base_date).days // interval)
        if base_date + timedelta(days=first_index * interval) < start_date:
            first_index += 1
        last_index = (range_end - base_date).days // interval
        if count is not None:
            last_index = min(last_index, count - 1)
        for index in range(first_index, last_index + 1):
            found.append(base_date + timedelta(days=index * interval))
        return found

    if frequency == "monthly":
        month_delta = (start_date.year - base_date.year) * 12 + start_date.month - base_date.month
        first_index = max(0, month_delta // interval)
        while _monthly_date(base_date, first_index * interval) < start_date:
            first_index += 1
        last_month_delta = (range_end.year - base_date.year) * 12 + range_end.month - base_date.month
        last_index = last_month_delta // interval
        if count is not None:
            last_index = min(last_index, count - 1)
        for index in range(first_index, last_index + 1):
            found.append(_monthly_date(base_date, index * interval))
        return found

    weekday_values = [WEEKDAYS[day] for day in normalized["weekdays"]]
    base_week = base_date - timedelta(days=base_date.weekday())
    first_week_days = [day for day in weekday_values if day >= base_date.weekday()]
    first_week_count = len(first_week_days)
    start_week_delta = max(0, (start_date - base_week).days // 7)
    first_week_index = start_week_delta // interval
    if first_week_index * interval < start_week_delta:
        first_week_index += 1
    last_week_delta = max(0, (range_end - base_week).days // 7)
    last_week_index = last_week_delta // interval
    for week_index in range(first_week_index, last_week_index + 1):
        week_start = base_week + timedelta(weeks=week_index * interval)
        for weekday_offset, weekday in enumerate(weekday_values):
            if weekday > (date.max - week_start).days:
                continue
            candidate = week_start + timedelta(days=weekday)
            if candidate < base_date or candidate < start_date or candidate > range_end:
                continue
            ordinal = (
                first_week_days.index(weekday)
                if week_index == 0
                else first_week_count + (week_index - 1) * len(weekday_values) + weekday_offset
            )
            if count is None or ordinal < count:
                found.append(candidate)
    return found


def next_occurrence_date(
    base_date: date,
    rule: dict[str, Any] | None,
    after_date: date,
) -> date | None:
    normalized = validate_rule(rule, base_date)
    if normalized is None:
        return None
    until = date.fromisoformat(normalized["until"]) if normalized["until"] else date.max
    frequency = normalized["freq"]
    interval = normalized["interval"]
    count = normalized["count"]

    if frequency == "daily":
        index = max(0, (after_date - base_date).days // interval + 1)
        if index * interval > (date.max - base_date).days:
            return None
        if count is not None and index >= count:
            return None
        candidate = base_date + timedelta(days=index * interval)
        return candidate if candidate <= until else None

    if frequency == "monthly":
        months_after = max(
            0,
            ((after_date.year - base_date.year) * 12 + after_date.month - base_date.month)
            // interval,
        )
        while True:
            if months_after * interval > (
                (date.max.year - base_date.year) * 12 + date.max.month - base_date.month
            ):
                return None
            if count is not None and months_after >= count:
                return None
            candidate = _monthly_date(base_date, months_after * interval)
            if candidate > after_date:
                return candidate if candidate <= until else None
            months_after += 1

    weekdays = [WEEKDAYS[day] for day in normalized["weekdays"]]
    base_week = base_date - timedelta(days=base_date.weekday())
    first_week_days = [day for day in weekdays if day >= base_date.weekday()]
    first_week_count = len(first_week_days)
    week_delta = max(0, (after_date - base_week).days // 7)
    week_index = week_delta // interval
    last_week_index = ((date.max - base_week).days // 7) // interval
    while week_index <= last_week_index:
        week_start = base_week + timedelta(weeks=week_index * interval)
        for weekday_offset, weekday in enumerate(weekdays):
            if weekday > (date.max - week_start).days:
                continue
            candidate = week_start + timedelta(days=weekday)
            if candidate <= after_date or candidate < base_date:
                continue
            ordinal = (
                first_week_days.index(weekday)
                if week_index == 0
                else first_week_count + (week_index - 1) * len(weekdays) + weekday_offset
            )
            if count is not None and ordinal >= count:
                return None
            if candidate <= until:
                return candidate
        week_index += 1
        if week_start > until:
            return None
    return None


def _monthly_date(base_date: date, months_after: int) -> date:
    month_index = base_date.month - 1 + months_after
    year = base_date.year + month_index // 12
    month = month_index % 12 + 1
    day = min(base_date.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)
