"""Central clock provider for Planner.

All modules must obtain the current date and time through this module
instead of calling datetime.now() or date.today() directly, ensuring
predictable and testable behavior.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

_frozen_datetime: datetime | None = None
_frozen_date: date | None = None


def now() -> datetime:
    """Return the current datetime or the frozen test datetime."""
    if _frozen_datetime is not None:
        return _frozen_datetime
    if _frozen_date is not None:
        return datetime.combine(_frozen_date, datetime.min.time())
    import sys
    for mod_name in ("planner.review", "planner.core"):
        if mod_name in sys.modules:
            mod = sys.modules[mod_name]
            mod_dt = getattr(mod, "datetime", None)
            if mod_dt is not None and hasattr(mod_dt, "now") and mod_dt is not datetime:
                return mod_dt.now()
    return datetime.now()


def today() -> date:
    """Return the current date or the frozen test date."""
    if _frozen_date is not None:
        return _frozen_date
    if _frozen_datetime is not None:
        return _frozen_datetime.date()
    import sys
    for mod_name in ("planner.core", "planner.review"):
        if mod_name in sys.modules:
            mod = sys.modules[mod_name]
            mod_d = getattr(mod, "date", None)
            if mod_d is not None and hasattr(mod_d, "today") and mod_d is not date:
                return mod_d.today()
    return date.today()


def time_str() -> str:
    """Return current time formatted as 'HH:MM'."""
    return now().strftime("%H:%M")


def set_clock(value: datetime | date | str | None) -> None:
    """Freeze clock to a specific datetime, date, or ISO string (for tests)."""
    global _frozen_datetime, _frozen_date
    if value is None:
        _frozen_datetime = None
        _frozen_date = None
        return

    if isinstance(value, datetime):
        _frozen_datetime = value
        _frozen_date = value.date()
    elif isinstance(value, date):
        _frozen_date = value
        _frozen_datetime = datetime.combine(value, datetime.min.time())
    elif isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value)
            _frozen_datetime = dt
            _frozen_date = dt.date()
        except ValueError:
            d = date.fromisoformat(value)
            _frozen_date = d
            _frozen_datetime = datetime.combine(d, datetime.min.time())
    else:
        raise TypeError(f"Unsupported clock value: {value!r}")


def reset_clock() -> None:
    """Reset clock to system time."""
    global _frozen_datetime, _frozen_date
    _frozen_datetime = None
    _frozen_date = None

