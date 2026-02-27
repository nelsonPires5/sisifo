"""
Tests for task worker pipeline.

Tests cover:
- TaskProcessor initialization and configuration
- Full task processing pipeline (setup, execute, success/failure)
- Error reporting and file generation
- Resource cleanup on failure
"""

import pytest
import tempfile
import json
from pathlib import Path
from datetime import datetime
from unittest.mock import Mock, MagicMock, patch
from io import StringIO

from orchestration.pipeline import (
    TaskProcessor,
    TaskProcessingError,
)
from orchestration.pipeline.stages import (
    bootstrap_opencode_config_snapshot,
    bootstrap_opencode_data_snapshot,
)
from orchestration.constants import (
    DEFAULT_DOCKER_IMAGE,
    DEFAULT_OPENCODE_SERVER_CMD,
    DEFAULT_CONTAINER_OPENCODE_CONFIG_DIR,
    DEFAULT_CONTAINER_OPENCODE_DATA_DIR,
)
from orchestration.store import (
    QueueStore,
    generate_error_report,
    write_error_report,
)
from orchestration.core.models import TaskRecord
from orchestration.core.naming import compact_timestamp
from orchestration.support.task_files import (
    create_canonical_task_file,
    write_task_file,
)
from orchestration.support.paths import (
    get_attempt_config_dir,
    get_attempt_data_dir,
)
from orchestration.adapters.docker import ContainerError
from orchestration.adapters.git import GitRuntimeError
from orchestration.adapters.opencode import PlanError, BuildError


@pytest.fixture
def temp_dirs():
    """Create temporary directories for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = Path(tmpdir)
        queue_dir = tmppath / "queue"
        tasks_dir = queue_dir / "tasks"
        errors_dir = queue_dir / "errors"
        worktrees_dir = tmppath / "worktrees"
        repo_dir = tmppath / "test-repo"

        tasks_dir.mkdir(parents=True, exist_ok=True)
        errors_dir.mkdir(parents=True, exist_ok=True)
        worktrees_dir.mkdir(parents=True, exist_ok=True)
        repo_dir.mkdir(parents=True, exist_ok=True)

        yield {
            "root": str(tmppath),
            "queue": str(queue_dir),
            "tasks": str(tasks_dir),
            "errors": str(errors_dir),
            "worktrees": str(worktrees_dir),
            "repo": str(repo_dir),
        }


@pytest.fixture
def temp_queue(temp_dirs):
    """Create a temporary queue store."""
    queue_file = Path(temp_dirs["queue"]) / "tasks.jsonl"
    return QueueStore(str(queue_file))


@pytest.fixture
def sample_task_record(temp_dirs):
    """Create a sample task record."""
    return TaskRecord(
        id="T-001",
        repo=temp_dirs["repo"],
        base="main",
        task_file=str(Path(temp_dirs["tasks"]) / "T-001.md"),
        status="planning",
        branch="task/t-001",
        worktree_path=str(Path(temp_dirs["worktrees"]) / "test-repo" / "T-001"),
        container="",
        port=0,
        session_id="session-123",
        attempt=1,
        error_file="",
        created_at=datetime.utcnow().isoformat(),
        updated_at=datetime.utcnow().isoformat(),
    )


@pytest.fixture
def sample_task_file(temp_dirs):
    """Create a canonical task file for testing."""
    content = create_canonical_task_file(
        "T-001",
        temp_dirs["repo"],
        "Implement feature X\n\nThis is a test task.",
        "main",
    )
    return write_task_file("T-001", content, temp_dirs["tasks"])


class TestBootstrapConfigSnapshot:
    """Test bootstrap_opencode_config_snapshot functionality."""

    def test_bootstrap_copies_existing_config(self, temp_dirs):
        """Test that bootstrap copies existing host config to target."""
        host_config = Path(temp_dirs["root"]) / "host_config"
        host_config.mkdir(parents=True, exist_ok=True)
        (host_config / "file1.txt").write_text("content1")
        (host_config / "subdir").mkdir()
        (host_config / "subdir" / "file2.txt").write_text("content2")

        target_config = Path(temp_dirs["root"]) / "target_config"

        bootstrap_opencode_config_snapshot(str(host_config), str(target_config))

        # Verify target was created with same structure
        assert target_config.exists()
        assert (target_config / "file1.txt").read_text() == "content1"
        assert (target_config / "subdir" / "file2.txt").read_text() == "content2"

    def test_bootstrap_creates_empty_dir_when_source_missing(self, temp_dirs):
        """Test that bootstrap creates empty dir when source doesn't exist."""
        nonexistent_config = Path(temp_dirs["root"]) / "nonexistent"
        target_config = Path(temp_dirs["root"]) / "target_config"

        bootstrap_opencode_config_snapshot(str(nonexistent_config), str(target_config))

        # Verify empty target dir was created
        assert target_config.exists()
        assert target_config.is_dir()
        assert len(list(target_config.iterdir())) == 0

    def test_bootstrap_overwrites_existing_target(self, temp_dirs):
        """Test that bootstrap removes and recreates target if it exists."""
        host_config = Path(temp_dirs["root"]) / "host_config"
        host_config.mkdir(parents=True, exist_ok=True)
        (host_config / "new_file.txt").write_text("new content")

        target_config = Path(temp_dirs["root"]) / "target_config"
        target_config.mkdir(parents=True, exist_ok=True)
        (target_config / "old_file.txt").write_text("old content")

        bootstrap_opencode_config_snapshot(str(host_config), str(target_config))

        # Verify old file is gone and new file exists
        assert not (target_config / "old_file.txt").exists()
        assert (target_config / "new_file.txt").read_text() == "new content"


