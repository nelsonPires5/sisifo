"""
taskq transitions command implementations.

Handles state transitions: cancel, retry, approve.
"""

import sys
import argparse

# Handle both absolute and relative imports
try:
    from orchestration.core.naming import derive_branch_name
except ImportError:
    from core.naming import derive_branch_name


def _derive_branch_name(task_id: str) -> str:
    """Derive default branch name from task ID."""
    return derive_branch_name(task_id)


def cmd_cancel(cli_instance, args: argparse.Namespace) -> int:
    """Cancel a task.

    Legal transitions to cancelled: todo, review, failed
    Enforces legal status transitions.

    Args:
        cli_instance: TaskQCLI instance with store
        args: Parsed command-line arguments with: id

    Returns:
        Exit code (0 on success, 1 on error)
    """
    try:
        task_id = args.id
        record = cli_instance.store.get_record(task_id)

        if not record:
            print(f"Error: Task not found: {task_id}", file=sys.stderr)
            return 1

        try:
            cli_instance.store.update_record(task_id, {"status": "cancelled"})
            print(f"Task cancelled: {task_id}")
            return 0
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        return 1


def cmd_retry(cli_instance, args: argparse.Namespace) -> int:
    """Retry a failed task.

    Transition: failed -> todo
    Clears runtime handles, opencode pointers, and increments attempt counter.

    Args:
        cli_instance: TaskQCLI instance with store
        args: Parsed command-line arguments with: id

    Returns:
        Exit code (0 on success, 1 on error)
    """
    try:
        task_id = args.id
        record = cli_instance.store.get_record(task_id)

        if not record:
            print(f"Error: Task not found: {task_id}", file=sys.stderr)
            return 1

        if record.status != "failed":
            print(
                f"Error: Can only retry tasks in 'failed' status, current status: {record.status}",
                file=sys.stderr,
            )
            return 1

        try:
            branch_name = record.branch or _derive_branch_name(task_id)
            worktree_path = record.worktree_path

            # Clear runtime handles, opencode pointers, and increment attempt
            cli_instance.store.update_record(
                task_id,
                {
                    "status": "todo",
                    "branch": branch_name,
                    "worktree_path": worktree_path,
                    "container": "",
                    "port": 0,
                    "session_id": "",
                    "error_file": "",
                    "opencode_attempt_dir": "",
                    "opencode_config_dir": "",
                    "opencode_data_dir": "",
                    "attempt": record.attempt + 1,
                },
            )
            print(f"Task retried: {task_id} (attempt {record.attempt + 1})")
            return 0
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        return 1


def cmd_approve(cli_instance, args: argparse.Namespace) -> int:
    """Approve a task in review.

    Transition: review -> done

    Args:
        cli_instance: TaskQCLI instance with store
        args: Parsed command-line arguments with: id

    Returns:
        Exit code (0 on success, 1 on error)
    """
    try:
        task_id = args.id
        record = cli_instance.store.get_record(task_id)

        if not record:
            print(f"Error: Task not found: {task_id}", file=sys.stderr)
            return 1

        if record.status != "review":
            print(
                f"Error: Can only approve tasks in 'review' status, current status: {record.status}",
                file=sys.stderr,
            )
            return 1

        try:
            cli_instance.store.update_record(task_id, {"status": "done"})
            print(f"Task approved: {task_id}")
            return 0
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        return 1
