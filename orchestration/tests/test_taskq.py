"""
Unit tests for taskq CLI module.
"""

import os
import tempfile
import json
from pathlib import Path
from datetime import datetime
import pytest
from unittest.mock import MagicMock, patch

from orchestration import taskq as taskq_module
from orchestration.taskq import TaskQCLI
from orchestration.queue_store import QueueStore, TaskRecord
from orchestration.task_files import (
    create_canonical_task_file,
    write_task_file,
    read_task_file,
)
import argparse


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


@pytest.fixture
def store(temp_queue_file):
    """Create a QueueStore instance with temporary file."""
    return QueueStore(str(temp_queue_file))


@pytest.fixture
def cli_with_temp_store(temp_queue_file, temp_queue_dir, monkeypatch):
    """Create a TaskQCLI instance with temporary store."""

    tasks_dir = temp_queue_dir / "tasks"

    # Monkeypatch QueueStore initialization for TaskQCLI
    def mock_init(self):
        self.tasks_file = Path(temp_queue_file)
        self._lock = __import__("threading").RLock()
        self._file_lock_handle = None
        self.tasks_file.parent.mkdir(parents=True, exist_ok=True)
        if not self.tasks_file.exists():
            self.tasks_file.touch()

    monkeypatch.setattr(taskq_module.QueueStore, "__init__", mock_init)

    # Keep task markdown files isolated per test.
    monkeypatch.setattr(
        taskq_module,
        "write_task_file",
        lambda task_id, content: write_task_file(task_id, content, str(tasks_dir)),
    )
    monkeypatch.setattr(
        taskq_module,
        "read_task_file",
        lambda task_id: read_task_file(task_id, tasks_dir=str(tasks_dir)),
    )

    return TaskQCLI()


