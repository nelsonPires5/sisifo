"""OpenChamber review launcher for queued task review.

Provides helpers to launch OpenChamber attached to a task's OpenCode container
endpoint, using stored port and session metadata from queue task record.

Designed for operator UX via `taskq review --id` - simple endpoint + environment
setup with no task input (uses container state).
"""

import subprocess
import logging
from typing import Optional, Dict, Any
from pathlib import Path


logger = logging.getLogger(__name__)


# ============================================================================
# Exceptions
# ============================================================================


class ReviewException(Exception):
    """Base exception for review launch errors."""

    pass


class ReviewLaunchError(ReviewException):
    """Raised when OpenChamber launch fails."""

    def __init__(self, task_id: str, exit_code: int, endpoint: str, stderr: str = ""):
        self.task_id = task_id
        self.exit_code = exit_code
        self.endpoint = endpoint
        self.stderr = stderr
        msg = f"OpenChamber launch failed for task {task_id} on {endpoint}"
        if exit_code != -1:
            msg += f" (exit code {exit_code})"
        if stderr:
            msg += f"\nError: {stderr[:200]}"
        super().__init__(msg)


# ============================================================================
# Review launch
# ============================================================================


def launch_review(
    task_id: str,
    host: str,
    port: int,
    skip_start: bool = True,
) -> int:
    """
    Launch OpenChamber attached to a task's OpenCode container endpoint.

    Runs: `OPENCODE_HOST=http://<host>:<port> OPENCODE_SKIP_START=true openchamber`

    Useful for operator reviewing task execution state. OpenChamber will connect
    to the container's OpenCode server without restarting it.

    Args:
        task_id: Task ID (for logging/error reporting).
        host: Hostname or IP of OpenCode server (e.g., "127.0.0.1").
        port: Port of OpenCode server (e.g., 30001).
        skip_start: If True, skip starting server (default True, assumes already running).

    Returns:
        Exit code from openchamber process (0 = success, non-zero = failure).

    Raises:
        ReviewLaunchError: If launch fails unexpectedly.

    Example:
        # Launch OpenChamber for task review
        exit_code = launch_review("T-001", "127.0.0.1", 30001)
        if exit_code == 0:
            print("Review completed")
    """
    endpoint = f"http://{host}:{port}"

    logger.info(f"Launching OpenChamber for task {task_id} on {endpoint}")

    try:
        # Build environment
        env = __build_env(endpoint, skip_start)

        # Launch openchamber
        result = subprocess.run(
            ["openchamber"],
            env=env,
            timeout=3600,  # 1 hour max (interactive session)
        )

        if result.returncode != 0:
            logger.warning(
                f"OpenChamber exited with code {result.returncode} for task {task_id}"
            )

        return result.returncode

    except subprocess.TimeoutExpired:
        logger.error(f"OpenChamber timeout for task {task_id}")
        raise ReviewLaunchError(
            task_id=task_id,
            exit_code=-1,
            endpoint=endpoint,
            stderr="Process timeout (1 hour)",
        )
    except FileNotFoundError:
        logger.error("openchamber command not found")
        raise ReviewLaunchError(
            task_id=task_id,
            exit_code=-1,
            endpoint=endpoint,
            stderr="openchamber command not found in PATH",
        )
    except Exception as e:
        logger.error(f"Unexpected error launching OpenChamber: {e}")
        raise ReviewLaunchError(
            task_id=task_id,
            exit_code=-1,
            endpoint=endpoint,
            stderr=str(e),
        )


def launch_review_from_record(task_record: Dict[str, Any]) -> int:
    """
    Launch OpenChamber using port/endpoint from task queue record.

    Extracts host:port from stored `port` field and derives endpoint URL.
    Task record must have been transitioned to `review` status with port set.

    Args:
        task_record: Task dictionary from queue store with keys:
            - 'id': Task ID (required)
            - 'port': Port number (required, must be > 0)
            - Additional fields ignored

    Returns:
        Exit code from openchamber process.

    Raises:
        ReviewLaunchError: If task_record invalid or launch fails.

    Example:
        # From queue_store.read_record(task_id)
        record = {"id": "T-001", "port": 30001, "status": "review", ...}
        exit_code = launch_review_from_record(record)
    """
    task_id_raw = task_record.get("id")
    task_id = task_id_raw if isinstance(task_id_raw, str) else ""
    port = task_record.get("port", 0)

    if not task_id:
        raise ReviewLaunchError(
            task_id="unknown",
            exit_code=-1,
            endpoint="",
            stderr="Task record missing 'id' field",
        )

    if not isinstance(port, int) or port <= 0:
        raise ReviewLaunchError(
            task_id=task_id,
            exit_code=-1,
            endpoint="",
            stderr=f"Task record has invalid port: {port}",
        )

    # Always use localhost for container-hosted OpenCode server
    host = "127.0.0.1"

    logger.info(f"Launching review from task record: {task_id}")

    return launch_review(task_id, host, port, skip_start=True)


# ============================================================================
# Utilities
# ============================================================================


def __build_env(endpoint: str, skip_start: bool = True) -> Dict[str, str]:
    """
    Build environment variables for openchamber subprocess.

    Args:
        endpoint: OpenCode server endpoint URL (e.g., "http://127.0.0.1:8000").
        skip_start: If True, set OPENCODE_SKIP_START=true.

    Returns:
        Dictionary of environment variables suitable for subprocess.run().
    """
    import os

    # Start with safe base environment
    env = __get_safe_env()

    # Add OpenCode-specific variables
    env["OPENCODE_HOST"] = endpoint
    if skip_start:
        env["OPENCODE_SKIP_START"] = "true"

    return env


def __get_safe_env() -> Dict[str, str]:
    """
    Get safe environment variables for subprocess.

    Preserves essential vars like PATH while filtering out sensitive ones.

    Returns:
        Dictionary of safe environment variables.
    """
    import os

    safe_keys = [
        "PATH",
        "HOME",
        "USER",
        "SHELL",
        "TERM",
        "LANG",
        "LC_ALL",
        "PWD",
        "TMPDIR",
        "DISPLAY",  # For potential X11 forwarding
        "XAUTHORITY",
    ]
    return {k: os.environ.get(k, "") for k in safe_keys if k in os.environ}
