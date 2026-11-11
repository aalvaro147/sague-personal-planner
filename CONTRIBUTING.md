# Contributing to Personal Planner

Thank you for your interest in contributing to Personal Planner! We welcome contributions from everyone—whether it's proposing new features, reporting bugs, improving documentation, or submitting pull requests.

## Ways to Contribute

1. **Feature Proposals & Ideas**:
   - Have an idea or proposal? Open a **GitHub Discussion** in the "Ideas" category or create an **Issue** with the `proposal` label.
   - For larger architectural changes, discussing beforehand helps align on design before writing code.
2. **Bug Reports**:
   - Check if an existing issue already describes the problem.
   - If not, open a new issue detailing:
     - Steps to reproduce
     - Expected vs. actual behavior
     - Environment details (OS, Python version)
3. **Code Contributions**:
   - Look for issues tagged with `good first issue` or `help wanted`.
   - Please ensure all tests pass before submitting a Pull Request.

---

## Development Setup

1. **Clone the repository**:
   ```bash
   git clone https://github.com/aalvaro147/sague-personal-planner.git
   cd sague-personal-planner
   ```

2. **Create and activate a virtual environment**:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. **Install the package in editable mode with dependencies**:
   ```bash
   pip install -e .
   pip install pytest typeguard
   ```

---

## Running Tests

All features and screens have test coverage. Before submitting changes, run the test suite:

```bash
pytest
```

To run a specific test module:
```bash
pytest test_review.py
pytest test_review_tui.py
```

---

## Pull Request Guidelines

1. Create a descriptive branch from `main`:
   ```bash
   git checkout -b feature/your-proposal-name
   ```
2. Make your changes adhering to existing architecture:
   - Keep the UI (`planner/tui/`) free of business logic; domain logic belongs in `planner/core.py` and `planner/review.py`.
   - Preserve existing docstrings, comments, and public APIs.
3. Add unit and/or TUI tests covering new behavior.
4. Ensure all tests pass (`pytest`).
5. Commit with clear, concise messages.
6. Open a Pull Request against the `main` branch with a summary of the changes and motivation.
