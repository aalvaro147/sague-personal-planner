import argparse
import os
import sys
from pathlib import Path

from planner import ensure_supported_python

ensure_supported_python()

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Button, Footer, Header

from planner import __version__, core
from planner.tui.screens.agenda import AgendaScreen
from planner.tui.screens.events import EventsScreen
from planner.tui.screens.habits import HabitsScreen
from planner.tui.screens.month import MonthScreen
from planner.tui.screens.notes import NotesScreen
from planner.tui.screens.review import ReviewScreen
from planner.tui.screens.tasks import TasksScreen
from planner.tui.screens.week import WeekScreen


class PlannerApp(App[None]):
    TITLE = "Personal Planner"
    SUB_TITLE = "Tasks, events, and daily agenda"
    CSS_PATH = Path(__file__).with_name("styles.tcss")
    SCREENS = {
        "agenda": AgendaScreen,
        "tasks": TasksScreen,
        "events": EventsScreen,
        "week": WeekScreen,
        "month": MonthScreen,
        "notes": NotesScreen,
        "habits": HabitsScreen,
    }
    MODES = {
        "default": "agenda",
        "tasks": "tasks",
        "events": "events",
        "week": "week",
        "month": "month",
        "notes": "notes",
        "habits": "habits",
    }
    DEFAULT_MODE = "default"
    BINDINGS = [
        ("a", "add", "Add"),
        ("e", "edit", "Edit"),
        ("d", "delete", "Delete"),
        ("p", "plan", "Plan"),
        ("t", "tasks", "Tasks"),
        ("v", "events", "Events"),
        ("w", "week", "Week"),
        ("m", "notes", "Notes"),
        Binding("M", "month", "Month"),
        ("b", "habits", "Habits"),
        Binding("H", "habits", "Habits", show=False),
        ("/", "search", "Search"),
        ("h", "today", "Today"),
        ("n", "plan_tomorrow", "Plan tomorrow"),
        ("c", "close_day", "Close the day"),
        ("left", "previous_day", "Previous"),
        ("right", "next_day", "Next"),
        Binding("u", "undo", "Undo", id="undo"),
        Binding("U", "redo", "Redo", id="redo"),
        Binding("ctrl+r", "redo", "Redo", show=False),
        ("q", "quit", "Quit"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Footer()

    def on_mount(self) -> None:
        if os.environ.get("PLANNER_DATA_DIR"):
            core.configure_data_dir()
        self._update_history_bindings()

    def action_undo(self) -> None:
        try:
            result = core.undo()
        except ValueError as error:
            if str(error) == "Nothing to undo":
                self.notify("Nothing to undo")
            else:
                self.notify(str(error), severity="warning")
            return
        except Exception as error:
            self.notify(str(error), severity="warning")
            return

        self.notify(f"Undone: {result.label}")
        self._refresh_after_history_action("undo", result)

    def action_redo(self) -> None:
        try:
            result = core.redo()
        except ValueError as error:
            if str(error) == "Nothing to redo":
                self.notify("Nothing to redo")
            else:
                self.notify(str(error), severity="warning")
            return
        except Exception as error:
            self.notify(str(error), severity="warning")
            return

        self.notify(f"Redone: {result.label}")
        self._refresh_after_history_action("redo", result)

    def _refresh_after_history_action(self, action_type: str, result: core.HistoryResult) -> None:
        self._update_history_bindings()
        screen = self.screen
        if hasattr(screen, "on_history_action"):
            screen.on_history_action(action_type, result)
        elif hasattr(screen, "refresh_data"):
            screen.run_worker(screen.refresh_data, exclusive=True)

    def _update_history_bindings(self) -> None:
        try:
            peek = core.history_peek()
        except Exception:
            peek = None

        undo_label = peek.undo if peek else None
        redo_label = peek.redo if peek else None

        undo_desc = f'undo "{undo_label}"' if undo_label else "Undo"
        redo_desc = f'redo "{redo_label}"' if redo_label else "Redo"

        targets = [self]
        if self.screen and self.screen != self:
            targets.append(self.screen)

        for target in targets:
            if hasattr(target, "_bindings"):
                bindings_map = target._bindings
                if "u" in bindings_map.key_to_bindings:
                    bindings_map.key_to_bindings["u"] = [
                        Binding("u", "undo", undo_desc, tooltip=undo_desc, id="undo")
                    ]
                if "U" in bindings_map.key_to_bindings:
                    bindings_map.key_to_bindings["U"] = [
                        Binding("U", "redo", redo_desc, tooltip=redo_desc, id="redo")
                    ]

        try:
            footers = self.query(Footer)
            for footer in footers:
                footer.refresh_bindings()
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "undo":
            self.action_undo()
        elif event.button.id == "redo":
            self.action_redo()
        elif event.button.id == "open-habits":
            self.action_habits()
        elif event.button.id == "open-month":
            self.action_month()

    def action_add(self) -> None:
        self._call_screen_action("add_item")

    def action_edit(self) -> None:
        self._call_screen_action("edit_item")

    def action_delete(self) -> None:
        self._call_screen_action("delete_item")

    def action_plan(self) -> None:
        self._call_screen_action("plan_selected_task")

    def action_tasks(self) -> None:
        self.switch_mode("tasks")

    def action_events(self) -> None:
        self.switch_mode("events")

    def action_week(self) -> None:
        self.switch_mode("week")

    def action_month(self) -> None:
        self.switch_mode("month")

    def action_notes(self) -> None:
        self.switch_mode("notes")

    def action_habits(self) -> None:
        self.switch_mode("habits")

    def action_search(self) -> None:
        from planner.tui.screens.search import SearchModal
        self.push_screen(SearchModal())

    def action_today(self) -> None:
        self._call_screen_action("action_today")

    def action_plan_tomorrow(self) -> None:
        self.push_screen(ReviewScreen("plan"))

    def action_close_day(self) -> None:
        self.push_screen(ReviewScreen("close"))

    def action_previous_day(self) -> None:
        self._call_screen_action("action_previous_day")

    def action_next_day(self) -> None:
        self._call_screen_action("action_next_day")

    def _call_screen_action(self, action_name: str) -> None:
        action = getattr(self.screen, action_name, None)
        if action is None:
            self.notify(
                f"This action is not available on the {self.screen.name} screen.",
                severity="warning",
            )
            return
        action()


def main() -> None:
    parser = argparse.ArgumentParser(prog="planificador")
    parser.add_argument(
        "--data-dir",
        action="store_true",
        help="Print the planner data directory and exit.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "--cli",
        action="store_true",
        help="Start the legacy command-line interface.",
    )
    args = parser.parse_args()

    try:
        if args.data_dir:
            print(core.get_data_dir())
            return
        data_dir, migrated = core.initialize_data_storage()
        if migrated:
            print(f"Migrated existing data to {data_dir}.")
        if args.cli:
            from planner.cli import main as cli_main

            cli_main()
            return
        PlannerApp().run()
    except (OSError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
