"""
Task processing pipeline stages.

Orchestrates the four main stages of task processing:
1. setup: Read task, create worktree/branch, launch container
2. execute: Run planning (make-plan) and building (execute-plan)
3. success: Persist successful completion and transition to review
4. failure: Generate error report and optionally cleanup
"""

import os
import shutil
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, Tuple

try:
    from orchestration.core.models import TaskRecord
    from orchestration.core.exceptions import TaskProcessingError
    from orchestration.constants import (
        DEFAULT_CONTAINER_OPENCODE_CONFIG_DIR,
        DEFAULT_CONTAINER_OPENCODE_DATA_DIR,
    )
    from orchestration.support.task_files import (
        read_task_body,
        TaskFileError,
    )
    from orchestration.support.paths import (
        get_attempt_dir,
        get_attempt_config_dir,
        get_attempt_data_dir,
    )
    from orchestration.adapters.git import (
        create_worktree,
        remove_worktree,
        GitRuntimeError,
    )
    from orchestration.adapters.docker import (
        reserve_port,
        launch_container,
        cleanup_task_containers,
        ContainerConfig,
        PortAllocationError,
        ContainerError,
    )
    from orchestration.adapters.opencode import (
        run_make_plan,
        run_execute_plan,
        run_plan_sequence,
        validate_endpoint,
        PlanError,
        BuildError,
        OpenCodeException,
    )
    from orchestration.constants import DEFAULT_OPENCODE_HOST
    from orchestration.pipeline.error_reporting import (
        generate_error_report,
        write_error_report,
    )
except ImportError:
    from core.models import TaskRecord
    from core.exceptions import TaskProcessingError
    from constants import (
        DEFAULT_CONTAINER_OPENCODE_CONFIG_DIR,
        DEFAULT_CONTAINER_OPENCODE_DATA_DIR,
    )
    from support.task_files import read_task_body, TaskFileError
    from support.paths import (
        get_attempt_dir,
        get_attempt_config_dir,
        get_attempt_data_dir,
    )
    from adapters.git import (
        create_worktree,
        remove_worktree,
        GitRuntimeError,
    )
    from adapters.docker import (
        reserve_port,
        launch_container,
        cleanup_task_containers,
        ContainerConfig,
        PortAllocationError,
        ContainerError,
    )
    from adapters.opencode import (
        run_make_plan,
        run_execute_plan,
        run_plan_sequence,
        validate_endpoint,
        PlanError,
        BuildError,
        OpenCodeException,
    )
    from constants import DEFAULT_OPENCODE_HOST
    from pipeline.error_reporting import (
        generate_error_report,
        write_error_report,
    )

logger = logging.getLogger(__name__)


# ============================================================================
# Helper Functions
# ============================================================================


def bootstrap_opencode_config_snapshot(
    source_config_dir: str, target_config_dir: str
) -> None:
    """
    Bootstrap OpenCode config snapshot for a task attempt.

    Copies host OpenCode config to attempt-specific config directory
    for strict-local runtime isolation. Creates target directory if missing.

    Args:
        source_config_dir: Host OpenCode config directory (e.g., ~/.config/opencode).
        target_config_dir: Target attempt config directory (e.g., queue/opencode/<task-id>/attempt-<n>/config).

    Raises:
        OSError: If copy operation fails.
    """
    source_path = Path(source_config_dir)
    target_path = Path(target_config_dir)

    # Ensure target parent exists
    target_path.parent.mkdir(parents=True, exist_ok=True)

    # Only copy if source exists
    if source_path.exists() and source_path.is_dir():
        # Remove target if it already exists (e.g., from previous failed attempt)
        if target_path.exists():
            shutil.rmtree(target_path)

        # Copy entire config tree
        shutil.copytree(source_path, target_path, dirs_exist_ok=False)
        logger.info(
            f"Bootstrapped config snapshot: {source_config_dir} -> {target_config_dir}"
        )
    else:
        logger.debug(
            f"Host config directory not found or not accessible: {source_config_dir}; "
            f"creating empty config directory at {target_config_dir}"
        )
        # Create empty config dir for attempt
        target_path.mkdir(parents=True, exist_ok=True)


