"""
taskq remove command implementation.

Removes a task from the queue (only non-active tasks).
"""

import sys
import argparse


def cmd_remove(cli_instance, args: argparse.Namespace) -> int:
    """Remove a task from the queue.

    Only allows removal of tasks that are not in 'planning' or 'building' status.

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

        # Block removal of planning/building tasks
        if record.status in ("planning", "building"):
            print(
                f"Error: Cannot remove task in '{record.status}' status",
                file=sys.stderr,
            )
            return 1

        try:
            cli_instance.store.remove_record(task_id)
            print(f"Task removed: {task_id}")
            return 0
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        return 1
