# Core API Documentation (`planner.core`)

The domain logic is completely decoupled from any user interface (no imports of Textual, no `print()`, no `input()`). All public functions accept and return pure Python primitives (`dict`, `list`, `str`, `int`, `float`, `bool`, `None`), with dates and times formatted as ISO strings. All outputs are directly serializable with `json.dumps()`.

Storage is managed through `planner/storage.py` and history/undo-redo snapshots are tracked in `planner/history.py`.

---

## 1. Independent Notes API

Notes are stored in `notes.json` with the following schema:
```json
{
  "id": "uuid",
  "title": "Call with the landlord",
  "body": "- deposit back by Dec\n- ask about...",
  "tags": ["home"],
  "project_id": null,
  "date": "2026-11-20",
  "pinned": false,
  "archived": false,
  "created": "2026-11-20T10:00:00.000000",
  "updated": "2026-11-20T10:00:00.000000",
  "deleted": false
}
```

### `create_note(title="", body="", tags=None, project_id=None, date=None, pinned=False, reference_date=None) -> dict[str, Any]`
Creates a new note.
- `title`: optional string, 0 to 120 characters.
- `body`: Markdown or plain text, up to 100,000 characters. At least one of `title` or `body` must be non-empty.
- `tags`: optional list of strings or comma/space-separated string; normalized to lowercase and validated.
- `project_id`: optional UUID string of an associated project.
- `date`: optional ISO date string (`YYYY-MM-DD`) or `date` object. Defaults to today's date (or `reference_date`).
- `pinned`: boolean indicating whether the note is pinned.
- Returns the created note dictionary. Wrapped in an undoable history action.

### `edit_note(note_id: str, **changes: Any) -> dict[str, Any]`
Edits an existing note.
- Supported changes: `title`, `body`, `tags`, `project_id`, `date`, `pinned`, `archived`.
- If no real values changed, no history entry is recorded and `updated` is not refreshed.
- Archiving a note (`archived=True`) automatically sets `pinned=False`.
- Attempting to pin an archived note raises a `ValueError`.
- Returns the updated note dictionary.

### `delete_note(note_id: str) -> dict[str, Any]`
Performs a logical deletion of the note (`deleted=True`, refreshed `updated`). Wrapped in an undoable history action.

### `pin_note(note_id: str, pinned: bool = True) -> dict[str, Any]`
Pins or unpins a note. Raises `ValueError` if the note is currently archived.

### `archive_note(note_id: str, archived: bool = True) -> dict[str, Any]`
Archives or unarchives a note. Archiving sets `pinned=False`.

### `get_note(note_id: str) -> dict[str, Any]`
Retrieves a note by ID. Includes `project_name` (looked up from active projects) and `preview` (first non-empty line of `body`, max 80 characters).

### `list_notes(date=None, project_id=None, tag=None, pinned=None, archived=False, limit=None) -> list[dict[str, Any]]`
Lists non-deleted notes matching the given filters.
- `archived`: if `False` (default), only non-archived notes are returned; if `True`, only archived notes; if `None`, all notes.
- Each returned note includes `project_name` and `preview`.
- Order: pinned notes first, then `date` descending, then `updated` descending.

### `notes_for_day(date: date | str) -> list[dict[str, Any]]`
Returns non-archived, non-deleted notes for the given calendar day, formatted and ordered identically to `list_notes`.

---

## 2. Projects API

Projects are stored in `projects.json`.

### `create_project(name: str, description: str | None = None, target_date: str | None = None, notes: str | None = None) -> dict[str, Any]`
Creates a new project.

### `get_project(project_id: str) -> dict[str, Any]`
Returns project details, including an augmented `"notes"` list containing all active non-archived notes assigned to this project.

### `list_projects(status: str | None = None) -> list[dict[str, Any]]`
Lists active projects.

### `edit_project(project_id: str, **changes: Any) -> dict[str, Any]`
Edits project metadata.

### `delete_project(project_id: str) -> dict[str, Any]`
Logically deletes the project. In the same atomic action, unassigns all associated tasks (`task.project_id = None`) and notes (`note["project_id"] = None`). A single `core.undo()` call restores the project along with its task and note assignments.

### `project_progress(project_id: str) -> dict[str, Any]`
Calculates completion progress (`total`, `completed`, `percentage`) based on assigned tasks. Notes do not count towards project progress.

---

## 3. Tags API

