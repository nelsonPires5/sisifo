"""
Unit tests for OpenChamber review launcher.
"""

import subprocess
import tempfile
from pathlib import Path
import pytest
from unittest.mock import Mock, patch, MagicMock

from orchestration.adapters.review import (
    launch_review,
    launch_review_from_record,
    ReviewException,
    ReviewLaunchError,
    StrictLocalValidationError,
)


class TestLaunchReview:
    """Test review launch functionality."""

    def test_launch_review_success(self):
        """Test successful OpenChamber launch."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0)

            exit_code = launch_review("T-001", "127.0.0.1", 30001)

            assert exit_code == 0
            mock_run.assert_called_once()
            args, kwargs = mock_run.call_args
            assert args[0] == ["openchamber"]
            assert kwargs["env"]["OPENCODE_HOST"] == "http://127.0.0.1:30001"
            assert kwargs["env"]["OPENCODE_SKIP_START"] == "true"

    def test_launch_review_with_skip_start_false(self):
        """Test launch with skip_start disabled."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0)

            exit_code = launch_review("T-001", "127.0.0.1", 30001, skip_start=False)

            assert exit_code == 0
            args, kwargs = mock_run.call_args
            env = kwargs["env"]
            assert (
                "OPENCODE_SKIP_START" not in env
                or env.get("OPENCODE_SKIP_START") != "true"
            )

    def test_launch_review_non_zero_exit(self):
        """Test OpenChamber non-zero exit code."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=1)

            exit_code = launch_review("T-001", "127.0.0.1", 30001)

            assert exit_code == 1

    def test_launch_review_timeout(self):
        """Test OpenChamber timeout."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired("openchamber", 3600)

            with pytest.raises(ReviewLaunchError) as exc_info:
                launch_review("T-001", "127.0.0.1", 30001)

            err = exc_info.value
            assert err.task_id == "T-001"
            assert err.exit_code == -1
            assert "timeout" in err.stderr.lower()

    def test_launch_review_command_not_found(self):
        """Test openchamber command not found."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError()

            with pytest.raises(ReviewLaunchError) as exc_info:
                launch_review("T-001", "127.0.0.1", 30001)

            err = exc_info.value
            assert "openchamber" in err.stderr.lower()

    def test_launch_review_unexpected_error(self):
        """Test unexpected error during launch."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = RuntimeError("Unexpected error")

            with pytest.raises(ReviewLaunchError) as exc_info:
                launch_review("T-001", "127.0.0.1", 30001)

            err = exc_info.value
            assert err.task_id == "T-001"
            assert err.exit_code == -1

    def test_launch_review_localhost(self):
        """Test launch with localhost hostname."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0)

            exit_code = launch_review("T-001", "localhost", 30001)

            assert exit_code == 0
            args, kwargs = mock_run.call_args
            assert "localhost:30001" in kwargs["env"]["OPENCODE_HOST"]

    def test_launch_review_high_port(self):
        """Test launch with high port number."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0)

            exit_code = launch_review("T-001", "127.0.0.1", 65534)

            assert exit_code == 0

    def test_launch_review_uses_worktree_cwd(self):
        """Valid worktree path should be used as subprocess cwd."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = Mock(returncode=0)

                exit_code = launch_review(
                    "T-001",
                    "127.0.0.1",
                    30001,
                    worktree_path=tmpdir,
                )

                assert exit_code == 0
                _, kwargs = mock_run.call_args
                assert kwargs["cwd"] == str(Path(tmpdir).resolve())


class TestLaunchReviewFromRecord:
    """Test review launch from queue record."""

    def test_launch_review_from_record_success(self):
        """Test successful launch from record."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "config"
            data_dir = Path(tmpdir) / "data"
            config_dir.mkdir()
            data_dir.mkdir()

            task_record = {
                "id": "T-001",
                "port": 30001,
                "status": "review",
                "repo": "/home/user/documents/repos/test",
                "opencode_config_dir": str(config_dir),
                "opencode_data_dir": str(data_dir),
            }

            with patch("orchestration.adapters.review.launch_review") as mock_launch:
                mock_launch.return_value = 0

                exit_code = launch_review_from_record(task_record)

                assert exit_code == 0
                mock_launch.assert_called_once_with(
                    "T-001",
                    "127.0.0.1",
                    30001,
                    skip_start=True,
                    worktree_path=None,
                    opencode_config_dir=str(config_dir),
                    opencode_data_dir=str(data_dir),
                )

    def test_launch_review_from_record_passes_worktree(self):
        """worktree_path should be forwarded when present in task record."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "config"
            data_dir = Path(tmpdir) / "data"
            config_dir.mkdir()
            data_dir.mkdir()

            task_record = {
                "id": "T-001",
                "port": 30001,
                "status": "review",
                "worktree_path": "/tmp/example-worktree",
                "opencode_config_dir": str(config_dir),
                "opencode_data_dir": str(data_dir),
            }

            with patch("orchestration.adapters.review.launch_review") as mock_launch:
                mock_launch.return_value = 0

                exit_code = launch_review_from_record(task_record)

                assert exit_code == 0
                mock_launch.assert_called_once_with(
                    "T-001",
                    "127.0.0.1",
                    30001,
                    skip_start=True,
                    worktree_path="/tmp/example-worktree",
                    opencode_config_dir=str(config_dir),
                    opencode_data_dir=str(data_dir),
                )

    def test_launch_review_from_record_missing_id(self):
        """Test record missing task ID."""
        task_record = {
            "port": 30001,
            "status": "review",
        }

        with pytest.raises(ReviewLaunchError) as exc_info:
            launch_review_from_record(task_record)

        err = exc_info.value
        assert "id" in err.stderr.lower()

    def test_launch_review_from_record_missing_port(self):
        """Test record missing port."""
        task_record = {
            "id": "T-001",
            "status": "review",
        }

        with pytest.raises(ReviewLaunchError) as exc_info:
            launch_review_from_record(task_record)

        err = exc_info.value
        assert err.task_id == "T-001"
        assert "invalid port" in err.stderr.lower()

    def test_launch_review_from_record_invalid_port_zero(self):
        """Test record with port = 0."""
        task_record = {
            "id": "T-001",
            "port": 0,
            "status": "review",
        }

        with pytest.raises(ReviewLaunchError) as exc_info:
            launch_review_from_record(task_record)

        err = exc_info.value
        assert "invalid port" in err.stderr.lower()

    def test_launch_review_from_record_invalid_port_negative(self):
        """Test record with negative port."""
        task_record = {
            "id": "T-001",
            "port": -1,
            "status": "review",
        }

        with pytest.raises(ReviewLaunchError) as exc_info:
            launch_review_from_record(task_record)

        err = exc_info.value
        assert "invalid port" in err.stderr.lower()

    def test_launch_review_from_record_non_int_port(self):
        """Test record with non-integer port."""
        task_record = {
            "id": "T-001",
            "port": "30001",
            "status": "review",
        }

        with pytest.raises(ReviewLaunchError) as exc_info:
            launch_review_from_record(task_record)

        err = exc_info.value
        assert "invalid port" in err.stderr.lower()

    def test_launch_review_from_record_empty_id(self):
        """Test record with empty task ID."""
        task_record = {
            "id": "",
            "port": 30001,
            "status": "review",
        }

        with pytest.raises(ReviewLaunchError) as exc_info:
            launch_review_from_record(task_record)

        err = exc_info.value
        assert "id" in err.stderr.lower()

    def test_launch_review_from_record_launch_fails(self):
        """Test when launch_review fails."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "config"
            data_dir = Path(tmpdir) / "data"
            config_dir.mkdir()
            data_dir.mkdir()

            task_record = {
                "id": "T-001",
                "port": 30001,
                "status": "review",
                "opencode_config_dir": str(config_dir),
                "opencode_data_dir": str(data_dir),
            }

            with patch("orchestration.adapters.review.launch_review") as mock_launch:
                launch_error = ReviewLaunchError(
                    task_id="T-001",
                    exit_code=-1,
                    endpoint="http://127.0.0.1:30001",
                    stderr="Connection failed",
                )
                mock_launch.side_effect = launch_error

                with pytest.raises(ReviewLaunchError):
                    launch_review_from_record(task_record)