class TestTaskQCLIAdd:
    """Test taskq add command."""

    def test_add_with_inline_task(self, cli_with_temp_store, tmp_path, monkeypatch):
        """Test adding a task with inline --task."""
        # Mock ensure_queue_dirs
        monkeypatch.setattr("orchestration.taskq.ensure_queue_dirs", lambda: None)

        # Change to temp directory
        monkeypatch.chdir(tmp_path)

        args = argparse.Namespace(
            id="T-001",
            repo=str(tmp_path),
            base="main",
            task="Test task description",
            task_file=None,
        )

        result = cli_with_temp_store.cmd_add(args)
        assert result == 0

        # Verify record was added
        record = cli_with_temp_store.store.get_record("T-001")
        assert record is not None
        assert record.id == "T-001"
        assert record.status == "todo"
        assert record.base == "main"
        assert record.branch == "task/t-001"
        assert record.worktree_path.endswith(f"/worktrees/{Path(tmp_path).name}/T-001")

    def test_add_duplicate_id_fails(self, cli_with_temp_store, tmp_path, monkeypatch):
        """Test that adding task with duplicate ID fails."""
        monkeypatch.setattr("orchestration.taskq.ensure_queue_dirs", lambda: None)
        monkeypatch.chdir(tmp_path)

        # Add first task
        args1 = argparse.Namespace(
            id="T-001",
            repo=str(tmp_path),
            base="main",
            task="First task",
            task_file=None,
        )
        result1 = cli_with_temp_store.cmd_add(args1)
        assert result1 == 0

        # Try to add duplicate
        args2 = argparse.Namespace(
            id="T-001",
            repo=str(tmp_path),
            base="main",
            task="Duplicate task",
            task_file=None,
        )
        result2 = cli_with_temp_store.cmd_add(args2)
        assert result2 == 1

    def test_add_with_task_file(self, cli_with_temp_store, tmp_path, monkeypatch):
        """Test adding a task from a task file."""
        monkeypatch.setattr("orchestration.taskq.ensure_queue_dirs", lambda: None)
        monkeypatch.chdir(tmp_path)

        # Create source task file
        source_file = tmp_path / "source.md"
        source_file.write_text(f"""---
id: T-002
repo: {tmp_path}
base: main
---
Task from file
""")

        args = argparse.Namespace(
            id="T-002",
            repo=str(tmp_path),
            base="main",
            task=None,
            task_file=str(source_file),
        )

        result = cli_with_temp_store.cmd_add(args)
        assert result == 0

        # Verify record was added
        record = cli_with_temp_store.store.get_record("T-002")
        assert record is not None
        assert record.id == "T-002"

    def test_add_with_task_file_uses_frontmatter_when_id_repo_omitted(
        self, cli_with_temp_store, tmp_path, monkeypatch
    ):
        """Task-file add should work without --id/--repo when frontmatter has both."""
        monkeypatch.setattr("orchestration.taskq.ensure_queue_dirs", lambda: None)
        monkeypatch.chdir(tmp_path)

        source_file = tmp_path / "frontmatter-task.md"
        source_file.write_text(
            f"""---
id: T-010
repo: {tmp_path}
base: main
---
Task from frontmatter only
"""
        )

        args = argparse.Namespace(
            id=None,
            repo=None,
            base="main",
            branch=None,
            task=None,
            task_file=str(source_file),
        )

        result = cli_with_temp_store.cmd_add(args)
        assert result == 0

        record = cli_with_temp_store.store.get_record("T-010")
        assert record is not None
        assert record.repo == str(tmp_path)

    def test_add_with_task_file_derives_id_from_filename(
        self, cli_with_temp_store, tmp_path, monkeypatch
    ):
        """Task-file without frontmatter should derive ID from filename."""
        monkeypatch.setattr("orchestration.taskq.ensure_queue_dirs", lambda: None)
        monkeypatch.chdir(tmp_path)

        source_file = tmp_path / "hello world.md"
        source_file.write_text("Simple task body without frontmatter\n")

        args = argparse.Namespace(
            id=None,
            repo=str(tmp_path),
            base="main",
            branch=None,
            task=None,
            task_file=str(source_file),
        )

        result = cli_with_temp_store.cmd_add(args)
        assert result == 0

        record = cli_with_temp_store.store.get_record("T-HELLO-WORLD")
        assert record is not None
        assert record.id == "T-HELLO-WORLD"

    def test_add_with_task_file_repo_only_frontmatter_derives_id_and_keeps_file(
        self, cli_with_temp_store, tmp_path, monkeypatch
    ):
        """Task-file with only repo frontmatter should derive ID from filename."""
        monkeypatch.setattr("orchestration.taskq.ensure_queue_dirs", lambda: None)
        monkeypatch.chdir(tmp_path)

        source_file = tmp_path / "T-TEST-HELLO-20260226.md"
        source_file.write_text(
            f"""---
repo: {tmp_path}
---
Task body from repo-only frontmatter
"""
        )
        original_content = source_file.read_text(encoding="utf-8")

        args = argparse.Namespace(
            id=None,
            repo=None,
            base=None,
            branch=None,
            task=None,
            task_file=str(source_file),
        )

        result = cli_with_temp_store.cmd_add(args)
        assert result == 0

        record = cli_with_temp_store.store.get_record("T-TEST-HELLO-20260226")
        assert record is not None
        assert record.repo == str(tmp_path)
        assert record.base == "main"
        assert record.branch == "task/t-test-hello-20260226"

        # Source task file should remain unchanged.
        assert source_file.read_text(encoding="utf-8") == original_content

    def test_add_inline_requires_id(self, cli_with_temp_store, tmp_path, monkeypatch):
        """Inline --task should fail if --id is omitted."""
        monkeypatch.setattr("orchestration.taskq.ensure_queue_dirs", lambda: None)
        monkeypatch.chdir(tmp_path)

        args = argparse.Namespace(
            id=None,
            repo=str(tmp_path),
            base="main",
            branch=None,
            task="Inline task",
            task_file=None,
        )

        result = cli_with_temp_store.cmd_add(args)
        assert result == 1

    def test_add_inline_requires_repo(self, cli_with_temp_store, tmp_path, monkeypatch):
        """Inline --task should fail if --repo is omitted."""
        monkeypatch.setattr("orchestration.taskq.ensure_queue_dirs", lambda: None)
        monkeypatch.chdir(tmp_path)

        args = argparse.Namespace(
            id="T-011",
            repo=None,
            base="main",
            branch=None,
            task="Inline task",
            task_file=None,
        )

        result = cli_with_temp_store.cmd_add(args)
        assert result == 1

    def test_add_branch_override(self, cli_with_temp_store, tmp_path, monkeypatch):
        """--branch should override default branch derivation."""
        monkeypatch.setattr("orchestration.taskq.ensure_queue_dirs", lambda: None)
        monkeypatch.chdir(tmp_path)

        args = argparse.Namespace(
            id="T-012",
            repo=str(tmp_path),
            base="main",
            branch="feature/custom-branch",
            task="Task with branch",
            task_file=None,
        )

        result = cli_with_temp_store.cmd_add(args)
        assert result == 0

        record = cli_with_temp_store.store.get_record("T-012")
        assert record is not None
        assert record.branch == "feature/custom-branch"

    def test_add_worktree_path_override_cli(
        self, cli_with_temp_store, tmp_path, monkeypatch
    ):
        """--worktree-path should override derived worktree path."""
        monkeypatch.setattr("orchestration.taskq.ensure_queue_dirs", lambda: None)
        monkeypatch.chdir(tmp_path)

        custom_worktree = tmp_path / "wt" / "custom-one"

        args = argparse.Namespace(
            id="T-013",
            repo=str(tmp_path),
            base="main",
            branch=None,
            worktree_path=str(custom_worktree),
            task="Task with custom worktree",
            task_file=None,
        )

        result = cli_with_temp_store.cmd_add(args)
        assert result == 0

        record = cli_with_temp_store.store.get_record("T-013")
        assert record is not None
        assert record.worktree_path == str(custom_worktree.resolve())

    def test_add_worktree_path_from_task_file_frontmatter(
        self, cli_with_temp_store, tmp_path, monkeypatch
    ):
        """task-file frontmatter worktree_path should populate runtime record."""
        monkeypatch.setattr("orchestration.taskq.ensure_queue_dirs", lambda: None)
        monkeypatch.chdir(tmp_path)

        source_file = tmp_path / "task-with-worktree.md"
        custom_worktree = tmp_path / "wt" / "from-frontmatter"
        source_file.write_text(
            f"""---
repo: {tmp_path}
worktree_path: {custom_worktree}
---
Task body from frontmatter worktree
"""
        )

        args = argparse.Namespace(
            id=None,
            repo=None,
            base=None,
            branch=None,
            worktree_path=None,
            task=None,
            task_file=str(source_file),
        )

        result = cli_with_temp_store.cmd_add(args)
        assert result == 0

        record = cli_with_temp_store.store.get_record("T-TASK-WITH-WORKTREE")
        assert record is not None
        assert record.worktree_path == str(custom_worktree.resolve())