### `set_tags(kind: str = "note", note_id: str | None = None, tags: list[str] | str | None = None) -> dict[str, Any]`
Normalizes and assigns tags to an entity. Tag characters are restricted to alphanumeric characters, hyphens, and underscores.

### `list_tags(kind: str | None = None) -> list[dict[str, Any]]`
Returns a list of tags and their usage counts across active entities: `[{"tag": "home", "name": "home", "count": 2}, ...]`.

---

## 4. Search and Query Parser

### `parse_query(query: str) -> dict[str, Any]`
Parses search queries into structured tokens:
- Terms: plain words (matched with case/accent insensitivity).
- `#tag` or `tag:name`: filters by tag.
- `project:name`: filters by project name.
- `type:note`: filters by entity type.
- `is:pinned`: filters pinned notes.
- `is:archived`: searches archived notes (by default excluded).
- `is:pending` / `is:done`: filters tasks by status (excludes notes).
- `date:today`, `date:yesterday`, `date:week`, `date:YYYY-MM-DD`.

### `search(query: str, reference_date: date | None = None) -> list[dict[str, Any]]`
Executes search over tasks and notes.
- An empty query continues to return all pending tasks.
- Notes match on `title`, `body`, `tags`, and `project_name` with AND semantics across terms.
- Note results contain `kind="note"`, `matched_in`, and `snippet` (plain text of up to 120 characters centered around the first match in `body`, or `None` if `body` did not match).

---

## 5. Habits API

Habits and their daily logs are stored in `habits.json` and `habit_logs.json` respectively:

### Habit Schema (`habits.json`)
```json
{
  "id": "uuid",
  "name": "Read 30 minutes",
  "description": null,
  "schedule": {"type": "daily"},
  "start_date": "2026-11-20",
  "archived": false,
  "archived_on": null,
  "created": "2026-11-20T10:00:00.000000",
  "updated": "2026-11-20T10:00:00.000000",
  "deleted": false
}
```
`schedule` may be `{"type": "daily"}` or `{"type": "weekdays", "days": ["mon", "wed", "fri"]}`.

### Habit Log Schema (`habit_logs.json`)
```json
{
  "id": "uuid",
  "habit_id": "uuid",
  "date": "2026-11-20",
  "status": "done",
  "created": "2026-11-20T10:00:00.000000",
  "updated": "2026-11-20T10:00:00.000000",
  "deleted": false
}
```
`status` can be `"done"`, `"missed"`, or `"skipped"`.

### Calculation Rules
- **Accountable Day**: A scheduled day is accountable if it is strictly before today, or if it is today and already logged. Today without a log does not count (neither adds to nor breaks streaks).
- **Unlogged Past Days**: Any past scheduled day without an explicit log counts as `missed` so forgotten entries do not artificially inflate statistics.
- **Skipped / Excused**: `skipped` entries represent excused days (illness, travel, etc.). They do not count as done or missed, and do not break streaks.
- **Completion Rate**: `round(100 * done / (done + missed))` over accountable days. Returns `None` if there are no accountable days.
- **Current Streak**: Consecutive `done` scheduled days walking backward from the most recent accountable day. `skipped` days neither increment nor break streak. Breaks on the first `missed` day.
- **Best Streak**: Longest continuous streak of `done` days across the habit's entire active history.
- **Archival**: For archived habits, calculations stop at `archived_on`.
- **Schedule Limitation**: Calculations evaluate historical dates using the habit's *current* schedule.

---

### Management Functions

#### `create_habit(name: str, description: str | None = None, days: list[str] | None = None, start_date: str | date | None = None) -> dict[str, Any]`
Creates a new habit.
- `name`: required string, 1 to 80 characters, unique among non-deleted habits (case-insensitive).
- `days`: list of weekday abbreviations (`["mon", "tue", "wed", "thu", "fri", "sat", "sun"]`). If `None`, defaults to daily (`{"type": "daily"}`).
- `start_date`: optional start date (defaults to today).
- Returns the created habit dictionary. Recorded in undo/redo history.

#### `edit_habit(habit_id: str, **changes: Any) -> dict[str, Any]`
Edits habit metadata (`name`, `description`, `days`, `schedule`, `start_date`). Validates constraints. If values are unchanged, no history entry is created.

