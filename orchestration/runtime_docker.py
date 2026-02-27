"""
Docker container lifecycle and port allocation utilities.

Provides collision-safe port reservation and container launch/stop wrappers.
Designed for worker integration - API accepts task_id, worktree_path, port, image.
Surfaces stdout/stderr and failures as structured exceptions.
"""

import json
import socket
import subprocess
import time
import logging
from typing import Optional, Tuple, Dict, Any, List
from pathlib import Path
from dataclasses import dataclass
from contextlib import contextmanager


logger = logging.getLogger(__name__)


# ============================================================================
# Exceptions
# ============================================================================


class DockerException(Exception):
    """Base exception for Docker-related errors."""

    pass


class PortAllocationError(DockerException):
    """Raised when port allocation fails."""

    pass


class ContainerError(DockerException):
    """Raised when container operations fail."""

    pass


class ContainerStartError(ContainerError):
    """Raised when container fails to start."""

    def __init__(self, container_id: str, exit_code: int, stdout: str, stderr: str):
        self.container_id = container_id
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr
        msg = f"Container {container_id} failed to start (exit code {exit_code})"
        if stderr:
            msg += f"\nStderr: {stderr[:500]}"
        super().__init__(msg)


class ContainerNotFoundError(ContainerError):
    """Raised when a container cannot be found."""

    pass


class InspectError(ContainerError):
    """Raised when container inspection fails."""

    pass


# ============================================================================
# Port allocation
# ============================================================================


def find_available_port(start_port: int = 30000, max_port: int = 65535) -> int:
    """
    Find an available localhost port in the given range.

    Checks for both TCP listen availability and no collision with known reserved ports.
    Uses SO_REUSEADDR to match behavior of actual binding.

    Args:
        start_port: Starting port to check (default 30000)
        max_port: Maximum port to try (default 65535)

    Returns:
        An available port number.

    Raises:
        PortAllocationError: If no available port can be found.
    """
    for port in range(start_port, max_port + 1):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("127.0.0.1", port))
            sock.close()
            logger.debug(f"Port {port} is available")
            return port
        except OSError:
            continue

    raise PortAllocationError(
        f"No available port found in range {start_port}-{max_port}"
    )


def is_port_available(port: int) -> bool:
    """
    Check if a specific port is available for binding.

    Args:
        port: Port number to check.

    Returns:
        True if port is available, False otherwise.
    """
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", port))
        sock.close()
        return True
    except OSError:
        return False


def reserve_port(preferred_port: Optional[int] = None) -> int:
    """
    Reserve an available port, optionally preferring a specific one.

    If preferred_port is provided and available, returns it.
    Otherwise, finds the next available port starting from 30000.

    Args:
        preferred_port: Port to prefer, or None to auto-select.

    Returns:
        The reserved port number.

    Raises:
        PortAllocationError: If no port can be reserved.
    """
    if preferred_port is not None:
        if is_port_available(preferred_port):
            logger.debug(f"Preferred port {preferred_port} is available")
            return preferred_port
        logger.warning(
            f"Preferred port {preferred_port} is not available, finding alternative"
        )

    return find_available_port()


# ============================================================================
# Container status
# ============================================================================


@dataclass
class ContainerStatus:
    """Represents the status of a Docker container."""

    container_id: str
    name: str
    state: str  # e.g., "running", "exited", "created"
    exit_code: int
    pid: int
    running: bool


def inspect_container(container_id: str) -> ContainerStatus:
    """
    Inspect a Docker container and return its status.

    Args:
        container_id: Container ID or name.

    Returns:
        ContainerStatus with current state.

    Raises:
        ContainerNotFoundError: If container does not exist.
        InspectError: If inspection fails.
    """
    try:
        result = subprocess.run(
            ["docker", "inspect", "--format", "{{json .}}", container_id],
            capture_output=True,
            text=True,
            timeout=5,
        )

        if result.returncode != 0:
            if "no such object" in result.stderr.lower():
                raise ContainerNotFoundError(f"Container {container_id} not found")
            raise InspectError(f"Failed to inspect container: {result.stderr}")

        data = json.loads(result.stdout)
        info = data[0] if isinstance(data, list) else data

        return ContainerStatus(
            container_id=info["Id"][:12],
            name=info["Name"].lstrip("/"),
            state=info["State"]["Status"],
            exit_code=info["State"].get("ExitCode", -1),
            pid=info["State"].get("Pid", 0),
            running=info["State"]["Running"],
        )

    except json.JSONDecodeError as e:
        raise InspectError(f"Failed to parse inspect output: {e}")
    except subprocess.TimeoutExpired:
        raise InspectError(f"Inspect timeout for container {container_id}")
    except ContainerNotFoundError:
        raise
    except Exception as e:
        raise InspectError(f"Unexpected error inspecting container: {e}")


# ============================================================================
# Container lifecycle
# ============================================================================


