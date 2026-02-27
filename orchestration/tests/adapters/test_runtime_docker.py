"""
Unit tests for Docker runtime and port allocation.
"""

import subprocess
import pytest
import socket
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path

from orchestration.adapters.docker import (
    find_available_port,
    is_port_available,
    reserve_port,
    build_runtime_image,
    inspect_container,
    launch_container,
    stop_container,
    remove_container,
    container_logs,
    ContainerConfig,
    ContainerStatus,
    PortAllocationError,
    ContainerError,
    ContainerStartError,
    ContainerNotFoundError,
    ImageBuildError,
)


class TestPortAllocation:
    """Test port allocation helpers."""

    def test_find_available_port_succeeds(self):
        """Test finding an available port in range."""
        port = find_available_port(start_port=40000, max_port=40100)
        assert 40000 <= port <= 40100
        assert is_port_available(port)

    def test_find_available_port_no_range(self):
        """Test that finding port fails when no range available."""
        with patch("socket.socket") as mock_socket:
            mock_instance = MagicMock()
            mock_socket.return_value = mock_instance
            mock_instance.bind.side_effect = OSError("Address in use")

            with pytest.raises(PortAllocationError):
                find_available_port(start_port=40000, max_port=40010)

    def test_is_port_available_true(self):
        """Test checking available port."""
        # Use a port unlikely to be in use
        port = find_available_port()
        assert is_port_available(port)

    def test_is_port_available_false(self):
        """Test checking unavailable port."""
        with patch("socket.socket") as mock_socket:
            mock_instance = MagicMock()
            mock_socket.return_value = mock_instance
            mock_instance.bind.side_effect = OSError("Address in use")

            result = is_port_available(9999)
            assert result is False

    def test_reserve_port_preferred_available(self):
        """Test reserving preferred port when available."""
        with patch(
            "orchestration.adapters.docker.is_port_available", return_value=True
        ):
            port = reserve_port(preferred_port=40000)
            assert port == 40000

    def test_reserve_port_preferred_unavailable(self):
        """Test reserving port when preferred unavailable."""
        with patch("orchestration.adapters.docker.is_port_available") as mock_check:
            with patch(
                "orchestration.adapters.docker.find_available_port", return_value=40001
            ) as mock_find:
                mock_check.return_value = False
                port = reserve_port(preferred_port=40000)
                assert port == 40001
                mock_find.assert_called_once()


class TestContainerStatus:
    """Test container status inspection."""

    def test_inspect_container_success(self):
        """Test successful container inspection."""
        mock_output = '{"Id": "abc123def456", "Name": "/my-container", "State": {"Status": "running", "Running": true, "ExitCode": 0, "Pid": 12345}}'

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout=mock_output, stderr="")

            status = inspect_container("abc123def456")

            assert status.container_id == "abc123def456"
            assert status.name == "my-container"
            assert status.state == "running"
            assert status.running is True
            assert status.exit_code == 0
            assert status.pid == 12345

    def test_inspect_container_not_found(self):
        """Test inspection fails when container not found."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(
                returncode=1, stdout="", stderr="no such object"
            )

            with pytest.raises(ContainerNotFoundError):
                inspect_container("nonexistent")

    def test_inspect_container_timeout(self):
        """Test inspection timeout."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired("docker", 5)

            with pytest.raises(ContainerError):
                inspect_container("abc123")