#### `archive_habit(habit_id: str, archived: bool = True, on_date: str | date | None = None) -> dict[str, Any]`
Archives or unarchives a habit. Sets `archived_on` to `on_date` (or today) when archiving; clears `archived_on` when unarchiving.

#### `delete_habit(habit_id: str) -> dict[str, Any]`
Performs a logical deletion (`deleted=True`). Associated logs are retained but excluded from calculations. Recorded in undo/redo history.

#### `list_habits(include_archived: bool = False, date: str | date | None = None) -> list[dict[str, Any]]`
Lists non-deleted habits with computed fields:
- `scheduled_today`: boolean indicating whether the habit is scheduled on `date`.
- `status_today`: `"done"`, `"missed"`, `"skipped"`, or `None`.
- `current_streak`: int current streak up to `date`.
- `rate_30d`: completion percentage (0-100 or `None`) over the 30 days up to `date`.

---

### Logging Functions

#### `set_habit_status(habit_id: str, date: str | date, status: str | None) -> dict[str, Any] | None`
Sets or removes the status for a habit on a given date.
- `status`: `"done"`, `"missed"`, `"skipped"`, or `None` (removes the log via soft-deletion).
- Rejects future dates, non-existent or deleted habits, and dates on which the habit is not scheduled (raises `ValueError`).
- Re-logging reactivates an existing soft-deleted log without duplicating UUIDs.
- Wrapped in undo/redo history with descriptive action labels.

#### `habits_for_day(date: str | date | None = None) -> list[dict[str, Any]]`
Returns habits scheduled for the given date (default today), ordered by creation date, with:
- `status`: `"done"`, `"missed"`, `"skipped"`, or `"unlogged"`.
- `current_streak`: int current streak up to `date`.

#### `habits_unlogged(days: int = 3, end_date: str | date | None = None) -> list[dict[str, Any]]`
Finds unlogged habits for each of the last `days` days prior to `end_date` (default today):
- Returns list of `{"date": "YYYY-MM-DD", "habits": [...]}` for dates with at least one unlogged scheduled habit.

---

### Statistics Functions

#### `habit_stats(habit_id: str, end_date: str | date | None = None) -> dict[str, Any]`
Detailed metrics for a habit up to `end_date`:
- `current_streak`, `best_streak`.
- `rate_7d`, `rate_30d`, `rate_all` (0-100 or `None`).
- `total_done`, `total_missed`, `total_skipped`.
- `last_done`: ISO date string of latest `done` or `None`.
- `by_weekday`: dict mapping `"mon"` through `"sun"` to percentage rate or `None`.

#### `habit_calendar(habit_id: str, start_date: str | date, end_date: str | date) -> list[dict[str, Any]]`
Daily status series for a date range (up to 400 days):
- Returns `[{"date": "YYYY-MM-DD", "status": ...}]` where status is one of `"done"`, `"missed"`, `"skipped"`, `"unlogged"` (today without log), `"not_scheduled"`, or `"out_of_range"` (before start date or after archive date).

#### `habits_series(start_date: str | date, end_date: str | date, habit_ids: list[str] | None = None) -> list[dict[str, Any]]`
Aggregated daily metrics across specified (or all active) habits:
- Returns `[{"date": "YYYY-MM-DD", "scheduled": int, "done": int, "missed": int, "skipped": int, "percent": int | None}]`.

#### `habits_summary(end_date: str | date | None = None) -> dict[str, Any]`
Global overview metrics:
- `rate_7d`, `rate_30d` across all active habits.
- `habits`: list of active habits with `rate_30d` and `current_streak`, sorted from highest to lowest 30-day rate.
- `best_habit`, `worst_habit`: habit dicts or `None` if fewer than two habits have data.

---

## 5. Block Completion & Live Day Agenda API (`planner.core`)

### Block Data Model
Each block in a task's `blocks` list includes:
- `id`: unique UUID string.
- `date`: ISO date string (`YYYY-MM-DD`).
- `start`: start time string (`HH:MM`).
- `end`: end time string (`HH:MM`).
- `status`: `"planned"` (default) or `"done"`.
- `completed_at`: ISO timestamp string when completed, or `None`.

### Block Visibility Rules
A block appears in daily, weekly, and monthly views and counts toward day load, free gaps, and overlaps if:
1. Its task is not deleted (`not task.deleted`), and
2. Either the block status is `"done"` (preserved as history even if task is completed) OR the task is pending (`not task.done`).
Planned blocks belonging to completed tasks remain hidden and do not take up scheduled time.

