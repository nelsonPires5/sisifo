#!/usr/bin/env python3
"""
Smoke tests for taskq cleanup and review commands.
Tests basic command instantiation and argument parsing.
"""

import sys
import os
import tempfile
from pathlib import Path

# Setup path
TEST_DIR = os.path.dirname(__file__)
ORCHESTRATION_DIR = os.path.dirname(TEST_DIR)
sys.path.insert(0, ORCHESTRATION_DIR)

from taskq import TaskQCLI
from queue_store import QueueStore
import argparse


def test_cleanup_command():
    """Test cleanup command instantiation."""
    print("Testing cleanup command...")

    cli = TaskQCLI()

    # Test with no flags
    args = argparse.Namespace(
        id=None,
        done_only=False,
        cancelled_only=False,
        keep_worktree=False,
    )
    result = cli.cmd_cleanup(args)
    assert result == 0, "Cleanup with no tasks should return 0"
    print("  [ok] Cleanup with no tasks works")

    # Test with conflicting flags
    args = argparse.Namespace(
        id=None,
        done_only=True,
        cancelled_only=True,
        keep_worktree=False,
    )
    result = cli.cmd_cleanup(args)
    assert result == 1, "Cleanup with conflicting flags should return 1"
    print("  [ok] Cleanup detects conflicting flags")

    # Test with non-existent task ID
    args = argparse.Namespace(
        id="T-nonexistent",
        done_only=False,
        cancelled_only=False,
        keep_worktree=False,
    )
    result = cli.cmd_cleanup(args)
    assert result == 1, "Cleanup with non-existent task should return 1"
    print("  [ok] Cleanup handles non-existent task ID")


def test_review_command():
    """Test review command instantiation."""
    print("Testing review command...")

    cli = TaskQCLI()

    # Test with non-existent task
    args = argparse.Namespace(id="T-nonexistent")
    result = cli.cmd_review(args)
    assert result == 1, "Review of non-existent task should return 1"
    print("  [ok] Review handles non-existent task")

    # Test with task in wrong status
    with tempfile.TemporaryDirectory() as tmpdir:
        tasks_file = Path(tmpdir) / "tasks.jsonl"
        store = QueueStore(str(tasks_file))

        # Add a task in 'todo' status
        from queue_store import TaskRecord
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()
        record = TaskRecord(
            id="T-001",
            repo="/tmp/test-repo",
            base="main",
            task_file="/tmp/test.md",
            status="todo",
            branch="",
            worktree_path="",
            container="",
            port=0,
            session_id="",
            attempt=0,
            error_file="",
            created_at=now,
            updated_at=now,
        )
        store.add_record(record)

        # Create CLI with custom store
        cli = TaskQCLI()
        cli.store = store

        args = argparse.Namespace(id="T-001")
        result = cli.cmd_review(args)
        assert result == 1, "Review of non-review task should return 1"
        print("  [ok] Review rejects task in wrong status")


def test_command_methods_exist():
    """Test that all expected command methods exist."""
    print("Testing command methods exist...")

    cli = TaskQCLI()

    expected_methods = [
        "cmd_add",
        "cmd_status",
        "cmd_remove",
        "cmd_cancel",
        "cmd_retry",
        "cmd_approve",
        "cmd_run",
        "cmd_review",  # NEW
        "cmd_cleanup",  # NEW
    ]

    for method_name in expected_methods:
        assert hasattr(cli, method_name), f"Missing method: {method_name}"
        method = getattr(cli, method_name)
        assert callable(method), f"{method_name} is not callable"

    print(f"  [ok] All {len(expected_methods)} command methods exist")


def main():
    """Run all smoke tests."""
    print("=" * 70)
    print("SMOKE TESTS - TASKQ CLEANUP AND REVIEW COMMANDS")
    print("=" * 70)
    print()

    try:
        test_command_methods_exist()
        print()
        test_cleanup_command()
        print()
        test_review_command()
        print()
        print("=" * 70)
        print("[ok] ALL SMOKE TESTS PASSED")
        print("=" * 70)
        return 0
    except AssertionError as e:
        print()
        print("=" * 70)
        print(f"[error] TEST FAILED: {e}")
        print("=" * 70)
        return 1
    except Exception as e:
        print()
        print("=" * 70)
        print(f"[error] UNEXPECTED ERROR: {e}")
        print("=" * 70)
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
