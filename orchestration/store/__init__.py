"""
Store layer for queue persistence and error reporting.

Canonical exports:
- QueueStore: Task record persistence with JSONL locking and atomic writes
- generate_error_report: Generate markdown error reports
- write_error_report: Persist error reports to disk
"""

try:
    from orchestration.store.repository import QueueStore
    from orchestration.store.error_store import (
        generate_error_report,
        write_error_report,
    )
except ImportError:
    from store.repository import QueueStore
    from store.error_store import (
        generate_error_report,
        write_error_report,
    )

__all__ = [
    "QueueStore",
    "generate_error_report",
    "write_error_report",
]