### `set_block_status(task_id: str, block_id: str, status: str, now: datetime | None = None) -> dict[str, Any]`
Changes block status (`"planned"` or `"done"`).
- Automatically updates `completed_at` timestamp and task's `updated` timestamp.
- If task is done and status is set back to `"planned"`, raises `ValueError("Reopen the task first")`.
- Idempotent: if status is unchanged, does not record a history action.
- Wrapped in undo/redo history. Returns the updated block dictionary.

### `complete_block(task_id: str, block_id: str, complete_task: bool = False, reference_date: date | None = None, now: datetime | None = None) -> dict[str, Any]`
Marks a block as done and optionally completes its parent task.
- `complete_task`: if `True`, marks the task as completed, marks any of today's started blocks (`start <= now`) as `"done"`, and automatically creates the next recurrence instance if the task is recurring.
- Everything is executed as a single atomic undoable action.
- Returns a dict:
  ```python
  {
      "block": dict,
      "task": dict,
      "task_completed": bool,
      "next_instance": dict | None,
      "suggest_complete_task": bool,
  }
  ```
  where `suggest_complete_task` is `True` if the task remains pending with no other planned blocks from today onward.

### `day_timeline(date_val: date | str | None = None, now_val: str | datetime | None = None) -> dict[str, Any]`
Builds the complete live timeline for a day, including item temporal phases and free gaps:
- `items`: scheduled blocks and events, each augmented with:
  - `phase`: `"past"` (end <= now), `"current"` (start <= now < end), or `"upcoming"` (start > now). (For past dates, all items are `"past"`; for future dates, all items are `"upcoming"`).
  - `status`: `"done"` or `"planned"` for blocks; `None` for events.
  - `missed`: boolean indicating whether an uncompleted block's end time has passed.
- `gaps`: free time slots between 00:00 and 23:59 (or working window) with phase classification.
- `summary`:
  - `blocks_total`, `blocks_done`, `blocks_missed`, `blocks_upcoming`.
  - `events_total`.
  - `minutes_planned`, `minutes_done`, `minutes_missed`, `minutes_free`.
  - `current_item`: item currently in progress or `None`.
  - `next_item`: first upcoming item or `None`.

### `get_task(identifier: str) -> Task`
Retrieves an active, non-deleted task by ID. Raises `ValueError` if not found.

---

## 6. Monthly Calendar View API (`planner.calendar_view`)

Completely decoupled from Textual and UI code. All functions accept pure primitives and return JSON-serializable structures.

### `shift_date(date_val: date | str, days: int = 0, weeks: int = 0, months: int = 0) -> date`
Performs calendar date arithmetic adjusting for month bounds. When shifting by months, clamps the day to the last valid day of the target month (e.g., Jan 31 + 1 month -> Feb 28/29).

### `month_overview(date_val: date | str | None = None, first_weekday: str | None = None, max_preview: int = 3, settings: dict[str, Any] | None = None) -> dict[str, Any]`
Computes the monthly overview grid:
- Reads storage (tasks, events, notes) exactly once per call.
- Returns:
  ```python
  {
      "year": int,
      "month": int,
      "month_name": str,
      "first_weekday": "mon" | "sun",
      "weeks": list[list[dict]],  # 4 to 6 weeks of 7 day cells each
  }
  ```
- Each day cell dictionary contains:
  - `date`: ISO date string (`YYYY-MM-DD`).
  - `is_today`: bool.
  - `in_month`: bool.
  - `load`: `"none"` (0m), `"light"` (< 120m), `"medium"` (< 300m), `"heavy"` (>= 300m).
  - `busy_minutes`: total minutes occupied by visible blocks and events.
  - `block_count`, `event_count`, `note_count`, `due_count`: counts.
  - `preview`: up to `max_preview` items (`{"type": "block" | "event", "title": str, "start": str, "recurring": bool}`).

---

## 7. Injectable Clock (`planner.clock`)

Centralized datetime provider allowing tests to substitute system time cleanly.

- `clock.now() -> datetime`: returns current `datetime` (or simulated time).
- `clock.today() -> date`: returns current `date` (or simulated date).
- `clock.time_str() -> str`: returns current time formatted as `"HH:MM"`.
- `clock.set_clock(dt: datetime | date | None)`: overrides system time for tests.
- `clock.reset_clock()`: restores normal clock operation.


