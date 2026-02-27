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

try:
    from orchestration.support.env import build_review_env
except ImportError:
    try:
        from ..support.env import build_review_env
    except ImportError:
        from support.env import build_review_env

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


class StrictLocalValidationError(ReviewException):
    """Raised when strict-local attempt dirs are missing or invalid."""

    def __init__(self, task_id: str, message: str):
        self.task_id = task_id
        msg = f"Strict-local validation failed for task {task_id}: {message}"
        super().__init__(msg)


# ============================================================================
# Review launch
# ============================================================================


def launch_review(
    task_id: str,
    host: str,
    port: int,
    skip_start: bool = True,
    worktree_path: Optional[str] = None,
    opencode_config_dir: Optional[str] = None,
    opencode_data_dir: Optional[str] = None,
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
        worktree_path: Optional host worktree path to launch OpenChamber from.
        opencode_config_dir: Path to OpenCode config directory (strict-local).
        opencode_data_dir: Path to OpenCode data directory (strict-local).

    Returns:
        Exit code from openchamber process (0 = success, non-zero = failure).

    Raises:
        ReviewLaunchError: If launch fails unexpectedly.

    Example:
        # Launch OpenChamber for task review with strict-local dirs
        exit_code = launch_review(
            "T-001",
            "127.0.0.1",
            30001,
            opencode_config_dir="/queue/opencode/T-001/attempt-1/config",
            opencode_data_dir="/queue/opencode/T-001/attempt-1/data",
        )
        if exit_code == 0:
            print("Review completed")
    """
    endpoint = f"http://{host}:{port}"

    logger.info(f"Launching OpenChamber for task {task_id} on {endpoint}")

    try:
        # Build environment
        env = build_review_env(
            f"http://{host}:{port}",
            skip_start=skip_start,
            opencode_config_dir=opencode_config_dir,
            opencode_data_dir=opencode_data_dir,
        )

        review_cwd: Optional[str] = None
        if worktree_path:
            candidate = Path(worktree_path).expanduser().resolve()
            if candidate.exists() and candidate.is_dir():
                review_cwd = str(candidate)
            else:
                logger.warning(
                    "Ignoring invalid review worktree path for task "
                    f"{task_id}: {worktree_path}"
                )

        # Launch openchamber
        result = subprocess.run(
            ["openchamber"],
            env=env,
            cwd=review_cwd,
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

    Enforces strict-local validation: both opencode_config_dir and
    opencode_data_dir must be present in record and exist on disk.

    Args:
        task_record: Task dictionary from queue store with keys:
            - 'id': Task ID (required)
            - 'port': Port number (required, must be > 0)
            - 'opencode_config_dir': Config directory path (required, must exist)
            - 'opencode_data_dir': Data directory path (required, must exist)
            - 'worktree_path': Optional worktree path for launch cwd
            - Additional fields ignored

    Returns:
        Exit code from openchamber process.

    Raises:
        ReviewLaunchError: If task_record invalid or launch fails.
        StrictLocalValidationError: If strict-local dirs missing or invalid.

    Example:
        # From queue_store.read_record(task_id)
        record = {
            "id": "T-001",
            "port": 30001,
            "status": "review",
            "opencode_config_dir": "/queue/opencode/T-001/attempt-1/config",
            "opencode_data_dir": "/queue/opencode/T-001/attempt-1/data",
            ...
        }
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

    # Validate strict-local directories
    config_dir_raw = task_record.get("opencode_config_dir", "")
    data_dir_raw = task_record.get("opencode_data_dir", "")
    config_dir = config_dir_raw if isinstance(config_dir_raw, str) else ""
    data_dir = data_dir_raw if isinstance(data_dir_raw, str) else ""

    if not config_dir:
        raise StrictLocalValidationError(
            task_id=task_id,
            message="opencode_config_dir is missing. "
            "Task may be a legacy task or missing proper execution. "
            f"Try: taskq retry --id {task_id} && taskq run",
        )

    if not data_dir:
        raise StrictLocalValidationError(
            task_id=task_id,
            message="opencode_data_dir is missing. "
            "Task may be a legacy task or missing proper execution. "
            f"Try: taskq retry --id {task_id} && taskq run",
        )

    config_path = Path(config_dir).expanduser().resolve()
    if not config_path.exists():
        raise StrictLocalValidationError(
            task_id=task_id,
            message=f"opencode_config_dir does not exist: {config_dir}",
        )

    data_path = Path(data_dir).expanduser().resolve()
    if not data_path.exists():
        raise StrictLocalValidationError(
            task_id=task_id,
            message=f"opencode_data_dir does not exist: {data_dir}",
        )

    worktree_path_raw = task_record.get("worktree_path", "")
    worktree_path = worktree_path_raw if isinstance(worktree_path_raw, str) else ""

    # Always use localhost for container-hosted OpenCode server
    host = "127.0.0.1"

    logger.info(f"Launching review from task record: {task_id}")

    return launch_review(
        task_id,
        host,
        port,
        skip_start=True,
        worktree_path=worktree_path or None,
        opencode_config_dir=config_dir,
        opencode_data_dir=data_dir,
    )