def bootstrap_opencode_data_snapshot(
    source_data_dir: str, target_data_dir: str
) -> None:
    """
    Bootstrap OpenCode data snapshot for a task attempt.

    Copies minimal auth artifacts from host data directory into attempt-specific
    data directory so provider auth is available under strict-local mounts.

    Args:
        source_data_dir: Host OpenCode data directory (e.g., ~/.local/share/opencode).
        target_data_dir: Target attempt data directory.

    Raises:
        OSError: If copy operation fails.
    """
    source_path = Path(source_data_dir)
    target_path = Path(target_data_dir)

    # Ensure target exists for runtime writes regardless of snapshot state.
    target_path.mkdir(parents=True, exist_ok=True)

    if not source_path.exists() or not source_path.is_dir():
        logger.debug(
            "Host data directory not found or not accessible: "
            f"{source_data_dir}; leaving attempt data directory empty"
        )
        return

    source_auth = source_path / "auth.json"
    target_auth = target_path / "auth.json"
    if source_auth.exists() and source_auth.is_file():
        shutil.copy2(source_auth, target_auth)
        logger.info(f"Bootstrapped auth snapshot: {source_auth} -> {target_auth}")
    else:
        logger.debug(
            f"No auth.json found in host data dir {source_data_dir}; "
            "provider auth snapshot skipped"
        )


def resolve_host_opencode_dirs() -> Tuple[str, str]:
    """Resolve host OpenCode config/data directories and ensure they exist."""
    home = Path.home()

    config_dir_raw = os.environ.get("OPENCODE_CONFIG_DIR", "")
    if config_dir_raw:
        config_dir = Path(config_dir_raw).expanduser()
    else:
        config_dir = home / ".config" / "opencode"

    xdg_data_home = os.environ.get("XDG_DATA_HOME", "")
    if xdg_data_home:
        data_dir = Path(xdg_data_home).expanduser() / "opencode"
    else:
        data_dir = home / ".local" / "share" / "opencode"

    for path in (config_dir, data_dir):
        if path.exists() and not path.is_dir():
            raise OSError(f"Expected directory path but found file: {path}")
        path.mkdir(parents=True, exist_ok=True)

    return str(config_dir.resolve()), str(data_dir.resolve())


# ============================================================================
# Stage Functions
# ============================================================================