class TestTaskQCLIStatus:
    """Test taskq status command."""

    def test_status_shows_all_tasks(
        self, cli_with_temp_store, tmp_path, monkeypatch, capsys
    ):
        """Test status command shows all tasks grouped by status."""
        monkeypatch.setattr("orchestration.taskq.ensure_queue_dirs", lambda: None)
        monkeypatch.chdir(tmp_path)

        # Add some tasks
        for i in range(3):
            args = argparse.Namespace(
                id=f"T-{i:03d}",
                repo=str(tmp_path),
                base="main",
                task=f"Task {i}",
                task_file=None,
            )
            cli_with_temp_store.cmd_add(args)

        # Get status
        args = argparse.Namespace(id=None, json=False)
        result = cli_with_temp_store.cmd_status(args)
        assert result == 0

        captured = capsys.readouterr()
        assert "TODO:" in captured.out
        assert "T-000" in captured.out
        assert "T-001" in captured.out
        assert "T-002" in captured.out

    def test_status_json_format(
        self, cli_with_temp_store, tmp_path, monkeypatch, capsys
    ):
        """Test status command with --json output."""
        monkeypatch.setattr("orchestration.taskq.ensure_queue_dirs", lambda: None)
        monkeypatch.chdir(tmp_path)

        # Add a task
        args = argparse.Namespace(
            id="T-001",
            repo=str(tmp_path),
            base="main",
            task="Test task",
            task_file=None,
        )
        cli_with_temp_store.cmd_add(args)
        capsys.readouterr()

        # Get status as JSON
        args = argparse.Namespace(id=None, json=True)
        result = cli_with_temp_store.cmd_status(args)
        assert result == 0

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["id"] == "T-001"
        assert data[0]["status"] == "todo"

    def test_status_filter_by_id(
        self, cli_with_temp_store, tmp_path, monkeypatch, capsys
    ):
        """Test status command filtered by ID."""
        monkeypatch.setattr("orchestration.taskq.ensure_queue_dirs", lambda: None)
        monkeypatch.chdir(tmp_path)

        # Add multiple tasks
        for i in range(3):
            args = argparse.Namespace(
                id=f"T-{i:03d}",
                repo=str(tmp_path),
                base="main",
                task=f"Task {i}",
                task_file=None,
            )
            cli_with_temp_store.cmd_add(args)
        capsys.readouterr()

        # Get status for specific task
        args = argparse.Namespace(id="T-001", json=False)
        result = cli_with_temp_store.cmd_status(args)
        assert result == 0

        captured = capsys.readouterr()
        assert "T-001" in captured.out
        # Other tasks should not appear
        assert "T-000" not in captured.out
        assert "T-002" not in captured.out