class TestBootstrapDataSnapshot:
    """Test bootstrap_opencode_data_snapshot functionality."""

    def test_bootstrap_copies_auth_file_when_present(self, temp_dirs):
        """Bootstrap should copy auth.json from host data directory."""
        host_data = Path(temp_dirs["root"]) / "host_data"
        host_data.mkdir(parents=True, exist_ok=True)
        source_auth = host_data / "auth.json"
        source_auth.write_text('{"openai": {"type": "oauth"}}', encoding="utf-8")

        target_data = Path(temp_dirs["root"]) / "target_data"

        bootstrap_opencode_data_snapshot(str(host_data), str(target_data))

        target_auth = target_data / "auth.json"
        assert target_auth.exists()
        assert target_auth.read_text(encoding="utf-8") == source_auth.read_text(
            encoding="utf-8"
        )

    def test_bootstrap_leaves_empty_target_when_source_missing(self, temp_dirs):
        """Bootstrap should not fail when source data directory is missing."""
        missing_source = Path(temp_dirs["root"]) / "missing_data"
        target_data = Path(temp_dirs["root"]) / "target_data"

        bootstrap_opencode_data_snapshot(str(missing_source), str(target_data))

        assert target_data.exists()
        assert (target_data / "auth.json").exists() is False

    def test_bootstrap_keeps_target_without_auth_when_not_present(self, temp_dirs):
        """Bootstrap should keep target directory when host auth.json is absent."""
        host_data = Path(temp_dirs["root"]) / "host_data"
        host_data.mkdir(parents=True, exist_ok=True)
        target_data = Path(temp_dirs["root"]) / "target_data"

        bootstrap_opencode_data_snapshot(str(host_data), str(target_data))

        assert target_data.exists()
        assert not (target_data / "auth.json").exists()


