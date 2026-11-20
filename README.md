# Personal Planner

A terminal task planner with a Textual interface and a core API that stores data
in JSON files.

## Install as a global command (recommended)

The project installs the `planificador` command, which opens the Textual
interface and uses the same user data directory regardless of the current
working directory. Data defaults to the platform's user data location as
provided by `platformdirs`; set `PLANNER_DATA_DIR` to use a different location.
Run `planificador --data-dir` to print the active directory.

For example, on Linux or macOS:

```bash
PLANNER_DATA_DIR="$HOME/planner-data" planificador
```

In PowerShell:

```powershell
$env:PLANNER_DATA_DIR = "$HOME\planner-data"
planificador
```

### Linux and macOS

Install `pipx` if necessary (for example, `python3 -m pip install --user pipx`),
then install the project in editable mode. Replace the example project path
with the absolute path where this repository is located:

```bash
pipx install --editable /path/to/monopoly
pipx ensurepath
```

Open a **new terminal** after `pipx ensurepath` so the updated `PATH` takes
effect. Check which executable will run:

```bash
which planificador
planificador
```

### Windows

Install `pipx` with `py -m pip install --user pipx` if needed. In PowerShell or
Windows Terminal, install the project (replace the example path with the
repository's path):

```powershell
pipx install --editable C:\path\to\monopoly
pipx ensurepath
```

Open a new terminal after `pipx ensurepath`, then check and run the command:

```powershell
where planificador
planificador
```

Use **Windows Terminal** for the Textual interface; the legacy Windows console
may render it incorrectly.

Because installation is editable, code changes take effect without reinstalling.
After changing dependencies, refresh the isolated environment with:

```bash
pipx reinstall planner
```

To uninstall:

```bash
pipx uninstall planner
```

### Troubleshooting

- **`planificador` is not found:** ensure the pipx executable directory is on
  `PATH`; run `pipx ensurepath` and open a new terminal.
- **The command still is not found after `ensurepath`:** close and reopen the
  terminal (or sign out and back in) so it reloads `PATH`.
- **An old version opens:** run `which planificador` on Linux/macOS or
  `where planificador` on Windows, remove older installations from `PATH`, and
  reinstall using `pipx install --editable /path/to/monopoly`.

## Alternative: virtual environment

This installs an editable command in a project-specific environment. The
command is available only while that environment is activated, unless its
`bin`/`Scripts` directory is added to `PATH`, so this option does not by itself
provide the global command:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
planificador
```

On Windows PowerShell, activate with `.venv\Scripts\Activate.ps1` instead.

## Commands and data migration

Python 3.10 or newer is required.

```bash
planificador             # Start the Textual interface
planificador --cli       # Start the legacy command-line interface
planificador --data-dir  # Print the data directory and exit
planificador --version   # Print the installed version and exit
python -m planner        # Also starts the Textual interface
```

The first launch copies any existing `tasks.json`, `events.json`, and
`settings.json` from the project directory into the new user data directory
without moving or overwriting files. The previous project layout's
`planificador/tareas.json` is also recognized as the legacy task file. A
message reports the destination when migration occurs. JSON saves remain
atomic and keep a neighboring `.bak` copy.

For a manual installation check, install with `pipx` in a clean environment,
open a terminal in a different directory, run `planificador`, and verify that
the same tasks and events are present. `planificador --data-dir` shows where
that data is stored.

## Repeating tasks and events

Open the **Repeat** section in a task or event form to choose daily, weekly, or
monthly recurrence, an interval, and an optional end date or occurrence count.
For weekly rules, enter weekday abbreviations separated by commas, such as
`mon,wed`. Leave the weekday field empty to repeat on the base date's weekday.
The count includes the first occurrence, and monthly dates that do not exist in
a month (for example, the 31st in February) use that month's last day.

Recurring events remain a single series in `events.json`; the agenda calculates
their occurrences for the selected date. Editing or deleting one from the
agenda offers **This one**, **This and future**, and **All**. The Events screen
shows upcoming occurrences for the next year. `core.list_events()` includes all
one-time events and recurring occurrences in the next year by default; pass
explicit start and end dates to query a different range.

Completing a recurring task creates its next pending instance automatically.
Each instance has its own blocks; blocks are not copied forward. The completed
task remains in the task history.

## Daily review

Press `n` from any screen to plan tomorrow. The review suggests overdue tasks,
tasks due soon, and high-priority unplanned tasks, then offers the first free
slot after fixed events and existing blocks. Schedule, skip, defer, or delete
each suggestion; every choice is saved immediately. Press `c` to close the day,
mark missed work done, reschedule it, defer it, or leave it unchanged. The final
summary includes planned and completed time, and can open the tomorrow review.

Use **Review settings** during either flow to change the planning-day window and
default block duration. Defaults are 09:00–18:00 and 60 minutes; these values
are stored alongside the existing week-start preference in `settings.json`.
Unscheduled tasks are shown in pages of 10 by default; change the page size in
Review settings or choose **Show more** to continue through the remaining tasks.
Press `q` or `Escape` to leave a review without undoing completed choices.

## Weekly agenda

Press `w` in the Textual interface to open the weekly agenda. Use `[` and `]`
to move between weeks and `0` to return to the current week. Select a day and a
task in the “Due this week without a planned block” panel, then press `p` to
schedule it for that day. Completed blocks display a `✓` checkmark. The layout switches
to a vertical list automatically when the terminal is too narrow for seven columns.

Use the “Week starts” button to switch between Monday and Sunday. The selection
is saved in the planner data directory (see `planificador --data-dir`); Monday
is used when no settings file exists.

From the daily agenda, use **Add task** to create a task with an optional
planned block. Its planning date defaults to the day being viewed, while the
due date remains empty. The block is created only when both start and end times
are supplied; otherwise the task is saved without a block. **Add event** also
defaults to the day being viewed.

The weekly agenda also has **Add task**; it uses the selected day as the
planning-date context, or leaves the date blank if no day is selected.

## Live Day Agenda & Block Completion

The daily agenda serves as a live working dashboard for the day:

- **Block Statuses:** Each block is either `planned` or `done`. Completing a block preserves it in history and keeps its scheduled time in day load and gap calculations.
- **Completing Blocks vs Tasks:**
  - Press `x`: toggles the selected block between `done` and `planned`. If marking done and it is the last planned block for that task from today onward, a prompt asks whether to complete the whole task.
  - Press `X` (capital): immediately marks the block done and completes the task (and schedules the next recurring instance if applicable) in a single action.
  - Events display a notification when pressing `x` since events cannot be completed.
- **Live Day Timeline:**
  - **Now-line:** A horizontal indicator (`──── 14:32 ────`) shows the current time position.
  - **Item Markers:** `▶` current item in progress, `✓` completed block, `!` missed block, and `·` upcoming item.
  - **Progress Header:** Displays `completed/total blocks · completed of planned time · next: <task> <time>`.
  - **Auto-refresh:** Refreshes automatically every 30 seconds while preserving the currently selected item.
- **Close the Day ("Worked on it"):** In the "Close the day" review (`c`), press `w` on a missed block to mark it done without completing the entire task. The final summary starts with `Today: X/Y blocks done`.

## Monthly Overview

Press `M` (or `Shift+M`) from any screen to open the 7-column monthly overview calendar:

- **Day Indicators:**
  - Load indicators: `○` (no scheduled time), `◔` light (< 2h), `◑` medium (< 5h), `●` heavy (>= 5h).
  - Due task indicator: `!` marks days with tasks due.
  - Previews: Displays up to 3 scheduled blocks or events (with `↻` indicating recurring series).
- **Side Panel:** Shows detailed summary of planned hours, scheduled items, and notes for the selected date.
- **Navigation & Shortcuts:**
  - Arrow keys or `h` / `j` / `k` / `l` navigate cell-by-cell (horizontally day-by-day, vertically week-by-week).
  - `[` and `]` navigate to the previous/next month; `0` returns to today.
  - `Enter` or double-clicking any cell opens the day agenda for that date.
  - `a` creates a task with the date preloaded; `v` creates an event.
- **Responsive Layout:** Automatically switches to a vertical compact list on narrow screens (< 90 columns).

## Undo and redo

Press `u` from any screen to undo the last action, or `U` / `ctrl+r` to redo it.
Actions are also accessible via buttons/mouse from the top navigation bar.

- **History Location:** Recorded entries are stored as individual JSON files in the `history/` directory inside the planner data location (see `planificador --data-dir`).
- **History Limit:** Stores up to 50 entries by default (configurable in `settings.json`). Exceeding the limit automatically removes the oldest entry. History persists across application restarts.
- **What is covered:** Creating, editing, and deleting tasks or events, marking tasks as done (including recurring tasks and their spawned instances), scheduling/moving/removing blocks, deferring tasks, and all decisions made during review flows ("Plan tomorrow" and "Close the day").
- **What is not covered:** Settings and preference changes, screen navigation or cancellation, and external file edits. If files are modified outside the app between actions, undo/redo safely refrains from overwriting changes and notifies the user.

## Notes

Press `m` in the Textual interface to open the Notes screen. Notes are free-form entries with Markdown support in the body, an optional title (up to 120 characters), tags, an optional project, and an assigned date.

- **Default Date & Agenda:** When creating a note, its date defaults to the current day (or the day currently viewed on the agenda). The daily agenda features a dedicated **Notes** section displaying all active notes for that day, and pressing `Enter` on a note opens it in a full-screen Markdown viewer. In narrow terminal windows, the daily agenda notes list compacts cleanly to show note titles.
- **Pinning & Archiving:** Notes can be pinned with `p` to stay pinned at the top of the list, ordered by date and recent update. Notes can be archived with `x` to hide them from standard lists and views without deleting them. Archiving a note automatically unpins it, and archived notes cannot be pinned. Use the **Show archived** toggle to inspect archived entries.
- **Projects Integration:** Projects display their assigned notes in project details. Deleting a project unassigns its tasks and notes cleanly in a single action that can be completely reverted with `u` (undo).
- **Search Syntax:** Press `/` from anywhere in the app to open the unified search modal:
  - `type:note` restricts results to notes; `type:task` restricts results to tasks.
  - `is:pinned` finds pinned notes.
  - `is:archived` allows searching through archived notes (which are hidden by default).
  - `date:today`, `date:yesterday`, `date:week`, or `date:YYYY-MM-DD` filters by calendar date.
  - `#tag` or `tag:name` filters by tags, and `project:name` filters by project.
  - Terms are evaluated case-insensitively and accent-insensitively across title, body, tags, and project name. Note results display a `[N]` marker, metadata, and an excerpt (`snippet`) centered around matches in the body.

## Habits

Press `b` (or `H`) in the Textual interface to open the Habits screen. Habits support daily or specific-weekday schedules, tracking completions, streaks, and performance over time.

- **Calculation Rules:**
  - **Accountable Days:** A scheduled day counts toward statistics only if it is in the past, or if it is today and has already been logged. Today without a log does not break or count toward streaks.
  - **Past Days Unlogged:** Any scheduled day prior to today left unlogged automatically counts as missed.
  - **Excused Days:** Marking a day as excused (`skipped`) neither counts as done nor missed and protects existing streaks.
  - **Streaks & Rates:** Current streak counts consecutive completions going backwards from the latest accountable day. Overall and 30-day completion rates compute `done / (done + missed)` (excluding skipped days).
- **Daily View & Actions:** Navigate days using `[` and `]` (or `0` for today; future dates are blocked). Press `d` for done, `m` for missed, `e` for excused, or `x` to clear a log. Press `a` to create a habit, `E` to edit, `r` to archive, or `Delete` to remove.
- **Detail & Overview:** Press `Enter` on any habit to inspect cards with current streak, best streak, 7/30/all-time completion rates, weekday distribution, a 26-week activity heatmap, and a 30-day sparkline trend. The **Overview** tab displays aggregate completion charts (with 7, 30, and 90-day filters), best/worst performers, and ranking tables.
- **Close the Day Integration:** Press `c` to close the day. After reviewing missed work blocks, the workflow steps through today's scheduled habits with instant action bindings (`d`, `m`, `e`, `k` to skip for later, and `a` to create a habit). If earlier days have unlogged habits, a catch-up prompt allows catching up immediately. The final summary highlights habit completion numbers and active streaks. All decisions support full undo (`u`) and redo (`U`).

## Test

```bash
python -m pip install pytest
python -m pytest -q
```
