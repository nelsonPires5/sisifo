"""Naming helpers: branch names, container names, and timestamp compaction."""

import re


def derive_branch_name(task_id: str) -> str:
    """
    Derive branch name from task ID.

    Converts task_id to a valid git branch name.
    Example: "T-001" -> "task/T-001"

    Args:
        task_id: Task identifier (e.g., "T-001").

    Returns:
        Valid git branch name.
    """
    # Simple mapping: prepend "task/" and lowercase
    # Handles special chars by replacing with hyphens
    safe_id = task_id.lower().replace(" ", "-").replace("_", "-")
    return f"task/{safe_id}"


def derive_container_name(task_id: str, created_at: str) -> str:
    """
    Derive deterministic container name with task ID and created_at timestamp.

    Args:
        task_id: Task identifier.
        created_at: ISO timestamp string from task record.

    Returns:
        Container name in format: task-<safe-id>-<compact-ts>
    """
    safe_task_id = re.sub(r"[^a-zA-Z0-9_.-]+", "-", task_id).strip("-")
    safe_task_id = safe_task_id or "task"
    created_compact = compact_timestamp(created_at)
    return f"task-{safe_task_id}-{created_compact}"


def compact_timestamp(value: str) -> str:
    """
    Compact timestamp for container names (YYYYMMDDHHMMSS).

    Args:
        value: ISO timestamp string (e.g., "2024-01-15T10:30:45.123456").

    Returns:
        Compacted timestamp string (14 digits) or "ts" as fallback.
    """
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) >= 14:
        return digits[:14]
    if digits:
        return digits
    return "ts"
