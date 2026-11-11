import sys
from datetime import date
from typing import Any

from planner import core


COLORS = {
    "red": "\033[31m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "cyan": "\033[36m",
    "bold": "\033[1m",
}
RESET = "\033[0m"
PRIORITY_LABELS = {"alta": "high", "media": "medium", "baja": "low"}


def colorize(text: str, color: str) -> str:
    if not sys.stdout.isatty():
        return text
    return f"{COLORS[color]}{text}{RESET}"


def describe_error(error: Exception) -> str:
    message = str(error)
    if message.startswith("Invalid JSON") or message.startswith("Duplicate "):
        return f"Saved data is invalid: {message}"
    if message.startswith(("Task ", "Block ", "Event ")):
        return message
    if isinstance(error, OSError):
        return f"Could not read or save data: {message}"
    return message


def prompt_due_date() -> date | None:
    while True:
        entry = input("Due date (YYYY-MM-DD, or Enter for none): ").strip()
        if not entry:
            return None
        try:
            due_date = date.fromisoformat(entry)
        except ValueError:
            print(colorize("Invalid date. Use YYYY-MM-DD.", "yellow"))
            continue
        if due_date.isoformat() != entry:
            print(colorize("Invalid date. Use YYYY-MM-DD.", "yellow"))
            continue
        return due_date


def prompt_priority() -> str:
    priorities = {
        "1": "alta",
        "2": "media",
        "3": "baja",
    }
    while True:
        print("Priority: 1) high  2) medium  3) low (Enter for medium)")
        selection = input("> ").strip()
        if not selection:
            return "media"
        if selection in priorities:
            return priorities[selection]
        print(colorize("Choose 1, 2, or 3.", "yellow"))


def create_task() -> None:
    title = input("Task title: ").strip()
    if not title:
        print(colorize("The title cannot be empty.", "yellow"))
        return

    due = prompt_due_date()
    priority = prompt_priority()
    core.create_task(title, due, priority)
    print(colorize("Task created.", "green"))


def due_status(due: date | None) -> str:
    if due is None:
        return "No due date"

    days_remaining = (due - date.today()).days
    if days_remaining < 0:
        days_overdue = abs(days_remaining)
        unit = "day" if days_overdue == 1 else "days"
        return f"Overdue by {days_overdue} {unit}"
    if days_remaining == 0:
        return "Due today"
    unit = "day" if days_remaining == 1 else "days"
    return f"{days_remaining} {unit} remaining"


def display_tasks(tasks: list[core.Task]) -> None:
    print(f"\n{colorize('Your tasks', 'bold')}")
    print("─" * 60)
    for number, task in enumerate(tasks, start=1):
        status = "✓ Done" if task.done else "Pending"
        due_details = (
            f"{task.due:%Y-%m-%d} ({due_status(task.due)})"
            if task.due is not None
            else due_status(None)
        )
        line = (
            f"{number:>2}. [{status}] [{PRIORITY_LABELS.get(task.priority, task.priority)}] "
            f"{task.title} - {due_details}"
        )
        if not task.done and task.due is not None and task.due < date.today():
            line = colorize(line, "red")
        print(line)
    print("─" * 60)


def list_tasks() -> list[core.Task]:
    tasks = core.list_tasks()
    if not tasks:
        print(colorize("There are no tasks yet.", "yellow"))
        return []
    display_tasks(tasks)
    return tasks


def display_filtered_tasks(tasks: list[core.Task], empty_message: str) -> None:
    if not tasks:
        print(colorize(empty_message, "yellow"))
        return
    display_tasks(tasks)


def choose_task(action: str, tasks: list[core.Task]) -> core.Task | None:
    action_labels = {
        "delete": "delete",
        "complete": "complete",
        "edit": "edit",
        "plan": "schedule",
    }
    action_label = action_labels.get(action, action)
    print(
        f"Enter the number of the task to {action_label} (or Enter to cancel):"
    )
    selection = input("> ").strip()
    if not selection:
        print("Action cancelled.")
        return None

    try:
        index = int(selection) - 1
    except ValueError:
        print(colorize("Invalid selection: enter a number.", "yellow"))
        return None
    if not 0 <= index < len(tasks):
        print(colorize("There is no task with that number.", "yellow"))
        return None
    return tasks[index]


def update_task(action: str) -> None:
    tasks = core.list_tasks()
    if not tasks:
        print(colorize("There are no tasks yet.", "yellow"))
        return

    if action == "complete":
        tasks = [task for task in tasks if not task.done]
        if not tasks:
            print(colorize("There are no pending tasks.", "yellow"))
            return
    display_tasks(tasks)

    task = choose_task(action, tasks)
    if task is None:
        return
    if action == "complete":
        core.complete_task(task.id)
        print(colorize("Task marked as done.", "green"))
    else:
        core.delete_task(task.id)
        print(colorize("Task deleted.", "green"))


def edit_task() -> None:
    tasks = core.list_tasks()
    if not tasks:
        print(colorize("There are no tasks yet.", "yellow"))
        return
    display_tasks(tasks)
    task = choose_task("edit", tasks)
    if task is None:
        return

    title = input("New title: ").strip()
    if not title:
        print(colorize("The title cannot be empty.", "yellow"))
        return
    core.edit_task(task.id, title)
    print(colorize("Task updated.", "green"))


def display_tasks_due_today() -> None:
    display_filtered_tasks(
        core.tasks_due_today(),
        "No pending tasks are due today or overdue.",
    )


def display_tasks_due_this_week() -> None:
    display_filtered_tasks(
        core.tasks_due_this_week(),
        "No pending tasks are due in the next 7 days.",
    )


def display_pending_tasks() -> None:
    display_filtered_tasks(core.pending_tasks(), "There are no pending tasks.")


def display_completed_tasks() -> None:
    display_filtered_tasks(core.completed_tasks(), "There are no completed tasks.")


def prompt_planning_date() -> date:
    while True:
        entry = input(
            "Block date (YYYY-MM-DD, today, tomorrow, or a weekday): "
        ).strip()
        try:
            return core.parse_date(entry)
        except ValueError:
            print(
                colorize(
                    "Invalid date. Use YYYY-MM-DD, today, tomorrow, or a weekday.",
                    "yellow",
                )
            )


def prompt_block_time(label: str) -> str:
    while True:
        entry = input(f"{label} time (HH:MM or hour, e.g. 9:00 or 10): ").strip()
        try:
            return core.normalize_time(entry, label.casefold())
        except ValueError as error:
            print(colorize(str(error), "yellow"))
            continue


def prompt_block_interval() -> tuple[str, str, str]:
    block_date = prompt_planning_date().isoformat()
    while True:
        start = prompt_block_time("Start")
        end = prompt_block_time("End")
        if end <= start:
            print("End time must be later than start time.")
            continue
        return block_date, start, end


def plan_task() -> None:
    tasks = core.pending_tasks()
    if not tasks:
        print(colorize("There are no pending tasks to schedule.", "yellow"))
        return

    unplanned_ids = {task.id for task in core.get_unplanned_tasks()}
    tasks.sort(key=lambda task: task.id not in unplanned_ids)
    print("\nTasks available to schedule:")
    for number, task in enumerate(tasks, start=1):
        if task.id in unplanned_ids:
            planning_status = "Unplanned"
        else:
            count = len(task.blocks)
            planning_status = (
                f"{count} scheduled block" if count == 1
                else f"{count} scheduled blocks"
            )
        print(f"{number:>2}. {task.title} ({planning_status})")

    task = choose_task("plan", tasks)
    if task is None:
        return

    block_date, start, end = prompt_block_interval()
    overlaps = core.find_overlaps(block_date, start, end)
    if overlaps:
        print(colorize(f"Warning: this block overlaps with {format_overlaps(overlaps)}.", "yellow"))
        if input("Schedule it anyway? (y/N): ").strip().casefold() not in {
            "y",
            "yes",
        }:
            print("Scheduling cancelled.")
            return

    core.plan_block(task.id, block_date, start, end)
    print(colorize("Block scheduled.", "green"))


def prompt_agenda_date() -> date:
    while True:
        entry = input(
            "Agenda date (YYYY-MM-DD, today, tomorrow, or a weekday): "
        ).strip()
        try:
            return core.parse_date(entry)
        except ValueError:
            print(
                colorize(
                    "Invalid date. Use YYYY-MM-DD, today, tomorrow, or a weekday.",
                    "yellow",
                )
            )


def display_day_agenda() -> None:
    selected_date = prompt_agenda_date()
    entries = core.get_day_agenda(selected_date.isoformat())
    weekday_names = (
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday",
    )
    weekday = weekday_names[selected_date.weekday()]
    print(f"\nAgenda for {weekday}, {selected_date:%Y-%m-%d}")
    print("─" * 60)
    if not entries:
        print("There are no scheduled items for this day.")
        return

    free_gaps = iter(core.get_free_gaps(entries))
    previous_end: str | None = None
    for entry in entries:
        if entry["kind"] == "block":
            start = entry["block"].start
            end = entry["block"].end
            priority = PRIORITY_LABELS.get(
                entry["task"].priority,
                entry["task"].priority,
            )
            label = f"[T] {entry['task'].title} [{priority}]"
        else:
            start = entry["event"].start
            end = entry["event"].end
            location = (
                f" ({entry['event'].location})"
                if entry["event"].location
                else ""
            )
            label = f"[E] {entry['event'].title}{location}"
        if previous_end is not None:
            if start > previous_end:
                gap_start, gap_end = next(free_gaps)
                print(f"  Free time: {gap_start}-{gap_end}")
            elif start < previous_end:
                print(colorize("  Warning: scheduled items overlap.", "yellow"))
        print(f"  {start}-{end}  {label}")
        if previous_end is None or end > previous_end:
            previous_end = end
    print("─" * 60)


def choose_block(
    entries: list[core.BlockAgendaEntry],
    action: str,
) -> core.BlockAgendaEntry | None:
    if not entries:
        print(colorize("There are no task blocks to manage.", "yellow"))
        return None

    print("\nScheduled task blocks:")
    for number, entry in enumerate(entries, start=1):
        block = entry["block"]
        task = entry["task"]
        print(
            f"{number:>2}. {block.date:%Y-%m-%d} "
            f"{block.start}-{block.end} - {task.title}"
        )
    action_labels = {"move": "move", "remove": "remove"}
    action_label = action_labels.get(action, action)
    selection = input(
        f"Block number to {action_label} (Enter to cancel): "
    ).strip()
    if not selection:
        print("Action cancelled.")
        return None
    try:
        index = int(selection) - 1
    except ValueError:
        print(colorize("Invalid selection: enter a number.", "yellow"))
        return None
    if not 0 <= index < len(entries):
        print(colorize("There is no block with that number.", "yellow"))
        return None
    return entries[index]


def manage_block(action: str) -> None:
    entry = choose_block(core.get_active_task_blocks(), action)
    if entry is None:
        return

    block = entry["block"]
    task = entry["task"]
    if action == "remove":
        core.remove_block(task.id, block.id)
        print(colorize("Block removed.", "green"))
        return

    block_date, start, end = prompt_block_interval()
    overlaps = core.find_overlaps(
        block_date,
        start,
        end,
        exclude_block_id=block.id,
    )
    if overlaps:
        print(colorize(f"Warning: this block overlaps with {format_overlaps(overlaps)}.", "yellow"))
        if input("Move it anyway? (y/N): ").strip().casefold() not in {
            "y",
            "yes",
        }:
            print("Move cancelled.")
            return
    core.move_block(task.id, block.id, block_date, start, end)
    print(colorize("Block moved.", "green"))


def format_overlaps(entries: list[core.AgendaEntry]) -> str:
    descriptions = []
    for entry in entries:
        if entry["kind"] == "block":
            descriptions.append(f'task "{entry["task"].title}"')
        else:
            descriptions.append(f'event "{entry["event"].title}"')
    return ", ".join(descriptions)


def prompt_event_date() -> date:
    while True:
        entry = input(
            "Event date (YYYY-MM-DD, today, tomorrow, or a weekday): "
        ).strip()
        try:
            return core.parse_date(entry)
        except ValueError:
            print(
                colorize(
                    "Invalid date. Use YYYY-MM-DD, today, tomorrow, or a weekday.",
                    "yellow",
                )
            )


def create_event() -> None:
    title = input("Event title: ").strip()
    if not title:
        print(colorize("The title cannot be empty.", "yellow"))
        return
    event_date = prompt_event_date().isoformat()
    start = prompt_block_time("Start")
    end = prompt_block_time("End")
    location = input("Location (optional): ").strip() or None
    notes = input("Notes (optional): ").strip() or None

    overlaps = core.find_overlaps(event_date, start, end)
    if overlaps:
        print(colorize(f"Warning: this event overlaps with {format_overlaps(overlaps)}.", "yellow"))
        if input("Create it anyway? (y/N): ").strip().casefold() not in {"y", "yes"}:
            print("Event creation cancelled.")
            return

    core.create_event(title, event_date, start, end, location, notes)
    print(colorize("Event created.", "green"))


def choose_event(action: str) -> core.EventOccurrence | None:
    events = core.list_events()
    if not events:
        print(colorize("There are no active events.", "yellow"))
        return None

    print("\nActive events:")
    for number, event in enumerate(events, start=1):
        location = f" ({event.location})" if event.location else ""
        recurrence = " ↻" if event.recurring else ""
        print(
            f"{number:>2}. {event.date:%Y-%m-%d} {event.start}-{event.end} "
            f"- {event.title}{recurrence}{location}"
        )
    selection = input(f"Event number to {action} (Enter to cancel): ").strip()
    if not selection:
        print("Action cancelled.")
        return None
    try:
        index = int(selection) - 1
    except ValueError:
        print(colorize("Invalid selection: enter a number.", "yellow"))
        return None
    if not 0 <= index < len(events):
        print(colorize("There is no event with that number.", "yellow"))
        return None
    return events[index]


def edit_event() -> None:
    event = choose_event("edit")
    if event is None:
        return

    title_input = input(f"Title [{event.title}] (Enter to keep): ").strip()
    date_input = input(
        f"Date [{event.date:%Y-%m-%d}] (Enter to keep): "
    ).strip()
    start_input = input(f"Start [{event.start}] (Enter to keep): ").strip()
    end_input = input(f"End [{event.end}] (Enter to keep): ").strip()
    location_input = input(
        f"Location [{event.location or 'none'}] (Enter to keep, - to clear): "
    ).strip()
    notes_input = input(
        f"Notes [{event.notes or 'none'}] (Enter to keep, - to clear): "
    ).strip()

    changes: dict[str, Any] = {}
    if title_input:
        changes["title"] = title_input
    if date_input:
        changes["date"] = core.parse_date(date_input).isoformat()
    if start_input:
        changes["start"] = start_input
    if end_input:
        changes["end"] = end_input
    if location_input:
        changes["location"] = None if location_input == "-" else location_input
    if notes_input:
        changes["notes"] = None if notes_input == "-" else notes_input

    if {"date", "start", "end"} & changes.keys():
        event_date = str(changes.get("date", event.date.isoformat()))
        start = str(changes.get("start", event.start))
        end = str(changes.get("end", event.end))
        overlaps = core.find_overlaps(
            event_date,
            start,
            end,
            exclude_event_id=event.id,
        )
        if overlaps:
            print(
                colorize(
                    f"Warning: this event overlaps with {format_overlaps(overlaps)}.",
                    "yellow",
                )
            )
            if input("Save the changes anyway? (y/N): ").strip().casefold() not in {
                "y",
                "yes",
            }:
                print("Event edit cancelled.")
                return

    core.edit_event(event.id, **changes)
    print(colorize("Event updated.", "green"))


def delete_event() -> None:
    event = choose_event("delete")
    if event is None:
        return
    core.delete_event(event.id)
    print(colorize("Event deleted.", "green"))


def display_menu() -> None:
    width = 55
    print(f"\n╭{'─' * width}╮")
    title = "PERSONAL PLANNER"
    margin = (width - len(title)) // 2
    print(
        f"│{' ' * margin}{colorize(title, 'bold')}"
        f"{' ' * (width - margin - len(title))}│"
    )
    print(f"├{'─' * width}┤")
    for number, label in (
        ("1", "Create task"),
        ("2", "List tasks"),
        ("3", "Due today / overdue"),
        ("4", "Next 7 days"),
        ("5", "Pending tasks"),
        ("6", "Completed tasks"),
        ("7", "Delete task"),
        ("8", "Complete task"),
        ("9", "Edit task"),
        ("10", "Schedule task"),
        ("11", "Day agenda"),
        ("12", "Move a block"),
        ("13", "Remove a block"),
        ("14", "Add event"),
        ("15", "Edit event"),
        ("16", "Delete event"),
        ("0", "Exit"),
    ):
        content = f"  {number}  {label}"
        line = (
            f"  {colorize(number, 'cyan')}  {label}"
            f"{' ' * (width - len(content))}"
        )
        print(f"│{line}│")
    print(f"╰{'─' * width}╯")


def main() -> None:
    while True:
        display_menu()
        try:
            option = input("Choose an option: ").strip()
            if option == "1":
                create_task()
            elif option == "2":
                list_tasks()
            elif option == "3":
                display_tasks_due_today()
            elif option == "4":
                display_tasks_due_this_week()
            elif option == "5":
                display_pending_tasks()
            elif option == "6":
                display_completed_tasks()
            elif option == "7":
                update_task("delete")
            elif option == "8":
                update_task("complete")
            elif option == "9":
                edit_task()
            elif option == "10":
                plan_task()
            elif option == "11":
                display_day_agenda()
            elif option == "12":
                manage_block("move")
            elif option == "13":
                manage_block("remove")
            elif option == "14":
                create_event()
            elif option == "15":
                edit_event()
            elif option == "16":
                delete_event()
            elif option == "0":
                print(colorize("Goodbye!", "cyan"))
                return
            else:
                print(
                    colorize(
                        "Invalid option. Choose 0 or a number from 1 to 16.",
                        "yellow",
                    )
                )
        except (OSError, ValueError) as error:
            print(colorize(describe_error(error), "red"))
        except EOFError:
            print("\nEnd of input. Goodbye!")
            return


if __name__ == "__main__":
    main()