@dataclass
class ContainerConfig:
    """Configuration for launching a container."""

    task_id: str
    image: str
    worktree_path: str
    port: int
    name: str = ""
    mounts: Optional[Dict[str, str]] = None  # {host_path: container_path}
    writable_mount_paths: Optional[List[str]] = None  # container paths mounted rw
    env_vars: Optional[Dict[str, str]] = None  # {KEY: VALUE}
    working_dir: Optional[str] = None
    entrypoint: Optional[str] = None
    cmd: Optional[List[str]] = None

    def __post_init__(self):
        """Validate and normalize config."""
        if not self.name:
            self.name = f"task-{self.task_id}"
        if self.mounts is None:
            self.mounts = {}
        if self.writable_mount_paths is None:
            self.writable_mount_paths = []
        if self.env_vars is None:
            self.env_vars = {}
        # Always mount worktree as writable code area at path parity
        if self.worktree_path:
            self.mounts[self.worktree_path] = self.worktree_path
        if self.worktree_path not in self.writable_mount_paths:
            self.writable_mount_paths.append(self.worktree_path)


def launch_container(config: ContainerConfig, wait_ready: bool = True) -> str:
    """
    Launch a Docker container with the given configuration.

    Mounts only the task worktree as writable. Container name includes task_id
    for easy cleanup and tracking.

    Args:
        config: ContainerConfig with launch parameters.
        wait_ready: If True, wait briefly for container to stabilize (default True).

    Returns:
        The container ID (short form).

    Raises:
        ContainerStartError: If the container fails to start or health check fails.
        ContainerError: For other Docker API errors.
    """
    try:
        # Build docker run command
        cmd = ["docker", "run", "-d"]

        # Name and port mapping
        cmd.extend(["--name", config.name])
        cmd.extend(["-p", f"127.0.0.1:{config.port}:8000"])

        # Mounts (read-only except configured writable targets)
        writable_mount_paths = set(config.writable_mount_paths or [])
        for host_path, container_path in (config.mounts or {}).items():
            if container_path in writable_mount_paths:
                cmd.extend(["-v", f"{host_path}:{container_path}"])
            else:
                cmd.extend(["-v", f"{host_path}:{container_path}:ro"])

        # Environment variables
        for key, value in (config.env_vars or {}).items():
            cmd.extend(["-e", f"{key}={value}"])

        # Working directory
        if config.working_dir:
            cmd.extend(["-w", config.working_dir])

        # Entrypoint and command
        if config.entrypoint:
            cmd.extend(["--entrypoint", config.entrypoint])

        # Image and optional command
        cmd.append(config.image)
        if config.cmd:
            cmd.extend(config.cmd)

        logger.debug(f"Launching container with: {' '.join(cmd)}")

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            raise ContainerStartError(
                container_id=config.name,
                exit_code=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
            )

        container_id = result.stdout.strip()[:12]
        logger.info(
            f"Container {container_id} ({config.name}) launched for task {config.task_id}"
        )

        # Wait for container to stabilize if requested
        if wait_ready:
            time.sleep(0.5)
            try:
                status = inspect_container(container_id)
                if not status.running:
                    raise ContainerStartError(
                        container_id=container_id,
                        exit_code=status.exit_code,
                        stdout="",
                        stderr=f"Container exited immediately (state: {status.state})",
                    )
            except ContainerNotFoundError:
                raise ContainerStartError(
                    container_id=container_id,
                    exit_code=-1,
                    stdout="",
                    stderr="Container not found after launch",
                )

        return container_id

    except ContainerStartError:
        raise
    except subprocess.TimeoutExpired:
        raise ContainerError(f"Container launch timeout for {config.task_id}")
    except Exception as e:
        raise ContainerError(f"Failed to launch container for {config.task_id}: {e}")


def stop_container(container_id: str, timeout: int = 10) -> bool:
    """
    Stop a running container gracefully.

    Args:
        container_id: Container ID or name.
        timeout: Grace period in seconds before force-kill (default 10).

    Returns:
        True if container was stopped, False if already stopped/not found.

    Raises:
        ContainerError: For unexpected Docker API errors.
    """
    try:
        # Check if container exists and is running
        try:
            status = inspect_container(container_id)
            if not status.running:
                logger.debug(f"Container {container_id} is not running")
                return False
        except ContainerNotFoundError:
            logger.debug(f"Container {container_id} not found")
            return False

        # Stop the container
        result = subprocess.run(
            ["docker", "stop", "-t", str(timeout), container_id],
            capture_output=True,
            text=True,
            timeout=timeout + 5,
        )

        if result.returncode != 0:
            if "no such object" in result.stderr.lower():
                return False
            raise ContainerError(
                f"Failed to stop container {container_id}: {result.stderr}"
            )

        logger.info(f"Container {container_id} stopped")
        return True

    except subprocess.TimeoutExpired:
        raise ContainerError(f"Timeout stopping container {container_id}")
    except ContainerError:
        raise
    except Exception as e:
        raise ContainerError(f"Unexpected error stopping container: {e}")


