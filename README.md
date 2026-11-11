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
schedule it for that day. The layout switches to a vertical list automatically
when the terminal is too narrow for seven columns.

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

## Test

```bash
python -m pip install pytest
python -m pytest -q
```