class TestErrorReporting:
    """Test error reporting functionality."""

    def test_generate_error_report_basic(self, sample_task_record):
        """Test basic error report generation."""
        report = generate_error_report(
            sample_task_record,
            stage="planning",
            command="make-plan",
            exit_code=1,
            stdout="Some output",
            stderr="Error occurred",
        )

        assert "Task Failure Report" in report
        assert "T-001" in report
        assert "planning" in report
        assert "make-plan" in report
        assert "Some output" in report
        assert "Error occurred" in report

    def test_generate_error_report_empty_output(self, sample_task_record):
        """Test error report with empty output."""
        report = generate_error_report(
            sample_task_record,
            stage="building",
            command="execute-plan",
            exit_code=127,
            stdout="",
            stderr="",
        )

        assert "(empty)" in report
        assert "execute-plan" in report

    def test_generate_error_report_long_output(self, sample_task_record):
        """Test error report truncates long output."""
        long_output = "x" * 1000
        report = generate_error_report(
            sample_task_record,
            stage="setup",
            command="git-worktree",
            exit_code=-1,
            stdout=long_output,
            stderr=long_output,
        )

        # Output should be truncated to 500 chars
        assert long_output not in report
        assert "x" * 500 in report

    def test_write_error_report(self, sample_task_record, temp_dirs):
        """Test writing error report to file."""
        report_content = generate_error_report(
            sample_task_record,
            stage="planning",
            command="make-plan",
            exit_code=1,
            stdout="output",
            stderr="error",
        )

        error_path = write_error_report(report_content, "T-001", temp_dirs["errors"])

        assert error_path.exists()
        assert error_path.name.startswith("T-001-")
        assert error_path.name.endswith(".md")

        # Verify content
        content = error_path.read_text()
        assert "Task Failure Report" in content
        assert "T-001" in content

    def test_write_error_report_creates_directory(self, sample_task_record, temp_dirs):
        """Test that write_error_report creates directory if missing."""
        nonexistent_dir = str(Path(temp_dirs["root"]) / "new" / "errors")

        report_content = generate_error_report(
            sample_task_record,
            stage="planning",
            command="make-plan",
            exit_code=1,
            stdout="output",
            stderr="error",
        )

        error_path = write_error_report(report_content, "T-001", nonexistent_dir)

        assert error_path.exists()
        assert Path(nonexistent_dir).exists()


class TestTaskProcessor:
    """Test TaskProcessor class."""

    def test_initialization(self, temp_queue, temp_dirs):
        """Test TaskProcessor initialization."""
        processor = TaskProcessor(
            temp_queue,
            session_id="test-session",
            docker_image="custom-image:latest",
            container_host="0.0.0.0",
        )

        assert processor.session_id == "test-session"
        assert processor.docker_image == "custom-image:latest"
        assert processor.container_host == "0.0.0.0"

    def test_initialization_defaults(self, temp_queue, temp_dirs):
        """Test TaskProcessor default image and server command."""
        processor = TaskProcessor(
            temp_queue,
            session_id="test-session",
        )

        assert processor.docker_image == DEFAULT_DOCKER_IMAGE
        assert processor.container_cmd == DEFAULT_OPENCODE_SERVER_CMD

    def test_derive_branch_name(self):
        """Test branch name derivation from task ID."""
        assert TaskProcessor._derive_branch_name("T-001") == "task/t-001"
        assert TaskProcessor._derive_branch_name("T-002") == "task/t-002"
        assert TaskProcessor._derive_branch_name("Task-Foo") == "task/task-foo"

    def test_derive_container_name(self, sample_task_record):
        """Container name includes task ID and compact created_at timestamp."""
        sample_task_record.id = "T 001/ABC"
        sample_task_record.created_at = "2026-02-26T17:19:40.010123+00:00"

        name = TaskProcessor._derive_container_name(sample_task_record)

        assert name == "task-T-001-ABC-20260226171940"

    def test_resolve_host_opencode_dirs_with_env(self, temp_dirs, monkeypatch):
        """Host config/data mounts should honor OPENCODE/XDG env settings."""
        config_dir = Path(temp_dirs["root"]) / "config" / "opencode"
        xdg_data_home = Path(temp_dirs["root"]) / "data"

        monkeypatch.setenv("OPENCODE_CONFIG_DIR", str(config_dir))
        monkeypatch.setenv("XDG_DATA_HOME", str(xdg_data_home))

        resolved_config, resolved_data = TaskProcessor._resolve_host_opencode_dirs()

        assert resolved_config == str(config_dir.resolve())
        assert resolved_data == str((xdg_data_home / "opencode").resolve())
        assert config_dir.is_dir()
        assert (xdg_data_home / "opencode").is_dir()


