"""
Path helpers for queue and attempt directory management.

Provides utilities for deriving queue root, attempt directories, and
ensuring queue bootstrap structure.
"""

import os
from pathlib import Path


def get_queue_root() -> Path:
    """Get the absolute path to the queue root directory.

    Returns:
        Absolute Path to queue/ directory.
    """
    repo_root = Path(__file__).resolve().parent.parent.parent
    return repo_root / "queue"


def get_attempt_dir(task_id: str, attempt: int) -> Path:
    """Get the absolute path to a task's attempt directory.

    Computes deterministic path: queue/opencode/<task-id>/attempt-<attempt_index>/
    where attempt_index = attempt + 1 (so first run attempt=0 maps to attempt-1).

    Args:
        task_id: Task identifier (e.g., "T-001").
        attempt: Current attempt count (0-indexed; 0 means first run).

    Returns:
        Absolute Path to the attempt directory.
    """
    queue_root = get_queue_root()
    attempt_index = attempt + 1
    return queue_root / "opencode" / task_id / f"attempt-{attempt_index}"


def get_attempt_config_dir(task_id: str, attempt: int) -> Path:
    """Get the absolute path to a task's attempt config directory.

    Computes: queue/opencode/<task-id>/attempt-<attempt_index>/config

    Args:
        task_id: Task identifier (e.g., "T-001").
        attempt: Current attempt count (0-indexed; 0 means first run).

    Returns:
        Absolute Path to the config directory.
    """
    return get_attempt_dir(task_id, attempt) / "config"


def get_attempt_data_dir(task_id: str, attempt: int) -> Path:
    """Get the absolute path to a task's attempt data directory.

    Computes: queue/opencode/<task-id>/attempt-<attempt_index>/data

    Args:
        task_id: Task identifier (e.g., "T-001").
        attempt: Current attempt count (0-indexed; 0 means first run).

    Returns:
        Absolute Path to the data directory.
    """
    return get_attempt_dir(task_id, attempt) / "data"


def ensure_queue_dirs() -> None:
    """Ensure queue directories and tasks.jsonl exist."""
    queue_root = get_queue_root()
    tasks_dir = queue_root / "tasks"
    errors_dir = queue_root / "errors"
    opencode_dir = queue_root / "opencode"

    queue_root.mkdir(parents=True, exist_ok=True)
    tasks_dir.mkdir(parents=True, exist_ok=True)
    errors_dir.mkdir(parents=True, exist_ok=True)
    opencode_dir.mkdir(parents=True, exist_ok=True)

    (tasks_dir / ".gitkeep").touch(exist_ok=True)
    (errors_dir / ".gitkeep").touch(exist_ok=True)
    (queue_root / "tasks.jsonl").touch(exist_ok=True)
