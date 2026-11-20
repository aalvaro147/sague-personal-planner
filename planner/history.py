import hashlib
import json
import os
import shutil
import tempfile
import warnings
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, NamedTuple

from planner import clock


class HistoryResult(NamedTuple):
    label: str
    affected_ids: list[str]


class HistoryPeek(NamedTuple):
    undo: str | None
    redo: str | None


_depth: int = 0
TRACKED_FILES = [
    "tasks.json",
    "events.json",
    "projects.json",
    "notes.json",
    "habits.json",
    "habit_logs.json",
]


def _get_history_dir() -> Path:
    from planner import core

    history_dir = core.TASKS_FILE.parent / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    return history_dir


def _get_state_file() -> Path:
    return _get_history_dir() / "state.json"


def _atomic_write_text(path: Path, text: str, make_backup: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as file:
            temporary_path = Path(file.name)
            file.write(text)
            file.flush()
            os.fsync(file.fileno())

        if make_backup and path.exists():
            shutil.copy2(path, path.with_name(f"{path.name}.bak"))
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _compute_hash(content: str | None) -> str | None:
    if content is None:
        return None
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _read_data_files() -> dict[str, tuple[str | None, str | None]]:
    from planner import core

    data_dir = core.TASKS_FILE.parent
    tracked = TRACKED_FILES
    result: dict[str, tuple[str | None, str | None]] = {}
    for filename in tracked:
        file_path = data_dir / filename
        if file_path.exists():
            try:
                content = file_path.read_text(encoding="utf-8")
                result[filename] = (content, _compute_hash(content))
            except OSError:
                result[filename] = (None, None)
        else:
            result[filename] = (None, None)
    return result


def _find_affected_ids(
    before_files: dict[str, tuple[str | None, str | None]],
    after_files: dict[str, tuple[str | None, str | None]],
) -> list[str]:
    affected: list[str] = []

    def extract_items(content: str | None) -> dict[str, Any]:
        if not content:
            return {}
        try:
            data = json.loads(content)
            if isinstance(data, list):
                return {
                    item["id"]: item
                    for item in data
                    if isinstance(item, dict) and "id" in item
                }
        except Exception:
            pass
        return {}

    for filename in TRACKED_FILES:
        b_content, _ = before_files.get(filename, (None, None))
        a_content, _ = after_files.get(filename, (None, None))
        if b_content == a_content:
            continue

        b_items = extract_items(b_content)
        a_items = extract_items(a_content)


        all_ids = list(dict.fromkeys(list(b_items.keys()) + list(a_items.keys())))
        for item_id in all_ids:
            if item_id not in b_items or item_id not in a_items:
                if item_id not in affected:
                    affected.append(item_id)
            elif b_items[item_id] != a_items[item_id]:
                if item_id not in affected:
                    affected.append(item_id)

    return affected


def _load_all_entries() -> list[dict[str, Any]]:
    history_dir = _get_history_dir()
    entry_files = sorted(history_dir.glob("[0-9]*.json"), key=lambda p: p.name)

    valid_entries: list[dict[str, Any]] = []
    for entry_file in entry_files:
        try:
            data = json.loads(entry_file.read_text(encoding="utf-8"))
            if (
                not isinstance(data, dict)
                or "sequence" not in data
                or "label" not in data
                or "files" not in data
            ):
                raise ValueError(f"Invalid entry structure in {entry_file.name}")
            valid_entries.append(data)
        except Exception as error:
            warnings.warn(
                f"Corrupt history entry at {entry_file.name}: {error}",
                UserWarning,
                stacklevel=2,
            )
            # Ignore this entry and all previous ones
            valid_entries.clear()

    return valid_entries


def _load_current_sequence(entries: list[dict[str, Any]]) -> int:
    state_file = _get_state_file()
    if state_file.exists():
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
            if isinstance(state, dict) and "current_sequence" in state:
                seq = state["current_sequence"]
                entry_seqs = {e["sequence"] for e in entries}
                if seq == 0 or seq in entry_seqs:
                    return int(seq)
        except Exception:
            pass

    # Fallback from entries: latest sequence that is not undone
    for entry in reversed(entries):
        if not entry.get("undone", False):
            return int(entry["sequence"])
    return 0


def _save_state(current_sequence: int) -> None:
    state_file = _get_state_file()
    data = {"current_sequence": current_sequence}
    _atomic_write_text(
        state_file,
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        make_backup=False,
    )


def _entry_path(sequence: int) -> Path:
    return _get_history_dir() / f"{sequence:06d}.json"


def _prune_entries_if_needed() -> None:
    from planner import core

    try:
        settings = core.load_settings()
        limit = int(settings.get("history_limit", 50))
    except Exception:
        limit = 50

    history_dir = _get_history_dir()
    entry_files = sorted(history_dir.glob("[0-9]*.json"), key=lambda p: p.name)
    while len(entry_files) > limit:
        oldest = entry_files.pop(0)
        try:
            oldest.unlink(missing_ok=True)
        except OSError:
            pass


@contextmanager
def record_action(label: str | Callable[[], str]):
    global _depth
    if _depth > 0:
        _depth += 1
        try:
            yield
        finally:
            _depth -= 1
        return

    _depth = 1
    before_files = _read_data_files()
    try:
        yield
    except Exception:
        # Revert any files modified during failed action
        from planner import core

        data_dir = core.TASKS_FILE.parent
        for filename, (content, _) in before_files.items():
            path = data_dir / filename
            if content is None:
                path.unlink(missing_ok=True)
            else:
                try:
                    if path.exists() and path.read_text(encoding="utf-8") != content:
                        _atomic_write_text(path, content, make_backup=True)
                except OSError:
                    pass
        raise
    finally:
        _depth -= 1

    # Check after files
    after_files = _read_data_files()
    changed_files: dict[str, dict[str, Any]] = {}
    for filename in TRACKED_FILES:
        b_content, b_hash = before_files.get(filename, (None, None))
        a_content, a_hash = after_files.get(filename, (None, None))
        if b_content != a_content:
            changed_files[filename] = {
                "before": b_content,
                "after": a_content,
                "before_hash": b_hash,
                "after_hash": a_hash,
            }

    if not changed_files:
        return

    resolved_label = label() if callable(label) else str(label)
    affected_ids = _find_affected_ids(before_files, after_files)

    entries = _load_all_entries()
    current_seq = _load_current_sequence(entries)

    # Delete any entries on redo stack (sequence > current_seq)
    history_dir = _get_history_dir()
    for entry_file in history_dir.glob("[0-9]*.json"):
        try:
            seq = int(entry_file.stem)
            if seq > current_seq:
                entry_file.unlink(missing_ok=True)
        except ValueError:
            pass

    next_seq = current_seq + 1
    entry_data = {
        "sequence": next_seq,
        "timestamp": clock.now().isoformat(),
        "label": resolved_label,
        "affected_ids": affected_ids,
        "undone": False,
        "files": changed_files,
    }

    entry_file = _entry_path(next_seq)
    _atomic_write_text(
        entry_file,
        json.dumps(entry_data, indent=2, ensure_ascii=False) + "\n",
        make_backup=False,
    )
    _save_state(next_seq)
    _prune_entries_if_needed()


def undo() -> HistoryResult:
    entries = _load_all_entries()
    current_seq = _load_current_sequence(entries)

    target_entry = next((e for e in entries if e["sequence"] == current_seq and not e.get("undone", False)), None)
    if target_entry is None:
        raise ValueError("Nothing to undo")

    from planner import core

    data_dir = core.TASKS_FILE.parent
    files_info = target_entry["files"]

    # Verify external changes
    for filename, info in files_info.items():
        file_path = data_dir / filename
        current_content = (
            file_path.read_text(encoding="utf-8") if file_path.exists() else None
        )
        current_hash = _compute_hash(current_content)
        if current_hash != info["after_hash"]:
            raise ValueError(
                "Data changed outside the app since this action; cannot undo safely."
            )

    # Atomic multi-file restoration
    original_states: dict[str, str | None] = {}
    for filename in files_info:
        file_path = data_dir / filename
        original_states[filename] = (
            file_path.read_text(encoding="utf-8") if file_path.exists() else None
        )

    restored: list[str] = []
    try:
        for filename, info in files_info.items():
            file_path = data_dir / filename
            target_text = info["before"]
            if target_text is None:
                file_path.unlink(missing_ok=True)
                file_path.with_name(f"{file_path.name}.bak").unlink(missing_ok=True)
            else:
                _atomic_write_text(file_path, target_text, make_backup=True)
            restored.append(filename)
    except Exception as error:
        # Revert already restored files
        for filename in restored:
            file_path = data_dir / filename
            orig = original_states[filename]
            if orig is None:
                file_path.unlink(missing_ok=True)
            else:
                _atomic_write_text(file_path, orig, make_backup=True)
        raise error

    target_entry["undone"] = True
    _atomic_write_text(
        _entry_path(current_seq),
        json.dumps(target_entry, indent=2, ensure_ascii=False) + "\n",
        make_backup=False,
    )

    # Next current_sequence is the previous valid entry (or 0)
    prev_entries = [e for e in entries if e["sequence"] < current_seq and not e.get("undone", False)]
    next_current = prev_entries[-1]["sequence"] if prev_entries else 0
    _save_state(next_current)

    return HistoryResult(
        label=target_entry["label"],
        affected_ids=list(target_entry["affected_ids"]),
    )


def redo() -> HistoryResult:
    entries = _load_all_entries()
    current_seq = _load_current_sequence(entries)

    # Find the next undone entry with sequence > current_seq
    target_entry = next(
        (e for e in entries if e["sequence"] > current_seq and e.get("undone", False)),
        None,
    )
    if target_entry is None:
        raise ValueError("Nothing to redo")

    from planner import core

    data_dir = core.TASKS_FILE.parent
    files_info = target_entry["files"]

    # Verify external changes against before_hash
    for filename, info in files_info.items():
        file_path = data_dir / filename
        current_content = (
            file_path.read_text(encoding="utf-8") if file_path.exists() else None
        )
        current_hash = _compute_hash(current_content)
        if current_hash != info["before_hash"]:
            raise ValueError(
                "Data changed outside the app since this action; cannot undo safely."
            )

    # Atomic multi-file restoration
    original_states: dict[str, str | None] = {}
    for filename in files_info:
        file_path = data_dir / filename
        original_states[filename] = (
            file_path.read_text(encoding="utf-8") if file_path.exists() else None
        )

    restored: list[str] = []
    try:
        for filename, info in files_info.items():
            file_path = data_dir / filename
            target_text = info["after"]
            if target_text is None:
                file_path.unlink(missing_ok=True)
                file_path.with_name(f"{file_path.name}.bak").unlink(missing_ok=True)
            else:
                _atomic_write_text(file_path, target_text, make_backup=True)
            restored.append(filename)
    except Exception as error:
        for filename in restored:
            file_path = data_dir / filename
            orig = original_states[filename]
            if orig is None:
                file_path.unlink(missing_ok=True)
            else:
                _atomic_write_text(file_path, orig, make_backup=True)
        raise error

    target_entry["undone"] = False
    _atomic_write_text(
        _entry_path(target_entry["sequence"]),
        json.dumps(target_entry, indent=2, ensure_ascii=False) + "\n",
        make_backup=False,
    )

    _save_state(target_entry["sequence"])

    return HistoryResult(
        label=target_entry["label"],
        affected_ids=list(target_entry["affected_ids"]),
    )


def history_peek() -> HistoryPeek:
    entries = _load_all_entries()
    current_seq = _load_current_sequence(entries)

    undo_entry = next((e for e in entries if e["sequence"] == current_seq and not e.get("undone", False)), None)
    redo_entry = next((e for e in entries if e["sequence"] > current_seq and e.get("undone", False)), None)

    return HistoryPeek(
        undo=undo_entry["label"] if undo_entry else None,
        redo=redo_entry["label"] if redo_entry else None,
    )


def history_list(limit: int = 10) -> list[dict[str, Any]]:
    entries = _load_all_entries()
    # Most recent to oldest
    reversed_entries = list(reversed(entries))
    result: list[dict[str, Any]] = []
    for entry in reversed_entries[:limit]:
        result.append(
            {
                "sequence": entry["sequence"],
                "timestamp": entry["timestamp"],
                "label": entry["label"],
                "affected_ids": list(entry["affected_ids"]),
                "undone": entry.get("undone", False),
                "files": list(entry["files"].keys()),
            }
        )
    return result

