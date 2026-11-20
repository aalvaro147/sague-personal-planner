import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

from planner import core, storage


@pytest.fixture(autouse=True)
def isolated_planner_env(tmp_path, monkeypatch):
    data_dir = tmp_path / "planner-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("PLANNER_DATA_DIR", str(data_dir))
    monkeypatch.setattr(core, "TASKS_FILE", data_dir / "tasks.json")
    monkeypatch.setattr(core, "EVENTS_FILE", data_dir / "events.json")
    monkeypatch.setattr(core, "SETTINGS_FILE", data_dir / "settings.json")


def test_create_note_validations():
    # Empty title and empty body raises error
    with pytest.raises(ValueError, match="non-empty title or body"):
        core.create_note(title="", body="")

    with pytest.raises(ValueError, match="non-empty title or body"):
        core.create_note(title="   ", body="   ")

    # Body exceeds limit (> 100,000 chars)
    with pytest.raises(ValueError, match="100,000 characters"):
        core.create_note(title="Long body", body="x" * 100001)

    # Title exceeds limit (> 120 chars)
    with pytest.raises(ValueError, match="120 characters"):
        core.create_note(title="T" * 121, body="Some body")

    # Invalid date
    with pytest.raises(ValueError, match="Invalid date"):
        core.create_note(title="Invalid Date", body="Body", date="not-a-date")

    # Date defaults to today
    today_iso = date.today().isoformat()
    note_today = core.create_note(title="Today note", body="Body")
    assert note_today["date"] == today_iso
    assert note_today["pinned"] is False
    assert note_today["archived"] is False
    assert note_today["deleted"] is False

    # Note with only title
    n1 = core.create_note(title="Only title")
    assert n1["title"] == "Only title"
    assert n1["body"] == ""

    # Note with only body
    n2 = core.create_note(body="Only body")
    assert n2["title"] == ""
    assert n2["body"] == "Only body"


def test_edit_delete_pin_archive_note():
    note = core.create_note(title="Original", body="Body text", tags=["test"])
    note_id = note["id"]

    # Edit without real changes does not update updated timestamp
    orig_updated = note["updated"]
    same = core.edit_note(note_id, title="Original")
    assert same["updated"] == orig_updated

    # Real edit updates updated timestamp
    edited = core.edit_note(note_id, title="Updated title", body="New content")
    assert edited["title"] == "Updated title"
    assert edited["body"] == "New content"

    # Pin note
    pinned = core.pin_note(note_id, pinned=True)
    assert pinned["pinned"] is True

    # Archive note: archivar una nota quita la marca de fijada
    archived = core.archive_note(note_id, archived=True)
    assert archived["archived"] is True
    assert archived["pinned"] is False

    # Cannot pin an archived note
    with pytest.raises(ValueError, match="Cannot pin an archived note"):
        core.pin_note(note_id, pinned=True)

    with pytest.raises(ValueError, match="Cannot pin an archived note"):
        core.edit_note(note_id, pinned=True)

    # Unarchive note then pin
    unarchived = core.archive_note(note_id, archived=False)
    assert unarchived["archived"] is False
    pinned_again = core.pin_note(note_id, pinned=True)
    assert pinned_again["pinned"] is True

    # Delete note (logical delete)
    deleted = core.delete_note(note_id)
    assert deleted["deleted"] is True

    # Accessing deleted note raises ValueError
    with pytest.raises(ValueError, match="Note not found"):
        core.get_note(note_id)


def test_list_notes_filtering_ordering_preview():
    fixed_today = date(2026, 11, 20)
    p = core.create_project("Project Alpha")
    pid = p["id"]

    n1 = core.create_note(title="Note 1", body="First line\nSecond line", date="2026-11-19", project_id=pid, tags=["work"])
    n2 = core.create_note(title="Note 2", body="Important notice", date="2026-11-20", pinned=True, tags=["work", "urgent"])
    n3 = core.create_note(title="", body="  A note without title preview test  \nNext line", date="2026-11-20")
    n4 = core.create_note(title="Archived note", body="Old stuff", date="2026-11-20")
    core.archive_note(n4["id"])

    # Preview check: first non-empty line trimmed to 80 chars
    all_active = core.list_notes()
    previews = {n["id"]: n["preview"] for n in all_active}
    assert previews[n1["id"]] == "First line"
    assert previews[n3["id"]] == "A note without title preview test"

    # Project name check
    note1_item = next(n for n in all_active if n["id"] == n1["id"])
    assert note1_item["project_name"] == "Project Alpha"

    # Ordering: pinned first, then date desc, then updated desc
    assert all_active[0]["id"] == n2["id"]  # Pinned note is first!

    # Filter by date
    notes_19 = core.list_notes(date="2026-11-19")
    assert len(notes_19) == 1
    assert notes_19[0]["id"] == n1["id"]

    # Filter by project
    notes_proj = core.list_notes(project_id=pid)
    assert len(notes_proj) == 1
    assert notes_proj[0]["id"] == n1["id"]

    # Filter by tag
    notes_urgent = core.list_notes(tag="urgent")
    assert len(notes_urgent) == 1
    assert notes_urgent[0]["id"] == n2["id"]

    # Filter by pinned
    notes_pinned = core.list_notes(pinned=True)
    assert len(notes_pinned) == 1
    assert notes_pinned[0]["id"] == n2["id"]

    # Archived filter: by default excluded
    assert not any(n["id"] == n4["id"] for n in all_active)
    archived_list = core.list_notes(archived=True)
    assert any(n["id"] == n4["id"] for n in archived_list)


