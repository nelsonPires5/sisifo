"""
Error reporting and persistence for task pipeline failures.

Generates detailed markdown error reports and persists them to disk,
delegating to store.error_store for the actual implementation.
"""

try:
    from orchestration.store import (
        generate_error_report,
        write_error_report,
    )
except ImportError:
    from store import generate_error_report, write_error_report

__all__ = [
    "generate_error_report",
    "write_error_report",
]
