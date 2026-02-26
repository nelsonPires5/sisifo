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
"""

import argparse
import sys
import json
import time
import uuid
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

# Handle both absolute and relative imports
try:
    from orchestration.queue_store import QueueStore, TaskRecord
    from orchestration.task_files import (
        create_canonical_task_file,
        write_task_file,
        normalize_task_from_file,
        read_task_file,
        parse_frontmatter_optional,
        normalize_task_id_from_filename,
        TaskFrontmatter,
        ensure_queue_dirs,
        TaskFileError,
    )
    from orchestration.worker import TaskProcessor, TaskProcessingError
    from orchestration.runtime_docker import cleanup_task_containers
    from orchestration.runtime_git import (
        remove_worktree,
        derive_worktree_path,
        GitRuntimeError,
    )
    from orchestration.runtime_review import (
        launch_review_from_record,
        ReviewLaunchError,
    )
except ImportError:
    from queue_store import QueueStore, TaskRecord
    from task_files import (
        create_canonical_task_file,
        write_task_file,
        normalize_task_from_file,
        read_task_file,
        parse_frontmatter_optional,
        normalize_task_id_from_filename,
        TaskFrontmatter,
        ensure_queue_dirs,
        TaskFileError,
    )
    from worker import TaskProcessor, TaskProcessingError
    from runtime_docker import cleanup_task_containers
    from runtime_git import remove_worktree, derive_worktree_path, GitRuntimeError
    from runtime_review import launch_review_from_record, ReviewLaunchError

# Setup logging for run command
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)


class TaskQCLI:
    """Task queue CLI interface."""

    @staticmethod
    def _derive_branch_name(task_id: str) -> str:
        """Derive default branch name from task ID."""
        safe_id = task_id.lower().replace(" ", "-").replace("_", "-")
        return f"task/{safe_id}"

    @staticmethod
    def _format_task_file_path(task_file_path: Path) -> str:
        """Store task file path relative to repo root when possible."""
        resolved = task_file_path.expanduser().resolve()
        repo_root = Path(__file__).resolve().parent.parent
        try:
            return str(resolved.relative_to(repo_root))
        except ValueError:
            return str(resolved)

    def __init__(self):
        """Initialize CLI with queue store."""
        self.store = QueueStore()
        # Ensure queue directory structure exists
        ensure_queue_dirs()

    def cmd_add(self, args: argparse.Namespace) -> int:
        """Add a new task to the queue.

        Args:
            args: Parsed command-line arguments with: id, repo, base, task, task_file

        Returns:
            Exit code (0 on success, 1 on error)
        """
        try:
            task_id_arg = (getattr(args, "id", "") or "").strip()
            repo_arg = (getattr(args, "repo", "") or "").strip()
            base_arg = (getattr(args, "base", "") or "").strip()
            branch_override = (getattr(args, "branch", "") or "").strip()

            if args.task_file:
                source_path = Path(args.task_file).expanduser()
                if not source_path.is_absolute():
                    source_path = (Path.cwd() / source_path).resolve()

                if not source_path.exists():
                    print(
                        f"Error: Failed to process task file: Source file not found: {source_path}",
                        file=sys.stderr,
                    )
                    return 1

                try:
                    source_content = source_path.read_text(encoding="utf-8")
                    frontmatter_data, _ = parse_frontmatter_optional(source_content)
                except (TaskFileError, OSError) as e:
                    print(f"Error: Failed to process task file: {e}", file=sys.stderr)
                    return 1

                fm_id = str(frontmatter_data.get("id", "") or "").strip()
                fm_repo = str(frontmatter_data.get("repo", "") or "").strip()
                fm_base = str(frontmatter_data.get("base", "") or "").strip()
                fm_branch = str(frontmatter_data.get("branch", "") or "").strip()

                task_id = (
                    task_id_arg or fm_id or normalize_task_id_from_filename(source_path)
                )
                repo_value = repo_arg or fm_repo

                if self.store.get_record(task_id) is not None:
                    print(
                        f"Error: Record with id '{task_id}' already exists",
                        file=sys.stderr,
                    )
                    return 1

                if not repo_value:
                    print(
                        "Error: Failed to process task file: missing repo (provide --repo or frontmatter repo)",
                        file=sys.stderr,
                    )
                    return 1

                try:
                    resolved_repo = TaskFrontmatter._resolve_repo_path(repo_value)
                except TaskFileError as e:
                    print(f"Error: Failed to process task file: {e}", file=sys.stderr)
                    return 1

                base = base_arg or fm_base or "main"
                branch_name = (
                    branch_override or fm_branch or self._derive_branch_name(task_id)
                )
                task_file_value = self._format_task_file_path(source_path)
                print(f"Task file registered: {task_file_value}")

            else:
                if not task_id_arg:
                    print("Error: --id is required when using --task", file=sys.stderr)
                    return 1
                if not repo_arg:
                    print(
                        "Error: --repo is required when using --task", file=sys.stderr
                    )
                    return 1

                task_id = task_id_arg
                base = base_arg or "main"

                if self.store.get_record(task_id) is not None:
                    print(
                        f"Error: Record with id '{task_id}' already exists",
                        file=sys.stderr,
                    )
                    return 1

                try:
                    content = create_canonical_task_file(
                        task_id,
                        repo_arg,
                        args.task,
                        base,
                        branch=branch_override or None,
                    )
                    canonical_path = write_task_file(task_id, content)
                    frontmatter, _ = read_task_file(task_id)
                except TaskFileError as e:
                    print(f"Error: Failed to create task file: {e}", file=sys.stderr)
                    return 1

                resolved_repo = frontmatter.repo
                base = frontmatter.base
                branch_name = (
                    branch_override
                    or frontmatter.branch
                    or self._derive_branch_name(task_id)
                )
                task_file_value = str(Path("queue") / "tasks" / f"{task_id}.md")
                print(f"Task file created: {canonical_path}")

            now = datetime.now(timezone.utc).isoformat()
            worktree_path = derive_worktree_path(resolved_repo, task_id)

            record = TaskRecord(
                id=task_id,
                repo=resolved_repo,
                base=base,
                task_file=task_file_value,
                status="todo",
                branch=branch_name,
                worktree_path=worktree_path,
                container="",
                port=0,
                session_id="",
                attempt=0,
                error_file="",
                created_at=now,
                updated_at=now,
            )

            try:
                self.store.add_record(record)
                print(f"Task added to queue: {task_id}")
                return 0
            except ValueError as e:
                print(f"Error: {e}", file=sys.stderr)
                return 1

        except Exception as e:
            print(f"Unexpected error: {e}", file=sys.stderr)
            return 1

    def cmd_status(self, args: argparse.Namespace) -> int:
        """Display task queue status.

        Args:
            args: Parsed command-line arguments with: id (optional), json (optional)

        Returns:
            Exit code (0 on success, 1 on error)
        """
        try:
            records = self.store.get_all_records()

            # Filter by ID if specified
            if args.id:
                records = [r for r in records if r.id == args.id]
                if not records:
                    print(f"No task found with id: {args.id}", file=sys.stderr)
                    return 1

            # Output format
            if args.json:
                output = json.dumps(
                    [r.to_dict() for r in records],
                    indent=2,
                    default=str,
                )
                print(output)
            else:
                # Group by status
                by_status = {}
                for record in records:
                    if record.status not in by_status:
                        by_status[record.status] = []
                    by_status[record.status].append(record)

                # Display grouped output
                status_order = [
                    "todo",
                    "planning",
                    "building",
                    "review",
                    "done",
                    "failed",
                    "cancelled",
                ]
                for status in status_order:
                    if status in by_status:
                        print(f"\n{status.upper()}:")
                        for record in by_status[status]:
                            print(f"  {record.id}")

            return 0

        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

    def cmd_remove(self, args: argparse.Namespace) -> int:
        """Remove a task from the queue.

        Only allows removal of tasks that are not in 'planning' or 'building' status.

        Args:
            args: Parsed command-line arguments with: id

        Returns:
            Exit code (0 on success, 1 on error)
        """
        try:
            task_id = args.id
            record = self.store.get_record(task_id)

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
                self.store.remove_record(task_id)
                print(f"Task removed: {task_id}")
                return 0
            except ValueError as e:
                print(f"Error: {e}", file=sys.stderr)
                return 1

        except Exception as e:
            print(f"Unexpected error: {e}", file=sys.stderr)
            return 1

    def cmd_cancel(self, args: argparse.Namespace) -> int:
        """Cancel a task.

        Legal transitions to cancelled: todo, review, failed
        Enforces legal status transitions.

        Args:
            args: Parsed command-line arguments with: id

        Returns:
            Exit code (0 on success, 1 on error)
        """
        try:
            task_id = args.id
            record = self.store.get_record(task_id)

            if not record:
                print(f"Error: Task not found: {task_id}", file=sys.stderr)
                return 1

            try:
                self.store.update_record(task_id, {"status": "cancelled"})
                print(f"Task cancelled: {task_id}")
                return 0
            except ValueError as e:
                print(f"Error: {e}", file=sys.stderr)
                return 1

        except Exception as e:
            print(f"Unexpected error: {e}", file=sys.stderr)
            return 1

    def cmd_retry(self, args: argparse.Namespace) -> int:
        """Retry a failed task.

        Transition: failed -> todo
        Clears runtime handles and increments attempt counter.

        Args:
            args: Parsed command-line arguments with: id

        Returns:
            Exit code (0 on success, 1 on error)
        """
        try:
            task_id = args.id
            record = self.store.get_record(task_id)

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
                branch_name = record.branch or self._derive_branch_name(task_id)
                try:
                    worktree_path = derive_worktree_path(record.repo, task_id)
                except Exception:
                    worktree_path = ""

                # Clear runtime handles and increment attempt
                self.store.update_record(
                    task_id,
                    {
                        "status": "todo",
                        "branch": branch_name,
                        "worktree_path": worktree_path,
                        "container": "",
                        "port": 0,
                        "session_id": "",
                        "error_file": "",
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

    def cmd_approve(self, args: argparse.Namespace) -> int:
        """Approve a task in review.

        Transition: review -> done

        Args:
            args: Parsed command-line arguments with: id

        Returns:
            Exit code (0 on success, 1 on error)
        """
        try:
            task_id = args.id
            record = self.store.get_record(task_id)

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
                self.store.update_record(task_id, {"status": "done"})
                print(f"Task approved: {task_id}")
                return 0
            except ValueError as e:
                print(f"Error: {e}", file=sys.stderr)
                return 1

        except Exception as e:
            print(f"Unexpected error: {e}", file=sys.stderr)
            return 1

    def cmd_run(self, args: argparse.Namespace) -> int:
        """Run task queue with concurrent workers.

        Executes tasks from the queue using a worker pool. Uses atomic
        claim_first_todo() to safely distribute work across multiple workers.

        Args:
            args: Parsed command-line arguments with:
                  max_parallel, once, poll_interval_sec, worktrees_root

        Returns:
            Exit code (0 on success, 1 on error)
        """
        try:
            max_parallel = args.max_parallel
            once = args.once
            poll_interval = args.poll_interval_sec
            worktrees_root = args.worktrees_root

            # Generate unique session ID for this run
            session_id = str(uuid.uuid4())[:8]

            print(f"Starting task queue runner (session: {session_id})")
            print(f"  Max parallel workers: {max_parallel}")
            print(f"  Poll interval: {poll_interval}s")
            print(f"  Worktrees root: {worktrees_root}")
            print(f"  Once mode: {once}")

            # Main loop
            all_successful = True
            iteration = 0

            while True:
                iteration += 1
                print(f"\n[Iteration {iteration}] Claiming tasks...")

                # Claim up to max_parallel tasks
                tasks_to_process = []
                for _ in range(max_parallel):
                    claimed = self.store.claim_first_todo()
                    if claimed:
                        tasks_to_process.append(claimed)
                    else:
                        break

                if not tasks_to_process:
                    print("No tasks to process.")
                    if once:
                        print("Queue empty (--once mode).")
                        break
                    print(f"Waiting {poll_interval}s before next poll...")
                    time.sleep(poll_interval)
                    continue

                print(
                    f"Claimed {len(tasks_to_process)} task(s): {[t.id for t in tasks_to_process]}"
                )

                # Process claimed tasks in parallel
                failed_count = self._process_tasks_parallel(
                    tasks_to_process, session_id, worktrees_root
                )

                if failed_count > 0:
                    all_successful = False
                    print(f"[Iteration {iteration}] {failed_count} task(s) failed")

                # If --once, exit after first iteration
                if once:
                    break

                # Check if there are more tasks before sleeping
                todo_count = len(self.store.get_records_by_status("todo"))
                if todo_count == 0:
                    print("No more tasks in queue. Exiting.")
                    break

                print(f"Waiting {poll_interval}s before next poll...")
                time.sleep(poll_interval)

            return 0 if all_successful else 1

        except Exception as e:
            print(f"Error in run loop: {e}", file=sys.stderr)
            return 1

    def _process_tasks_parallel(
        self, tasks: list, session_id: str, worktrees_root: Optional[str]
    ) -> int:
        """
        Process multiple tasks in parallel using a thread pool.

        Args:
            tasks: List of TaskRecord objects to process
            session_id: Session identifier for this run
            worktrees_root: Root directory for worktrees

        Returns:
            Number of failed tasks
        """
        failed_count = 0

        # Create a processor for this thread pool
        processor = TaskProcessor(
            store=self.store,
            session_id=session_id,
            worktrees_root=worktrees_root,
        )

        # Use ThreadPoolExecutor to process tasks concurrently
        with ThreadPoolExecutor(max_workers=len(tasks)) as executor:
            # Submit all tasks
            future_to_task = {
                executor.submit(processor.process_task, task): task for task in tasks
            }

            # Process completed futures
            for future in as_completed(future_to_task):
                task = future_to_task[future]
                try:
                    result = future.result()
                    status = result.status
                    print(f"  Task {task.id}: {status}")
                    if status == "failed":
                        failed_count += 1
                except Exception as e:
                    print(f"  Task {task.id}: ERROR - {e}", file=sys.stderr)
                    failed_count += 1

        return failed_count

    def cmd_review(self, args: argparse.Namespace) -> int:
        """Launch OpenChamber review for a task in review status.

        Uses runtime_review to launch OpenChamber attached to the task's
        OpenCode container endpoint. Task must be in 'review' status
        with port already allocated.

        Args:
            args: Parsed command-line arguments with: id

        Returns:
            Exit code (0 on success, non-zero on failure)
        """
        try:
            task_id = args.id
            record = self.store.get_record(task_id)

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

            try:
                print(f"Launching OpenChamber for task review: {task_id}")
                exit_code = launch_review_from_record(record.to_dict())
                return exit_code
            except ReviewLaunchError as e:
                print(f"Error: {e}", file=sys.stderr)
                return 1

        except Exception as e:
            print(f"Unexpected error: {e}", file=sys.stderr)
            return 1

    def cmd_cleanup(self, args: argparse.Namespace) -> int:
        """Clean up runtime artifacts for completed or cancelled tasks.

        Removes docker containers and worktrees associated with tasks.
        By default only cleans done and cancelled tasks. Can filter by:
        - --done-only: Only clean tasks in 'done' status
        - --cancelled-only: Only clean tasks in 'cancelled' status
        - --id: Clean specific task ID
        - --keep-worktree: Remove containers but keep worktrees

        Args:
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
                record = self.store.get_record(task_id)
                if not record:
                    print(f"Error: Task not found: {task_id}", file=sys.stderr)
                    return 1
                records = [record] if record.status in statuses else []
            else:
                records = []
                for status in statuses:
                    records.extend(self.store.get_records_by_status(status))

            if not records:
                print("No tasks to clean up")
                return 0

            print(f"Cleaning up {len(records)} task(s)...")

            cleaned = 0
            failed = 0

            for record in records:
                try:
                    self._cleanup_task_artifacts(record, keep_worktree)
                    cleaned += 1
                    print(f"  [ok] Cleaned {record.id}")
                except Exception as e:
                    print(
                        f"  [error] Failed to clean {record.id}: {e}", file=sys.stderr
                    )
                    failed += 1

            print(f"\nCleaned: {cleaned}, Failed: {failed}")
            return 0 if failed == 0 else 1

        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

    def _cleanup_task_artifacts(
        self, record: TaskRecord, keep_worktree: bool = False
    ) -> None:
        """Clean up runtime artifacts for a single task.

        Removes:
        - Docker containers
        - Worktrees (unless keep_worktree=True)
        - Error files
        - Clears runtime fields in task record

        Args:
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

        # Clear runtime fields
        self.store.update_record(
            record.id,
            {
                "branch": "",
                "worktree_path": "",
                "container": "",
                "port": 0,
                "session_id": "",
                "error_file": "",
            },
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

    # Mutually exclusive group for task content
    task_group = add_parser.add_mutually_exclusive_group(required=True)
    task_group.add_argument("--task", help="Task description (inline text)")
    task_group.add_argument("--task-file", help="Path to task markdown file")

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
        "--max-parallel",
        type=int,
        default=3,
        help="Maximum parallel workers (default: 3)",
    )
    run_parser.add_argument(
        "--once",
        action="store_true",
        help="Process available tasks once and exit (no polling)",
    )
    run_parser.add_argument(
        "--poll-interval-sec",
        type=int,
        default=5,
        help="Poll interval in seconds for checking new tasks (default: 5)",
    )
    run_parser.add_argument(
        "--worktrees-root",
        default=None,
        help="Root directory for worktrees (default: ~/documents/repos/worktrees)",
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
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