class TestTaskQCLIRemove:
    """Test taskq remove command."""

    def test_remove_todo_task(self, cli_with_temp_store, tmp_path, monkeypatch, capsys):
        """Test removing a task with todo status."""
        monkeypatch.setattr("orchestration.taskq.ensure_queue_dirs", lambda: None)
        monkeypatch.chdir(tmp_path)

        # Add a task
        args = argparse.Namespace(
            id="T-001",
            repo=str(tmp_path),
            base="main",
            task="Test task",
            task_file=None,
        )
        cli_with_temp_store.cmd_add(args)

        # Remove it
        args = argparse.Namespace(id="T-001")
        result = cli_with_temp_store.cmd_remove(args)
        assert result == 0

        # Verify it's gone
        record = cli_with_temp_store.store.get_record("T-001")
        assert record is None

    def test_remove_blocks_planning_status(
        self, cli_with_temp_store, tmp_path, monkeypatch, capsys
    ):
        """Test that remove blocks tasks in planning status."""
        monkeypatch.setattr("orchestration.taskq.ensure_queue_dirs", lambda: None)
        monkeypatch.chdir(tmp_path)

        # Add a task
        args = argparse.Namespace(
            id="T-001",
            repo=str(tmp_path),
            base="main",
            task="Test task",
            task_file=None,
        )
        cli_with_temp_store.cmd_add(args)

        # Update to planning status
        cli_with_temp_store.store.update_record("T-001", {"status": "planning"})

        # Try to remove - should fail
        args = argparse.Namespace(id="T-001")
        result = cli_with_temp_store.cmd_remove(args)
        assert result == 1

        captured = capsys.readouterr()
        assert "Cannot remove task in 'planning' status" in captured.err

        # Verify task still exists
        record = cli_with_temp_store.store.get_record("T-001")
        assert record is not None

    def test_remove_blocks_building_status(
        self, cli_with_temp_store, tmp_path, monkeypatch, capsys
    ):
        """Test that remove blocks tasks in building status."""
        monkeypatch.setattr("orchestration.taskq.ensure_queue_dirs", lambda: None)
        monkeypatch.chdir(tmp_path)

        # Add a task
        args = argparse.Namespace(
            id="T-001",
            repo=str(tmp_path),
            base="main",
            task="Test task",
            task_file=None,
        )
        cli_with_temp_store.cmd_add(args)

        # Update to building status via legal transition
        cli_with_temp_store.store.update_record("T-001", {"status": "planning"})
        cli_with_temp_store.store.update_record("T-001", {"status": "building"})

        # Try to remove - should fail
        args = argparse.Namespace(id="T-001")
        result = cli_with_temp_store.cmd_remove(args)
        assert result == 1

        # Verify task still exists
        record = cli_with_temp_store.store.get_record("T-001")
        assert record is not None

    def test_remove_nonexistent_task(self, cli_with_temp_store, capsys):
        """Test removing a task that doesn't exist."""
        args = argparse.Namespace(id="NONEXISTENT")
        result = cli_with_temp_store.cmd_remove(args)
        assert result == 1

        captured = capsys.readouterr()
        assert "Task not found" in captured.err