class TestTaskProcessorPipeline:
    """Test full task processing pipeline with mocks."""

    @pytest.fixture
    def processor(self, temp_queue, temp_dirs):
        """Create a TaskProcessor for testing."""
        return TaskProcessor(
            temp_queue,
            session_id="test-session",
        )

    def test_process_task_success_flow(
        self, processor, sample_task_record, sample_task_file, temp_queue
    ):
        """Test successful task processing through all stages."""
        # Add record to queue
        temp_queue.add_record(sample_task_record)

        with (
            patch("orchestration.pipeline.stages.create_worktree") as mock_create_wt,
            patch("orchestration.pipeline.stages.reserve_port") as mock_reserve_port,
            patch(
                "orchestration.pipeline.stages.launch_container"
            ) as mock_launch_container,
            patch("orchestration.pipeline.stages.run_make_plan") as mock_make_plan,
            patch(
                "orchestration.pipeline.stages.run_execute_plan"
            ) as mock_execute_plan,
        ):
            # Setup mocks
            mock_create_wt.return_value = sample_task_record.worktree_path
            mock_reserve_port.return_value = 30001
            mock_launch_container.return_value = "container-abc123"
            mock_make_plan.return_value = ("plan output", "plan stderr")
            mock_execute_plan.return_value = ("build output", "build stderr")

            # Process task
            result = processor.process_task(sample_task_record)

            # Verify final state
            assert result.status == "review"
            assert result.container == "container-abc123"
            assert result.port == 30001
            assert result.error_file == ""

            # Verify all stages were called
            mock_create_wt.assert_called_once()
            mock_reserve_port.assert_called_once()
            mock_launch_container.assert_called_once()
            mock_make_plan.assert_called_once()
            mock_execute_plan.assert_called_once()

            launch_config = mock_launch_container.call_args[0][0]
            assert launch_config.image == DEFAULT_DOCKER_IMAGE
            assert launch_config.cmd == DEFAULT_OPENCODE_SERVER_CMD
            assert launch_config.name.startswith("task-T-001-")
            assert launch_config.name.endswith(
                compact_timestamp(sample_task_record.created_at)
            )
            # Verify working_dir matches worktree_path for path parity
            assert launch_config.working_dir == sample_task_record.worktree_path
            assert launch_config.mounts is not None
            assert (
                DEFAULT_CONTAINER_OPENCODE_CONFIG_DIR in launch_config.mounts.values()
            )
            assert DEFAULT_CONTAINER_OPENCODE_DATA_DIR in launch_config.mounts.values()
            assert launch_config.writable_mount_paths is not None
            assert (
                DEFAULT_CONTAINER_OPENCODE_DATA_DIR
                in launch_config.writable_mount_paths
            )

    def test_process_task_planning_failure(
        self, processor, sample_task_record, sample_task_file, temp_queue, temp_dirs
    ):
        """Test task processing failure in planning stage."""
        temp_queue.add_record(sample_task_record)

        with (
            patch("orchestration.pipeline.stages.create_worktree") as mock_create_wt,
            patch("orchestration.pipeline.stages.reserve_port") as mock_reserve_port,
            patch(
                "orchestration.pipeline.stages.launch_container"
            ) as mock_launch_container,
            patch("orchestration.pipeline.stages.run_make_plan") as mock_make_plan,
            patch(
                "orchestration.pipeline.stages.cleanup_task_containers"
            ) as mock_cleanup_containers,
            patch("orchestration.pipeline.stages.remove_worktree") as mock_remove_wt,
            patch(
                "orchestration.pipeline.error_reporting.write_error_report"
            ) as mock_write_error,
        ):
            # Setup mocks
            mock_create_wt.return_value = sample_task_record.worktree_path
            mock_reserve_port.return_value = 30001
            mock_launch_container.return_value = "container-abc123"

            # Make planning fail
            error = PlanError(
                stage="planning",
                exit_code=1,
                stdout="",
                stderr="Plan failed",
                endpoint="http://127.0.0.1:30001",
            )
            mock_make_plan.side_effect = error

            # Mock error file writing
            mock_write_error.return_value = Path(temp_dirs["errors"]) / "T-001-12345.md"

            # Process task
            result = processor.process_task(sample_task_record)

            # Verify failure state
            assert result.status == "failed"
            assert result.error_file != ""

            # Default behavior preserves artifacts on failure.
            mock_cleanup_containers.assert_not_called()
            mock_remove_wt.assert_not_called()

    def test_process_task_building_failure(
        self, processor, sample_task_record, sample_task_file, temp_queue, temp_dirs
    ):
        """Test task processing failure in building stage."""
        temp_queue.add_record(sample_task_record)

        with (
            patch("orchestration.pipeline.stages.create_worktree") as mock_create_wt,
            patch("orchestration.pipeline.stages.reserve_port") as mock_reserve_port,
            patch(
                "orchestration.pipeline.stages.launch_container"
            ) as mock_launch_container,
            patch("orchestration.pipeline.stages.run_make_plan") as mock_make_plan,
            patch(
                "orchestration.pipeline.stages.run_execute_plan"
            ) as mock_execute_plan,
            patch(
                "orchestration.pipeline.stages.cleanup_task_containers"
            ) as mock_cleanup_containers,
            patch("orchestration.pipeline.stages.remove_worktree") as mock_remove_wt,
            patch(
                "orchestration.pipeline.error_reporting.write_error_report"
            ) as mock_write_error,
        ):
            # Setup mocks
            mock_create_wt.return_value = sample_task_record.worktree_path
            mock_reserve_port.return_value = 30001
            mock_launch_container.return_value = "container-abc123"
            mock_make_plan.return_value = ("plan output", "plan stderr")

            # Make building fail
            error = BuildError(
                stage="building",
                exit_code=1,
                stdout="",
                stderr="Build failed",
                endpoint="http://127.0.0.1:30001",
            )
            mock_execute_plan.side_effect = error

            # Mock error file writing
            mock_write_error.return_value = Path(temp_dirs["errors"]) / "T-001-12345.md"

            # Process task
            result = processor.process_task(sample_task_record)

            # Verify failure state
            assert result.status == "failed"
            assert result.error_file != ""

            # Default behavior preserves artifacts on failure.
            mock_cleanup_containers.assert_not_called()
            mock_remove_wt.assert_not_called()

    def test_process_task_setup_failure_git(
        self, processor, sample_task_record, sample_task_file, temp_queue, temp_dirs
    ):
        """Test task processing failure in setup (git) stage."""
        temp_queue.add_record(sample_task_record)

        with (
            patch("orchestration.pipeline.stages.create_worktree") as mock_create_wt,
            patch(
                "orchestration.pipeline.error_reporting.write_error_report"
            ) as mock_write_error,
        ):
            # Make git worktree creation fail
            error = GitRuntimeError("Worktree creation failed")
            mock_create_wt.side_effect = error

            # Mock error file writing
            mock_write_error.return_value = Path(temp_dirs["errors"]) / "T-001-12345.md"

            # Process task
            result = processor.process_task(sample_task_record)

            # Verify failure state
            assert result.status == "failed"
            assert result.error_file != ""

    def test_process_task_setup_failure_port(
        self, processor, sample_task_record, sample_task_file, temp_queue, temp_dirs
    ):
        """Test task processing failure in setup (port) stage."""
        temp_queue.add_record(sample_task_record)

        with (
            patch("orchestration.pipeline.stages.create_worktree") as mock_create_wt,
            patch("orchestration.pipeline.stages.reserve_port") as mock_reserve_port,
            patch(
                "orchestration.pipeline.error_reporting.write_error_report"
            ) as mock_write_error,
            patch("orchestration.pipeline.stages.remove_worktree") as mock_remove_wt,
        ):
            # Setup success, then port fails
            mock_create_wt.return_value = sample_task_record.worktree_path
            from orchestration.adapters.docker import PortAllocationError

            error = PortAllocationError("No available ports")
            mock_reserve_port.side_effect = error

            # Mock error file writing
            mock_write_error.return_value = Path(temp_dirs["errors"]) / "T-001-12345.md"

            # Process task
            result = processor.process_task(sample_task_record)

            # Verify failure state
            assert result.status == "failed"
            assert result.error_file != ""

            # Default behavior preserves artifacts on failure.
            mock_remove_wt.assert_not_called()

    def test_process_task_setup_missing_worktree_path(
        self, processor, sample_task_record, sample_task_file, temp_queue, temp_dirs
    ):
        """Task should fail setup when worktree_path is missing from record."""
        sample_task_record.worktree_path = ""
        temp_queue.add_record(sample_task_record)

        with (
            patch("orchestration.pipeline.stages.create_worktree") as mock_create_wt,
            patch(
                "orchestration.pipeline.error_reporting.write_error_report"
            ) as mock_write_error,
        ):
            mock_write_error.return_value = Path(temp_dirs["errors"]) / "T-001-12345.md"

            result = processor.process_task(sample_task_record)

            assert result.status == "failed"
            assert result.error_file != ""
            mock_create_wt.assert_not_called()

    def test_process_task_failure_cleanup_errors_ignored(
        self, processor, sample_task_record, sample_task_file, temp_queue, temp_dirs
    ):
        """Test that cleanup errors don't prevent failure handling."""
        temp_queue.add_record(sample_task_record)
        processor.cleanup_on_fail = True

        with (
            patch("orchestration.pipeline.stages.create_worktree") as mock_create_wt,
            patch("orchestration.pipeline.stages.reserve_port") as mock_reserve_port,
            patch(
                "orchestration.pipeline.stages.launch_container"
            ) as mock_launch_container,
            patch("orchestration.pipeline.stages.run_make_plan") as mock_make_plan,
            patch(
                "orchestration.pipeline.stages.cleanup_task_containers"
            ) as mock_cleanup_containers,
            patch("orchestration.pipeline.stages.remove_worktree") as mock_remove_wt,
            patch(
                "orchestration.pipeline.error_reporting.write_error_report"
            ) as mock_write_error,
        ):
            # Setup success
            mock_create_wt.return_value = sample_task_record.worktree_path
            mock_reserve_port.return_value = 30001
            mock_launch_container.return_value = "container-abc123"

            # Make planning fail
            error = PlanError(
                stage="planning",
                exit_code=1,
                stdout="",
                stderr="Plan failed",
                endpoint="http://127.0.0.1:30001",
            )
            mock_make_plan.side_effect = error

            # Make cleanup fail
            mock_cleanup_containers.side_effect = ContainerError("Cleanup failed")
            mock_remove_wt.side_effect = GitRuntimeError("Cleanup failed")

            # Mock error file writing
            mock_write_error.return_value = Path(temp_dirs["errors"]) / "T-001-12345.md"

            # Process task - should not raise despite cleanup failures
            result = processor.process_task(sample_task_record)

            # Verify failure state was still persisted
            assert result.status == "failed"
            assert result.error_file != ""

            # Verify cleanup was attempted (even though it failed)
            mock_cleanup_containers.assert_called_once_with("T-001")
            mock_remove_wt.assert_called_once()

    def test_process_task_dirty_run_reuses_existing_worktree(
        self, sample_task_record, sample_task_file, temp_queue
    ):
        """Dirty run should reuse existing worktree and clear stale containers."""
        processor = TaskProcessor(
            temp_queue,
            session_id="test-session",
            dirty_run=True,
        )
        Path(sample_task_record.worktree_path).mkdir(parents=True, exist_ok=True)
        temp_queue.add_record(sample_task_record)

        with (
            patch("orchestration.pipeline.stages.create_worktree") as mock_create_wt,
            patch(
                "orchestration.pipeline.stages.cleanup_task_containers"
            ) as mock_cleanup_containers,
            patch("orchestration.pipeline.stages.reserve_port") as mock_reserve_port,
            patch(
                "orchestration.pipeline.stages.launch_container"
            ) as mock_launch_container,
            patch("orchestration.pipeline.stages.run_make_plan") as mock_make_plan,
            patch(
                "orchestration.pipeline.stages.run_execute_plan"
            ) as mock_execute_plan,
        ):
            mock_cleanup_containers.return_value = 1
            mock_reserve_port.return_value = 30001
            mock_launch_container.return_value = "container-abc123"
            mock_make_plan.return_value = ("plan output", "")
            mock_execute_plan.return_value = ("build output", "")

            result = processor.process_task(sample_task_record)

            assert result.status == "review"
            mock_create_wt.assert_not_called()
            mock_cleanup_containers.assert_called_once_with("T-001")

    def test_stage_setup_creates_attempt_dirs(
        self, processor, sample_task_record, sample_task_file, temp_queue, temp_dirs
    ):
        """Test that _stage_setup creates per-attempt OpenCode directories."""
        temp_queue.add_record(sample_task_record)

        with (
            patch("orchestration.pipeline.stages.create_worktree") as mock_create_wt,
            patch("orchestration.pipeline.stages.reserve_port") as mock_reserve_port,
            patch(
                "orchestration.pipeline.stages.launch_container"
            ) as mock_launch_container,
            patch("orchestration.pipeline.stages.run_make_plan") as mock_make_plan,
            patch(
                "orchestration.pipeline.stages.run_execute_plan"
            ) as mock_execute_plan,
        ):
            mock_create_wt.return_value = sample_task_record.worktree_path
            mock_reserve_port.return_value = 30001
            mock_launch_container.return_value = "container-abc123"
            mock_make_plan.return_value = ("plan output", "")
            mock_execute_plan.return_value = ("build output", "")

            result = processor.process_task(sample_task_record)

            # Verify attempt dirs were created
            assert result.opencode_attempt_dir != ""
            assert result.opencode_config_dir != ""
            assert result.opencode_data_dir != ""

            # Verify paths are under queue/opencode
            attempt_config = get_attempt_config_dir(
                sample_task_record.id, sample_task_record.attempt
            )
            attempt_data = get_attempt_data_dir(
                sample_task_record.id, sample_task_record.attempt
            )

            assert result.opencode_config_dir == str(attempt_config)
            assert result.opencode_data_dir == str(attempt_data)
            assert attempt_config.exists()
            assert attempt_data.exists()

    def test_stage_setup_bootstraps_config_snapshot(
        self, processor, sample_task_record, sample_task_file, temp_queue, temp_dirs
    ):
        """Test that _stage_setup bootstraps config snapshot from host."""
        # Create a mock host config directory with test content
        host_config_dir = Path(temp_dirs["root"]) / "host_config"
        host_config_dir.mkdir(parents=True, exist_ok=True)
        (host_config_dir / "test_file.txt").write_text("test content")

        temp_queue.add_record(sample_task_record)

        with (
            patch("orchestration.pipeline.stages.create_worktree") as mock_create_wt,
            patch("orchestration.pipeline.stages.reserve_port") as mock_reserve_port,
            patch(
                "orchestration.pipeline.stages.launch_container"
            ) as mock_launch_container,
            patch("orchestration.pipeline.stages.run_make_plan") as mock_make_plan,
            patch(
                "orchestration.pipeline.stages.run_execute_plan"
            ) as mock_execute_plan,
            patch(
                "orchestration.pipeline.stages.resolve_host_opencode_dirs"
            ) as mock_resolve_dirs,
        ):
            mock_create_wt.return_value = sample_task_record.worktree_path
            mock_reserve_port.return_value = 30001
            mock_launch_container.return_value = "container-abc123"
            mock_make_plan.return_value = ("plan output", "")
            mock_execute_plan.return_value = ("build output", "")
            # Return mock host config dir and a data dir
            mock_resolve_dirs.return_value = (
                str(host_config_dir),
                str(Path(temp_dirs["root"]) / "host_data"),
            )

            result = processor.process_task(sample_task_record)

            # Verify config was bootstrapped
            attempt_config = get_attempt_config_dir(
                sample_task_record.id, sample_task_record.attempt
            )
            assert (attempt_config / "test_file.txt").exists()
            assert (attempt_config / "test_file.txt").read_text() == "test content"

    def test_stage_setup_bootstraps_data_auth_snapshot(
        self, processor, sample_task_record, sample_task_file, temp_queue, temp_dirs
    ):
        """Test that _stage_setup copies auth.json into attempt data dir."""
        host_config_dir = Path(temp_dirs["root"]) / "host_config"
        host_config_dir.mkdir(parents=True, exist_ok=True)
        host_data_dir = Path(temp_dirs["root"]) / "host_data"
        host_data_dir.mkdir(parents=True, exist_ok=True)
        (host_data_dir / "auth.json").write_text(
            '{"openai": {"type": "oauth"}}', encoding="utf-8"
        )

        temp_queue.add_record(sample_task_record)

        with (
            patch("orchestration.pipeline.stages.create_worktree") as mock_create_wt,
            patch("orchestration.pipeline.stages.reserve_port") as mock_reserve_port,
            patch(
                "orchestration.pipeline.stages.launch_container"
            ) as mock_launch_container,
            patch("orchestration.pipeline.stages.run_make_plan") as mock_make_plan,
            patch(
                "orchestration.pipeline.stages.run_execute_plan"
            ) as mock_execute_plan,
            patch(
                "orchestration.pipeline.stages.resolve_host_opencode_dirs"
            ) as mock_resolve_dirs,
        ):
            mock_create_wt.return_value = sample_task_record.worktree_path
            mock_reserve_port.return_value = 30001
            mock_launch_container.return_value = "container-abc123"
            mock_make_plan.return_value = ("plan output", "")
            mock_execute_plan.return_value = ("build output", "")
            mock_resolve_dirs.return_value = (str(host_config_dir), str(host_data_dir))

            result = processor.process_task(sample_task_record)

            attempt_data = get_attempt_data_dir(
                sample_task_record.id, sample_task_record.attempt
            )
            auth_path = attempt_data / "auth.json"
            assert result.status == "review"
            assert auth_path.exists()
            assert auth_path.read_text(encoding="utf-8") == (
                host_data_dir / "auth.json"
            ).read_text(encoding="utf-8")

    def test_stage_setup_uses_strict_local_mounts(
        self, processor, sample_task_record, sample_task_file, temp_queue, temp_dirs
    ):
        """Test that container mounts use strict-local attempt dirs, not host dirs."""
        temp_queue.add_record(sample_task_record)

        with (
            patch("orchestration.pipeline.stages.create_worktree") as mock_create_wt,
            patch("orchestration.pipeline.stages.reserve_port") as mock_reserve_port,
            patch(
                "orchestration.pipeline.stages.launch_container"
            ) as mock_launch_container,
            patch("orchestration.pipeline.stages.run_make_plan") as mock_make_plan,
            patch(
                "orchestration.pipeline.stages.run_execute_plan"
            ) as mock_execute_plan,
        ):
            mock_create_wt.return_value = sample_task_record.worktree_path
            mock_reserve_port.return_value = 30001
            mock_launch_container.return_value = "container-abc123"
            mock_make_plan.return_value = ("plan output", "")
            mock_execute_plan.return_value = ("build output", "")

            result = processor.process_task(sample_task_record)

            # Verify container was launched with strict-local attempt dirs
            launch_config = mock_launch_container.call_args[0][0]
            assert launch_config.mounts is not None

            attempt_config = get_attempt_config_dir(
                sample_task_record.id, sample_task_record.attempt
            )
            attempt_data = get_attempt_data_dir(
                sample_task_record.id, sample_task_record.attempt
            )

            # Mounts should use attempt dirs, not host dirs
            assert str(attempt_config) in launch_config.mounts
            assert str(attempt_data) in launch_config.mounts
            assert (
                launch_config.mounts[str(attempt_config)]
                == DEFAULT_CONTAINER_OPENCODE_CONFIG_DIR
            )
            assert (
                launch_config.mounts[str(attempt_data)]
                == DEFAULT_CONTAINER_OPENCODE_DATA_DIR
            )


