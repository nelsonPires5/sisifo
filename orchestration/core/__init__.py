"""Core package: centralized domain model, exceptions, naming helpers, and constants."""

from orchestration.core.models import TaskRecord
from orchestration.core.exceptions import (
    WorkerError,
    TaskProcessingError,
)
from orchestration.core.naming import (
    derive_branch_name,
    derive_container_name,
    compact_timestamp,
)

try:
    from orchestration.constants import (
        DEFAULT_DOCKER_IMAGE,
        DEFAULT_OPENCODE_SERVER_CMD,
        DEFAULT_CONTAINER_OPENCODE_CONFIG_DIR,
        DEFAULT_CONTAINER_OPENCODE_DATA_DIR,
    )
except ImportError:
    from constants import (
        DEFAULT_DOCKER_IMAGE,
        DEFAULT_OPENCODE_SERVER_CMD,
        DEFAULT_CONTAINER_OPENCODE_CONFIG_DIR,
        DEFAULT_CONTAINER_OPENCODE_DATA_DIR,
    )

__all__ = [
    "TaskRecord",
    "WorkerError",
    "TaskProcessingError",
    "derive_branch_name",
    "derive_container_name",
    "compact_timestamp",
    "DEFAULT_DOCKER_IMAGE",
    "DEFAULT_OPENCODE_SERVER_CMD",
    "DEFAULT_CONTAINER_OPENCODE_CONFIG_DIR",
    "DEFAULT_CONTAINER_OPENCODE_DATA_DIR",
]