class TestTaskQCLIRun:
    """Test taskq run command."""

    def test_run_once_no_tasks(self, cli_with_temp_store, capsys):
        """Test run --once with no tasks in queue."""
        args = argparse.Namespace(
            id=None,
            max_parallel=2,
            once=True,
            poll_interval_sec=1,
        )

        result = cli_with_temp_store.cmd_run(args)
        assert result == 0

        captured = capsys.readouterr()
        assert "Starting task queue runner" in captured.out
        assert "No tasks to process" in captured.out

    def test_run_with_mocked_processor(
        self, cli_with_temp_store, tmp_path, monkeypatch, capsys
    ):
        """Test run command with mocked task processor."""
        monkeypatch.setattr("orchestration.taskq.ensure_queue_dirs", lambda: None)
        monkeypatch.chdir(tmp_path)

        # Add a task
        args = argparse.Namespace(
            id="T-001",
            repo=str(tmp_path),
            base="main",
            task="Test task",
            task_file=None,
        )
        cli_with_temp_store.cmd_add(args)

        # Mock the TaskProcessor to avoid docker/git setup
        from unittest.mock import MagicMock, patch

        mock_processor = MagicMock()
        mock_record = cli_with_temp_store.store.get_record("T-001")
        mock_record.status = "review"
        mock_processor.process_task.return_value = mock_record

        with patch("orchestration.taskq.TaskProcessor", return_value=mock_processor):
            args = argparse.Namespace(
                id=None,
                max_parallel=1,
                once=True,
                poll_interval_sec=1,
            )

            result = cli_with_temp_store.cmd_run(args)
            assert result == 0

            # Verify processor was called
            assert mock_processor.process_task.called

    def test_run_specific_id_once(self, cli_with_temp_store, tmp_path, monkeypatch):
        """--id should run only one todo task without polling."""
        monkeypatch.setattr("orchestration.taskq.ensure_queue_dirs", lambda: None)
        monkeypatch.chdir(tmp_path)

        for task_id in ("T-101", "T-102"):
            args = argparse.Namespace(
                id=task_id,
                repo=str(tmp_path),
                base="main",
                branch=None,
                worktree_path=None,
                task=f"Task {task_id}",
                task_file=None,
            )
            assert cli_with_temp_store.cmd_add(args) == 0

        mock_processor = MagicMock()
        processed_record = cli_with_temp_store.store.get_record("T-101")
        processed_record.status = "review"
        mock_processor.process_task.return_value = processed_record

        with patch("orchestration.taskq.TaskProcessor", return_value=mock_processor):
            run_args = argparse.Namespace(
                id="T-101",
                max_parallel=3,
                once=False,
                poll_interval_sec=5,
            )
            result = cli_with_temp_store.cmd_run(run_args)

        assert result == 0
        assert mock_processor.process_task.call_count == 1
        assert mock_processor.process_task.call_args[0][0].id == "T-101"

        record_101 = cli_with_temp_store.store.get_record("T-101")
        record_102 = cli_with_temp_store.store.get_record("T-102")
        assert record_101.status == "planning"
        assert record_102.status == "todo"

    def test_run_specific_id_requires_todo(
        self, cli_with_temp_store, tmp_path, monkeypatch
    ):
        """--id run should fail when target task is not in todo status."""
        monkeypatch.setattr("orchestration.taskq.ensure_queue_dirs", lambda: None)
        monkeypatch.chdir(tmp_path)

        add_args = argparse.Namespace(
            id="T-103",
            repo=str(tmp_path),
            base="main",
            branch=None,
            worktree_path=None,
            task="Task",
            task_file=None,
        )
        assert cli_with_temp_store.cmd_add(add_args) == 0
        cli_with_temp_store.store.update_record("T-103", {"status": "planning"})

        run_args = argparse.Namespace(
            id="T-103",
            max_parallel=1,
            once=False,
            poll_interval_sec=1,
        )
        result = cli_with_temp_store.cmd_run(run_args)
        assert result == 1

    def test_run_arguments_parsing(self, cli_with_temp_store):
        """Test that run command parses all required arguments."""
        # Test default values
        args = argparse.Namespace(
            id=None,
            max_parallel=3,
            once=False,
            poll_interval_sec=5,
        )
        # Should not raise
        assert args.max_parallel == 3
        assert args.once is False
        assert args.poll_interval_sec == 5

        # Test custom values
        args = argparse.Namespace(
            id="T-555",
            max_parallel=10,
            once=True,
            poll_interval_sec=2,
        )
        assert args.id == "T-555"
        assert args.max_parallel == 10
        assert args.once is True
        assert args.poll_interval_sec == 2


