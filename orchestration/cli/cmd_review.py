"""
taskq review command implementation.

Launches OpenChamber review for a task in review status.
"""

import sys
import argparse

# Handle both absolute and relative imports
try:
    from orchestration.adapters.review import (
        launch_review_from_record,
        ReviewLaunchError,
        StrictLocalValidationError,
    )
except ImportError:
    from adapters.review import (
        launch_review_from_record,
        ReviewLaunchError,
        StrictLocalValidationError,
    )


def cmd_review(cli_instance, args: argparse.Namespace) -> int:
    """Launch OpenChamber review for a task in review status.

    Uses adapters.review to launch OpenChamber attached to the task's
    OpenCode container endpoint. Task must be in 'review' status
    with port already allocated.

    Enforces strict-local validation: both opencode_config_dir and
    opencode_data_dir must be present in task record and exist on disk.

    Args:
        cli_instance: TaskQCLI instance with store
        args: Parsed command-line arguments with: id

    Returns:
        Exit code (0 on success, non-zero on failure)
    """
    try:
        task_id = args.id
        record = cli_instance.store.get_record(task_id)

        if not record:
            print(f"Error: Task not found: {task_id}", file=sys.stderr)
            return 1

        if record.status != "review":
            print(
                f"Error: Can only review tasks in 'review' status, current status: {record.status}",
                file=sys.stderr,
            )
            return 1

        if record.port <= 0:
            print(
                f"Error: Task does not have valid port allocated: {record.port}",
                file=sys.stderr,
            )
            return 1

        # Validate strict-local attempt directories before launch
        if not record.opencode_config_dir:
            print(
                f"Error: Task {task_id} is missing opencode_config_dir. "
                f"This is a legacy task or execution was incomplete.",
                file=sys.stderr,
            )
            print(
                f"Suggestion: Retry and rerun the task to populate strict-local dirs:",
                file=sys.stderr,
            )
            print(f"  taskq retry --id {task_id}", file=sys.stderr)
            print(f"  taskq run --id {task_id}", file=sys.stderr)
            return 1

        if not record.opencode_data_dir:
            print(
                f"Error: Task {task_id} is missing opencode_data_dir. "
                f"This is a legacy task or execution was incomplete.",
                file=sys.stderr,
            )
            print(
                f"Suggestion: Retry and rerun the task to populate strict-local dirs:",
                file=sys.stderr,
            )
            print(f"  taskq retry --id {task_id}", file=sys.stderr)
            print(f"  taskq run --id {task_id}", file=sys.stderr)
            return 1

        try:
            print(f"Launching OpenChamber for task review: {task_id}")
            exit_code = launch_review_from_record(record.to_dict())
            return exit_code
        except StrictLocalValidationError as e:
            print(f"Error: {e}", file=sys.stderr)
            print(
                f"Suggestion: Retry and rerun the task to populate strict-local dirs:",
                file=sys.stderr,
            )
            print(f"  taskq retry --id {task_id}", file=sys.stderr)
            print(f"  taskq run --id {task_id}", file=sys.stderr)
            return 1
        except ReviewLaunchError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        return 1