def remove_container(container_id: str, force: bool = False) -> bool:
    """
    Remove a Docker container.

    Args:
        container_id: Container ID or name.
        force: If True, force removal even if running (default False).

    Returns:
        True if container was removed, False if not found.

    Raises:
        ContainerError: For unexpected Docker API errors.
    """
    try:
        cmd = ["docker", "rm"]
        if force:
            cmd.append("-f")
        cmd.append(container_id)

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode != 0:
            if "no such object" in result.stderr.lower():
                logger.debug(f"Container {container_id} not found")
                return False
            raise ContainerError(
                f"Failed to remove container {container_id}: {result.stderr}"
            )

        logger.info(f"Container {container_id} removed")
        return True

    except subprocess.TimeoutExpired:
        raise ContainerError(f"Timeout removing container {container_id}")
    except ContainerError:
        raise
    except Exception as e:
        raise ContainerError(f"Unexpected error removing container: {e}")


def container_logs(container_id: str, tail: int = 100) -> Tuple[str, str]:
    """
    Retrieve stdout and stderr from a container.

    Args:
        container_id: Container ID or name.
        tail: Number of lines to retrieve from end (default 100).

    Returns:
        Tuple of (stdout, stderr). Docker merges both to stdout, but format indicates stderr.

    Raises:
        ContainerError: If log retrieval fails.
    """
    try:
        result = subprocess.run(
            ["docker", "logs", "--tail", str(tail), container_id],
            capture_output=True,
            text=True,
            timeout=5,
        )

        if result.returncode != 0:
            if "no such object" in result.stderr.lower():
                raise ContainerNotFoundError(f"Container {container_id} not found")
            raise ContainerError(f"Failed to get logs: {result.stderr}")

        # Docker logs combines stdout and stderr; we return as stdout
        return result.stdout, result.stderr

    except subprocess.TimeoutExpired:
        raise ContainerError(f"Timeout retrieving logs for {container_id}")
    except ContainerNotFoundError:
        raise
    except Exception as e:
        raise ContainerError(f"Failed to retrieve logs: {e}")


@contextmanager
def managed_container(config: ContainerConfig, remove_on_exit: bool = False):
    """
    Context manager for container lifecycle.

    Launches container on entry, stops and optionally removes on exit.

    Args:
        config: ContainerConfig with launch parameters.
        remove_on_exit: If True, remove container instead of just stopping (default False).

    Yields:
        Container ID.

    Example:
        with managed_container(config, remove_on_exit=True) as container_id:
            # Use container_id
            pass
    """
    container_id = None
    try:
        container_id = launch_container(config)
        yield container_id
    except Exception:
        raise
    finally:
        if container_id:
            try:
                if remove_on_exit:
                    remove_container(container_id, force=True)
                else:
                    stop_container(container_id)
            except ContainerError as e:
                logger.warning(f"Error during container cleanup: {e}")


# ============================================================================
# Utility functions
# ============================================================================


def wait_for_container_ready(
    container_id: str,
    max_wait: int = 30,
    check_interval: float = 0.5,
) -> bool:
    """
    Wait for a container to enter healthy running state.

    Polls container status until running or timeout.

    Args:
        container_id: Container ID or name.
        max_wait: Maximum seconds to wait (default 30).
        check_interval: Interval between checks in seconds (default 0.5).

    Returns:
        True if container is running, False if timeout.

    Raises:
        ContainerError: If inspection fails unexpectedly.
    """
    elapsed = 0
    while elapsed < max_wait:
        try:
            status = inspect_container(container_id)
            if status.running:
                logger.debug(f"Container {container_id} is ready")
                return True
        except ContainerNotFoundError:
            return False

        time.sleep(check_interval)
        elapsed += check_interval

    logger.warning(f"Container {container_id} not ready after {max_wait}s")
    return False


def cleanup_task_containers(task_id: str) -> int:
    """
    Remove all containers associated with a task.

    Useful for cleanup operations. Looks for containers named task-{task_id}*.

    Args:
        task_id: Task ID to clean up containers for.

    Returns:
        Number of containers removed.

    Raises:
        ContainerError: If cleanup fails unexpectedly.
    """
    try:
        # List containers for this task
        result = subprocess.run(
            [
                "docker",
                "ps",
                "-a",
                "--filter",
                f"name=task-{task_id}",
                "--format",
                "{{.ID}}",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )

        if result.returncode != 0:
            raise ContainerError(f"Failed to list containers: {result.stderr}")

        container_ids = (
            result.stdout.strip().split("\n") if result.stdout.strip() else []
        )
        removed_count = 0

        for cid in container_ids:
            if cid:
                try:
                    if remove_container(cid, force=True):
                        removed_count += 1
                except ContainerError as e:
                    logger.warning(f"Failed to remove container {cid}: {e}")

        return removed_count

    except subprocess.TimeoutExpired:
        raise ContainerError("Timeout listing containers")
    except Exception as e:
        raise ContainerError(f"Unexpected error during cleanup: {e}")
