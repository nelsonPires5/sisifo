#!/usr/bin/env python3
"""
taskq: Task queue management CLI.

Commands:
  add      Add a new task to the queue
  status   Display task status grouped by status
  remove   Remove a task from the queue
  cancel   Cancel a task (todo/review/failed -> cancelled)
  retry    Retry a failed task (failed -> todo)
  approve  Approve a task in review (review -> done)
  run      Execute tasks from queue with worker pool
  review   Launch OpenChamber review for a task
  cleanup  Clean up runtime artifacts for completed/cancelled tasks
  build-image  Build or rebuild runtime Docker image

This module is the thin entrypoint that parses arguments and dispatches
to command handlers in the orchestration.cli package.
"""

import argparse
import sys
import logging

# Handle both absolute and relative imports
try:
    from orchestration.cli import TaskQCLI
except ImportError:
    from cli import TaskQCLI

# Re-export TaskQCLI for backward compatibility with tests
__all__ = ["TaskQCLI", "main"]

# Setup logging for run command
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)


def main():
    """Main entry point for taskq CLI."""
    parser = argparse.ArgumentParser(
        prog="taskq", description="Task queue management CLI"
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # 'add' command
    add_parser = subparsers.add_parser("add", help="Add a new task to the queue")
    add_parser.add_argument("--id", help="Task ID (optional for --task-file)")
    add_parser.add_argument(
        "--repo",
        help="Repository path or name (required for --task if absent in task-file frontmatter)",
    )
    add_parser.add_argument(
        "--base",
        default=None,
        help="Base branch (default: main, or task-file frontmatter when provided)",
    )
    add_parser.add_argument(
        "--branch",
        help="Branch name override (default: task/<id>)",
    )
    add_parser.add_argument(
        "--worktree-path",
        help="Worktree path override (frontmatter key: worktree_path)",
    )

    # Mutually exclusive group for task content
    task_group = add_parser.add_mutually_exclusive_group(required=True)
    task_group.add_argument("--task", help="Task description (inline text)")
    task_group.add_argument(
        "--task-file",
        help="Path to task markdown file (frontmatter keys: id, repo, base, branch, worktree_path)",
    )

    # 'status' command
    status_parser = subparsers.add_parser("status", help="Display task queue status")
    status_parser.add_argument("--id", help="Filter by task ID")
    status_parser.add_argument("--json", action="store_true", help="Output as JSON")

    # 'remove' command
    remove_parser = subparsers.add_parser("remove", help="Remove a task from the queue")
    remove_parser.add_argument("--id", required=True, help="Task ID to remove")

    # 'cancel' command
    cancel_parser = subparsers.add_parser(
        "cancel", help="Cancel a task (todo/review/failed -> cancelled)"
    )
    cancel_parser.add_argument("--id", required=True, help="Task ID to cancel")

    # 'retry' command
    retry_parser = subparsers.add_parser(
        "retry", help="Retry a failed task (failed -> todo)"
    )
    retry_parser.add_argument("--id", required=True, help="Task ID to retry")

    # 'approve' command
    approve_parser = subparsers.add_parser(
        "approve", help="Approve a task in review (review -> done)"
    )
    approve_parser.add_argument("--id", required=True, help="Task ID to approve")

    # 'run' command
    run_parser = subparsers.add_parser(
        "run", help="Execute tasks from queue with worker pool"
    )
    run_parser.add_argument(
        "--id",
        help="Run only this task ID once (must be in todo status; no polling)",
    )
    run_parser.add_argument(
        "--max-parallel",
        type=int,
        default=3,
        help="Maximum parallel workers (default: 3)",
    )
    run_parser.add_argument(
        "--poll",
        nargs="?",
        type=int,
        const=5,
        default=None,
        help="Enable polling; optional interval seconds (default: 5)",
    )
    run_parser.add_argument(
        "--cleanup-on-fail",
        action="store_true",
        help="Remove task container and worktree when task fails (default: keep for inspection)",
    )
    run_parser.add_argument(
        "--dirty-run",
        action="store_true",
        help="Reuse existing worktree and remove stale task containers before launching a new one",
    )
    run_parser.add_argument(
        "--follow",
        action="store_true",
        help="Stream worker/runtime logs during task execution (default: quiet launch output)",
    )

    # 'review' command
    review_parser = subparsers.add_parser(
        "review",
        help="Launch OpenChamber review for a task (task must be in review status)",
    )
    review_parser.add_argument("--id", required=True, help="Task ID to review")

    # 'cleanup' command
    cleanup_parser = subparsers.add_parser(
        "cleanup", help="Clean up runtime artifacts for completed/cancelled tasks"
    )
    cleanup_parser.add_argument(
        "--id", help="Task ID to clean (optional, default: all done/cancelled)"
    )
    cleanup_parser.add_argument(
        "--done-only",
        action="store_true",
        help="Only clean tasks in 'done' status",
    )
    cleanup_parser.add_argument(
        "--cancelled-only",
        action="store_true",
        help="Only clean tasks in 'cancelled' status",
    )
    cleanup_parser.add_argument(
        "--keep-worktree",
        action="store_true",
        help="Remove containers but keep worktrees",
    )

    # 'build-image' command
    build_image_parser = subparsers.add_parser(
        "build-image",
        help="Build or rebuild runtime Docker image",
    )
    build_image_parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Build without cache (passes --no-cache)",
    )
    build_image_parser.add_argument(
        "--no-pull",
        action="store_true",
        help="Skip pulling latest base image layers",
    )

    # Parse arguments
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    # Create CLI instance and execute command
    cli = TaskQCLI()

    if args.command == "add":
        return cli.cmd_add(args)
    elif args.command == "status":
        return cli.cmd_status(args)
    elif args.command == "remove":
        return cli.cmd_remove(args)
    elif args.command == "cancel":
        return cli.cmd_cancel(args)
    elif args.command == "retry":
        return cli.cmd_retry(args)
    elif args.command == "approve":
        return cli.cmd_approve(args)
    elif args.command == "run":
        return cli.cmd_run(args)
    elif args.command == "review":
        return cli.cmd_review(args)
    elif args.command == "cleanup":
        return cli.cmd_cleanup(args)
    elif args.command == "build-image":
        return cli.cmd_build_image(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