class TestContainerConfig:
    """Test container configuration."""

    def test_container_config_defaults(self):
        """Test that ContainerConfig applies defaults."""
        config = ContainerConfig(
            task_id="T-001",
            image="opencode:latest",
            worktree_path="/home/user/worktrees/T-001",
            port=8000,
        )

        assert config.name == "task-T-001"
        assert config.mounts == {
            "/home/user/worktrees/T-001": "/home/user/worktrees/T-001"
        }
        assert config.writable_mount_paths == ["/home/user/worktrees/T-001"]
        assert config.env_vars == {}

    def test_container_config_custom(self):
        """Test ContainerConfig with custom values."""
        config = ContainerConfig(
            task_id="T-001",
            image="opencode:latest",
            worktree_path="/workspace/T-001",
            port=8000,
            name="custom-name",
            env_vars={"KEY": "value"},
        )

        assert config.name == "custom-name"
        assert config.env_vars == {"KEY": "value"}
        assert config.mounts is not None
        assert "/workspace/T-001" in config.mounts

    def test_container_config_always_mounts_worktree(self):
        """Test that worktree is always mounted at path parity even with custom mounts."""
        config = ContainerConfig(
            task_id="T-001",
            image="opencode:latest",
            worktree_path="/home/user/worktrees/T-001",
            port=8000,
            mounts={"/home/user/.opencode": "/opencode"},
        )

        assert config.mounts is not None
        assert (
            config.mounts["/home/user/worktrees/T-001"] == "/home/user/worktrees/T-001"
        )
        assert config.mounts["/home/user/.opencode"] == "/opencode"
        assert config.writable_mount_paths is not None
        assert "/home/user/worktrees/T-001" in config.writable_mount_paths

    def test_container_config_path_parity_mount(self):
        """Test that worktree is mounted at same absolute path for git metadata parity."""
        worktree_path = "/var/workspace/my-task-001"
        config = ContainerConfig(
            task_id="T-001",
            image="opencode:latest",
            worktree_path=worktree_path,
            port=8000,
        )

        # Verify path parity: host path == container path
        assert config.mounts is not None
        assert config.mounts[worktree_path] == worktree_path
        assert config.writable_mount_paths == [worktree_path]


class TestContainerLifecycle:
    """Test container launch/stop/remove operations."""

    def test_launch_container_success(self):
        """Test successful container launch."""
        worktree_path = "/home/user/worktrees/T-001"
        config = ContainerConfig(
            task_id="T-001",
            image="opencode:latest",
            worktree_path=worktree_path,
            port=8000,
        )

        with patch("subprocess.run") as mock_run:
            with patch(
                "orchestration.adapters.docker.inspect_container"
            ) as mock_inspect:
                mock_run.return_value = Mock(
                    returncode=0, stdout="abc123def456\n", stderr=""
                )
                mock_inspect.return_value = Mock(running=True)

                container_id = launch_container(config)

                assert container_id == "abc123def456"
                mock_run.assert_called_once()
                call_args = mock_run.call_args[0][0]
                assert "docker" in call_args
                assert "run" in call_args
                assert "-p" in call_args
                assert "8000:8000" in " ".join(call_args)

    def test_launch_container_failure(self):
        """Test container launch failure."""
        config = ContainerConfig(
            task_id="T-001",
            image="bad-image:latest",
            worktree_path="/home/user/worktrees/T-001",
            port=8000,
        )

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(
                returncode=1, stdout="", stderr="image not found"
            )

            with pytest.raises(ContainerStartError) as exc_info:
                launch_container(config)

            assert exc_info.value.container_id == "task-T-001"
            assert "image not found" in exc_info.value.stderr

    def test_launch_container_mount_modes(self):
        """Non-writable mounts should be read-only in docker args."""
        config = ContainerConfig(
            task_id="T-001",
            image="opencode:latest",
            worktree_path="/home/user/worktrees/T-001",
            port=8000,
            mounts={
                "/home/user/.config/opencode": "/root/.config/opencode",
                "/home/user/.local/share/opencode": "/root/.local/share/opencode",
            },
            writable_mount_paths=["/root/.local/share/opencode"],
        )

        with patch("subprocess.run") as mock_run:
            with patch(
                "orchestration.adapters.docker.inspect_container"
            ) as mock_inspect:
                mock_run.return_value = Mock(
                    returncode=0, stdout="abc123def456\n", stderr=""
                )
                mock_inspect.return_value = Mock(running=True)

                launch_container(config)

                call_args = mock_run.call_args[0][0]
                joined = " ".join(call_args)
                assert (
                    "-v /home/user/.config/opencode:/root/.config/opencode:ro" in joined
                )
                assert (
                    "-v /home/user/.local/share/opencode:/root/.local/share/opencode"
                    in joined
                )
                assert (
                    "/home/user/.local/share/opencode:/root/.local/share/opencode:ro"
                    not in joined
                )

    def test_launch_container_working_dir_path_parity(self):
        """Test that working_dir is set to worktree_path for path parity."""
        worktree_path = "/home/user/worktrees/T-001"
        config = ContainerConfig(
            task_id="T-001",
            image="opencode:latest",
            worktree_path=worktree_path,
            port=8000,
            working_dir=worktree_path,
        )

        with patch("subprocess.run") as mock_run:
            with patch(
                "orchestration.adapters.docker.inspect_container"
            ) as mock_inspect:
                mock_run.return_value = Mock(
                    returncode=0, stdout="abc123def456\n", stderr=""
                )
                mock_inspect.return_value = Mock(running=True)

                launch_container(config)

                call_args = mock_run.call_args[0][0]
                joined = " ".join(call_args)
                # Verify -w flag with worktree path
                assert f"-w {worktree_path}" in joined

    def test_stop_container_success(self):
        """Test successful container stop."""
        with patch("subprocess.run") as mock_run:
            with patch(
                "orchestration.adapters.docker.inspect_container"
            ) as mock_inspect:
                mock_inspect.return_value = Mock(running=True)
                mock_run.return_value = Mock(returncode=0, stdout="abc123\n", stderr="")

                result = stop_container("abc123")

                assert result is True
                mock_run.assert_called_once()
                call_args = mock_run.call_args[0][0]
                assert "docker" in call_args
                assert "stop" in call_args

    def test_stop_container_not_running(self):
        """Test stopping a container that's not running."""
        with patch("orchestration.adapters.docker.inspect_container") as mock_inspect:
            mock_inspect.return_value = Mock(running=False)

            result = stop_container("abc123")

            assert result is False

    def test_stop_container_not_found(self):
        """Test stopping a non-existent container."""
        with patch("orchestration.adapters.docker.inspect_container") as mock_inspect:
            mock_inspect.side_effect = ContainerNotFoundError("not found")

            result = stop_container("nonexistent")

            assert result is False

    def test_remove_container_success(self):
        """Test successful container removal."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout="", stderr="")

            result = remove_container("abc123")

            assert result is True
            mock_run.assert_called_once()
            call_args = mock_run.call_args[0][0]
            assert "docker" in call_args
            assert "rm" in call_args

    def test_remove_container_force(self):
        """Test force removal of container."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout="", stderr="")

            remove_container("abc123", force=True)

            call_args = mock_run.call_args[0][0]
            assert "-f" in call_args

    def test_remove_container_not_found(self):
        """Test removing non-existent container."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(
                returncode=1, stdout="", stderr="no such object"
            )

            result = remove_container("nonexistent")

            assert result is False


class TestContainerLogs:
    """Test container log retrieval."""

    def test_container_logs_success(self):
        """Test successful log retrieval."""
        expected_output = "Container output here\n"

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(
                returncode=0, stdout=expected_output, stderr=""
            )

            stdout, stderr = container_logs("abc123")

            assert stdout == expected_output
            assert stderr == ""

    def test_container_logs_not_found(self):
        """Test log retrieval for non-existent container."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(
                returncode=1, stdout="", stderr="no such object"
            )

            with pytest.raises(ContainerNotFoundError):
                container_logs("nonexistent")