class TestEnvironmentVariables:
    """Test environment variable setup."""

    def test_env_contains_opencode_host(self):
        """Test OPENCODE_HOST in environment."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0)

            launch_review("T-001", "127.0.0.1", 30001)

            args, kwargs = mock_run.call_args
            env = kwargs["env"]
            assert "OPENCODE_HOST" in env
            assert env["OPENCODE_HOST"] == "http://127.0.0.1:30001"

    def test_env_contains_skip_start(self):
        """Test OPENCODE_SKIP_START in environment."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0)

            launch_review("T-001", "127.0.0.1", 30001, skip_start=True)

            args, kwargs = mock_run.call_args
            env = kwargs["env"]
            assert "OPENCODE_SKIP_START" in env
            assert env["OPENCODE_SKIP_START"] == "true"

    def test_env_preserves_path(self):
        """Test PATH is preserved in environment."""
        with patch("subprocess.run") as mock_run:
            with patch("os.environ", {"PATH": "/usr/bin:/bin"}):
                mock_run.return_value = Mock(returncode=0)

                launch_review("T-001", "127.0.0.1", 30001)

                args, kwargs = mock_run.call_args
                env = kwargs["env"]
                assert "PATH" in env


class TestExceptionHierarchy:
    """Test exception relationships."""

    def test_review_launch_error_is_review_exception(self):
        """Test ReviewLaunchError is ReviewException."""
        err = ReviewLaunchError(
            task_id="T-001",
            exit_code=1,
            endpoint="http://127.0.0.1:8000",
        )
        assert isinstance(err, ReviewException)

    def test_exception_attributes(self):
        """Test ReviewLaunchError has correct attributes."""
        err = ReviewLaunchError(
            task_id="T-001",
            exit_code=1,
            endpoint="http://127.0.0.1:30001",
            stderr="Test error",
        )
        assert err.task_id == "T-001"
        assert err.exit_code == 1
        assert err.endpoint == "http://127.0.0.1:30001"
        assert err.stderr == "Test error"


