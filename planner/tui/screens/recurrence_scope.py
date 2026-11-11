from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label


class RecurrenceScopeDialog(ModalScreen[str | None]):
    def __init__(self, action: str) -> None:
        super().__init__()
        self.action = action

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label(
                f"{self.action} recurring event",
                classes="dialog-title",
            )
            yield Label("Choose which occurrences to affect.")
            yield Button("This one", id="scope-this")
            yield Button("This and future", id="scope-this-and-future")
            yield Button("All", id="scope-all", variant="primary")
            yield Button("Cancel", id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        scope_by_button = {
            "scope-this": "this",
            "scope-this-and-future": "this_and_future",
            "scope-all": "all",
        }
        if event.button.id == "cancel":
            self.dismiss(None)
        else:
            self.dismiss(scope_by_button[event.button.id])
