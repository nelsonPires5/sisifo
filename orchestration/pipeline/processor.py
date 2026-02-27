"""
Main task processor for orchestrating the complete task execution pipeline.

Provides TaskProcessor class that coordinates setup, execution, success and failure stages
through the complete lifecycle of a task from claim through completion or failure.
"""

import logging
from typing import Optional, Tuple

try:
    from orchestration.store import QueueStore
    from orchestration.core.models import TaskRecord
    from orchestration.core.exceptions import TaskProcessingError
    from orchestration.core.naming import (
        derive_branch_name,
        derive_container_name,
    )
    from orchestration.constants import (
        DEFAULT_DOCKER_IMAGE,
        DEFAULT_OPENCODE_SERVER_CMD,
    )
    from orchestration.pipeline.stages import (
        setup_stage,
        execute_stage,
        success_stage,
        failure_stage,
        resolve_host_opencode_dirs,
    )
except ImportError:
    from store import QueueStore
    from core.models import TaskRecord
    from core.exceptions import TaskProcessingError
    from core.naming import (
        derive_branch_name,
        derive_container_name,
    )
    from constants import (
        DEFAULT_DOCKER_IMAGE,
        DEFAULT_OPENCODE_SERVER_CMD,
    )
    from pipeline.stages import (
        setup_stage,
        execute_stage,
        success_stage,
        failure_stage,
        resolve_host_opencode_dirs,
    )


logger = logging.getLogger(__name__)


class TaskProcessor:
    """
    Processes a claimed task record through the full execution pipeline.

    Orchestrates:
    1. Reading task metadata from canonical file
    2. Creating git worktree and branch
    3. Reserving port and launching docker container
    4. Running make-plan (planning stage)
    5. Running execute-plan (building stage)
    6. Persisting success state or error report on failure

    Attributes:
        store: QueueStore instance for persistence.
        session_id: Unique session identifier for this worker.
        docker_image: Docker image to use.
        container_cmd: OpenCode container command used to start headless server.
        container_host: Host for container mapping (default: 127.0.0.1).
        cleanup_on_fail: Remove container/worktree on failure when True.
        dirty_run: Reuse existing worktree and clear stale task containers before setup.
    """

    def __init__(
        self,
        store: QueueStore,
        session_id: str,
        docker_image: str = DEFAULT_DOCKER_IMAGE,
        container_cmd: Optional[list[str]] = None,
        container_host: str = "127.0.0.1",
        cleanup_on_fail: bool = False,
        dirty_run: bool = False,
    ):
        """
        Initialize task processor.

        Args:
            store: QueueStore instance.
            session_id: Unique session identifier.
            docker_image: Docker image name.
            container_cmd: Command args to run inside container.
            container_host: Host for container port mapping (default: 127.0.0.1).
            cleanup_on_fail: If True, remove worktree/container on task failure.
            dirty_run: If True, reuse existing worktree and remove stale task containers before launch.
        """
        self.store = store
        self.session_id = session_id
        self.docker_image = docker_image
        self.container_cmd = container_cmd or list(DEFAULT_OPENCODE_SERVER_CMD)
        self.container_host = container_host
        self.cleanup_on_fail = cleanup_on_fail
        self.dirty_run = dirty_run

        logger.info(f"TaskProcessor initialized with session {session_id}")

    def process_task(self, record: TaskRecord) -> TaskRecord:
        """
        Process a claimed task record through full pipeline.

        Transitions task through stages:
        - planning: read task, setup worktree
        - building: run make-plan, then execute-plan
        - review: on success, persist runtime handles
        - failed: on error, generate error report

        Args:
            record: Claimed TaskRecord (status should be "planning").

        Returns:
            Updated TaskRecord after processing.

        Raises:
            TaskProcessingError: On pipeline failure at any stage.
        """
        logger.info(f"Starting task processing for {record.id}")

        try:
            # Stage 1: Read task and setup git/docker
            setup_stage(
                record,
                self.store,
                self.docker_image,
                dirty_run=self.dirty_run,
                container_cmd=self.container_cmd,
            )

            # Stage 2: Run planning and building
            execute_stage(
                record,
                container_host=self.container_host,
            )

            # Stage 3: Success - transition to review
            record = success_stage(record, self.store)

            logger.info(f"Task {record.id} completed successfully")
            return record

        except TaskProcessingError as e:
            logger.error(f"Task {record.id} processing failed: {e}")
            return failure_stage(
                record,
                e,
                self.store,
                cleanup_on_fail=self.cleanup_on_fail,
            )

    # ========================================================================
    # Static helper methods (for backward compatibility with tests)
    # ========================================================================

    @staticmethod
    def _derive_branch_name(task_id: str) -> str:
        """
        Derive branch name from task ID.

        Delegates to core.naming.derive_branch_name.

        Args:
            task_id: Task identifier (e.g., "T-001").

        Returns:
            Valid git branch name.
        """
        return derive_branch_name(task_id)

    @staticmethod
    def _derive_container_name(record: TaskRecord) -> str:
        """
        Derive deterministic container name with task ID and created_at.

        Delegates to core.naming.derive_container_name.
        """
        return derive_container_name(record.id, record.created_at)

    @staticmethod
    def _resolve_host_opencode_dirs() -> Tuple[str, str]:
        """Resolve host OpenCode config/data directories and ensure they exist."""
        return resolve_host_opencode_dirs()