class TestStrictLocalValidation:
    """Test strict-local OpenCode directory validation."""

    def test_launch_review_from_record_missing_config_dir(self):
        """Test record missing opencode_config_dir."""
        task_record = {
            "id": "T-001",
            "port": 30001,
            "status": "review",
            "opencode_data_dir": "/queue/opencode/T-001/attempt-1/data",
        }

        with pytest.raises(StrictLocalValidationError) as exc_info:
            launch_review_from_record(task_record)

        err = exc_info.value
        assert err.task_id == "T-001"
        assert "opencode_config_dir" in str(err).lower()

    def test_launch_review_from_record_missing_data_dir(self):
        """Test record missing opencode_data_dir."""
        task_record = {
            "id": "T-001",
            "port": 30001,
            "status": "review",
            "opencode_config_dir": "/queue/opencode/T-001/attempt-1/config",
        }

        with pytest.raises(StrictLocalValidationError) as exc_info:
            launch_review_from_record(task_record)

        err = exc_info.value
        assert err.task_id == "T-001"
        assert "opencode_data_dir" in str(err).lower()

    def test_launch_review_from_record_both_dirs_missing(self):
        """Test record with both strict-local dirs missing."""
        task_record = {
            "id": "T-001",
            "port": 30001,
            "status": "review",
        }

        with pytest.raises(StrictLocalValidationError) as exc_info:
            launch_review_from_record(task_record)

        err = exc_info.value
        assert err.task_id == "T-001"

    def test_launch_review_from_record_config_dir_not_exist(self):
        """Test record with config_dir path that doesn't exist."""
        task_record = {
            "id": "T-001",
            "port": 30001,
            "status": "review",
            "opencode_config_dir": "/nonexistent/queue/opencode/T-001/attempt-1/config",
            "opencode_data_dir": "/queue/opencode/T-001/attempt-1/data",
        }

        with pytest.raises(StrictLocalValidationError) as exc_info:
            launch_review_from_record(task_record)

        err = exc_info.value
        assert err.task_id == "T-001"
        assert "does not exist" in str(err).lower()

    def test_launch_review_from_record_data_dir_not_exist(self):
        """Test record with data_dir path that doesn't exist."""
        task_record = {
            "id": "T-001",
            "port": 30001,
            "status": "review",
            "opencode_config_dir": "/queue/opencode/T-001/attempt-1/config",
            "opencode_data_dir": "/nonexistent/queue/opencode/T-001/attempt-1/data",
        }

        with pytest.raises(StrictLocalValidationError) as exc_info:
            launch_review_from_record(task_record)

        err = exc_info.value
        assert err.task_id == "T-001"
        assert "does not exist" in str(err).lower()

    def test_launch_review_with_strict_local_dirs_success(self):
        """Test successful launch with valid strict-local directories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "config"
            data_dir = Path(tmpdir) / "data"
            config_dir.mkdir()
            data_dir.mkdir()

            task_record = {
                "id": "T-001",
                "port": 30001,
                "status": "review",
                "opencode_config_dir": str(config_dir),
                "opencode_data_dir": str(data_dir),
            }

            with patch("orchestration.adapters.review.launch_review") as mock_launch:
                mock_launch.return_value = 0

                exit_code = launch_review_from_record(task_record)

                assert exit_code == 0
                mock_launch.assert_called_once()
                args, kwargs = mock_launch.call_args
                assert kwargs.get("opencode_config_dir") == str(config_dir)
                assert kwargs.get("opencode_data_dir") == str(data_dir)

    def test_launch_review_env_includes_strict_local_dirs(self):
        """Test that env includes strict-local directories when provided."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = f"{tmpdir}/config"
            data_dir = f"{tmpdir}/data"

            with patch("subprocess.run") as mock_run:
                mock_run.return_value = Mock(returncode=0)

                launch_review(
                    "T-001",
                    "127.0.0.1",
                    30001,
                    opencode_config_dir=config_dir,
                    opencode_data_dir=data_dir,
                )

                args, kwargs = mock_run.call_args
                env = kwargs["env"]
                assert env.get("OPENCODE_CONFIG_DIR") == config_dir
                assert env.get("OPENCODE_DATA_DIR") == data_dir

    def test_launch_review_env_without_strict_local_dirs(self):
        """Test that env does not include strict-local dirs when not provided."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0)

            launch_review("T-001", "127.0.0.1", 30001)

            args, kwargs = mock_run.call_args
            env = kwargs["env"]
            assert "OPENCODE_CONFIG_DIR" not in env
            assert "OPENCODE_DATA_DIR" not in env

    def test_strict_local_validation_error_is_review_exception(self):
        """Test StrictLocalValidationError is ReviewException."""
        err = StrictLocalValidationError(
            task_id="T-001",
            message="Test validation error",
        )
        assert isinstance(err, ReviewException)

    def test_strict_local_validation_error_attributes(self):
        """Test StrictLocalValidationError has correct attributes."""
        err = StrictLocalValidationError(
            task_id="T-001",
            message="Missing config directory",
        )
        assert err.task_id == "T-001"
        assert "Missing config directory" in str(err)