class TestTaskQCLIReview:
    """Test taskq review command."""

    def test_review_task_not_found(self, cli_with_temp_store):
        """Test review with non-existent task."""
        args = argparse.Namespace(id="T-nonexistent")
        result = cli_with_temp_store.cmd_review(args)
        assert result == 1

    def test_review_task_not_in_review_status(
        self, cli_with_temp_store, tmp_path, monkeypatch
    ):
        """Test review of task not in review status."""
        monkeypatch.setattr("orchestration.taskq.ensure_queue_dirs", lambda: None)
        monkeypatch.chdir(tmp_path)

        # Add a task with todo status
        args = argparse.Namespace(
            id="T-001",
            repo=str(tmp_path),
            base="main",
            task="Test task",
            task_file=None,
        )
        cli_with_temp_store.cmd_add(args)

        # Try to review it (should fail - not in review status)
        args = argparse.Namespace(id="T-001")
        result = cli_with_temp_store.cmd_review(args)
        assert result == 1

    def test_review_task_no_port(self, cli_with_temp_store, tmp_path, monkeypatch):
        """Test review of task with no port allocated."""
        monkeypatch.setattr("orchestration.taskq.ensure_queue_dirs", lambda: None)
        monkeypatch.chdir(tmp_path)

        # Add a task
        args = argparse.Namespace(
            id="T-001",
            repo=str(tmp_path),
            base="main",
            task="Test task",
            task_file=None,
        )
        cli_with_temp_store.cmd_add(args)

        # Transition to review manually via legal transitions
        cli_with_temp_store.store.update_record("T-001", {"status": "planning"})
        cli_with_temp_store.store.update_record("T-001", {"status": "building"})
        cli_with_temp_store.store.update_record("T-001", {"status": "review"})

        # Try to review it (should fail - no port)
        args = argparse.Namespace(id="T-001")
        result = cli_with_temp_store.cmd_review(args)
        assert result == 1

    def test_review_with_port_launch_fails(
        self, cli_with_temp_store, tmp_path, monkeypatch
    ):
        """Test review launch failure."""
        monkeypatch.setattr("orchestration.taskq.ensure_queue_dirs", lambda: None)
        monkeypatch.chdir(tmp_path)

        # Add a task
        args = argparse.Namespace(
            id="T-001",
            repo=str(tmp_path),
            base="main",
            task="Test task",
            task_file=None,
        )
        cli_with_temp_store.cmd_add(args)

        # Transition to review with port via legal transitions
        cli_with_temp_store.store.update_record("T-001", {"status": "planning"})
        cli_with_temp_store.store.update_record("T-001", {"status": "building"})
        cli_with_temp_store.store.update_record(
            "T-001", {"status": "review", "port": 30001}
        )

        # Mock launch_review_from_record to raise
        def mock_launch(record):
            raise Exception("Launch failed")

        with patch(
            "orchestration.taskq.launch_review_from_record", side_effect=mock_launch
        ):
            args = argparse.Namespace(id="T-001")
            result = cli_with_temp_store.cmd_review(args)
            assert result == 1


