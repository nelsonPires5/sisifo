"""
taskq run command implementation.

Executes tasks from queue with concurrent worker pool.
"""

import sys
import time
import uuid
import logging
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed

# Handle both absolute and relative imports
try:
    from orchestration.pipeline import TaskProcessor, TaskProcessingError
except ImportError:
    from pipeline import TaskProcessor, TaskProcessingError


def cmd_run(cli_instance, args: argparse.Namespace) -> int:
    """Run task queue with concurrent workers.

    Executes tasks from the queue using a worker pool. Uses atomic
    claim_first_todo() to safely distribute work across multiple workers.

    Args:
        cli_instance: TaskQCLI instance with store
        args: Parsed command-line arguments with:
              id, max_parallel, poll, cleanup_on_fail, dirty_run, follow

    Returns:
        Exit code (0 on success, 1 on error)
    """
    try:
        max_parallel = args.max_parallel
        poll_interval = getattr(args, "poll", None)
        polling_enabled = poll_interval is not None
        run_task_id = (getattr(args, "id", "") or "").strip() or None
        cleanup_on_fail = bool(getattr(args, "cleanup_on_fail", False))
        dirty_run = bool(getattr(args, "dirty_run", False))
        follow_logs = bool(getattr(args, "follow", False))

        root_logger = logging.getLogger()
        previous_log_level = root_logger.level
        root_logger.setLevel(logging.INFO if follow_logs else logging.WARNING)

        try:
            if polling_enabled and poll_interval <= 0:
                print("Error: --poll must be greater than 0", file=sys.stderr)
                return 1

            if run_task_id and polling_enabled:
                print("Error: --id cannot be combined with --poll", file=sys.stderr)
                return 1

            # Generate unique session ID for this run
            session_id = str(uuid.uuid4())[:8]

            print(f"Starting task queue runner (session: {session_id})")
            print(f"  Max parallel workers: {max_parallel}")
            if polling_enabled:
                print(f"  Polling: enabled ({poll_interval}s)")
            else:
                print("  Polling: disabled (single pass)")
            print(
                "  On failure cleanup: "
                + ("enabled (--cleanup-on-fail)" if cleanup_on_fail else "disabled")
            )
            print(
                "  Dirty rerun mode: "
                + ("enabled (--dirty-run)" if dirty_run else "disabled")
            )
            print(
                "  Log streaming: "
                + ("enabled (--follow)" if follow_logs else "disabled")
            )
            if not follow_logs:
                print("  Launch mode: quiet (use --follow to stream worker logs)")

            if run_task_id:
                print(f"  Task filter: {run_task_id}")
                claimed = cli_instance.store.claim_todo_by_id(run_task_id)
                if not claimed:
                    existing = cli_instance.store.get_record(run_task_id)
                    if not existing:
                        print(f"Error: Task not found: {run_task_id}", file=sys.stderr)
                    else:
                        print(
                            f"Error: Task {run_task_id} is not in 'todo' status (current: {existing.status})",
                            file=sys.stderr,
                        )
                    return 1

                failed_count = _process_tasks_parallel(
                    cli_instance,
                    [claimed],
                    session_id,
                    cleanup_on_fail=cleanup_on_fail,
                    dirty_run=dirty_run,
                )
                return 0 if failed_count == 0 else 1

            # Main loop
            all_successful = True
            iteration = 0

            while True:
                iteration += 1
                print(f"\n[Iteration {iteration}] Claiming tasks...")

                # Claim up to max_parallel tasks
                tasks_to_process = []
                for _ in range(max_parallel):
                    claimed = cli_instance.store.claim_first_todo()
                    if claimed:
                        tasks_to_process.append(claimed)
                    else:
                        break

                if not tasks_to_process:
                    print("No tasks to process.")
                    if not polling_enabled:
                        print("Queue empty (single-pass mode).")
                        break
                    print(f"Waiting {poll_interval}s before next poll...")
                    time.sleep(poll_interval)
                    continue

                print(
                    f"Claimed {len(tasks_to_process)} task(s): {[t.id for t in tasks_to_process]}"
                )

                # Process claimed tasks in parallel
                failed_count = _process_tasks_parallel(
                    cli_instance,
                    tasks_to_process,
                    session_id,
                    cleanup_on_fail=cleanup_on_fail,
                    dirty_run=dirty_run,
                )

                if failed_count > 0:
                    all_successful = False
                    print(f"[Iteration {iteration}] {failed_count} task(s) failed")

                # Exit after first iteration when polling is disabled
                if not polling_enabled:
                    break

                print(f"Waiting {poll_interval}s before next poll...")
                time.sleep(poll_interval)

            return 0 if all_successful else 1
        finally:
            root_logger.setLevel(previous_log_level)

    except Exception as e:
        print(f"Error in run loop: {e}", file=sys.stderr)
        return 1


def _process_tasks_parallel(
    cli_instance,
    tasks: list,
    session_id: str,
    cleanup_on_fail: bool = False,
    dirty_run: bool = False,
) -> int:
    """Process multiple tasks in parallel using a thread pool.

    Args:
        cli_instance: TaskQCLI instance with store
        tasks: List of TaskRecord objects to process
        session_id: Session identifier for this run
        cleanup_on_fail: Remove runtime artifacts when a task fails.
        dirty_run: Reuse existing worktree and pre-clean stale containers.

    Returns:
        Number of failed tasks
    """
    failed_count = 0

    # Create a processor for this thread pool
    processor = TaskProcessor(
        store=cli_instance.store,
        session_id=session_id,
        cleanup_on_fail=cleanup_on_fail,
        dirty_run=dirty_run,
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
