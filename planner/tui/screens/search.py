from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, ListItem, ListView, Static

from planner import core
from planner.tui.screens.note_detail import NoteDetailModal


class SearchModal(ModalScreen[None]):
    """Modal screen for searching tasks and notes."""

    BINDINGS = [
        ("escape", "close", "Close"),
    ]

    def __init__(self, initial_query: str = "") -> None:
        super().__init__()
        self.initial_query = initial_query
        self.results: list[dict[str, Any]] = []

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog search-dialog"):
            yield Label("Search", classes="dialog-title")
            yield Input(
                value=self.initial_query,
                placeholder="Search (e.g. type:note #home project:Work query)...",
                id="search-input",
            )
            yield Static("", id="search-status", classes="status")
            yield ListView(id="search-results-list")
            with Horizontal(classes="form-actions"):
                yield Button("Close", id="close-search")

    async def on_mount(self) -> None:
        if self.initial_query:
            await self._perform_search(self.initial_query)

    async def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "search-input":
            await self._perform_search(event.value)

    async def _perform_search(self, query: str) -> None:
        lv = self.query_one("#search-results-list", ListView)
        await lv.clear()
        if not query.strip():
            self.results = []
            self.query_one("#search-status", Static).update("Type a query to search.")
            return

        try:
            self.results = core.search(query)
            self.query_one("#search-status", Static).update(f"{len(self.results)} result(s)")

            for item in self.results:
                kind = item.get("kind", "task")
                if kind == "note":
                    title = item.get("title") or item.get("preview") or "Untitled Note"
                    date_str = item.get("date", "")
                    proj = f" · {item['project_name']}" if item.get("project_name") else ""
                    tags = " · " + " ".join(f"#{t}" for t in item.get("tags", [])) if item.get("tags") else ""
                    header = f"[N] {title} ({date_str}{proj}{tags})"
                    snippet = item.get("snippet")
                    if snippet:
                        text = f"{header}\n    {snippet}"
                    else:
                        text = header
                    await lv.append(ListItem(Static(text), classes="search-result-note"))
                else:
                    title = item.get("title", "")
                    status = "DONE" if item.get("done") else "PENDING"
                    due = item.get("due") or "No due date"
                    await lv.append(ListItem(Static(f"[T] [{status}] {title} · Due: {due}"), classes="search-result-task"))
        except Exception as e:
            self.query_one("#search-status", Static).update(f"Error: {e}")

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.id == "search-results-list" and event.index < len(self.results):
            selected = self.results[event.index]
            if selected.get("kind") == "note":
                self.app.push_screen(NoteDetailModal(selected["id"]))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "close-search":
            self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)

