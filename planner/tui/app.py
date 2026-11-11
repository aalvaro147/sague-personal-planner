import argparse
import os
import sys
from pathlib import Path

from planner import ensure_supported_python

ensure_supported_python()

from textual.app import App, ComposeResult
from textual.widgets import Footer, Header

from planner import __version__, core
from planner.tui.screens.agenda import AgendaScreen
from planner.tui.screens.events import EventsScreen
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
    }
    MODES = {
        "default": "agenda",
        "tasks": "tasks",
        "events": "events",
        "week": "week",
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
        ("h", "today", "Today"),
        ("n", "plan_tomorrow", "Plan tomorrow"),
        ("c", "close_day", "Close the day"),
        ("left", "previous_day", "Previous"),
        ("right", "next_day", "Next"),
        ("q", "quit", "Quit"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Footer()

    def on_mount(self) -> None:
        if os.environ.get("PLANNER_DATA_DIR"):
            core.configure_data_dir()

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
