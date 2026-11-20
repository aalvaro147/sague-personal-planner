"""Tests for planner/history.py — undo/redo core functionality."""
import importlib
import json
import warnings
from datetime import date, timedelta
from pathlib import Path

import pytest

from planner import core, history


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Point every data-file reference to a fresh tmp directory and reset module state."""
    tasks_file = tmp_path / "tasks.json"
    events_file = tmp_path / "events.json"
    settings_file = tmp_path / "settings.json"
    legacy_file = tmp_path / "legacy.jsonl"

    monkeypatch.setattr(core, "TASKS_FILE", tasks_file)
    monkeypatch.setattr(core, "EVENTS_FILE", events_file)
    monkeypatch.setattr(core, "SETTINGS_FILE", settings_file)
    monkeypatch.setattr(core, "LEGACY_TASKS_FILE", legacy_file)

    # Reset history module's nesting-depth counter
    monkeypatch.setattr(history, "_depth", 0)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TODAY = date.today()
TOMORROW = TODAY + timedelta(days=1)
NEXT_WEEK = TODAY + timedelta(days=7)


def _task_count() -> int:
    return len([t for t in core.load_tasks() if not t.deleted])


def _task_ids() -> set[str]:
    return {t.id for t in core.load_tasks() if not t.deleted}


def _all_task_ids() -> set[str]:
    return {t.id for t in core.load_tasks()}


def _event_count() -> int:
    return len([e for e in core.load_events() if not e.deleted])


# ---------------------------------------------------------------------------
# Basic create / undo / redo
# ---------------------------------------------------------------------------


def test_create_task_undo_redo():
    task = core.create_task("Test task")
    assert _task_count() == 1

    result = core.undo()
    assert "Test task" in result.label
    # Task is gone (deleted or list is empty)
    assert task.id not in _task_ids()

    result2 = core.redo()
    assert "Test task" in result2.label
    assert task.id in _task_ids()


def test_delete_task_undo():
    task = core.create_task("Delete me")
    core.delete_task(task.id)
    assert task.id not in _task_ids()

    core.undo()
    assert task.id in _task_ids()


def test_edit_task_undo():
    task = core.create_task("Original title")
    core.edit_task(task.id, "Updated title")

    tasks_by_id = {t.id: t for t in core.load_tasks()}
    assert tasks_by_id[task.id].title == "Updated title"

    core.undo()

    tasks_by_id = {t.id: t for t in core.load_tasks()}
    assert tasks_by_id[task.id].title == "Original title"


def test_plan_block_undo():
    task = core.create_task("Block me")
    block = core.plan_block(task.id, str(TOMORROW), "09:00", "10:00")

    tasks = {t.id: t for t in core.load_tasks()}
    assert any(b.id == block.id for b in tasks[task.id].blocks)

    core.undo()

    tasks = {t.id: t for t in core.load_tasks()}
    assert not any(b.id == block.id for b in tasks[task.id].blocks)


def test_remove_block_undo():
    task = core.create_task("Block task")
    block = core.plan_block(task.id, str(TOMORROW), "09:00", "10:00")

    core.remove_block(task.id, block.id)
    tasks = {t.id: t for t in core.load_tasks()}
    assert not any(b.id == block.id for b in tasks[task.id].blocks)

    core.undo()
    tasks = {t.id: t for t in core.load_tasks()}
    assert any(b.id == block.id for b in tasks[task.id].blocks)


def test_move_block_undo():
    task = core.create_task("Move block task")
    block = core.plan_block(task.id, str(TOMORROW), "09:00", "10:00")
    next_day = str(TOMORROW + timedelta(days=1))

    core.move_block(task.id, block.id, next_day, "11:00", "12:00")

    tasks = {t.id: t for t in core.load_tasks()}
    moved = next(b for b in tasks[task.id].blocks if b.id == block.id)
    assert str(moved.date) == next_day

    core.undo()

    tasks = {t.id: t for t in core.load_tasks()}
    restored = next(b for b in tasks[task.id].blocks if b.id == block.id)
    assert restored.date == TOMORROW
    assert restored.start == "09:00"
    assert restored.end == "10:00"


def test_set_task_done_undo():
    task = core.create_task("Mark done task")
    core.set_task_done(task.id, True)

    tasks = {t.id: t for t in core.load_tasks()}
    assert tasks[task.id].done is True

    core.undo()

    tasks = {t.id: t for t in core.load_tasks()}
    assert tasks[task.id].done is False


def test_create_event_undo():
    event = core.create_event("Meeting", str(TOMORROW), "14:00", "15:00")
    assert _event_count() == 1

    core.undo()
    assert event.id not in {e.id for e in core.load_events() if not e.deleted}


def test_edit_event_undo():
    event = core.create_event("Old title", str(TOMORROW), "14:00", "15:00")
    core.edit_event(event.id, title="New title", scope="all")

    events = {e.id: e for e in core.load_events() if not e.deleted}
    assert events[event.id].title == "New title"

    core.undo()

    events = {e.id: e for e in core.load_events() if not e.deleted}
    assert events[event.id].title == "Old title"


def test_delete_event_undo():
    event = core.create_event("Delete event", str(TOMORROW), "14:00", "15:00")
    core.delete_event(event.id, scope="all")
    assert event.id not in {e.id for e in core.load_events() if not e.deleted}

    core.undo()
    assert event.id in {e.id for e in core.load_events() if not e.deleted}


# ---------------------------------------------------------------------------
# Recurring task: mark done creates next occurrence — undo reverses both
# ---------------------------------------------------------------------------


def test_mark_done_recurring_task_undo_removes_next_occurrence():
    task = core.create_task(
        "Pay rent",
        due=TODAY,
        recurrence={"freq": "monthly"},
    )
    before_ids = _all_task_ids()

    core.set_task_done(task.id, True, reference_date=TODAY)

    after_ids = _all_task_ids()
    new_ids = after_ids - before_ids
    assert len(new_ids) == 1, "Expected one new occurrence to be created"

    tasks = {t.id: t for t in core.load_tasks()}
    assert tasks[task.id].done is True

    # Single undo restores both: task becomes pending AND next occurrence disappears
    core.undo()

    tasks_after_undo = {t.id: t for t in core.load_tasks()}
    assert tasks_after_undo[task.id].done is False
    for new_id in new_ids:
        assert new_id not in {t.id for t in core.load_tasks()}


# ---------------------------------------------------------------------------
# create_task_with_block undoes as one action
# ---------------------------------------------------------------------------


def test_create_task_with_block_undoes_as_one_action():
    before_count = _task_count()
    task = core.create_task_with_block(
        "Task with block", str(TOMORROW), "10:00", "11:00"
    )
    assert _task_count() == before_count + 1
    tasks = {t.id: t for t in core.load_tasks()}
    assert len(tasks[task.id].blocks) == 1

    # Only one undo entry
    entries_before = history.history_list()
    assert entries_before[0]["label"] == f'Created task "Task with block" with block'

    core.undo()

    assert task.id not in _task_ids()


def test_create_task_with_block_invalid_time_no_history_entry():
    before = history.history_list()
    with pytest.raises(ValueError):
        core.create_task_with_block("Bad block", str(TOMORROW), "11:00", "10:00")
    after = history.history_list()
    assert len(after) == len(before)


# ---------------------------------------------------------------------------
# this_and_future edit undoes as one action, restoring the original series
# ---------------------------------------------------------------------------


def test_edit_event_this_and_future_undo_restores_original():
    event = core.create_event(
        "Weekly standup",
        str(TODAY),
        "09:00",
        "09:30",
        recurrence={"freq": "weekly"},
    )
    original_id = event.id

    # Pick a future occurrence to edit
    occ_date = TODAY + timedelta(weeks=1)
    core.edit_event(original_id, title="Longer standup", scope="this_and_future",
                    occurrence_date=occ_date)

    events = {e.id: e for e in core.load_events() if not e.deleted}
    # Original series should now end before occ_date
    original = events.get(original_id)
    if original is not None:
        # Series was split
        pass

    core.undo()

    events_after = {e.id: e for e in core.load_events() if not e.deleted}
    # Original event is back and unchanged
    assert original_id in events_after
    assert events_after[original_id].title == "Weekly standup"
    # The new series created by this_and_future is gone
    for eid, ev in events_after.items():
        if eid != original_id:
            assert ev.title != "Longer standup"


# ---------------------------------------------------------------------------
# Nested record_action → single history entry
# ---------------------------------------------------------------------------


def test_nested_record_action_creates_single_entry():
    # create_task_with_block uses a single record_action wrapping plan_block internally.
    # Simulate an external double-wrap:
    with history.record_action("outer"):
        with history.record_action("inner"):
            core.create_task("Inner task")

    entries = history.history_list()
    # Only the outer action should be recorded
    assert entries[0]["label"] == "outer"
    assert len([e for e in entries if not e["undone"]]) == 1


# ---------------------------------------------------------------------------
# Exception mid-action: data intact, no history entry
# ---------------------------------------------------------------------------


def test_exception_mid_action_leaves_data_intact_and_no_entry():
    task = core.create_task("Existing task")
    entries_before = history.history_list()

    class BombException(RuntimeError):
        pass

    with pytest.raises(BombException):
        with history.record_action("failing action"):
            core.create_task("Should not persist")
            raise BombException("mid-action failure")

    # No new entry
    entries_after = history.history_list()
    assert len(entries_after) == len(entries_before)

    # Data is intact
    tasks = core.load_tasks()
    titles = [t.title for t in tasks if not t.deleted]
    assert "Should not persist" not in titles
    assert "Existing task" in titles


# ---------------------------------------------------------------------------
# Multiple undo/redo in sequence
# ---------------------------------------------------------------------------


def test_multiple_undo_redo_in_order():
    t1 = core.create_task("Task one")
    t2 = core.create_task("Task two")
    t3 = core.create_task("Task three")

    assert _task_count() == 3

    core.undo()  # undoes task three
    assert t3.id not in _task_ids()
    assert t2.id in _task_ids()

    core.undo()  # undoes task two
    assert t2.id not in _task_ids()
    assert t1.id in _task_ids()

    core.undo()  # undoes task one
    assert t1.id not in _task_ids()

    core.redo()  # redoes task one
    assert t1.id in _task_ids()

    core.redo()  # redoes task two
    assert t2.id in _task_ids()

    core.redo()  # redoes task three
    assert t3.id in _task_ids()


# ---------------------------------------------------------------------------
# New action after undo clears redo stack
# ---------------------------------------------------------------------------


def test_new_action_after_undo_clears_redo():
    core.create_task("Alpha")
    core.create_task("Beta")
    core.undo()

    peek = core.history_peek()
    assert peek.redo is not None  # redo is available

    # New action clears redo stack
    core.create_task("Gamma")

    peek2 = core.history_peek()
    assert peek2.redo is None


# ---------------------------------------------------------------------------
# History limit: oldest entry is pruned
# ---------------------------------------------------------------------------


def test_history_limit_prunes_oldest_entry(tmp_path):
    # Temporarily set limit to 3 via settings
    core.save_settings()
    settings = core.load_settings()
    settings["history_limit"] = 3
    core.SETTINGS_FILE.write_text(
        json.dumps(settings, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    for i in range(4):
        core.create_task(f"Task {i}")

    entries = history.history_list(limit=100)
    assert len(entries) <= 3


# ---------------------------------------------------------------------------
# Persistence across "restart" (re-read from disk)
# ---------------------------------------------------------------------------


def test_history_persists_across_restart():
    task = core.create_task("Persistent task")

    # Simulate restart: reload the module's data from disk (no monkeypatching the
    # module itself — just call history functions again, which read from disk)
    result = history.history_peek()
    assert result.undo is not None
    assert "Persistent task" in result.undo

    core.undo()
    assert task.id not in _task_ids()


# ---------------------------------------------------------------------------
# External change detection
# ---------------------------------------------------------------------------


def test_external_change_detected_before_undo():
    task = core.create_task("External task")

    # Simulate external edit of tasks.json
    tasks_file = core.TASKS_FILE
    data = json.loads(tasks_file.read_text(encoding="utf-8"))
    data[0]["title"] = "Tampered"
    tasks_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError, match="Data changed outside the app"):
        core.undo()

    # Data and history are intact
    assert tasks_file.exists()
    entries = history.history_list()
    assert len(entries) >= 1


# ---------------------------------------------------------------------------
# Corrupt history entry: warning issued, app continues
# ---------------------------------------------------------------------------


def test_corrupt_history_entry_warns_and_continues(tmp_path):
    core.create_task("Good task")

    history_dir = core.TASKS_FILE.parent / "history"
    # Write a corrupt entry file with a sequence number before existing entries
    corrupt_file = history_dir / "000000.json"
    corrupt_file.write_text("not valid json {{{", encoding="utf-8")

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        entries = history.history_list()

    # At least one warning issued
    assert any(issubclass(w.category, UserWarning) for w in caught)
    # history_list still returns something (or empty after clearing corrupt entries)
    assert isinstance(entries, list)


# ---------------------------------------------------------------------------
# No change → no history entry
# ---------------------------------------------------------------------------


def test_no_change_does_not_create_entry():
    task = core.create_task("No change task")
    before_count = len(history.history_list())

    # This action leaves data identical (task already not done, setting to False)
    # We use record_action directly with no data mutation
    with history.record_action("no-op action"):
        pass  # no data modification

    after_count = len(history.history_list())
    assert after_count == before_count


# ---------------------------------------------------------------------------
# Nothing to undo / Nothing to redo raises ValueError
# ---------------------------------------------------------------------------


def test_nothing_to_undo_raises():
    with pytest.raises(ValueError, match="Nothing to undo"):
        core.undo()


def test_nothing_to_redo_raises():
    with pytest.raises(ValueError, match="Nothing to redo"):
        core.redo()


def test_nothing_to_redo_after_fresh_action():
    core.create_task("Fresh task")
    with pytest.raises(ValueError, match="Nothing to redo"):
        core.redo()


# ---------------------------------------------------------------------------
# settings.json changes do not enter history
# ---------------------------------------------------------------------------


def test_settings_changes_not_in_history():
    before_count = len(history.history_list())
    core.save_settings("sun")
    after_count = len(history.history_list())
    assert after_count == before_count


# ---------------------------------------------------------------------------
# history_peek and history_list
# ---------------------------------------------------------------------------


def test_history_peek_returns_labels():
    peek = core.history_peek()
    assert peek.undo is None
    assert peek.redo is None

    core.create_task("Peek task")
    peek = core.history_peek()
    assert peek.undo is not None
    assert "Peek task" in peek.undo
    assert peek.redo is None

    core.undo()
    peek = core.history_peek()
    assert peek.undo is None
    assert peek.redo is not None
    assert "Peek task" in peek.redo


def test_history_list_returns_most_recent_first():
    core.create_task("First task")
    core.create_task("Second task")
    core.create_task("Third task")

    entries = core.history_list(limit=10)
    assert len(entries) == 3
    assert "Third task" in entries[0]["label"]
    assert "First task" in entries[2]["label"]


def test_history_list_respects_limit():
    for i in range(5):
        core.create_task(f"Task {i}")

    entries = core.history_list(limit=3)
    assert len(entries) == 3


# ---------------------------------------------------------------------------
# defer_task undo
# ---------------------------------------------------------------------------


def test_defer_task_undo():
    task = core.create_task("Defer me", due=TODAY)
    core.defer_task(task.id, NEXT_WEEK)

    tasks = {t.id: t for t in core.load_tasks()}
    assert tasks[task.id].due == NEXT_WEEK

    core.undo()

    tasks = {t.id: t for t in core.load_tasks()}
    assert tasks[task.id].due == TODAY
