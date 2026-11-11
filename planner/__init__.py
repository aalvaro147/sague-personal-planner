"""Personal task planner package."""

__version__ = "0.1.0"


def ensure_supported_python():
    import sys

    if sys.version_info < (3, 10):
        raise SystemExit("Planner requires Python 3.10 or newer.")
