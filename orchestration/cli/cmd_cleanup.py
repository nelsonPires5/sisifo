"""
taskq cleanup command implementation.

Cleans up runtime artifacts for completed or cancelled tasks.
"""

import sys
import logging
import argparse
import shutil
from pathlib import Path

# Handle both absolute and relative imports
try:
    from orchestration.core.models import TaskRecord
    from orchestration.adapters.docker import cleanup_task_containers
    from orchestration.adapters.git import remove_worktree, GitRuntimeError
except ImportError:
    from core.models import TaskRecord
    from adapters.docker import cleanup_task_containers
    from adapters.git import remove_worktree, GitRuntimeError


def cmd_cleanup(cli_instance, args: argparse.Namespace) -> int:
    """Clean up runtime artifacts for completed or cancelled tasks.

    Removes docker containers and worktrees associated with tasks.
    By default only cleans done and cancelled tasks. Can filter by:
    - --done-only: Only clean tasks in 'done' status
    - --cancelled-only: Only clean tasks in 'cancelled' status
    - --id: Clean specific task ID
    - --keep-worktree: Remove containers but keep worktrees

    Args:
        cli_instance: TaskQCLI instance with store
        args: Parsed command-line arguments with: id, done_only, cancelled_only, keep_worktree

    Returns:
        Exit code (0 on success, 1 on error)
    """
    try:
        task_id = args.id
        done_only = args.done_only
        cancelled_only = args.cancelled_only
        keep_worktree = args.keep_worktree

        # Determine which statuses to clean
        if done_only and cancelled_only:
            print(
                "Error: Cannot use both --done-only and --cancelled-only",
                file=sys.stderr,
            )
            return 1

        if done_only:
            statuses = ["done"]
        elif cancelled_only:
            statuses = ["cancelled"]
        else:
            statuses = ["done", "cancelled"]

        # Get records to clean
        if task_id:
            record = cli_instance.store.get_record(task_id)
            if not record:
                print(f"Error: Task not found: {task_id}", file=sys.stderr)
                return 1
            records = [record] if record.status in statuses else []
        else:
            records = []
            for status in statuses:
                records.extend(cli_instance.store.get_records_by_status(status))

        if not records:
            print("No tasks to clean up")
            return 0

        print(f"Cleaning up {len(records)} task(s)...")

        cleaned = 0
        failed = 0

        for record in records:
            try:
                _cleanup_task_artifacts(cli_instance, record, keep_worktree)
                cleaned += 1
                print(f"  [ok] Cleaned {record.id}")
            except Exception as e:
                print(f"  [error] Failed to clean {record.id}: {e}", file=sys.stderr)
                failed += 1

        print(f"\nCleaned: {cleaned}, Failed: {failed}")
        return 0 if failed == 0 else 1

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def _cleanup_task_artifacts(
    cli_instance, record: TaskRecord, keep_worktree: bool = False
) -> None:
    """Clean up runtime artifacts for a single task.

    Removes:
    - Docker containers
    - Worktrees (unless keep_worktree=True)
    - Error files
    - OpenCode attempt artifacts (queue/opencode/<task-id>/)
    - Clears runtime fields in task record

    Args:
        cli_instance: TaskQCLI instance with store
        record: TaskRecord to clean up
        keep_worktree: If True, keep the worktree directory

    Raises:
        Exception: If cleanup fails
    """
    # Remove container
    if record.container:
        try:
            cleanup_task_containers(record.id)
            logging.debug(f"Removed container for {record.id}")
        except Exception as e:
            logging.warning(f"Failed to remove container: {e}")

    # Remove worktree
    if not keep_worktree and record.worktree_path:
        try:
            remove_worktree(record.repo, record.worktree_path, force=True)
            logging.debug(f"Removed worktree for {record.id}")
        except GitRuntimeError as e:
            logging.warning(f"Failed to remove worktree: {e}")

    # Remove error file
    if record.error_file:
        try:
            error_path = Path(record.error_file)
            if error_path.exists():
                error_path.unlink()
                logging.debug(f"Removed error file for {record.id}")
        except Exception as e:
            logging.warning(f"Failed to remove error file: {e}")

    # Remove OpenCode attempt artifacts
    try:
        _cleanup_opencode_artifacts(record.id)
    except Exception as e:
        logging.warning(f"Failed to remove OpenCode artifacts: {e}")

    # Clear runtime fields
    cli_instance.store.update_record(
        record.id,
        {
            "branch": "",
            "worktree_path": "",
            "container": "",
            "port": 0,
            "session_id": "",
            "error_file": "",
            "opencode_attempt_dir": "",
            "opencode_config_dir": "",
            "opencode_data_dir": "",
        },
    )


def _cleanup_opencode_artifacts(task_id: str) -> None:
    """Recursively remove OpenCode attempt artifacts for a task.

    Removes the directory: queue/opencode/<task-id>/

    Args:
        task_id: Task ID to clean up artifacts for

    Raises:
        Exception: If cleanup fails
    """
    try:
        repo_root = Path(__file__).resolve().parent.parent.parent
        task_opencode_dir = repo_root / "queue" / "opencode" / task_id

        if task_opencode_dir.exists():
            # Recursively remove the task's opencode directory
            shutil.rmtree(task_opencode_dir, ignore_errors=False)
            logging.debug(f"Removed OpenCode artifacts for {task_id}")
    except Exception as e:
        # Re-raise the exception to be handled by caller
        raise Exception(f"Failed to cleanup opencode artifacts: {e}")