class TestTaskProcessorIntegration:
    """Integration tests with real task files."""

    def test_process_task_with_real_files(
        self, temp_queue, temp_dirs, sample_task_file
    ):
        """Test task processing with real task file (setup stage only)."""
        processor = TaskProcessor(
            temp_queue,
            session_id="test-session",
        )

        record = TaskRecord(
            id="T-001",
            repo=temp_dirs["repo"],
            base="main",
            task_file=str(sample_task_file),
            status="planning",
            branch="",
            worktree_path=str(Path(temp_dirs["worktrees"]) / "test-repo" / "T-001"),
            container="",
            port=0,
            session_id="test-session",
            attempt=1,
            error_file="",
            created_at=datetime.utcnow().isoformat(),
            updated_at=datetime.utcnow().isoformat(),
        )

        temp_queue.add_record(record)

        with (
            patch("orchestration.pipeline.stages.create_worktree") as mock_create_wt,
            patch("orchestration.pipeline.stages.reserve_port") as mock_reserve_port,
            patch(
                "orchestration.pipeline.stages.launch_container"
            ) as mock_launch_container,
            patch("orchestration.pipeline.stages.run_make_plan") as mock_make_plan,
            patch(
                "orchestration.pipeline.stages.run_execute_plan"
            ) as mock_execute_plan,
        ):
            mock_create_wt.return_value = str(
                Path(temp_dirs["worktrees"]) / "test-repo" / "T-001"
            )
            mock_reserve_port.return_value = 30001
            mock_launch_container.return_value = "abc123"
            mock_make_plan.return_value = ("", "")
            mock_execute_plan.return_value = ("", "")

            result = processor.process_task(record)

            assert result.status == "review"
            assert result.branch == "task/t-001"
            assert result.container == "abc123"
            assert result.port == 30001
