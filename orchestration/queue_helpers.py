"""
Helper functions for common queue store operations.
"""

from datetime import datetime
from typing import Dict, Any, Optional, List
from orchestration.queue_store import QueueStore, TaskRecord


# Global store instance (lazy-loaded)
_store_instance: Optional[QueueStore] = None


def get_store(tasks_file: Optional[str] = None) -> QueueStore:
    """
    Get or create global queue store instance.

    Args:
        tasks_file: Path to JSONL task file (optional)

    Returns:
        QueueStore instance
    """
    global _store_instance
    if _store_instance is None:
        _store_instance = QueueStore(tasks_file)
    return _store_instance


def create_record(
    task_id: str,
    repo: str,
    base: str,
    task_file: str,
    branch: str,
    worktree_path: str,
    container: str,
    port: int,
    session_id: str,
    error_file: str,
    attempt: int = 1,
    status: str = "todo",
) -> TaskRecord:
    """
    Helper to create a new task record with current timestamps.

    Args:
        task_id: Unique task identifier
        repo: Repository URL
        base: Base branch name
        task_file: Path to task definition file
        branch: Working branch name
        worktree_path: Path to git worktree
        container: Container identifier
        port: Port number
        session_id: Session identifier
        error_file: Path to error log file
        attempt: Attempt number (default: 1)
        status: Initial status (default: "todo")

    Returns:
        New TaskRecord

    Raises:
        ValueError: If status is invalid
    """
    now = datetime.utcnow().isoformat()
    record = TaskRecord(
        id=task_id,
        repo=repo,
        base=base,
        task_file=task_file,
        status=status,
        branch=branch,
        worktree_path=worktree_path,
        container=container,
        port=port,
        session_id=session_id,
        attempt=attempt,
        error_file=error_file,
        created_at=now,
        updated_at=now,
    )
    record.validate()
    return record


def add_task(store: QueueStore, record: TaskRecord) -> None:
    """
    Add a new task to the queue.

    Args:
        store: QueueStore instance
        record: TaskRecord to add

    Raises:
        ValueError: If record already exists or has invalid status
    """
    store.add_record(record)


def update_task_status(store: QueueStore, task_id: str, new_status: str) -> TaskRecord:
    """
    Update a task's status.

    Args:
        store: QueueStore instance
        task_id: ID of task to update
        new_status: New status value

    Returns:
        Updated TaskRecord

    Raises:
        ValueError: If task not found or status is invalid
    """
    return store.update_record(task_id, {"status": new_status})


def claim_next_task(store: QueueStore) -> Optional[TaskRecord]:
    """
    Claim the next available task (atomically transition from todo to planning).

    Args:
        store: QueueStore instance

    Returns:
        Claimed TaskRecord if available, None otherwise
    """
    return store.claim_first_todo()


def get_task(store: QueueStore, task_id: str) -> Optional[TaskRecord]:
    """
    Get a task by ID.

    Args:
        store: QueueStore instance
        task_id: ID of task to retrieve

    Returns:
        TaskRecord if found, None otherwise
    """
    return store.get_record(task_id)


def get_tasks_by_status(store: QueueStore, status: str) -> List[TaskRecord]:
    """
    Get all tasks with a specific status.

    Args:
        store: QueueStore instance
        status: Status to filter by

    Returns:
        List of TaskRecords with matching status
    """
    return store.get_records_by_status(status)


def list_all_tasks(store: QueueStore) -> List[TaskRecord]:
    """
    List all tasks in the queue.

    Args:
        store: QueueStore instance

    Returns:
        List of all TaskRecords
    """
    return store.get_all_records()


def remove_task(store: QueueStore, task_id: str) -> None:
    """
    Remove a task from the queue.

    Args:
        store: QueueStore instance
        task_id: ID of task to remove

    Raises:
        ValueError: If task not found
    """
    store.remove_record(task_id)