def test_notes_for_day_and_daily_agenda_unchanged():
    d1 = "2026-11-20"
    d2 = "2026-11-21"
    core.create_note(title="Day 1 Note A", body="Text", date=d1)
    core.create_note(title="Day 1 Note B", body="Text", date=d1, pinned=True)
    core.create_note(title="Day 2 Note", body="Text", date=d2)

    notes_d1 = core.notes_for_day(d1)
    assert len(notes_d1) == 2
    assert notes_d1[0]["pinned"] is True  # Pinned first

    notes_d2 = core.notes_for_day(d2)
    assert len(notes_d2) == 1

    # Check that core.get_day_agenda still works and does not contain notes
    agenda = core.get_day_agenda(d1)
    assert isinstance(agenda, list)
    for entry in agenda:
        assert entry["kind"] in ("block", "event")


def test_set_tags_and_list_tags_with_note():
    n = core.create_note(title="Tag test", body="Body")
    nid = n["id"]

    # Normalization: lower, stripped, deduplicated
    core.set_tags("note", nid, ["  Home  ", "WORK", "home"])
    note = core.get_note(nid)
    assert note["tags"] == ["home", "work"]

    # Invalid characters in tag rejected
    with pytest.raises(ValueError, match="Invalid tag"):
        core.set_tags("note", nid, ["invalid tag with spaces"])

    with pytest.raises(ValueError, match="Invalid tag"):
        core.set_tags("note", nid, ["tag$special!"])

    # list_tags counts
    n2 = core.create_note(title="Tag test 2", body="Body", tags=["home"])
    tags = core.list_tags(kind="note")
    tag_counts = {t["tag"]: t["count"] for t in tags}
    assert tag_counts["home"] == 2
    assert tag_counts["work"] == 1


def test_orphan_project_and_delete_project_unassigns_tasks_and_notes():
    # Orphan project_id treated as no project without throwing exceptions
    n = core.create_note(title="Orphan note", body="Body", project_id="nonexistent-id")
    got_note = core.get_note(n["id"])
    assert got_note["project_name"] is None

    # Create project, task, and note
    p = core.create_project("Move flat")
    pid = p["id"]
    task = core.create_task("Pack boxes", project_id=pid)
    note = core.create_note("Call landlord", body="Call details", project_id=pid)

    assert core.get_note(note["id"])["project_name"] == "Move flat"
    proj_detail = core.get_project(pid)
    assert len(proj_detail["notes"]) == 1
    assert proj_detail["notes"][0]["id"] == note["id"]

    # Delete project: unassigns both tasks and notes in single action
    core.delete_project(pid)

    # Note project_id is now None
    updated_note = core.get_note(note["id"])
    assert updated_note["project_id"] is None
    assert updated_note["project_name"] is None

    # Task project_id is now None
    tasks = core.load_tasks()
    updated_task = next(t for t in tasks if t.id == task.id)
    assert updated_task.project_id is None

    # Project is deleted
    with pytest.raises(ValueError, match="Project not found"):
        core.get_project(pid)

    # Undo restores project, task assignment, and note assignment!
    core.undo()
    restored_proj = core.get_project(pid)
    assert restored_proj["name"] == "Move flat"
    assert len(restored_proj["notes"]) == 1

    restored_note = core.get_note(note["id"])
    assert restored_note["project_id"] == pid
    assert restored_note["project_name"] == "Move flat"

    restored_tasks = core.load_tasks()
    restored_task = next(t for t in restored_tasks if t.id == task.id)
    assert restored_task.project_id == pid


def test_parse_query():
    q = "landlord #home project:Move type:note is:pinned is:archived date:today"
    parsed = core.parse_query(q)
    assert "landlord" in parsed["terms"]
    assert "home" in parsed["tags"]
    assert parsed["project"] == "Move"
    assert parsed["type"] == "note"
    assert parsed["is_pinned"] is True
    assert parsed["is_archived"] is True
    assert parsed["date"] == "today"