def setup_stage(
    record: TaskRecord,
    store,
    docker_image: str,
    dirty_run: bool = False,
    container_cmd: list | None = None,
) -> None:
    """
    Setup stage: read task file, create worktree and branch, launch container.

    Updates record with derived values:
    - branch: derived from task_id
    - worktree_path: deterministic path
    - port: reserved port
    - container: container ID
    - opencode_attempt_dir: per-attempt base directory
    - opencode_config_dir: per-attempt config directory (bootstrapped from host)
    - opencode_data_dir: per-attempt data directory

    Creates per-attempt OpenCode directories under queue/opencode/<task-id>/attempt-<n>/
    and bootstraps config snapshot from host OpenCode config for strict-local isolation.

    Container mounts use attempt-specific directories, not host directories.

    Args:
        record: TaskRecord to setup (status=planning).
        store: QueueStore instance for persistence.
        docker_image: Docker image to use.
        dirty_run: If True, reuse existing worktree and remove stale containers.
        container_cmd: Container command to run (optional).

    Raises:
        TaskProcessingError: On setup failure.
    """
    logger.info(f"[setup] Starting setup for {record.id}")

    try:
        # Read task body (frontmatter optional)
        logger.debug(f"Reading task file: {record.task_file}")
        task_body = read_task_body_from_file(record.task_file)
        logger.debug(f"Task body length: {len(task_body)} chars")

        # Use stored branch if present, otherwise derive from task_id
        from orchestration.core.naming import derive_branch_name

        branch_name = record.branch or derive_branch_name(record.id)
        record.branch = branch_name

        # Require precomputed worktree path from task record
        if not record.worktree_path:
            raise TaskProcessingError(
                stage="setup",
                task_id=record.id,
                message="Missing required worktree_path in task record",
            )

        worktree_path = record.worktree_path
        logger.debug(f"Worktree path: {worktree_path}")

        worktree_path_obj = Path(worktree_path).expanduser().resolve()
        if dirty_run and worktree_path_obj.exists():
            record.worktree_path = str(worktree_path_obj)
            logger.info(
                f"Dirty run enabled: reusing existing worktree {record.worktree_path}"
            )
        else:
            # Create worktree and branch
            logger.info(f"Creating worktree at {worktree_path}")
            created_path = create_worktree(
                record.repo, worktree_path, record.branch, record.base
            )
            record.worktree_path = created_path
            logger.info(f"Worktree created: {created_path}")

        if dirty_run:
            removed = cleanup_task_containers(record.id)
            if removed:
                logger.info(
                    "Dirty run removed "
                    f"{removed} existing container(s) for task {record.id}"
                )

        # Create per-attempt OpenCode directories
        logger.debug(
            f"Setting up per-attempt OpenCode directories for {record.id} attempt {record.attempt}"
        )
        attempt_dir = get_attempt_dir(record.id, record.attempt)
        attempt_config_dir = get_attempt_config_dir(record.id, record.attempt)
        attempt_data_dir = get_attempt_data_dir(record.id, record.attempt)

        # Create config and data directories
        attempt_config_dir.mkdir(parents=True, exist_ok=True)
        attempt_data_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Created attempt directories: {attempt_dir}")

        # Bootstrap config snapshot from host OpenCode config
        host_config_dir, host_data_dir = resolve_host_opencode_dirs()
        logger.debug(
            f"Bootstrapping config from {host_config_dir} to {attempt_config_dir}"
        )
        bootstrap_opencode_config_snapshot(host_config_dir, str(attempt_config_dir))
        logger.debug(
            f"Bootstrapping data auth from {host_data_dir} to {attempt_data_dir}"
        )
        bootstrap_opencode_data_snapshot(host_data_dir, str(attempt_data_dir))

        # Persist strict-local pointers to record
        record.opencode_attempt_dir = str(attempt_dir)
        record.opencode_config_dir = str(attempt_config_dir)
        record.opencode_data_dir = str(attempt_data_dir)
        logger.debug(
            f"Persisted strict-local pointers: "
            f"attempt={record.opencode_attempt_dir}, "
            f"config={record.opencode_config_dir}, "
            f"data={record.opencode_data_dir}"
        )

        # Reserve port for container
        logger.debug("Reserving port for container")
        port = reserve_port()
        record.port = port
        logger.debug(f"Reserved port: {port}")

        # Launch container
        from orchestration.core.naming import derive_container_name

        container_name = derive_container_name(record.id, record.created_at)
        logger.info(f"Launching container {container_name} on port {port}")
        config = ContainerConfig(
            task_id=record.id,
            image=docker_image,
            worktree_path=record.worktree_path,
            port=port,
            name=container_name,
            mounts={
                str(attempt_config_dir): DEFAULT_CONTAINER_OPENCODE_CONFIG_DIR,
                str(attempt_data_dir): DEFAULT_CONTAINER_OPENCODE_DATA_DIR,
            },
            writable_mount_paths=[DEFAULT_CONTAINER_OPENCODE_DATA_DIR],
            working_dir=record.worktree_path,
            cmd=container_cmd,
        )
        container_id = launch_container(config)
        record.container = container_id
        logger.info(f"Container launched: {container_id} ({container_name})")

        # Update status to building (after successful setup)
        record.status = "building"
        record = store.update_record(record.id, record.to_dict())
        logger.info(f"Status transitioned to building for {record.id}")

    except (TaskFileError, GitRuntimeError, OSError) as e:
        raise TaskProcessingError(
            stage="setup",
            task_id=record.id,
            message=str(e),
        )
    except (PortAllocationError, ContainerError) as e:
        raise TaskProcessingError(
            stage="setup",
            task_id=record.id,
            message=str(e),
        )


def execute_stage(
    record: TaskRecord,
    container_host: str = DEFAULT_OPENCODE_HOST,
) -> None:
    """
    Execute stage: run make-plan and execute-plan on container.

    Reads task body and orchestrates planning and building commands
    through the running container.

    Args:
        record: TaskRecord with worktree and container set.
        container_host: Host for container connection.

    Raises:
        TaskProcessingError: On planning or building failure.
    """
    logger.info(f"[execute] Starting execution for {record.id}")

    try:
        # Read task body for planning input
        logger.debug(f"Reading task file for body: {record.task_file}")
        task_body = read_task_body_from_file(record.task_file)

        # Build endpoint URL
        endpoint = validate_endpoint(container_host, record.port)
        logger.debug(f"Validated endpoint: {endpoint}")

        # Run full planning + building sequence
        logger.info(f"[execute] Running plan sequence on {endpoint}")
        result = run_plan_sequence(
            endpoint,
            task_body,
            workdir=record.worktree_path,
        )

        if result["status"] == "plan_failed":
            err = result["error"]
            raise TaskProcessingError(
                stage="planning",
                task_id=record.id,
                message=f"make-plan failed: {err}",
                command="make-plan",
                exit_code=getattr(err, "exit_code", -1),
                stdout=result.get("plan_stdout", ""),
                stderr=result.get("plan_stderr", ""),
            )

        if result["status"] == "build_failed":
            err = result["error"]
            raise TaskProcessingError(
                stage="building",
                task_id=record.id,
                message=f"execute-plan failed: {err}",
                command="execute-plan",
                exit_code=getattr(err, "exit_code", -1),
                stdout=result.get("build_stdout", ""),
                stderr=result.get("build_stderr", ""),
            )

        logger.info(f"[execute] Execution completed for {record.id}")

    except TaskFileError as e:
        raise TaskProcessingError(
            stage="building",
            task_id=record.id,
            message=f"Failed to read task file: {e}",
        )
    except OpenCodeException as e:
        raise TaskProcessingError(
            stage="building",
            task_id=record.id,
            message=str(e),
        )


