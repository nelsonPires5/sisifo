"""
Tests for taskq cancel, retry, and approve command transitions.

Tests cover:
- cmd_cancel: Valid transitions (todo/review/failed -> cancelled)
- cmd_approve: Valid transitions (review -> done)
- Status validation and error handling
"""

import tempfile
import argparse
import pytest
from pathlib import Path
from datetime import datetime
from unittest.mock import MagicMock, patch

from orchestration.taskq import TaskQCLI
from orchestration.store import QueueStore
from orchestration.core.models import TaskRecord
from orchestration.support.task_files import write_task_file, read_task_file


@pytest.fixture
def temp_queue_dir():
    """Create a temporary queue directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        queue_dir = Path(tmpdir) / "queue"
        queue_dir.mkdir()
        (queue_dir / "tasks").mkdir()
        (queue_dir / "errors").mkdir()
        yield queue_dir


@pytest.fixture
def temp_queue_file(temp_queue_dir):
    """Create a temporary queue file for testing."""
    queue_file = temp_queue_dir / "tasks.jsonl"
    yield queue_file


def create_test_record(task_id, status="todo", attempt=0, **kwargs):
    """Helper to create TaskRecord with all required fields."""
    return TaskRecord(
        id=task_id,
        repo=kwargs.get("repo", "/test/repo"),
        base=kwargs.get("base", "main"),
        task_file=kwargs.get("task_file", f"/queue/tasks/{task_id}.md"),
        branch=kwargs.get("branch", f"task/{task_id}"),
        worktree_path=kwargs.get("worktree_path", "/tmp/worktree"),
        status=status,
        attempt=attempt,
        container=kwargs.get("container", ""),
        port=kwargs.get("port", 0),
        session_id=kwargs.get("session_id", ""),
        error_file=kwargs.get("error_file", ""),
        created_at=kwargs.get("created_at", datetime.utcnow().isoformat()),
        updated_at=kwargs.get("updated_at", datetime.utcnow().isoformat()),
    )


@pytest.fixture
def cli_with_temp_store(temp_queue_file, temp_queue_dir, monkeypatch):
    """Create a TaskQCLI instance with temporary store."""
    tasks_dir = temp_queue_dir / "tasks"

    # Monkeypatch QueueStore initialization
    def mock_init(self):
        self.tasks_file = Path(temp_queue_file)
        self._lock = __import__("threading").RLock()
        self._file_lock_handle = None
        self.tasks_file.parent.mkdir(parents=True, exist_ok=True)
        if not self.tasks_file.exists():
            self.tasks_file.touch()

    monkeypatch.setattr("orchestration.store.QueueStore.__init__", mock_init)

    # Keep task markdown files isolated per test.
    monkeypatch.setattr(
        "orchestration.support.task_files.write_task_file",
        lambda task_id, content: write_task_file(task_id, content, str(tasks_dir)),
    )
    monkeypatch.setattr(
        "orchestration.support.task_files.read_task_file",
        lambda task_id: read_task_file(task_id, tasks_dir=str(tasks_dir)),
    )

    return TaskQCLI()


class TestCancelCommand:
    """Test taskq cancel command."""

    def test_cancel_from_todo_status(self, cli_with_temp_store, monkeypatch, capsys):
        """Test cancelling a task in 'todo' status."""
        monkeypatch.setattr(
            "orchestration.support.paths.ensure_queue_dirs", lambda: None
        )

        # Create a task in 'todo' status
        cli_with_temp_store.store.add_record(create_test_record("T-001", status="todo"))

        args = argparse.Namespace(id="T-001")
        result = cli_with_temp_store.cmd_cancel(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "Task cancelled: T-001" in captured.out

        # Verify status changed
        record = cli_with_temp_store.store.get_record("T-001")
        assert record.status == "cancelled"

    def test_cancel_from_review_status(self, cli_with_temp_store, monkeypatch, capsys):
        """Test cancelling a task in 'review' status."""
        monkeypatch.setattr(
            "orchestration.support.paths.ensure_queue_dirs", lambda: None
        )

        # Create a task in 'review' status
        cli_with_temp_store.store.add_record(
            create_test_record("T-002", status="review")
        )

        args = argparse.Namespace(id="T-002")
        result = cli_with_temp_store.cmd_cancel(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "Task cancelled: T-002" in captured.out

        # Verify status changed
        record = cli_with_temp_store.store.get_record("T-002")
        assert record.status == "cancelled"

    def test_cancel_from_failed_status(self, cli_with_temp_store, monkeypatch, capsys):
        """Test cancelling a task in 'failed' status."""
        monkeypatch.setattr(
            "orchestration.support.paths.ensure_queue_dirs", lambda: None
        )

        # Create a task in 'failed' status
        cli_with_temp_store.store.add_record(
            create_test_record("T-003", status="failed")
        )

        args = argparse.Namespace(id="T-003")
        result = cli_with_temp_store.cmd_cancel(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "Task cancelled: T-003" in captured.out

        # Verify status changed
        record = cli_with_temp_store.store.get_record("T-003")
        assert record.status == "cancelled"

    def test_cancel_nonexistent_task(self, cli_with_temp_store, monkeypatch, capsys):
        """Test cancelling a task that does not exist."""
        monkeypatch.setattr(
            "orchestration.support.paths.ensure_queue_dirs", lambda: None
        )

        args = argparse.Namespace(id="T-999")
        result = cli_with_temp_store.cmd_cancel(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "Error: Task not found: T-999" in captured.err


class TestApproveCommand:
    """Test taskq approve command."""

    def test_approve_from_review_status(self, cli_with_temp_store, monkeypatch, capsys):
        """Test approving a task in 'review' status."""
        monkeypatch.setattr(
            "orchestration.support.paths.ensure_queue_dirs", lambda: None
        )

        # Create a task in 'review' status
        cli_with_temp_store.store.add_record(
            create_test_record("T-010", status="review")
        )

        args = argparse.Namespace(id="T-010")
        result = cli_with_temp_store.cmd_approve(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "Task approved: T-010" in captured.out

        # Verify status changed
        record = cli_with_temp_store.store.get_record("T-010")
        assert record.status == "done"

    def test_approve_nonexistent_task(self, cli_with_temp_store, monkeypatch, capsys):
        """Test approving a task that does not exist."""
        monkeypatch.setattr(
            "orchestration.support.paths.ensure_queue_dirs", lambda: None
        )

        args = argparse.Namespace(id="T-999")
        result = cli_with_temp_store.cmd_approve(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "Error: Task not found: T-999" in captured.err

    def test_approve_from_todo_status_fails(
        self, cli_with_temp_store, monkeypatch, capsys
    ):
        """Test approving a task NOT in 'review' status fails."""
        monkeypatch.setattr(
            "orchestration.support.paths.ensure_queue_dirs", lambda: None
        )

        # Create a task in 'todo' status
        cli_with_temp_store.store.add_record(create_test_record("T-011", status="todo"))

        args = argparse.Namespace(id="T-011")
        result = cli_with_temp_store.cmd_approve(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "Can only approve tasks in 'review' status" in captured.err

        # Verify status unchanged
        record = cli_with_temp_store.store.get_record("T-011")
        assert record.status == "todo"

    def test_approve_from_done_status_fails(
        self, cli_with_temp_store, monkeypatch, capsys
    ):
        """Test approving a task already in 'done' status fails."""
        monkeypatch.setattr(
            "orchestration.support.paths.ensure_queue_dirs", lambda: None
        )

        # Create a task in 'done' status
        cli_with_temp_store.store.add_record(create_test_record("T-012", status="done"))

        args = argparse.Namespace(id="T-012")
        result = cli_with_temp_store.cmd_approve(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "Can only approve tasks in 'review' status" in captured.err

        # Verify status unchanged
        record = cli_with_temp_store.store.get_record("T-012")
        assert record.status == "done"


class TestRetryCommand:
    """Test taskq retry command."""

    def test_retry_from_failed_status(self, cli_with_temp_store, monkeypatch, capsys):
        """Test retrying a task in 'failed' status."""
        monkeypatch.setattr(
            "orchestration.support.paths.ensure_queue_dirs", lambda: None
        )

        # Create a task in 'failed' status with attempt=0
        cli_with_temp_store.store.add_record(
            create_test_record(
                "T-020",
                status="failed",
                attempt=0,
                container="task-T-020-abc123",
                port=8080,
            )
        )

        args = argparse.Namespace(id="T-020")
        result = cli_with_temp_store.cmd_retry(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "Task retried: T-020" in captured.out
        assert "attempt 1" in captured.out

        # Verify status changed and attempt incremented
        record = cli_with_temp_store.store.get_record("T-020")
        assert record.status == "todo"
        assert record.attempt == 1
        # Verify runtime handles cleared
        assert record.container == ""
        assert record.port == 0

    def test_retry_from_todo_status_fails(
        self, cli_with_temp_store, monkeypatch, capsys
    ):
        """Test retrying a task NOT in 'failed' status fails."""
        monkeypatch.setattr(
            "orchestration.support.paths.ensure_queue_dirs", lambda: None
        )

        # Create a task in 'todo' status
        cli_with_temp_store.store.add_record(create_test_record("T-021", status="todo"))

        args = argparse.Namespace(id="T-021")
        result = cli_with_temp_store.cmd_retry(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "Can only retry tasks in 'failed' status" in captured.err

        # Verify status and attempt unchanged
        record = cli_with_temp_store.store.get_record("T-021")
        assert record.status == "todo"
        assert record.attempt == 0

    def test_retry_nonexistent_task(self, cli_with_temp_store, monkeypatch, capsys):
        """Test retrying a task that does not exist."""
        monkeypatch.setattr(
            "orchestration.support.paths.ensure_queue_dirs", lambda: None
        )

        args = argparse.Namespace(id="T-999")
        result = cli_with_temp_store.cmd_retry(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "Error: Task not found: T-999" in captured.err