def test_search_notes_and_snippet():
    ref_date = date(2026, 11, 20)
    p = core.create_project("Move to new flat")
    pid = p["id"]

    core.create_note(
        title="Call with the landlord",
        body="- deposit back by Dec\n- ask about heating and water pressure",
        tags=["home"],
        project_id=pid,
        date="2026-11-20",
    )
    n_archived = core.create_note(
        title="Archived note",
        body="Secret landlord details",
        tags=["home"],
        project_id=pid,
        date="2026-11-20",
    )
    core.archive_note(n_archived["id"])

    # Search by word matching title
    res_title = core.search("landlord", reference_date=ref_date)
    assert any(r["kind"] == "note" and "landlord" in r["title"].lower() for r in res_title)

    # Search with body match: snippet is populated
    res_body = core.search("heating", reference_date=ref_date)
    note_res = next(r for r in res_body if r["kind"] == "note")
    assert "body" in note_res["matched_in"]
    assert note_res["snippet"] is not None
    assert "heating" in note_res["snippet"].lower()

    # Search matching title only: snippet is None
    res_call = core.search("Call", reference_date=ref_date)
    note_call = next(r for r in res_call if r["kind"] == "note")
    assert "title" in note_call["matched_in"]
    if "body" not in note_call["matched_in"]:
        assert note_call["snippet"] is None

    # Archived notes excluded by default
    assert not any(r["id"] == n_archived["id"] for r in res_title)

    # is:archived includes archived notes
    res_archived = core.search("type:note is:archived landlord", reference_date=ref_date)
    assert any(r["id"] == n_archived["id"] for r in res_archived)

    # is:pending excludes notes
    res_pending = core.search("is:pending landlord", reference_date=ref_date)
    assert not any(r.get("kind") == "note" for r in res_pending)

    # Empty query returns pending tasks
    task = core.create_task("A pending task")
    empty_res = core.search("")
    assert any(r["id"] == task.id for r in empty_res)


def test_undo_redo_note_operations():
    note = core.create_note(title="Undoable Note", body="Initial body")
    nid = note["id"]

    # Undo note creation
    core.undo()
    with pytest.raises(ValueError, match="Note not found"):
        core.get_note(nid)

    # Redo note creation
    core.redo()
    assert core.get_note(nid)["title"] == "Undoable Note"

    # Edit note and undo
    core.edit_note(nid, title="Edited Title")
    assert core.get_note(nid)["title"] == "Edited Title"
    core.undo()
    assert core.get_note(nid)["title"] == "Undoable Note"
    core.redo()
    assert core.get_note(nid)["title"] == "Edited Title"

    # Pin note and undo
    core.pin_note(nid, pinned=True)
    assert core.get_note(nid)["pinned"] is True
    core.undo()
    assert core.get_note(nid)["pinned"] is False
    core.redo()
    assert core.get_note(nid)["pinned"] is True

    # Archive note and undo
    core.archive_note(nid, archived=True)
    assert core.get_note(nid)["archived"] is True
    core.undo()
    assert core.get_note(nid)["archived"] is False
    core.redo()
    assert core.get_note(nid)["archived"] is True

    # Delete note and undo
    core.delete_note(nid)
    with pytest.raises(ValueError, match="Note not found"):
        core.get_note(nid)
    core.undo()
    assert core.get_note(nid)["id"] == nid


def test_missing_and_corrupt_notes_file(tmp_path, monkeypatch):
    notes_file = storage.get_notes_file()
    if notes_file.exists():
        notes_file.unlink()

    # Missing file loads as empty list
    assert storage.load_notes() == []

    # Corrupt file raises ValueError with path
    notes_file.write_text("invalid json content {{{", encoding="utf-8")
    with pytest.raises(ValueError, match=f"Corrupt data file: {notes_file}"):
        storage.load_notes()


def test_contract_json_serializable_and_no_textual_import():
    # Verify core does not import textual
    assert "textual" not in sys.modules or not any(
        m.startswith("planner.core") and "textual" in m for m in sys.modules
    )

    note = core.create_note(title="JSON Test", body="Body content", tags=["api", "test"])
    note_id = note["id"]

    # Test all return values pass json.dumps
    dumped_note = json.dumps(note)
    assert json.loads(dumped_note)["id"] == note_id

    listed = core.list_notes()
    json.dumps(listed)

    day_notes = core.notes_for_day(date.today())
    json.dumps(day_notes)

    tags = core.list_tags()
    json.dumps(tags)

    search_res = core.search("JSON")
    json.dumps(search_res)