class TestBuildRuntimeImage:
    """Test Docker image build utility."""

    def test_build_runtime_image_success(self):
        """Successful image build returns docker stdout."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(
                returncode=0,
                stdout="Successfully built\n",
                stderr="",
            )

            output = build_runtime_image(
                image="sisifo/opencode:latest",
                dockerfile_path="/repo/orchestration/Dockerfile",
                context_path="/repo",
            )

            assert "Successfully built" in output
            call_args = mock_run.call_args[0][0]
            assert call_args[0:2] == ["docker", "build"]
            assert "--pull" in call_args
            assert "--no-cache" not in call_args

    def test_build_runtime_image_rebuild_uses_no_cache(self):
        """Rebuild mode should append --no-cache."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout="ok", stderr="")

            build_runtime_image(
                image="sisifo/opencode:latest",
                dockerfile_path="/repo/orchestration/Dockerfile",
                context_path="/repo",
                rebuild=True,
            )

            call_args = mock_run.call_args[0][0]
            assert "--no-cache" in call_args

    def test_build_runtime_image_failure(self):
        """Non-zero docker build should raise ImageBuildError."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(
                returncode=1,
                stdout="",
                stderr="build failed",
            )

            with pytest.raises(ImageBuildError) as exc_info:
                build_runtime_image(
                    image="sisifo/opencode:latest",
                    dockerfile_path="/repo/orchestration/Dockerfile",
                    context_path="/repo",
                )

            assert "build failed" in str(exc_info.value)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