class TestTaskQCLICleanup:
    """Test taskq cleanup command."""

    def test_cleanup_no_tasks(self, cli_with_temp_store):
        """Test cleanup with no tasks to clean."""
        args = argparse.Namespace(
            id=None,
            done_only=False,
            cancelled_only=False,
            keep_worktree=False,
        )
        result = cli_with_temp_store.cmd_cleanup(args)
        assert result == 0

    def test_cleanup_done_tasks(self, cli_with_temp_store, tmp_path, monkeypatch):
        """Test cleanup of done tasks."""
        monkeypatch.setattr("orchestration.taskq.ensure_queue_dirs", lambda: None)
        monkeypatch.chdir(tmp_path)

        # Add and complete a task
        args = argparse.Namespace(
            id="T-001",
            repo=str(tmp_path),
            base="main",
            task="Test task",
            task_file=None,
        )
        cli_with_temp_store.cmd_add(args)
        cli_with_temp_store.store.update_record("T-001", {"status": "planning"})
        cli_with_temp_store.store.update_record("T-001", {"status": "building"})
        cli_with_temp_store.store.update_record("T-001", {"status": "review"})
        cli_with_temp_store.store.update_record(
            "T-001",
            {
                "status": "done",
                "worktree_path": "/fake/path",
                "container": "task-001-xxx",
            },
        )

        # Mock cleanup functions
        with patch("orchestration.taskq.cleanup_task_containers", return_value=1):
            with patch("orchestration.taskq.remove_worktree"):
                args = argparse.Namespace(
                    id=None,
                    done_only=True,
                    cancelled_only=False,
                    keep_worktree=False,
                )
                result = cli_with_temp_store.cmd_cleanup(args)
                assert result == 0

                # Verify task was cleaned (runtime fields cleared)
                record = cli_with_temp_store.store.get_record("T-001")
                assert record.worktree_path == ""
                assert record.container == ""

    def test_cleanup_specific_task(self, cli_with_temp_store, tmp_path, monkeypatch):
        """Test cleanup of specific task by ID."""
        monkeypatch.setattr("orchestration.taskq.ensure_queue_dirs", lambda: None)
        monkeypatch.chdir(tmp_path)

        # Add two tasks
        args = argparse.Namespace(
            id="T-001",
            repo=str(tmp_path),
            base="main",
            task="Test task 1",
            task_file=None,
        )
        cli_with_temp_store.cmd_add(args)

        args = argparse.Namespace(
            id="T-002",
            repo=str(tmp_path),
            base="main",
            task="Test task 2",
            task_file=None,
        )
        cli_with_temp_store.cmd_add(args)

        # Mark both as done
        cli_with_temp_store.store.update_record("T-001", {"status": "planning"})
        cli_with_temp_store.store.update_record("T-001", {"status": "building"})
        cli_with_temp_store.store.update_record("T-001", {"status": "review"})
        cli_with_temp_store.store.update_record(
            "T-001", {"status": "done", "worktree_path": "/fake/path1"}
        )
        cli_with_temp_store.store.update_record("T-002", {"status": "planning"})
        cli_with_temp_store.store.update_record("T-002", {"status": "building"})
        cli_with_temp_store.store.update_record("T-002", {"status": "review"})
        cli_with_temp_store.store.update_record(
            "T-002", {"status": "done", "worktree_path": "/fake/path2"}
        )

        # Cleanup only T-001
        with patch("orchestration.taskq.cleanup_task_containers"):
            with patch("orchestration.taskq.remove_worktree"):
                args = argparse.Namespace(
                    id="T-001",
                    done_only=False,
                    cancelled_only=False,
                    keep_worktree=False,
                )
                result = cli_with_temp_store.cmd_cleanup(args)
                assert result == 0

                # Verify only T-001 was cleaned
                record1 = cli_with_temp_store.store.get_record("T-001")
                assert record1.worktree_path == ""

                record2 = cli_with_temp_store.store.get_record("T-002")
                assert record2.worktree_path == "/fake/path2"

    def test_cleanup_with_conflicting_flags(self, cli_with_temp_store):
        """Test cleanup with conflicting --done-only and --cancelled-only."""
        args = argparse.Namespace(
            id=None,
            done_only=True,
            cancelled_only=True,
            keep_worktree=False,
        )
        result = cli_with_temp_store.cmd_cleanup(args)
        assert result == 1

    def test_cleanup_keep_worktree(self, cli_with_temp_store, tmp_path, monkeypatch):
        """Test cleanup with --keep-worktree flag."""
        monkeypatch.setattr("orchestration.taskq.ensure_queue_dirs", lambda: None)
        monkeypatch.chdir(tmp_path)

        # Add and complete a task
        args = argparse.Namespace(
            id="T-001",
            repo=str(tmp_path),
            base="main",
            task="Test task",
            task_file=None,
        )
        cli_with_temp_store.cmd_add(args)
        cli_with_temp_store.store.update_record("T-001", {"status": "planning"})
        cli_with_temp_store.store.update_record("T-001", {"status": "building"})
        cli_with_temp_store.store.update_record("T-001", {"status": "review"})
        cli_with_temp_store.store.update_record(
            "T-001",
            {
                "status": "done",
                "worktree_path": "/fake/path",
                "container": "task-001-xxx",
            },
        )

        # Mock cleanup - should not call remove_worktree
        with patch(
            "orchestration.taskq.cleanup_task_containers"
        ) as mock_cleanup_container:
            with patch("orchestration.taskq.remove_worktree") as mock_remove_worktree:
                args = argparse.Namespace(
                    id=None,
                    done_only=False,
                    cancelled_only=False,
                    keep_worktree=True,
                )
                result = cli_with_temp_store.cmd_cleanup(args)
                assert result == 0

                # remove_worktree should NOT have been called
                assert not mock_remove_worktree.called