def success_stage(record: TaskRecord, store) -> TaskRecord:
    """
    Success stage: persist runtime handles and transition to review.

    Updates record:
    - status: review
    - container, port, worktree_path, branch retained for review
    - error_file cleared

    Args:
        record: Completed TaskRecord.
        store: QueueStore instance for persistence.

    Returns:
        Updated TaskRecord persisted with review status.

    Raises:
        TaskProcessingError: On persistence failure.
    """
    logger.info(f"[success] Transitioning {record.id} to review")

    try:
        updates = {
            "status": "review",
            "error_file": "",
            "updated_at": datetime.utcnow().isoformat(),
        }
        record = store.update_record(record.id, updates)
        logger.info(f"Task {record.id} transitioned to review")
        return record
    except Exception as e:
        raise TaskProcessingError(
            stage="success",
            task_id=record.id,
            message=f"Failed to persist success state: {e}",
        )


def failure_stage(
    record: TaskRecord,
    error: TaskProcessingError,
    store,
    cleanup_on_fail: bool = False,
) -> TaskRecord:
    """
    Failure stage: generate error report and optionally clean up resources.

    Generates error markdown, persists it, and transitions task to failed.
    Cleans up container/worktree only when cleanup_on_fail is enabled.

    Args:
        record: TaskRecord that failed.
        error: TaskProcessingError with failure details.
        store: QueueStore instance for persistence.
        cleanup_on_fail: If True, remove container and worktree.

    Returns:
        Updated TaskRecord with status=failed and error_file set.
    """
    logger.info(f"[failure] Processing failure for {record.id}")

    # Generate error report
    error_report = generate_error_report(
        record,
        stage=error.stage,
        command=error.command,
        exit_code=error.exit_code,
        stdout=error.stdout,
        stderr=error.stderr,
    )

    # Write error report to file
    try:
        error_path = write_error_report(error_report, record.id)
        error_file = str(error_path)
        logger.info(f"Error report written to {error_file}")
    except OSError as e:
        logger.error(f"Failed to write error report: {e}")
        error_file = ""

    if cleanup_on_fail:
        # Clean up all containers related to this task ID.
        # This handles both known launched containers and stale name conflicts.
        try:
            removed = cleanup_task_containers(record.id)
            if removed:
                logger.info(f"Removed {removed} container(s) for task {record.id}")
        except ContainerError as e:
            logger.warning(f"Failed to cleanup task containers: {e}")

        # Clean up worktree
        if record.worktree_path:
            try:
                logger.info(f"Removing worktree {record.worktree_path}")
                remove_worktree(record.repo, record.worktree_path, force=True)
                logger.info(f"Worktree {record.worktree_path} removed")
            except GitRuntimeError as e:
                logger.warning(f"Failed to remove worktree: {e}")
    else:
        logger.info(
            f"Failure cleanup disabled; preserving runtime artifacts for {record.id}"
        )

    # Persist failure state
    try:
        updates = {
            "status": "failed",
            "error_file": error_file,
            "updated_at": datetime.utcnow().isoformat(),
        }
        record = store.update_record(record.id, updates)
        logger.info(f"Task {record.id} transitioned to failed")
    except Exception as e:
        logger.error(f"Failed to persist failure state: {e}")

    return record


def read_task_body_from_file(task_file: str) -> str:
    """Read task markdown body from stored task_file path.

    Uses support.task_files.read_task_body for canonical handling.
    """
    task_path = Path(task_file).expanduser()
    if not task_path.is_absolute():
        repo_root = Path(__file__).resolve().parent.parent.parent
        task_path = repo_root / task_path

    return read_task_body(str(task_path))
